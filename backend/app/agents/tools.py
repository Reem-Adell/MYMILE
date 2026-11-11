"""
Real backend functions exposed to Gemini through function calling.

The trip's destination, dates and travelers are FIXED by the server (TripContext);
the model can only choose filters. So a tool call can never start a SerpApi
search for another destination or other dates, and the existing caches
(SerpApi, weather lookups per request) protect the quotas.

Limits per agent run: MAX_TOOL_CALLS executions in total, MAX_CALLS_PER_TOOL per
tool, and identical calls (same tool + arguments) are answered from the run's own
cache without calling the service again.

Results sent back to the model are compact (no booking URLs, images, tokens or
personal data); the full objects are kept in `self.hotels` / `self.weather` /
`self.budget` for building the API response.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.schemas.hotel_schema import HotelItem
from app.services import channel3_service
from app.services.channel3_service import Channel3Error
from app.schemas.weather_schema import WeatherResponse
from app.services.budget_service import optimize_budget
from app.services.hotel_service import search_hotels
from app.services.places_service import search_places
from app.services.weather_service import get_weather_forecast

log = logging.getLogger(__name__)

MAX_TOOL_CALLS = 8
MAX_CALLS_PER_TOOL = 3
LIVE_WEATHER_SOURCE = "Open-Meteo Live API"
SORT_TO_PREFERENCE = {"price_low_to_high": "Budget stay", "rating": None, "relevance": None}


@dataclass
class TripContext:
    destination: str
    city: Optional[str]
    country: Optional[str]
    check_in: str
    check_out: str
    nights: int
    travelers: int
    purpose: str
    stay_preference: str
    priorities: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    total_budget: Optional[float] = None


def _compact_hotel(h: HotelItem) -> dict:
    if h.is_placeholder:
        return {"id": h.id, "unavailable": True, "message": h.best_match_reason}
    out = {
        "id": h.id, "name": h.name, "category": h.category, "location": h.location,
        "rating": h.rating or None, "reviews": h.reviews_count or None,
        "price_per_night_usd": h.price_per_night, "total_stay_usd": h.total_price,
        "price_is": "listed" if h.price_source == "live" else "estimate",
        "near": h.distance_to_center, "amenities": (h.amenities or [])[:5],
    }
    return {k: v for k, v in out.items() if v not in (None, [], "")}


class AgentToolbox:
    def __init__(self, ctx: TripContext, plan: str, allow_products: bool = False):
        self.ctx = ctx
        self.plan = "premium" if plan == "premium" else "free"
        # Product search (Channel3) is offered during trip planning only, when configured.
        self.allow_products = allow_products and channel3_service.is_enabled()
        self.products: Dict[str, dict] = {}     # normalized Channel3 products by id
        self.product_queries: List[str] = []    # searches actually run
        self.product_error: Optional[str] = None
        self.calls: List[str] = []          # tools actually executed, in order
        self._cache: Dict[str, dict] = {}
        self._per_tool: Dict[str, int] = {}
        self.hotels: Dict[str, HotelItem] = {}
        self.hotel_lists: List[List[str]] = []  # ids of each hotel search, in order
        self.weather: Optional[WeatherResponse] = None
        self.budget = None
        self.last_hotel_query: Optional[dict] = None

    # ------------------------------------------------------------ schema ---
    def declarations(self) -> list:
        from google.genai import types

        decls = [
            types.FunctionDeclaration(
                name="get_weather_forecast",
                description="Live weather forecast for the trip destination and dates (Open-Meteo).",
                parameters_json_schema={"type": "object", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="search_hotels",
                description=("Hotels for the trip's destination, dates and travelers (Google Hotels via SerpApi "
                             "when configured, otherwise MYMILE's curated list). Prices are USD."),
                parameters_json_schema={"type": "object", "properties": {
                    "sort_by": {"type": "string", "enum": ["relevance", "price_low_to_high", "rating"]},
                    "max_price_per_night": {"type": "number", "description": "Only hotels at or below this USD price"},
                }},
            ),
            types.FunctionDeclaration(
                name="find_activities",
                description=("Verified attractions for the destination with ticket prices and durations. "
                             "May be empty for destinations MYMILE has no data for."),
                parameters_json_schema={"type": "object", "properties": {
                    "max_ticket_price": {"type": "number", "description": "Only activities at or below this USD price"},
                }},
            ),
        ]
        if self.allow_products:
            decls.append(types.FunctionDeclaration(
                name="find_travel_products",
                description=("Searches real products (Channel3) the traveler may need for this trip. Call it once "
                             "with 1-3 short, specific product searches (e.g. 'packable rain jacket'). Returns "
                             "product ids, titles, brands, prices and retailers."),
                parameters_json_schema={"type": "object", "properties": {
                    "queries": {"type": "array", "items": {"type": "string"}, "maxItems": 3,
                                "description": "1-3 specific product searches"},
                }, "required": ["queries"]},
            ))
        if self.plan == "premium":
            decls.append(types.FunctionDeclaration(
                name="estimate_budget",
                description="Premium budget breakdown (USD) for the trip, using a chosen hotel's total if given.",
                parameters_json_schema={"type": "object", "properties": {
                    "hotel_id": {"type": "string", "description": "id from search_hotels"},
                }},
            ))
        return [types.Tool(function_declarations=decls)]

    @property
    def calls_left(self) -> int:
        return MAX_TOOL_CALLS - len(self.calls)

    # --------------------------------------------------------- execution ---
    async def execute(self, name: str, args: Optional[Dict[str, Any]]) -> dict:
        args = {k: v for k, v in (args or {}).items() if v is not None}
        key = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        if key in self._cache:
            return self._cache[key]
        if name not in ("get_weather_forecast", "search_hotels", "find_activities", "estimate_budget",
                        "find_travel_products"):
            return {"error": f"Unknown tool {name}."}
        if name == "estimate_budget" and self.plan != "premium":
            return {"error": "Budget estimates are a Premium feature."}
        if name == "find_travel_products" and not self.allow_products:
            return {"error": "Product search is not available."}
        per_tool_limit = 1 if name == "find_travel_products" else MAX_CALLS_PER_TOOL
        if self.calls_left <= 0 or self._per_tool.get(name, 0) >= per_tool_limit:
            return {"error": "Tool call limit reached. Answer with the information you already have."}

        self._per_tool[name] = self._per_tool.get(name, 0) + 1
        self.calls.append(name)
        try:
            result = await getattr(self, f"_{name}")(args)
        except Exception as exc:  # a failing service must not break the agent
            log.warning("Agent tool %s failed: %s", name, type(exc).__name__)
            result = {"error": f"{name} is unavailable right now."}
        self._cache[key] = result
        return result

    async def _get_weather_forecast(self, args: dict) -> dict:
        ctx = self.ctx
        weather = await get_weather_forecast(ctx.destination, days=min(max(ctx.nights, 1), 10))
        self.weather = weather
        if weather.source != LIVE_WEATHER_SOURCE:
            return {"available": False,
                    "message": "Live weather is unavailable. Do not state temperatures or conditions."}
        return {
            "available": True,
            "current": f"{weather.current_condition}, {weather.current_temp_c}°C",
            "forecast": [{"date": f.date, "condition": f.condition, "min_c": f.temp_min_c,
                          "max_c": f.temp_max_c, "rain_chance": f.precipitation_prob}
                         for f in weather.forecast[:10]],
            "note": "Forecast covers the next days from today, which may not overlap the trip dates.",
        }

    async def fetch_hotels(self, sort_by: Optional[str] = None,
                           max_price: Optional[float] = None) -> List[HotelItem]:
        ctx = self.ctx
        preference = SORT_TO_PREFERENCE.get(sort_by or "relevance") or ctx.stay_preference
        res = await search_hotels(
            destination=ctx.destination, check_in=ctx.check_in, check_out=ctx.check_out,
            total_nights=ctx.nights, stay_preference=preference, plan=self.plan,
            budget=ctx.total_budget, travelers=ctx.travelers, purpose=ctx.purpose,
            priorities=ctx.priorities, notes=ctx.notes, city=ctx.city, country=ctx.country,
        )
        hotels = list(res.hotels)
        if max_price is not None:
            hotels = [h for h in hotels if h.is_placeholder
                      or (h.price_per_night is not None and h.price_per_night <= max_price)]
        if sort_by == "rating":
            hotels.sort(key=lambda h: (-(h.rating or 0), -(h.reviews_count or 0)))
        for h in hotels:
            self.hotels[h.id] = h
        self.hotel_lists.append([h.id for h in hotels])
        self.last_hotel_query = {"sort_by": sort_by, "max_price": max_price}
        return hotels

    async def _search_hotels(self, args: dict) -> dict:
        max_price = args.get("max_price_per_night")
        try:
            max_price = float(max_price) if max_price is not None else None
        except (TypeError, ValueError):
            max_price = None
        hotels = await self.fetch_hotels(args.get("sort_by"), max_price)
        if not hotels:
            return {"hotels": [], "message": "No hotels match these filters."}
        return {"hotels": [_compact_hotel(h) for h in hotels], "nights": self.ctx.nights,
                "travelers": self.ctx.travelers}

    async def _find_activities(self, args: dict) -> dict:
        places = search_places(self.ctx.destination).places
        cap = args.get("max_ticket_price")
        if isinstance(cap, (int, float)):
            places = [p for p in places if p.estimated_ticket_price <= cap]
        if not places:
            return {"activities": [], "message": ("MYMILE has no verified attraction data for this destination. "
                                                  "Suggest well-known places only and mark costs as estimates.")}
        return {"activities": [{"name": p.name, "category": p.category, "description": p.description[:160],
                                "rating": p.rating, "duration_hours": p.estimated_duration_hours,
                                "ticket_price_usd": p.estimated_ticket_price, "best_time": p.best_time_to_visit}
                               for p in places[:10]]}

    async def fetch_products(self, queries: List[str]) -> None:
        """Run up to CHANNEL3_MAX_QUERIES_PER_TRIP distinct searches (cached by the service)."""
        seen = {q.lower() for q in self.product_queries}
        for q in queries:
            q = channel3_service.clean_query(q)
            if len(self.product_queries) >= channel3_service.max_queries_per_trip():
                break
            if len(q) < 2 or q.lower() in seen:
                continue
            seen.add(q.lower())
            self.product_queries.append(q)
            try:
                found = await channel3_service.search(q)
            except Channel3Error as err:
                self.product_error = err.code
                if err.code in ("NOT_CONFIGURED", "INVALID_API_KEY", "CREDITS_EXHAUSTED"):
                    break  # the other searches would fail the same way
                continue
            for p in found["products"]:
                self.products.setdefault(p["id"], p)

    async def _find_travel_products(self, args: dict) -> dict:
        queries = [q for q in (args.get("queries") or []) if isinstance(q, str)]
        await self.fetch_products(queries)
        if not self.products:
            msg = (channel3_service.ERROR_MESSAGES.get(self.product_error) if self.product_error
                   else "No products found for these searches.")
            return {"products": [], "message": msg}
        return {"products": [{k: v for k, v in {
            "id": p["id"], "title": p["name"], "brand": p.get("brand"), "price": p.get("price"),
            "currency": p.get("currency"), "retailer": p.get("retailer"),
            "in_stock": p.get("in_stock"), "found_by": p.get("search_query"),
        }.items() if v is not None} for p in self.products.values()]}

    async def _estimate_budget(self, args: dict) -> dict:
        ctx = self.ctx
        hotel = self.hotels.get(str(args.get("hotel_id") or ""))
        res = optimize_budget(destination=ctx.destination, duration_days=ctx.nights, travelers=ctx.travelers,
                              total_budget=ctx.total_budget, currency="USD",
                              selected_hotel_total=hotel.total_price if hotel else None,
                              stay_preference=ctx.stay_preference, plan=self.plan)
        self.budget = res.breakdown
        b = res.breakdown
        return {"currency": "USD", "user_budget": b.user_budget, "total_estimated": b.total_estimated,
                "remaining": b.remaining_balance, "status": b.status,
                "breakdown": {"accommodation": b.accommodation, "food": b.food, "transport": b.transportation,
                              "activities": b.activities, "essentials": b.travel_essentials,
                              "contingency": b.contingency_and_other},
                "hotel_used": hotel.name if hotel else None}
