"""
Prices currently listed for a hotel for the traveler's exact dates and group size.

Provider: SerpApi's Google Hotels engine (https://serpapi.com/google-hotels-api).
Google Hotels lists the prices each booking site charges, so we prefer the Booking.com
price when it is there.

Enable it by putting a SerpApi key in backend/.env:
    HOTEL_API_KEY=<your SerpApi key>
Without a key (or if the lookup fails) hotels keep MYMILE's estimated price.

What a "listed" price is (and is not):
  * It is what the booking site shows Google Hotels for these dates and up to two
    adults per room, at the time we fetched it (price_checked_at).
  * It is NOT a confirmed, bookable rate: availability and price can change, and
    the booking site may add taxes/fees we cannot see.
  * rate_per_night.extracted_lowest is the price with taxes/fees as listed;
    extracted_before_taxes_fees is without. We mark taxes_included=True only when
    both are present and differ; otherwise it stays unknown (None).
  * When Google Hotels returns a total for the whole stay (total_rate) we use it,
    instead of multiplying one nightly rate (rates can differ night to night).
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx

from app.core.config import settings
from app.schemas.hotel_schema import HotelItem

log = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search.json"
CACHE_TTL_SECONDS = 60 * 60  # prices don't need to be re-fetched more than hourly
# key: (hotel name, location hint, check-in, check-out, adults per room)
_cache: Dict[Tuple[str, str, str, str, int], Tuple[float, Optional[dict]]] = {}


def live_pricing_enabled() -> bool:
    return bool(settings.HOTEL_API_KEY)


def _num(value) -> Optional[float]:
    try:
        n = float(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _rates(entry: dict) -> Optional[dict]:
    """{nightly, total (whole stay, per room) or None, taxes_included or None}."""
    nightly_info = entry.get("rate_per_night") or {}
    total_info = entry.get("total_rate") or {}
    with_taxes = _num(nightly_info.get("extracted_lowest"))
    before_taxes = _num(nightly_info.get("extracted_before_taxes_fees"))
    nightly = with_taxes or before_taxes
    if nightly is None:
        return None
    if with_taxes and before_taxes:
        taxes_included = True if with_taxes > before_taxes else None
    elif before_taxes and not with_taxes:
        taxes_included = False
    else:
        taxes_included = None
    total = (_num(total_info.get("extracted_lowest")) if with_taxes
             else _num(total_info.get("extracted_before_taxes_fees")))
    return {"nightly": nightly, "total": total, "taxes_included": taxes_included}


def _price_from_offers(offers: List[dict]) -> Optional[dict]:
    """Prefer Booking.com's offer; otherwise the cheapest listed offer."""
    best: Optional[dict] = None
    for offer in offers or []:
        rates = _rates(offer)
        if rates is None:
            continue
        source = offer.get("source") or "Google Hotels"
        found = {**rates, "source": "Booking.com" if "booking.com" in source.lower() else source}
        if found["source"] == "Booking.com":
            return found
        if best is None or found["nightly"] < best["nightly"]:
            best = found
    return best


def _names_match(a: str, b: str) -> bool:
    words = lambda s: {w for w in "".join(c.lower() if c.isalnum() else " " for c in s).split() if len(w) > 2}
    wa, wb = words(a), words(b)
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def _extract_price(data: dict, hotel_name: str) -> Optional[dict]:
    # Exact hotel match: SerpApi returns that property's details at the top level.
    if data.get("name") and _names_match(data["name"], hotel_name):
        found = _price_from_offers(data.get("prices", [])) or _price_from_offers(
            data.get("featured_prices", [])
        )
        if found:
            return found
        own = _rates(data)
        if own:
            return {**own, "source": "Google Hotels"}

    # Otherwise a list of properties: use the one whose name matches ours.
    for prop in data.get("properties", []) or []:
        if _names_match(prop.get("name", ""), hotel_name):
            rates = _rates(prop)
            if rates:
                return {**rates, "source": "Google Hotels"}
    return None


async def _fetch_price(
    client: httpx.AsyncClient, hotel_name: str, location: str, check_in: str, check_out: str, adults: int
) -> Optional[dict]:
    adults_per_room = min(adults, 2)  # price is per room; rooms are multiplied in later
    key = (hotel_name, location, check_in, check_out, adults_per_room)
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    params = {
        "engine": "google_hotels",
        "q": f"{hotel_name} {location}".strip(),
        "check_in_date": check_in,
        "check_out_date": check_out,
        "adults": adults_per_room,
        "currency": "USD",
        "gl": "us",
        "hl": "en",
        "api_key": settings.HOTEL_API_KEY,
    }
    try:
        resp = await client.get(SERPAPI_URL, params=params)
        resp.raise_for_status()
        result = _extract_price(resp.json(), hotel_name)
    except Exception as exc:  # network error, quota, bad key... fall back to the estimate
        log.warning("Listed price lookup failed for %s: %s", hotel_name, type(exc).__name__)
        return None
    checked = time.time()
    if result is not None:
        result = {**result, "checked_at": datetime.fromtimestamp(checked, timezone.utc).isoformat(timespec="seconds")}
    _cache[key] = (checked, result)
    return result


async def apply_live_prices(
    hotels: List[HotelItem],
    location_by_id: Dict[str, str],
    check_in: str,
    check_out: str,
    adults: int,
    nights: int,
    rooms: int,
) -> List[HotelItem]:
    """Replace estimated prices with listed ones where a lookup succeeds. All lookups run in parallel."""
    if not live_pricing_enabled() or not hotels:
        return hotels

    async with httpx.AsyncClient(timeout=8.0) as client:
        results = await asyncio.gather(
            *[
                _fetch_price(client, h.name, location_by_id.get(h.id, ""), check_in, check_out, adults)
                for h in hotels
            ]
        )

    for hotel, found in zip(hotels, results):
        if not found:
            continue
        hotel.price_per_night = round(found["nightly"], 2)
        stay_total = found.get("total") or found["nightly"] * nights
        hotel.total_price = round(stay_total * rooms, 2)
        hotel.price_source = "live"
        hotel.price_provider = found["source"]
        hotel.taxes_included = found.get("taxes_included")
        hotel.price_checked_at = found.get("checked_at")
    return hotels
