import datetime
import hashlib
import json
import logging
import time
import uuid
from contextlib import closing
from typing import Dict, List, Optional, Tuple

from pydantic import ValidationError

from app.agents import llm
from app.agents.agent_loop import run_agent
from app.agents.llm_errors import LLMError
from app.agents.prompts import chat_system_prompt, plan_system_prompt
from app.agents.tools import AgentToolbox, TripContext
from app.core import database
from app.core.config import settings
from app.core.destinations import compose_destination
from app.schemas.hotel_schema import HotelItem
from app.schemas.trip_schema import (
    AgentInfo,
    EssentialsInfo,
    ChatTripContext,
    TripChatRequest,
    TripChatResponse,
    TripPlanRequest,
    TripPlanResponse,
)
from app.services.budget_service import optimize_budget
from app.services import channel3_service, trip_shopping
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

HISTORY_MESSAGES = 8


def _clip(value, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


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
    raw = json.dumps({"req": request.model_dump(), "plan": plan, "provider": llm.provider(),
                      "model": llm.resolve_model(), "v": 4}, sort_keys=True, default=str)
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
def _shopping_context(ctx: TripContext, weather=None) -> dict:
    """Structured product-discovery context from every Plan a Trip field (budget only when
    the server passed it, i.e. Premium with a budget)."""
    return trip_shopping.shopping_context(
        purpose=ctx.purpose, check_in=ctx.check_in, check_out=ctx.check_out, nights=ctx.nights,
        travelers=ctx.travelers, description=ctx.notes, total_budget=ctx.total_budget,
        max_searches=channel3_service.max_queries_per_trip(), weather=weather, audience=ctx.shopping_audience)


def _trip_prompt(ctx: TripContext, is_premium: bool, tool_data: Optional[dict] = None,
                 shopping: Optional[dict] = None) -> str:
    trip = {
        "destination": ctx.destination, "city": ctx.city, "country": ctx.country,
        "check_in": ctx.check_in, "check_out": ctx.check_out,
        "nights": ctx.nights, "travelers": ctx.travelers, "purpose": ctx.purpose,
        "stay_preference": ctx.stay_preference, "priorities": ctx.priorities[:6],
        # The traveler's own description: the primary source for product needs.
        "trip_description": _clip(ctx.notes, DESCRIPTION_MAX) if ctx.notes else None,
        "total_budget_usd": ctx.total_budget if is_premium else None,
    }
    prompt = "Plan this trip:\n" + json.dumps({k: v for k, v in trip.items() if v not in (None, [], "")})
    if shopping:  # product discovery context (compact JSON: no spaces)
        prompt += "\nshopping: " + json.dumps(shopping, ensure_ascii=False, separators=(",", ":"))
    if tool_data:  # results of the server-side prefetch (compact JSON: no spaces)
        prompt += "\ntool_data: " + json.dumps(tool_data, ensure_ascii=False, separators=(",", ":"), default=str)
    return prompt


DESCRIPTION_MAX = 500  # characters; same limit as the Plan a Trip form

# A response-size safeguard, not a target: the model includes every genuinely useful
# product it found (and none that aren't), aiming for about 10.
MAX_ESSENTIALS = 24
MAX_MISSING_CATEGORIES = 10
# Category coverage: a category never fills the list for missing ones. 2 per category,
# 3 once at least COVERAGE_FOR_MORE categories have products; one per brand per category;
# no close variants of the same item within a category.
MAX_PER_CATEGORY = 2
MAX_PER_CATEGORY_COVERED = 3
COVERAGE_FOR_MORE = 4
MAX_PER_PRODUCT_TYPE = 2  # same Channel3 product type (e.g. "Travel Plug Adapters") within a category


def _per_category_cap(groups: int) -> int:
    return MAX_PER_CATEGORY_COVERED if groups >= COVERAGE_FOR_MORE else MAX_PER_CATEGORY


def _parse_essentials(raw, toolbox: AgentToolbox) -> List[dict]:
    """The model's picks, kept only when the product id really came from Channel3 (and passed
    the search's relevance guard). Reasons claiming unverified attributes are dropped."""
    picks, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("product_id") or "")
        if pid not in toolbox.products or pid in seen:
            continue
        seen.add(pid)
        product, meta = toolbox.products[pid], toolbox.product_meta.get(pid, {})
        searched_for = meta.get("audience") if meta.get("audience") in ("men", "women") else None
        per_traveler = item.get("per_traveler")
        picks.append({
            "product_id": pid,
            # The category the product was searched (and checked) for, not a label the AI
            # may attach afterwards, so a product always matches the category it is shown in.
            "group": (meta.get("category") or trip_shopping.category_name(item.get("category"))
                      or trip_shopping.category_name(product.get("category")) or "Travel essentials"),
            # What the product says beats the search's label; "all" only when unisex or unknown.
            "audience": trip_shopping.infer_audience(product) or searched_for or "all",
            "per_traveler": per_traveler if isinstance(per_traveler, bool) else None,
            "reason": trip_shopping.safe_reason(_clip(item.get("reason"), 160) or None, product),
        })
    # No near-identical products (same item in another pack size or color) ...
    distinct: List[dict] = []
    for pick in picks:
        product = toolbox.products[pick["product_id"]]
        if not any(trip_shopping.is_near_duplicate(product, toolbox.products[d["product_id"]]) for d in distinct):
            distinct.append(pick)
    # ... and no category crowding out the others, repeating a brand, or listing close variants.
    # While a product the traveler named is still uncovered, no need gets more than 2 options.
    cap = _per_category_cap(len({p["group"].lower() for p in distinct}))
    if _uncovered_named(toolbox):
        cap = min(cap, MAX_PER_CATEGORY)
    by_group: Dict[str, List[dict]] = {}
    kept: List[dict] = []
    for pick in distinct:
        group = pick["group"].lower()
        product = toolbox.products[pick["product_id"]]
        in_group = by_group.get(group, [])
        if len(in_group) >= cap:
            continue
        chosen = [toolbox.products[p["product_id"]] for p in in_group]
        # Functionally alike items (same Channel3 product type) are limited too.
        kind = (product.get("category") or "").strip().lower()
        if kind and sum((o.get("category") or "").strip().lower() == kind for o in chosen) >= MAX_PER_PRODUCT_TYPE:
            continue
        # Brand and similarity limits: an explicit men's item and women's item are different
        # products; "all" (unisex or unknown) competes with both.
        rivals = [toolbox.products[p["product_id"]] for p in in_group
                  if p["audience"] == pick["audience"] or "all" in (p["audience"], pick["audience"])]
        if any(trip_shopping.same_brand(product, other) or trip_shopping.is_similar(product, other)
               for other in rivals):
            continue
        by_group.setdefault(group, []).append(pick)
        kept.append(pick)
    return kept[:MAX_ESSENTIALS]


def _uncovered_named(toolbox: AgentToolbox) -> List[str]:
    """Named products (from the description) that no search found a relevant product for."""
    found = [r for r in toolbox.product_searches if r["found"]]
    return [n["category"] for n in trip_shopping.named_products(toolbox.ctx.notes)
            if not any(trip_shopping.search_covers_need(r["category"], r["query"], n) for r in found)]


def _declared_missing(raw) -> List[str]:
    """The model's missing_categories, validated (a list of short names)."""
    names = [trip_shopping.category_name(x) for x in raw if isinstance(x, str)] if isinstance(raw, list) else []
    return [n for n in names if n][:MAX_MISSING_CATEGORIES]


# How each state is worded for the traveler (the UI uses the same words).
MISSING_WORDING = (
    ("not_found", "No relevant options were found for: {}."),
    ("not_selected", "Relevant options were found but not selected for: {}."),
    ("not_searched", "Not searched (the search limit was reached) for: {}."),
)


def _missing_details(picks: List[dict], toolbox: AgentToolbox) -> List[dict]:
    """Trip needs with no product shown, each with its state: not_searched, not_found (a search
    ran, no product passed the filters) or not_selected (products passed, the AI chose none).
    Only needs this trip really has: categories actually searched (refused searches never count)
    and products the traveler named (unless refused for the trip's purpose). The AI's own
    "missing" list can't add a category."""
    covered = {p["group"].lower() for p in picks}
    covered |= {(toolbox.product_meta.get(p["product_id"], {}).get("category") or "").lower() for p in picks}
    picked_from = [toolbox.product_meta.get(p["product_id"], {}) for p in picks]
    details: List[dict] = []

    def state_of(records: List[dict]) -> str:
        if not records:
            return "not_searched"
        return "not_selected" if any(r["found"] for r in records) else "not_found"

    # Named needs first, under the traveler's own word ("Computer Mouse", even when the search
    # that covered it was filed as "Work Electronics"), so one need is reported once.
    attributed = set()
    for need in trip_shopping.named_products(toolbox.ctx.notes):
        if trip_shopping.purpose_conflict(toolbox.ctx.purpose, toolbox.ctx.notes, need["query"], need["category"]):
            continue
        records = [r for r in toolbox.product_searches
                   if trip_shopping.search_covers_need(r.get("category"), r.get("query"), need)]
        attributed |= {id(r) for r in records}
        # Covered when a picked product came from a search for it (category OR query overlap).
        if any(trip_shopping.search_covers_need(m.get("category"), m.get("query"), need) for m in picked_from):
            continue
        details.append({"category": need["category"], "state": state_of(records)})
    for name in dict.fromkeys(r["category"] for r in toolbox.product_searches if r.get("category")):
        if name.lower() in covered or any(trip_shopping.same_category(name, d["category"]) for d in details):
            continue
        records = [r for r in toolbox.product_searches if (r.get("category") or "").lower() == name.lower()]
        if all(id(r) in attributed for r in records):
            continue  # already reported (or covered) as the named need it searched for
        details.append({"category": name, "state": state_of(records)})
    return details[:MAX_MISSING_CATEGORIES]


def _missing_categories(declared, picks: List[dict], toolbox: AgentToolbox) -> List[str]:
    """Names of the trip needs with no product shown (see _missing_details for why)."""
    return [d["category"] for d in _missing_details(picks, toolbox)]


def _missing_message(details: List[dict]) -> Optional[str]:
    parts = [text.format(", ".join(d["category"] for d in details if d["state"] == state))
             for state, text in MISSING_WORDING if any(d["state"] == state for d in details)]
    return " ".join(parts) or None


async def _travel_essentials(ai_result: Optional[dict], toolbox: AgentToolbox, plan: str):
    """(products with Premium-only links, EssentialsInfo). Only genuine Channel3 products the
    AI judged relevant; never unvetted search results."""
    if not channel3_service.is_enabled():
        return [], EssentialsInfo(status="not_configured", message="Travel product suggestions aren't set up yet.")
    if not ai_result:
        return [], EssentialsInfo(status="ai_unavailable",
                                  message="Personalized product suggestions need the AI planner.")
    queries = ai_result.get("product_queries") or []
    searches = ai_result.get("product_searches") or queries
    if searches and not toolbox.products:  # cached AI plan: re-read the searches (served from cache)
        await toolbox.fetch_products(searches)
    picks = [p for p in ai_result.get("essentials") or [] if p["product_id"] in toolbox.products]
    order: Dict[str, int] = {}
    for p in picks:  # keep the model's priority order, with each category together
        order.setdefault(p.get("group") or "", len(order))
    picks.sort(key=lambda p: order[p.get("group") or ""])
    items = [channel3_service.to_item(toolbox.products[p["product_id"]], p.get("reason")).model_copy(update={
        "group": p.get("group"), "audience": p.get("audience"), "per_traveler": p.get("per_traveler")})
        for p in picks]
    details = _missing_details(picks, toolbox)
    missing = [d["category"] for d in details]
    error = toolbox.product_error or ai_result.get("product_error")
    if items:
        info = EssentialsInfo(status="ok", queries=queries, missing=missing, missing_detail=details,
                              message=_missing_message(details))
    elif error:
        info = EssentialsInfo(status="unavailable", queries=queries, missing=missing, missing_detail=details,
                              message=channel3_service.ERROR_MESSAGES.get(error))
    elif toolbox.products:
        info = EssentialsInfo(status="empty", queries=queries, missing=missing, missing_detail=details,
                              message="Relevant products were found, but none were selected for this trip.")
    else:
        info = EssentialsInfo(status="empty", queries=queries, missing=missing, missing_detail=details,
                              message="No matching products were found.")
    response = channel3_service.apply_purchase_link_policy(
        ProductSearchResponse(query_context=", ".join(queries), products=items), plan)
    return response.products, info


async def _ai_plan(request: TripPlanRequest, ctx: TripContext, toolbox: AgentToolbox, plan: str,
                   total_days: int) -> Tuple[dict, bool]:
    """(AI result, from_cache). Raises LLMError."""
    llm.check_available()
    key = _plan_cache_key(request, plan)
    cached = _plan_cache_get(key)
    if cached:
        return cached, True
    # Groq (8K tokens/minute on the free plan, one tool call per turn with gpt-oss):
    # the server fetches weather and hotels first, so the model only calls the
    # Channel3 product search.
    tool_data = await toolbox.prefetch() if llm.provider() == "groq" else None
    data, requests = await run_agent(
        plan_system_prompt(plan, toolbox.allow_products, prefetched=tool_data is not None),
        _trip_prompt(ctx, plan == "premium", tool_data,
                     _shopping_context(ctx, toolbox.weather) if toolbox.allow_products else None), toolbox)
    result = {
        "summary": _clip(data.get("summary"), 400),
        "why_recommended": _clip(data.get("why_recommended"), 700),
        "recommended_hotel_id": str(data.get("recommended_hotel_id") or "") or None,
        "tools_used": list(dict.fromkeys(toolbox.calls)),
        "hotel_query": toolbox.last_hotel_query,
        "provider": llm.provider(),
        "model": llm.resolve_model(),
        # Channel3: the searches the model ran and the products it picked (ids, groups, reasons).
        "product_queries": list(toolbox.product_queries),
        "product_searches": [{"query": r["query"], "category": r["category"], "audience": r["audience"]}
                             for r in toolbox.product_searches],
        "essentials": _parse_essentials(data.get("essentials"), toolbox),
        "missing_categories": _declared_missing(data.get("missing_categories")),
        "product_error": toolbox.product_error,
    }
    if not result["summary"] or not result["why_recommended"]:
        raise llm.error("INVALID_RESPONSE")
    log.info("AI trip plan (%s): %d request(s), tools=%s", llm.provider(), requests,
             ",".join(toolbox.calls) or "none")
    _plan_cache_put(key, result)
    return result, False


async def plan_trip_agent(request: TripPlanRequest, plan: str = "free") -> TripPlanResponse:
    """
    Plans a trip with the LLM (Groq by default, Gemini if LLM_PROVIDER=gemini) as
    the decision maker:
      1. The model works from real backend tools (weather and hotels; with Groq
         these are fetched by the server before the first request), calls the
         Channel3 product search via function calling, then returns the summary,
         the chosen hotel, the explanation and its product picks as JSON, which is
         validated here. (There is no day-by-day itinerary.)
      2. The response is built from the tools' real data (hotels, weather) plus
         the model's text and picks. Missing data is fetched directly by the server.
      3. Without the AI (no key, error, invalid output) a clearly labelled
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
                      total_budget=request.total_budget if is_premium else None,
                      shopping_audience=trip_shopping.shopping_audience(request.shopping_audience))
    # No budget tool in planning: the Premium breakdown below is computed by the server.
    toolbox = AgentToolbox(ctx, plan, allow_products=True, allow_budget=False)

    ai_result, from_cache, notice = None, False, None
    try:
        ai_result, from_cache = await _ai_plan(request, ctx, toolbox, plan, total_days)
    except LLMError as err:
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

    # Travel products: the model's Channel3 searches and picks (links Premium-only, server-side)
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
        summary, why = ai_result["summary"], ai_result["why_recommended"]
        ai_info = AgentInfo(generated_by=ai_result.get("provider") or "gemini", model=ai_result.get("model"),
                            tools_used=ai_result.get("tools_used") or [], cached=from_cache)
    else:
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
        shopping_audience=trip_shopping.shopping_audience(request.shopping_audience),
        plan_tier="premium" if is_premium else "free",
        match_score=None,
        destination_summary=summary,
        why_recommended=why,
        weather=weather_data,
        recommended_hotel=recommended_hotel,
        all_hotels=hotels,
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
    }
    compact = {k: v for k, v in compact.items() if v not in (None, [], "")}
    return f"Current trip: {json.dumps(compact, ensure_ascii=False)}\nUser message: {message}"


def _history_contents(history) -> list:
    """Recent conversation, provider-neutral (the agent loop converts it per provider)."""
    out = []
    for msg in (history or [])[-HISTORY_MESSAGES:]:
        text = _clip(msg.content, 800)
        if text:
            out.append({"role": "assistant" if msg.role == "assistant" else "user", "content": text})
    return out


async def chat_with_trip_agent(request: TripChatRequest, plan: str = "free") -> TripChatResponse:
    """
    Conversational trip refinement with the LLM and real tools (hotel search,
    weather; budget for Premium), using the current trip and the recent
    conversation as context. Returns validated hotel options the app can apply.

    `plan` is the server-verified plan from the route. The chat cannot unlock
    booking links or budget data, whatever the user's message claims.
    Without the AI the reply says the assistant is unavailable; it never
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
        llm.check_available()
        data, requests = await run_agent(chat_system_prompt(plan, trip is not None),
                                         _chat_prompt(trip, message, plan), toolbox,
                                         history=_history_contents(request.history))
        reply = _clip(data.get("reply"), 2000)
        if not reply:
            raise llm.error("INVALID_RESPONSE")
    except LLMError as err:
        if err.code != "NOT_CONFIGURED":
            log.warning("AI chat unavailable: %s", err.code)
        return TripChatResponse(reply=f"The AI assistant is unavailable right now. {err.message}",
                                suggestions=[], tools_called=list(toolbox.calls) if toolbox else [],
                                generated_by="unavailable")

    suggestions = [_clip(s, 80) for s in (data.get("suggestions") or []) if isinstance(s, str) and s.strip()][:3]
    hotel_options: List[HotelItem] = []
    if toolbox and toolbox.hotel_lists:
        hotel_options = [toolbox.hotels[i] for i in toolbox.hotel_lists[-1] if not toolbox.hotels[i].is_placeholder][:6]
    suggested = str(data.get("suggested_hotel_id") or "") or None
    if suggested and suggested not in {h.id for h in hotel_options}:
        suggested = None
    log.info("AI chat (%s): %d request(s), tools=%s", llm.provider(), requests, ",".join(toolbox.calls) if toolbox else "none")
    return TripChatResponse(
        reply=reply,
        suggestions=suggestions,
        tools_called=list(toolbox.calls) if toolbox else [],
        generated_by=llm.provider(),
        model=llm.resolve_model(),
        hotel_options=hotel_options,
        suggested_hotel_id=suggested,
    )
