"""
Live hotel prices for the traveler's exact dates and group size.

Provider: SerpApi's Google Hotels engine (https://serpapi.com/google-hotels-api).
Google Hotels lists the prices each booking site charges, so we prefer the Booking.com
price when it is there. That's the same site the "See live price & book" button opens.

Enable it by putting a SerpApi key in backend/.env:
    HOTEL_API_KEY=<your SerpApi key>
Without a key (or if the lookup fails) hotels keep their estimated price.
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple

import httpx

from app.core.config import settings
from app.schemas.hotel_schema import HotelItem

log = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search.json"
CACHE_TTL_SECONDS = 60 * 60  # prices don't need to be re-fetched more than hourly
_cache: Dict[Tuple[str, str, str, int], Tuple[float, Optional[Tuple[float, str]]]] = {}


def live_pricing_enabled() -> bool:
    return bool(settings.HOTEL_API_KEY)


def _num(value) -> Optional[float]:
    try:
        n = float(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _rate(entry: dict) -> Optional[float]:
    rate = entry.get("rate_per_night") or {}
    return _num(rate.get("extracted_lowest")) or _num(rate.get("extracted_before_taxes_fees"))


def _price_from_offers(offers: List[dict]) -> Optional[Tuple[float, str]]:
    """Prefer Booking.com's price; otherwise the cheapest listed offer."""
    best: Optional[Tuple[float, str]] = None
    for offer in offers or []:
        price = _rate(offer)
        if price is None:
            continue
        source = offer.get("source") or "Google Hotels"
        if "booking.com" in source.lower():
            return price, "Booking.com"
        if best is None or price < best[0]:
            best = (price, source)
    return best


def _names_match(a: str, b: str) -> bool:
    words = lambda s: {w for w in "".join(c.lower() if c.isalnum() else " " for c in s).split() if len(w) > 2}
    wa, wb = words(a), words(b)
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def _extract_price(data: dict, hotel_name: str) -> Optional[Tuple[float, str]]:
    # Exact hotel match: SerpApi returns that property's details at the top level.
    if data.get("name") and _names_match(data["name"], hotel_name):
        found = _price_from_offers(data.get("prices", [])) or _price_from_offers(
            data.get("featured_prices", [])
        )
        if found:
            return found
        own = _rate(data)
        if own:
            return own, "Google Hotels"

    # Otherwise a list of properties: use the one whose name matches ours.
    for prop in data.get("properties", []) or []:
        if _names_match(prop.get("name", ""), hotel_name):
            price = _rate(prop)
            if price:
                return price, "Google Hotels"
    return None


async def _fetch_price(
    client: httpx.AsyncClient, hotel_name: str, city: str, check_in: str, check_out: str, adults: int
) -> Optional[Tuple[float, str]]:
    key = (hotel_name, check_in, check_out, adults)
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    params = {
        "engine": "google_hotels",
        "q": f"{hotel_name} {city}",
        "check_in_date": check_in,
        "check_out_date": check_out,
        "adults": min(adults, 2),  # price is per room; rooms are multiplied in later
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
        log.warning("Live price lookup failed for %s: %s", hotel_name, exc)
        return None
    _cache[key] = (time.time(), result)
    return result


async def apply_live_prices(
    hotels: List[HotelItem],
    city_by_id: Dict[str, str],
    check_in: str,
    check_out: str,
    adults: int,
    nights: int,
    rooms: int,
) -> List[HotelItem]:
    """Replace estimated prices with live ones where a lookup succeeds. All lookups run in parallel."""
    if not live_pricing_enabled() or not hotels:
        return hotels

    async with httpx.AsyncClient(timeout=8.0) as client:
        results = await asyncio.gather(
            *[
                _fetch_price(client, h.name, city_by_id.get(h.id, ""), check_in, check_out, adults)
                for h in hotels
            ]
        )

    for hotel, found in zip(hotels, results):
        if not found:
            continue
        nightly, source = found
        hotel.price_per_night = round(nightly, 2)
        hotel.total_price = round(nightly * nights * rooms, 2)
        hotel.price_source = "live"
        hotel.price_provider = source
    return hotels
