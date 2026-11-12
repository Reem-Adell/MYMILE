"""
Real backend functions exposed to the LLM (Groq or Gemini) through function calling.

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
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.schemas.hotel_schema import HotelItem
from app.services import channel3_service, trip_shopping
from app.services.channel3_service import Channel3Error
from app.schemas.weather_schema import WeatherResponse
from app.services.budget_service import optimize_budget
from app.services.hotel_service import search_hotels
from app.services.weather_service import get_weather_forecast

log = logging.getLogger(__name__)

MAX_TOOL_CALLS = 8
MAX_CALLS_PER_TOOL = 3
MAX_PRODUCT_TOOL_CALLS = 2  # searches + at most one follow-up for categories that found nothing relevant
PRODUCT_ABOUT_CHARS = 60    # description snippet sent to the model to judge relevance (token budget)
LIVE_WEATHER_SOURCE = "Open-Meteo Live API"
PREFETCH_TOOLS = ("get_weather_forecast", "search_hotels")
POST_PREFETCH_TOOLS = ("find_travel_products",)  # still Channel3-gated below
PROMPT_MAX_HOTELS = 10  # hotels put in a prompt; the full list is kept for the response
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
    shopping_audience: Optional[str] = None  # "men" | "women" | None (everyone)


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
    def __init__(self, ctx: TripContext, plan: str, allow_products: bool = False, allow_budget: bool = True):
        self.ctx = ctx
        self.plan = "premium" if plan == "premium" else "free"
        # Product search (Channel3) is offered during trip planning only, when configured.
        self.allow_products = allow_products and channel3_service.is_enabled()
        # The budget tool is for chat. Trip planning doesn't offer it: the server adds the
        # Premium budget breakdown itself (optimize_budget in plan_trip_agent), saving a model round.
        self.allow_budget = allow_budget
        self.products: Dict[str, dict] = {}     # normalized Channel3 products by id
        self.product_queries: List[str] = []    # searches actually run
        # Each search actually run: {query, category, audience, found, filtered, duplicates, error}.
        self.product_searches: List[dict] = []
        self.skipped_searches: List[dict] = []   # searches refused in the latest call (and why)
        self.product_meta: Dict[str, dict] = {}  # product id -> {query, category, audience} that found it
        self.product_error: Optional[str] = None
        self.calls: List[str] = []          # tools actually executed, in order
        self._cache: Dict[str, dict] = {}
        self._per_tool: Dict[str, int] = {}
        self.hotels: Dict[str, HotelItem] = {}
        self.hotel_lists: List[List[str]] = []  # ids of each hotel search, in order
        self.weather: Optional[WeatherResponse] = None
        self.budget = None
        self.last_hotel_query: Optional[dict] = None
        self.offered: Optional[set] = None  # None = every permitted tool; set by prefetch()

    # ------------------------------------------------------------ schema ---
    def tool_specs(self) -> List[dict]:
        """Provider-neutral tool schemas (JSON Schema parameters) this run may use."""
        specs = [
            {"name": "get_weather_forecast",
             "description": "Live weather forecast for the trip destination and dates (Open-Meteo).",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "search_hotels",
             "description": ("Hotels for the trip's destination, dates and travelers (Google Hotels via SerpApi "
                             "when configured, otherwise MYMILE's curated list). Prices are USD."),
             "parameters": {"type": "object", "properties": {
                 "sort_by": {"type": "string", "enum": ["relevance", "price_low_to_high", "rating"]},
                 "max_price_per_night": {"type": "number", "description": "Only hotels at or below this USD price"},
             }}},
        ]
        if self.allow_products:
            cap = channel3_service.max_queries_per_trip()
            specs.append({
                "name": "find_travel_products",
                "description": (f"Searches real products (Channel3) for the categories this trip needs: one short, "
                                f"specific search per category (e.g. 'travel prayer mat'), up to {cap} searches per "
                                "trip in total. Returns, per search, product ids, titles, brands, prices, ratings, "
                                "stock and a short description. Off-topic results are removed by the server."),
                "parameters": {"type": "object", "properties": {
                    "searches": {"type": "array", "maxItems": cap, "items": {
                        "type": "object", "properties": {
                            "category": {"type": "string", "description": "display category, e.g. 'Footwear'"},
                            "query": {"type": "string", "description": "specific product search"},
                            "audience": {"type": "string", "enum": list(trip_shopping.AUDIENCES)},
                        }, "required": ["category", "query"]}},
                }, "required": ["searches"]}})
        if self.plan == "premium" and self.allow_budget:
            specs.append({
                "name": "estimate_budget",
                "description": "Premium budget breakdown (USD) for the trip, using a chosen hotel's total if given.",
                "parameters": {"type": "object", "properties": {
                    "hotel_id": {"type": "string", "description": "id from search_hotels"},
                }}})
        if self.offered is not None:
            specs = [s for s in specs if s["name"] in self.offered]
        return specs

    def declarations(self) -> list:
        """Gemini (google-genai) tool declarations."""
        from google.genai import types

        return [types.Tool(function_declarations=[
            types.FunctionDeclaration(name=s["name"], description=s["description"],
                                      parameters_json_schema=s["parameters"])
            for s in self.tool_specs()])]

    def openai_tools(self) -> list:
        """OpenAI-compatible (Groq) function tools."""
        return [{"type": "function", "function": {"name": s["name"], "description": s["description"],
                                                  "parameters": s["parameters"]}}
                for s in self.tool_specs()]

    async def prefetch(self) -> dict:
        """Run the tools whose inputs the server fixes (weather, default hotels, activities)
        once, before the first model request, and offer the model only the remaining tools.
        Saves a model round per tool and keeps large results out of tool-call turns.
        Returns compact results for the prompt; the full objects stay on the toolbox."""
        weather, hotels = await asyncio.gather(
            *(self.execute(name, {}) for name in PREFETCH_TOOLS))
        if isinstance(hotels.get("hotels"), list):
            hotels = {**hotels, "hotels": hotels["hotels"][:PROMPT_MAX_HOTELS]}
        self.offered = set(POST_PREFETCH_TOOLS)
        return {"get_weather_forecast": weather, "search_hotels": hotels}

    @property
    def calls_left(self) -> int:
        return MAX_TOOL_CALLS - len(self.calls)

    # --------------------------------------------------------- execution ---
    async def execute(self, name: str, args: Optional[Dict[str, Any]]) -> dict:
        args = {k: v for k, v in (args or {}).items() if v is not None}
        if self.offered is not None and name in PREFETCH_TOOLS and name not in self.offered:
            return {"error": f"{name} isn't available now: its results are already in the prompt."}
        key = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        if key in self._cache:
            return self._cache[key]
        if name not in ("get_weather_forecast", "search_hotels", "estimate_budget",
                        "find_travel_products"):
            return {"error": f"Unknown tool {name}."}
        if name == "estimate_budget" and self.plan != "premium":
            return {"error": "Budget estimates are a Premium feature."}
        if name == "estimate_budget" and not self.allow_budget:
            return {"error": "The server adds the budget breakdown to this plan; don't request it."}
        if name == "find_travel_products" and not self.allow_products:
            return {"error": "Product search is not available."}
        per_tool_limit = MAX_PRODUCT_TOOL_CALLS if name == "find_travel_products" else MAX_CALLS_PER_TOOL
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

    @staticmethod
    def _search_specs(raw) -> List[dict]:
        """[{query, category, audience}] from the model's `searches` (or plain query strings)."""
        out = []
        for item in raw if isinstance(raw, list) else []:
            if isinstance(item, str):
                item = {"query": item}
            if not isinstance(item, dict):
                continue
            out.append({"query": channel3_service.clean_query(item.get("query")),
                        "category": trip_shopping.category_name(item.get("category")),
                        "audience": trip_shopping.audience(item.get("audience")) or "all"})
        return out

    @property
    def expects_tool_call(self) -> bool:
        """True while the next model turn should be a tool call, not the answer: trip planning
        hasn't run its Channel3 search yet. Only such rounds get the small tool-round limit;
        any other round may carry the final JSON."""
        return (self.allow_products and not self.product_searches and self.calls_left > 0
                and any(s["name"] == "find_travel_products" for s in self.tool_specs()))

    @property
    def product_searches_left(self) -> int:
        return max(channel3_service.max_queries_per_trip() - len(self.product_queries), 0)

    def _with_named_products(self, specs: List[dict]) -> List[dict]:
        """Searches for the products the traveler named come first, in description order: the
        AI's own search when it covers the need (its wording is kept), else the server's default
        query. The AI's other searches follow, so a generic search never displaces a named need."""
        chosen: List[dict] = []
        used = set()
        for need in trip_shopping.named_products(self.ctx.notes):
            if any(trip_shopping.search_covers_need(c["category"], c["query"], need) for c in chosen):
                continue  # one search already covers it (e.g. "wireless mouse and keyboard")
            ai = next((i for i, s in enumerate(specs)
                       if i not in used and trip_shopping.search_covers_need(s["category"], s["query"], need)), None)
            if ai is not None:
                used.add(ai)
                chosen.append(specs[ai])
            else:
                chosen.append({"query": channel3_service.clean_query(need["query"]), "category": need["category"],
                               "audience": need["audience"], "named": True})
        return chosen + [s for i, s in enumerate(specs) if i not in used]

    async def fetch_products(self, searches, enforce_named: bool = False) -> List[dict]:
        """Run distinct searches up to CHANNEL3_MAX_QUERIES_PER_TRIP per trip (cached by the
        service, so a cached plan re-reads them without credits). Products that fail the
        search's relevance guard are dropped, and so are products already shown (same id or a
        near-identical title). A category that already has relevant products is not searched
        again, so the searches stay diverse. Returns the search records run by this call."""
        seen = {q.lower() for q in self.product_queries}
        ran = []
        self.skipped_searches = []
        specs = self._search_specs(searches)
        if enforce_named:
            specs = self._with_named_products(specs)
        for spec in specs:
            # Clothing and footwear searches say who they are for, when the traveler chose.
            q = trip_shopping.audience_query(spec["query"], self.ctx.shopping_audience, spec["category"])
            if trip_shopping.purpose_conflict(self.ctx.purpose, self.ctx.notes, q, spec["category"]):
                self.skipped_searches.append({"query": q, "category": spec["category"],
                                              "reason": "Not for this trip's purpose or description."})
                continue
            if not self.product_searches_left:
                break
            if len(q) < 2 or q.lower() in seen:
                continue
            covered = next((r for r in self.product_searches if r["found"] and (
                (spec["category"] and trip_shopping.same_category(spec["category"], r["category"]))
                or trip_shopping.similar_query(q, r["query"]))), None)
            if covered:
                self.skipped_searches.append({"query": q, "category": spec["category"],
                                              "reason": "This kind of item already has products; search another category."})
                continue
            seen.add(q.lower())
            self.product_queries.append(q)
            record = {**spec, "found": [], "filtered": 0, "duplicates": 0, "error": None}
            self.product_searches.append(record)
            ran.append(record)
            try:
                found = await channel3_service.search(q)
            except Channel3Error as err:
                self.product_error = record["error"] = err.code
                if err.code in ("NOT_CONFIGURED", "INVALID_API_KEY", "CREDITS_EXHAUSTED"):
                    break  # the other searches would fail the same way
                continue
            other = trip_shopping.opposite_audience(self.ctx.shopping_audience)
            for p in found["products"]:
                if (not trip_shopping.is_relevant(q, p) or not trip_shopping.matches_category(q, spec["category"], p)
                        or (other and trip_shopping.infer_audience(p) == other)):
                    record["filtered"] += 1  # off-topic, not the searched item, or for the other audience
                    continue
                if p["id"] in self.products or any(trip_shopping.is_near_duplicate(p, other)
                                                   for other in self.products.values()):
                    record["duplicates"] += 1
                    continue
                record["found"].append(p["id"])
                self.products.setdefault(p["id"], p)
                self.product_meta.setdefault(p["id"], {"query": q, "category": spec["category"],
                                                       "audience": spec["audience"]})
        return ran

    @staticmethod
    def _compact_product(p: dict) -> dict:
        """What the model needs to judge a product. The full product (images, offers,
        variants, links) stays on the toolbox for the response; nothing is invented."""
        about = " ".join((p.get("description") or "").split())[:PRODUCT_ABOUT_CHARS].strip() or None
        currency = p.get("currency")
        return {k: v for k, v in {
            "id": p["id"], "title": p["name"], "brand": p.get("brand"), "price": p.get("price"),
            # USD is stated once for the whole result (prices_in); other currencies are kept per product.
            "currency": currency if currency and currency.upper() != "USD" else None,
            "rating": p.get("rating"), "reviews": p.get("rating_count"),
            "in_stock": p.get("in_stock"), "type": p.get("category"), "about": about,
            "for": trip_shopping.infer_audience(p) if trip_shopping.infer_audience(p) in ("men", "women") else None,
        }.items() if v is not None}

    async def _find_travel_products(self, args: dict) -> dict:
        ran = await self.fetch_products(args.get("searches") or args.get("queries") or [],
                                        enforce_named=not self.product_searches)
        if not ran:
            msg = ("Product search limit reached for this trip." if not self.product_searches_left
                   else "No valid searches were given.")
            out = {"searches": [], "message": msg}
            if self.skipped_searches:
                out["skipped"] = self.skipped_searches
            return out
        results = []
        for r in ran:
            entry = {"category": r["category"], "query": r["query"], "audience": r["audience"],
                     "products": [self._compact_product(self.products[i]) for i in r["found"]]}
            if r["error"]:
                entry["error"] = channel3_service.ERROR_MESSAGES.get(r["error"])
            elif not r["found"]:
                entry["note"] = ("Only off-topic results were returned, so they were removed." if r["filtered"]
                                 else "Only products already shown above were returned." if r["duplicates"]
                                 else "No products found.")
            results.append({k: v for k, v in entry.items() if v is not None})
        out = {"prices_in": "USD unless a product lists a currency", "searches": results,
               "searches_left": self.product_searches_left}
        if self.skipped_searches:
            out["skipped"] = self.skipped_searches
        if not any(r["products"] for r in results):
            out["message"] = (channel3_service.ERROR_MESSAGES.get(self.product_error) if self.product_error
                              else "No relevant products found for these searches.")
        return out

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
