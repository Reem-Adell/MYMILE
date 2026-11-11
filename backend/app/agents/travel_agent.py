import datetime
import hashlib
import json
import logging
import time
import uuid
from contextlib import closing
from typing import Dict, List, Optional, Tuple

from pydantic import ValidationError

from app.agents import gemini_client
from app.agents.agent_loop import run_agent
from app.agents.gemini_client import GeminiError
from app.agents.prompts import chat_system_prompt, plan_system_prompt
from app.agents.tools import AgentToolbox, TripContext
from app.core import database
from app.core.config import settings
from app.core.destinations import compose_destination, display_city, resolve_city
from app.schemas.hotel_schema import HotelItem
from app.schemas.trip_schema import (
    AgentInfo,
    EssentialsInfo,
    ChatTripContext,
    ItineraryActivity,
    ItineraryDay,
    TripChatRequest,
    TripChatResponse,
    TripPlanRequest,
    TripPlanResponse,
)
from app.services.budget_service import optimize_budget
from app.services import channel3_service
from app.schemas.product_schema import ProductSearchResponse
from app.services.weather_service import get_weather_forecast

log = logging.getLogger(__name__)


def calculate_days(dep: str, ret: str) -> int:
    try:
        d1 = datetime.datetime.strptime(dep.strip(), "%Y-%m-%d")
        d2 = datetime.datetime.strptime(ret.strip(), "%Y-%m-%d")
        delta = (d2 - d1).days
        return max(delta, 1)
    except Exception:
        return 7

def generate_destination_itinerary(
    destination: str,
    purpose: str,
    days: int,
    start_date_str: str,
    priorities: List[str]
) -> List[ItineraryDay]:
    """Generates day-by-day tailored itinerary with realistic timestamps, activities, and locations."""
    dest_lower = destination.lower()
    itinerary_days: List[ItineraryDay] = []
    
    try:
        base_date = datetime.datetime.strptime(start_date_str.strip(), "%Y-%m-%d")
    except Exception:
        base_date = datetime.datetime(2026, 4, 8)
        
    city = resolve_city(destination)
    city_name = display_city(destination)
    is_umrah = "umrah" in purpose.lower() or city == "makkah" or "madinah" in dest_lower
    is_cairo = city == "cairo"
    is_alexandria = city == "alexandria"
    is_paris = city == "paris"
    is_kyoto = city == "kyoto"
    
    for i in range(days):
        current_date = base_date + datetime.timedelta(days=i)
        day_date_str = current_date.strftime("%A, %b %d")
        day_num = i + 1
        
        if is_umrah:
            if day_num == 1:
                theme = "Arrival, Ihram & Performing Umrah"
                acts = [
                    ItineraryActivity(time="02:00 PM", title="Arrival & Hotel Check-in", description="Settle into your hotel near the Grand Mosque courtyard.", location="Makkah Hotel", icon="hotel", cost_estimate=0.0),
                    ItineraryActivity(time="05:30 PM", title="Enter Masjid Al-Haram in Ihram", description="Perform Tawaf around the Holy Kaaba with mindfulness.", location="Kaaba Courtyard", icon="route", cost_estimate=0.0),
                    ItineraryActivity(time="08:00 PM", title="Sa'i between Safa and Marwah", description="Complete the 7 circuits of Sa'i followed by Tahallul.", location="Al-Masa'a", icon="spark", cost_estimate=0.0)
                ]
            elif day_num == 2:
                theme = "Spiritual Contemplation & Historical Sites"
                acts = [
                    ItineraryActivity(time="04:30 AM", title="Fajr Prayer at the Haram", description="Experience the profound serenity of dawn prayer.", location="Masjid Al-Haram", icon="clock", cost_estimate=0.0),
                    ItineraryActivity(time="09:30 AM", title="Visit Jabal Al-Noor (Cave of Hira)", description="Historic mountain where the first revelation occurred.", location="Jabal Al-Noor", icon="pin", cost_estimate=15.0),
                    ItineraryActivity(time="06:30 PM", title="Maghrib & Evening Recitation", description="Time for personal du'a and peaceful reflection.", location="Masjid Al-Haram", icon="spark", cost_estimate=0.0)
                ]
            else:
                theme = f"Day {day_num}: Spiritual Devotion & Zamzam"
                acts = [
                    ItineraryActivity(time="10:00 AM", title="Quran Reading & Du'a Session", description="Peaceful morning in the shaded courtyards.", location="Grand Mosque", icon="spark", cost_estimate=0.0),
                    ItineraryActivity(time="04:00 PM", title="Islamic Heritage Library & Souq", description="Browse traditional dates, oud, and gifts for family.", location="Makkah Center", icon="bag", cost_estimate=25.0)
                ]
        elif is_cairo:
            if day_num == 1:
                theme = "Arrival & Downtown Cairo Heritage"
                acts = [
                    ItineraryActivity(time="01:00 PM", title="Arrival & Check-in", description="Check in with views of the historic Nile river or pyramids.", location="Hotel Lobby", icon="hotel", cost_estimate=0.0),
                    ItineraryActivity(time="04:30 PM", title="Khan el-Khalili Bazaar Walk", description="Explore 14th-century souqs, spice merchants, and El Fishawy cafe.", location="Khan el-Khalili", icon="bag", cost_estimate=15.0)
                ]
            elif day_num == 2:
                theme = "The Great Pyramids & The Sphinx"
                acts = [
                    ItineraryActivity(time="08:30 AM", title="Giza Plateau & Great Pyramid of Khufu", description="Marvel at the monumental engineering of antiquity with your guide.", location="Giza Plateau", icon="pin", cost_estimate=20.0),
                    ItineraryActivity(time="12:30 PM", title="The Great Sphinx & Valley Temple", description="Examine the enigmatic limestone sculpture and royal mortuary temple.", location="Sphinx Complex", icon="spark", cost_estimate=0.0),
                    ItineraryActivity(time="07:00 PM", title="Egyptian Dinner overlooking the Nile", description="Taste authentic koshari, grilled meats, and fresh hibiscus tea.", location="Zamalek Island", icon="clock", cost_estimate=35.0)
                ]
            else:
                theme = f"Day {day_num}: Grand Egyptian Museum & Citadel"
                acts = [
                    ItineraryActivity(time="09:30 AM", title="The Grand Egyptian Museum (GEM)", description="Tour the complete King Tutankhamun collection.", location="GEM Complex", icon="pin", cost_estimate=25.0),
                    ItineraryActivity(time="03:00 PM", title="Saladin Citadel & Mosque of Muhammad Ali", description="Panoramic city skyline views and Ottoman alabaster domes.", location="Citadel of Cairo", icon="route", cost_estimate=15.0)
                ]
        elif is_alexandria:
            if day_num == 1:
                theme = "Arrival & the Corniche at Sunset"
                acts = [
                    ItineraryActivity(time="01:00 PM", title="Arrival & Check-in", description="Settle in and get your first look at the Mediterranean.", location="Hotel", icon="hotel", cost_estimate=0.0),
                    ItineraryActivity(time="05:00 PM", title="Corniche Walk to Qaitbay Citadel", description="Stroll the seafront promenade to the 15th-century fort built on the site of the ancient Pharos lighthouse.", location="Qaitbay Citadel", icon="route", cost_estimate=5.0),
                    ItineraryActivity(time="08:00 PM", title="Seafood Dinner in Anfoushi", description="Pick your fish fresh and have it grilled at a harbour-side restaurant.", location="Anfoushi", icon="clock", cost_estimate=20.0)
                ]
            elif day_num == 2:
                theme = "The Library & Graeco-Roman Alexandria"
                acts = [
                    ItineraryActivity(time="09:30 AM", title="Bibliotheca Alexandrina", description="The modern revival of the ancient library, with museums, manuscripts and a planetarium.", location="Shatby", icon="pin", cost_estimate=10.0),
                    ItineraryActivity(time="01:00 PM", title="Roman Amphitheatre (Kom el-Dikka)", description="The only Roman theatre found in Egypt, with mosaics and villa ruins nearby.", location="Kom el-Dikka", icon="spark", cost_estimate=5.0),
                    ItineraryActivity(time="04:00 PM", title="Alexandria National Museum", description="Compact collection spanning Pharaonic, Graeco-Roman and Coptic Alexandria.", location="Fouad Street", icon="pin", cost_estimate=6.0)
                ]
            elif day_num == 3:
                theme = "Catacombs, Pompey's Pillar & Old Cafes"
                acts = [
                    ItineraryActivity(time="09:30 AM", title="Catacombs of Kom el-Shoqafa", description="Underground tombs blending Egyptian, Greek and Roman styles.", location="Karmouz", icon="pin", cost_estimate=6.0),
                    ItineraryActivity(time="11:30 AM", title="Pompey's Pillar & the Serapeum", description="A towering granite column on the site of the ancient Serapeum temple.", location="Karmouz", icon="route", cost_estimate=4.0),
                    ItineraryActivity(time="05:00 PM", title="Historic Cafes of Raml Station", description="Pastries and coffee at the city's century-old cafes around Saad Zaghloul Square.", location="Raml Station", icon="clock", cost_estimate=8.0)
                ]
            else:
                theme = f"Day {day_num}: Montaza Gardens & the Seaside"
                acts = [
                    ItineraryActivity(time="10:00 AM", title="Montaza Palace Gardens", description="Wander the royal gardens and palms around the palace overlooking the sea.", location="Montaza", icon="pin", cost_estimate=3.0),
                    ItineraryActivity(time="01:00 PM", title="Beach Time at Mamoura", description="Relax by the Mediterranean on one of the calmer east-side beaches.", location="Mamoura Beach", icon="spark", cost_estimate=5.0),
                    ItineraryActivity(time="06:30 PM", title="Stanley Bridge at Dusk", description="Watch the sunset light up the bay from the city's best-known bridge.", location="Stanley", icon="route", cost_estimate=0.0)
                ]
        elif is_paris:
            if day_num == 1:
                theme = "Arrival & Le Marais Stroll"
                acts = [
                    ItineraryActivity(time="02:30 PM", title="Boutique Check-in", description="Unpack in the heart of charming Parisian quarters.", location="Hotel", icon="hotel", cost_estimate=0.0),
                    ItineraryActivity(time="05:00 PM", title="Le Marais Architecture & Patisserie", description="Sample fresh macarons and explore hidden courtyard gardens.", location="Place des Vosges", icon="bag", cost_estimate=18.0)
                ]
            elif day_num == 2:
                theme = "The Louvre & Seine River Sunset"
                acts = [
                    ItineraryActivity(time="09:00 AM", title="Louvre Museum Masterpieces", description="Discover the Mona Lisa and Winged Victory with timed entry.", location="Louvre Museum", icon="pin", cost_estimate=22.0),
                    ItineraryActivity(time="06:30 PM", title="Sunset Seine River Cruise", description="Glide past the illuminated Notre-Dame and Eiffel Tower.", location="Pont Neuf", icon="route", cost_estimate=20.0)
                ]
            else:
                theme = f"Day {day_num}: Montmartre & Art Cafes"
                acts = [
                    ItineraryActivity(time="10:00 AM", title="Montmartre & Sacré-Cœur Basilica", description="Wander cobblestone lanes once inhabited by Picasso and Monet.", location="Montmartre", icon="pin", cost_estimate=0.0),
                    ItineraryActivity(time="01:30 PM", title="French Bistro Tasting Lunch", description="Savor traditional duck confit, fresh baguettes, and tarte tatin.", location="Rue des Martyrs", icon="clock", cost_estimate=40.0)
                ]
        elif is_kyoto:
            if day_num == 1:
                theme = "Arrival & Gion Lanterns"
                acts = [
                    ItineraryActivity(time="03:00 PM", title="Check in & settle at your hotel", description="Settle in and enjoy traditional welcome matcha.", location="Hotel Lobby", icon="hotel", cost_estimate=0.0),
                    ItineraryActivity(time="06:00 PM", title="Evening walk through Gion", description="Stroll historic Hanamikoji street bathed in warm paper lanterns.", location="Gion District", icon="route", cost_estimate=0.0)
                ]
            elif day_num == 2:
                theme = "Temples, Tea & Philosophy"
                acts = [
                    ItineraryActivity(time="08:30 AM", title="Kiyomizu-dera Wooden Stage", description="Stand over the maple canopy overlooking Kyoto city.", location="Higashiyama", icon="pin", cost_estimate=4.0),
                    ItineraryActivity(time="02:00 PM", title="Traditional Uji Tea Ceremony", description="Learn authentic whisking techniques with a local tea master.", location="Ninenzaka", icon="spark", cost_estimate=35.0)
                ]
            elif day_num == 3:
                theme = "Arashiyama Bamboo & Zen Gardens"
                acts = [
                    ItineraryActivity(time="08:00 AM", title="Arashiyama Bamboo Grove", description="Morning walk through towering bamboo before crowds arrive.", location="Arashiyama", icon="pin", cost_estimate=0.0),
                    ItineraryActivity(time="11:30 AM", title="Tenryu-ji UNESCO Zen Temple", description="14th-century pond garden framed by rolling green mountains.", location="Tenryu-ji", icon="route", cost_estimate=5.0)
                ]
            else:
                theme = f"Day {day_num}: Hidden Markets & Cultural Crafts"
                acts = [
                    ItineraryActivity(time="10:00 AM", title="Nishiki Market Culinary Tour", description="Taste charcoal-grilled skewers, mochi, and artisanal pickles.", location="Nishiki Arcade", icon="bag", cost_estimate=25.0),
                    ItineraryActivity(time="03:00 PM", title="Fushimi Inari Torii Gate Trail", description="Hike beneath thousands of sacred red torii gates.", location="Fushimi", icon="pin", cost_estimate=0.0)
                ]
                
        else:
            # No curated plan for this city yet: a sensible general plan named after it,
            # never another city's sights.
            if day_num == 1:
                theme = f"Arrival & First Look at {city_name}"
                acts = [
                    ItineraryActivity(time="02:00 PM", title="Arrival & Check-in", description="Settle into your stay and get your bearings.", location="Hotel", icon="hotel", cost_estimate=0.0),
                    ItineraryActivity(time="05:00 PM", title=f"Old Town Walk in {city_name}", description="Wander the historic centre and find a good spot for sunset.", location=f"{city_name} city centre", icon="route", cost_estimate=0.0),
                    ItineraryActivity(time="08:00 PM", title="Dinner at a Local Favourite", description="Try the dishes the city is known for at a well-reviewed local restaurant.", location=f"{city_name} city centre", icon="clock", cost_estimate=25.0)
                ]
            elif day_num == 2:
                theme = f"{city_name}'s Top Landmarks & Museums"
                acts = [
                    ItineraryActivity(time="09:30 AM", title="Main Museum or Landmark", description="Start early at the city's best-known museum or monument to beat the crowds.", location=city_name, icon="pin", cost_estimate=15.0),
                    ItineraryActivity(time="02:00 PM", title="Guided Neighbourhood Tour", description="A local guide shows you the stories behind the streets.", location=city_name, icon="spark", cost_estimate=20.0)
                ]
            else:
                theme = f"Day {day_num}: Markets, Food & Hidden Corners"
                acts = [
                    ItineraryActivity(time="10:00 AM", title="Local Market Visit", description="Browse the main market for food, crafts and souvenirs.", location=city_name, icon="bag", cost_estimate=15.0),
                    ItineraryActivity(time="03:00 PM", title="Free Time to Explore", description="Revisit a favourite area or ask MYMILE for ideas that fit your pace.", location=city_name, icon="route", cost_estimate=0.0)
                ]

        itinerary_days.append(ItineraryDay(
            day_number=day_num,
            date_str=day_date_str,
            theme=theme,
            activities=acts
        ))
        
    return itinerary_days

VALID_ICONS = {"pin", "hotel", "route", "clock", "spark", "bag"}
MAX_ACTIVITIES_PER_DAY = 6
HISTORY_MESSAGES = 8


def _clip(value, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _day_label(start_date: str, day_number: int) -> str:
    try:
        base = datetime.datetime.strptime(start_date.strip(), "%Y-%m-%d")
    except (ValueError, AttributeError):
        return f"Day {day_number}"
    return (base + datetime.timedelta(days=day_number - 1)).strftime("%A, %b %d")


def _parse_day(raw, start_date: str) -> Optional[ItineraryDay]:
    """One itinerary day from model JSON, validated and clipped. None if unusable."""
    if not isinstance(raw, dict):
        return None
    try:
        day_number = int(raw.get("day_number"))
    except (TypeError, ValueError):
        return None
    activities = []
    for act in (raw.get("activities") or [])[:MAX_ACTIVITIES_PER_DAY]:
        if not isinstance(act, dict) or not str(act.get("title") or "").strip():
            continue
        try:
            cost = min(max(float(act.get("cost_estimate") or 0), 0.0), 10000.0)
        except (TypeError, ValueError):
            cost = 0.0
        icon = str(act.get("icon") or "pin").strip().lower()
        activities.append(ItineraryActivity(
            time=_clip(act.get("time") or "", 20),
            title=_clip(act.get("title"), 120),
            description=_clip(act.get("description") or "", 300),
            location=_clip(act.get("location") or "", 120) or None,
            icon=icon if icon in VALID_ICONS else "pin",
            cost_estimate=round(cost, 2),
        ))
    if not activities:
        return None
    return ItineraryDay(day_number=day_number, date_str=_day_label(start_date, day_number),
                        theme=_clip(raw.get("theme") or f"Day {day_number}", 120), activities=activities)


def _parse_itinerary(raw_days, total_days: int, start_date: str) -> List[ItineraryDay]:
    """Every day 1..total_days exactly once, else GeminiError (never a partial plan)."""
    days: Dict[int, ItineraryDay] = {}
    for raw in raw_days if isinstance(raw_days, list) else []:
        day = _parse_day(raw, start_date)
        if day and 1 <= day.day_number <= total_days and day.day_number not in days:
            days[day.day_number] = day
    if len(days) != total_days:
        raise GeminiError("INVALID_RESPONSE")
    return [days[n] for n in range(1, total_days + 1)]


# ------------------------------------------------------------ plan cache ---
_plan_cache_ready: set = set()


def _plan_cache_db():
    conn = database.connect()
    path = str(database.DB_PATH)
    if path not in _plan_cache_ready:
        conn.execute("CREATE TABLE IF NOT EXISTS ai_plan_cache ("
                     " cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at REAL NOT NULL)")
        conn.commit()
        _plan_cache_ready.add(path)
    return conn


def _plan_cache_key(request: TripPlanRequest, plan: str) -> str:
    raw = json.dumps({"req": request.model_dump(), "plan": plan, "model": gemini_client.resolve_model(),
                      "v": 2}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _plan_cache_get(key: str) -> Optional[dict]:
    ttl = max(float(settings.AI_PLAN_CACHE_TTL_HOURS or 0), 0.0) * 3600
    with closing(_plan_cache_db()) as conn:
        row = conn.execute("SELECT payload, created_at FROM ai_plan_cache WHERE cache_key=?", (key,)).fetchone()
    if not row or time.time() - row["created_at"] > ttl:
        return None
    return json.loads(row["payload"])


def _plan_cache_put(key: str, payload: dict) -> None:
    ttl = max(float(settings.AI_PLAN_CACHE_TTL_HOURS or 0), 0.0) * 3600
    with closing(_plan_cache_db()) as conn:
        conn.execute("INSERT OR REPLACE INTO ai_plan_cache (cache_key, payload, created_at) VALUES (?,?,?)",
                     (key, json.dumps(payload), time.time()))
        conn.execute("DELETE FROM ai_plan_cache WHERE created_at < ?", (time.time() - ttl,))
        conn.commit()


# ------------------------------------------------------------------ plan ---
def _trip_prompt(ctx: TripContext, is_premium: bool) -> str:
    trip = {
        "destination": ctx.destination, "check_in": ctx.check_in, "check_out": ctx.check_out,
        "nights": ctx.nights, "travelers": ctx.travelers, "purpose": ctx.purpose,
        "stay_preference": ctx.stay_preference, "priorities": ctx.priorities[:6],
        "notes": _clip(ctx.notes, 500) if ctx.notes else None,
        "total_budget_usd": ctx.total_budget if is_premium else None,
    }
    return "Plan this trip:\n" + json.dumps({k: v for k, v in trip.items() if v not in (None, [], "")})


MAX_ESSENTIALS = 6


def _parse_essentials(raw, toolbox: AgentToolbox) -> List[dict]:
    """Gemini's picks, kept only when the product id really came from Channel3."""
    picks, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("product_id") or "")
        if pid in toolbox.products and pid not in seen:
            seen.add(pid)
            picks.append({"product_id": pid, "reason": _clip(item.get("reason"), 160) or None})
        if len(picks) >= MAX_ESSENTIALS:
            break
    return picks


async def _travel_essentials(ai_result: Optional[dict], toolbox: AgentToolbox, plan: str):
    """(products with Premium-only links, EssentialsInfo). Only genuine Channel3 products."""
    if not channel3_service.is_enabled():
        return [], EssentialsInfo(status="not_configured", message="Travel product suggestions aren't set up yet.")
    if not ai_result:
        return [], EssentialsInfo(status="ai_unavailable",
                                  message="Personalized product suggestions need the AI planner.")
    queries = ai_result.get("product_queries") or []
    if queries and not toolbox.products:  # cached AI plan: re-read the searches (served from cache)
        await toolbox.fetch_products(queries)
    picks = ai_result.get("essentials") or []
    if picks:
        items = [channel3_service.to_item(toolbox.products[p["product_id"]], p.get("reason"))
                 for p in picks if p["product_id"] in toolbox.products]
    else:  # Gemini searched but didn't pick: show what Channel3 found, without invented reasons
        items = [channel3_service.to_item(p) for p in list(toolbox.products.values())[:MAX_ESSENTIALS]]
    error = toolbox.product_error or ai_result.get("product_error")
    if items:
        info = EssentialsInfo(status="ok", queries=queries)
    elif error:
        info = EssentialsInfo(status="unavailable", queries=queries,
                              message=channel3_service.ERROR_MESSAGES.get(error))
    else:
        info = EssentialsInfo(status="empty", queries=queries, message="No matching products were found.")
    response = channel3_service.apply_purchase_link_policy(
        ProductSearchResponse(query_context=", ".join(queries), products=items), plan)
    return response.products, info


async def _ai_plan(request: TripPlanRequest, ctx: TripContext, toolbox: AgentToolbox, plan: str,
                   total_days: int) -> Tuple[dict, bool]:
    """(AI result, from_cache). Raises GeminiError."""
    gemini_client.check_available()
    key = _plan_cache_key(request, plan)
    cached = _plan_cache_get(key)
    if cached:
        return cached, True
    data, requests = await run_agent(plan_system_prompt(plan, total_days, toolbox.allow_products),
                                     _trip_prompt(ctx, plan == "premium"), toolbox)
    itinerary = _parse_itinerary(data.get("itinerary"), total_days, request.departure_date)
    result = {
        "summary": _clip(data.get("summary"), 400),
        "why_recommended": _clip(data.get("why_recommended"), 700),
        "recommended_hotel_id": str(data.get("recommended_hotel_id") or "") or None,
        "itinerary": [d.model_dump() for d in itinerary],
        "tools_used": list(dict.fromkeys(toolbox.calls)),
        "hotel_query": toolbox.last_hotel_query,
        "model": gemini_client.resolve_model(),
        # Channel3: the searches Gemini asked for and the products it picked (ids + reasons).
        "product_queries": list(toolbox.product_queries),
        "essentials": _parse_essentials(data.get("essentials"), toolbox),
        "product_error": toolbox.product_error,
    }
    if not result["summary"] or not result["why_recommended"]:
        raise GeminiError("INVALID_RESPONSE")
    log.info("Gemini trip plan: %d request(s), tools=%s", requests, ",".join(toolbox.calls) or "none")
    _plan_cache_put(key, result)
    return result, False


async def plan_trip_agent(request: TripPlanRequest, plan: str = "free") -> TripPlanResponse:
    """
    Plans a trip with Gemini as the decision maker:
      1. Gemini calls real backend tools (weather, hotels, activities, budget for
         Premium) via function calling, then returns the itinerary, the chosen
         hotel and the explanation as JSON, which is validated here.
      2. The response is built from the tools' real data (hotels, weather) plus
         Gemini's itinerary. Missing data is fetched directly by the server.
      3. Without Gemini (no key, error, invalid output) a clearly labelled
         template plan is returned (ai.generated_by="rules", ai.notice says why).

    `plan` is the SERVER-VERIFIED plan passed in by the route (never taken from
    the request body or from anything the user types). Premium features below
    are decided only by this value.
    """
    total_days = calculate_days(request.departure_date, request.return_date)
    plan = "premium" if plan == "premium" else "free"
    is_premium = plan == "premium"
    # The structured City/Country fields are authoritative; the free-text
    # destination is only used by older clients that don't send them.
    city = (request.destination_city or "").strip() or None
    country = (request.destination_country or "").strip() or None
    destination = compose_destination(city, country, request.destination)
    ctx = TripContext(destination=destination, city=city, country=country, check_in=request.departure_date,
                      check_out=request.return_date, nights=total_days, travelers=request.travelers,
                      purpose=request.purpose, stay_preference=request.stay_preference,
                      priorities=list(request.priorities or []), notes=request.notes,
                      total_budget=request.total_budget if is_premium else None)
    toolbox = AgentToolbox(ctx, plan, allow_products=True)

    ai_result, from_cache, notice = None, False, None
    try:
        ai_result, from_cache = await _ai_plan(request, ctx, toolbox, plan, total_days)
    except GeminiError as err:
        notice = err.message
        if err.code != "NOT_CONFIGURED":
            log.warning("AI trip planning unavailable: %s", err.code)

    # Real data for the response: what the agent's tools fetched, else fetched now.
    if toolbox.hotel_lists:
        hotel_ids = toolbox.hotel_lists[-1] or toolbox.hotel_lists[0]
        hotels = [toolbox.hotels[i] for i in hotel_ids]
    else:
        query = (ai_result or {}).get("hotel_query") or {}
        hotels = await toolbox.fetch_hotels(query.get("sort_by"), query.get("max_price"))
    if not hotels:  # filters removed everything: fall back to the unfiltered list
        hotels = await toolbox.fetch_hotels()
    weather_data = toolbox.weather or await get_weather_forecast(destination, days=min(total_days, 10))

    chosen_id = (ai_result or {}).get("recommended_hotel_id")
    recommended_hotel = toolbox.hotels.get(chosen_id) if chosen_id else None
    if recommended_hotel is None or recommended_hotel.id not in {h.id for h in hotels}:
        recommended_hotel = hotels[0]
    if ai_result:
        hotels = [h.model_copy(update={"is_best_match": h.id == recommended_hotel.id}) for h in hotels]
        recommended_hotel = next(h for h in hotels if h.id == recommended_hotel.id)

    # Travel products: Gemini's Channel3 searches and picks (links Premium-only, server-side)
    travel_essentials, essentials_info = await _travel_essentials(ai_result, toolbox, plan)

    # Budget (Premium only: Budget Snapshot / Estimated Cost are not sent to Free)
    budget_breakdown = None
    if is_premium:
        budget_breakdown = optimize_budget(
            destination=destination,
            duration_days=total_days,
            travelers=request.travelers,
            total_budget=request.total_budget,
            currency="USD",  # all prices and budgets are in US dollars
            selected_hotel_total=recommended_hotel.total_price,
            stay_preference=request.stay_preference,
            plan=plan
        ).breakdown

    if ai_result:
        itinerary = [ItineraryDay(**d) for d in ai_result["itinerary"]]
        summary, why = ai_result["summary"], ai_result["why_recommended"]
        ai_info = AgentInfo(generated_by="gemini", model=ai_result.get("model"),
                            tools_used=ai_result.get("tools_used") or [], cached=from_cache)
    else:
        itinerary = generate_destination_itinerary(
            destination=destination, purpose=request.purpose, days=total_days,
            start_date_str=request.departure_date, priorities=request.priorities)
        if recommended_hotel.is_placeholder and recommended_hotel.data_source == "serpapi":
            stay_phrase = "live hotel listings couldn't be shown for your dates (see the Stay section)"
        elif recommended_hotel.is_placeholder:
            stay_phrase = (f"we don't have verified hotels there yet, so search Booking.com for "
                           f"'{request.stay_preference}' options")
        else:
            stay_phrase = f"the suggested stay is {recommended_hotel.name}"
        summary = f"A basic {total_days}-day {request.purpose.lower()} template for {destination}."
        why = f"Template plan (not AI-personalized): {stay_phrase}."
        ai_info = AgentInfo(generated_by="rules", notice=notice)

    return TripPlanResponse(
        trip_id=f"trip-{uuid.uuid4().hex[:8]}",
        destination=destination,
        destination_city=city,
        destination_country=country,
        departure_date=request.departure_date,
        return_date=request.return_date,
        total_days=total_days,
        travelers=request.travelers,
        purpose=request.purpose,
        stay_preference=request.stay_preference,
        plan_tier="premium" if is_premium else "free",
        match_score=None,
        destination_summary=summary,
        why_recommended=why,
        weather=weather_data,
        recommended_hotel=recommended_hotel,
        all_hotels=hotels,
        itinerary=itinerary,
        budget_breakdown=budget_breakdown,
        travel_essentials=travel_essentials,
        is_premium=is_premium,
        ai=ai_info,
        essentials=essentials_info,
    )


# ------------------------------------------------------------------ chat ---
def _chat_context(req: TripChatRequest) -> Optional[ChatTripContext]:
    if not req.current_trip_context:
        return None
    try:
        return ChatTripContext.model_validate(req.current_trip_context)
    except ValidationError:
        return None  # older clients send a loose summary: chat works, tools don't


def _chat_prompt(trip: Optional[ChatTripContext], message: str, plan: str) -> str:
    if trip is None:
        return f"User message: {message}"
    compact = {
        "destination": trip.destination, "dates": f"{trip.departure_date} to {trip.return_date}",
        "travelers": trip.travelers, "purpose": trip.purpose, "stay_preference": trip.stay_preference,
        "priorities": trip.priorities[:6], "notes": _clip(trip.notes, 300) if trip.notes else None,
        "budget_usd": trip.total_budget if plan == "premium" else None,
        "current_hotel": trip.recommended_hotel.model_dump(exclude_none=True) if trip.recommended_hotel else None,
        "itinerary": [{"day": d.day_number, "theme": d.theme,
                       "activities": [f"{a.time or ''} {a.title}".strip() for a in d.activities]}
                      for d in trip.itinerary],
    }
    compact = {k: v for k, v in compact.items() if v not in (None, [], "")}
    return f"Current trip: {json.dumps(compact, ensure_ascii=False)}\nUser message: {message}"


def _history_contents(history) -> list:
    from google.genai import types

    out = []
    for msg in (history or [])[-HISTORY_MESSAGES:]:
        text = _clip(msg.content, 800)
        if text:
            role = "model" if msg.role == "assistant" else "user"
            out.append(types.Content(role=role, parts=[types.Part(text=text)]))
    return out


async def chat_with_trip_agent(request: TripChatRequest, plan: str = "free") -> TripChatResponse:
    """
    Conversational trip refinement with Gemini and real tools (hotel search,
    activities, weather; budget for Premium), using the current trip, its
    itinerary and the recent conversation as context. Returns validated
    itinerary changes and hotel options the app can apply.

    `plan` is the server-verified plan from the route. The chat cannot unlock
    booking links or budget data, whatever the user's message claims.
    Without Gemini the reply says the assistant is unavailable; it never
    pretends to have changed anything.
    """
    plan = "premium" if plan == "premium" else "free"
    message = request.message.strip()
    trip = _chat_context(request)
    toolbox = None
    if trip:
        nights = calculate_days(trip.departure_date, trip.return_date)
        city = (trip.destination_city or "").strip() or None
        country = (trip.destination_country or "").strip() or None
        toolbox = AgentToolbox(TripContext(
            destination=compose_destination(city, country, trip.destination), city=city, country=country,
            check_in=trip.departure_date, check_out=trip.return_date, nights=nights, travelers=trip.travelers,
            purpose=trip.purpose, stay_preference=trip.stay_preference, priorities=list(trip.priorities),
            notes=trip.notes, total_budget=trip.total_budget if plan == "premium" else None), plan)

    try:
        gemini_client.check_available()
        data, requests = await run_agent(chat_system_prompt(plan, trip is not None),
                                         _chat_prompt(trip, message, plan), toolbox,
                                         history=_history_contents(request.history))
        reply = _clip(data.get("reply"), 2000)
        if not reply:
            raise GeminiError("INVALID_RESPONSE")
    except GeminiError as err:
        if err.code != "NOT_CONFIGURED":
            log.warning("AI chat unavailable: %s", err.code)
        return TripChatResponse(reply=f"The AI assistant is unavailable right now. {err.message}",
                                suggestions=[], tools_called=list(toolbox.calls) if toolbox else [],
                                generated_by="unavailable")

    suggestions = [_clip(s, 80) for s in (data.get("suggestions") or []) if isinstance(s, str) and s.strip()][:3]
    changes: List[ItineraryDay] = []
    if trip:
        existing = {d.day_number for d in trip.itinerary}
        seen = set()
        for raw in data.get("itinerary_changes") or []:
            day = _parse_day(raw, trip.departure_date)
            if day and day.day_number in existing and day.day_number not in seen:
                seen.add(day.day_number)
                changes.append(day)
    hotel_options: List[HotelItem] = []
    if toolbox and toolbox.hotel_lists:
        hotel_options = [toolbox.hotels[i] for i in toolbox.hotel_lists[-1] if not toolbox.hotels[i].is_placeholder][:6]
    suggested = str(data.get("suggested_hotel_id") or "") or None
    if suggested and suggested not in {h.id for h in hotel_options}:
        suggested = None
    log.info("Gemini chat: %d request(s), tools=%s", requests, ",".join(toolbox.calls) if toolbox else "none")
    return TripChatResponse(
        reply=reply,
        suggestions=suggestions,
        tools_called=list(toolbox.calls) if toolbox else [],
        generated_by="gemini",
        model=gemini_client.resolve_model(),
        updated_itinerary_days=changes,
        hotel_options=hotel_options,
        suggested_hotel_id=suggested,
    )
