"""
SerpApi Google Hotels client: real hotels, listed prices and provider booking links.

    GET https://serpapi.com/search.json?engine=google_hotels&q=<City, Country>
        &check_in_date=YYYY-MM-DD&check_out_date=YYYY-MM-DD&adults=N&currency=USD
        [&property_token=<id>]          (property details: provider links)

The API key comes only from settings.HOTEL_API_KEY (backend/.env). It is never
logged, returned or put in an error message. SerpApi only accepts it as a query
parameter, and httpx logs request URLs at INFO level, so httpx/httpcore logging
is capped at WARNING here.

Quota (free plan: 250 searches/month). Every SerpApi request is one search, so:
  * Results are cached in the app database (table hotel_api_cache), keyed by the
    exact search parameters, for settings.HOTEL_CACHE_TTL_HOURS. The cache
    survives page refreshes and backend restarts.
  * Identical requests that arrive while one is in flight share that request.
  * Failures are not cached. When a refresh fails, the last cached answer (kept
    for STALE_KEEP_SECONDS) is returned marked stale, with its checked time.
  * After an invalid-key or quota error, no request is sent for BLOCK_SECONDS.
  * Requests with impossible dates (past, or check-out not after check-in) are
    never sent.

Only data SerpApi returned is used. Missing fields stay None/empty; URLs are kept
only if they are absolute http(s) URLs exactly as returned (never constructed).
"""
import asyncio
import json
import logging
import time
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from app.core import database
from app.core.config import settings
from app.services.hotel_pricing import _num, _rates

log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

SERPAPI_URL = "https://serpapi.com/search.json"
CURRENCY = "USD"
STALE_KEEP_SECONDS = 14 * 24 * 60 * 60
BLOCK_SECONDS = 10 * 60
RATE_LIMIT_BLOCK_SECONDS = 60

ERROR_MESSAGES = {
    "NOT_CONFIGURED": "Live hotel search is not configured.",
    "INVALID_DATES": "The trip dates can't be searched (they must be today or later, "
                     "with check-out after check-in).",
    "INVALID_API_KEY": "The hotel search service rejected MYMILE's API key.",
    "QUOTA_EXHAUSTED": "MYMILE's monthly hotel search allowance has been used up.",
    "RATE_LIMITED": "The hotel search service is busy. Please try again in a minute.",
    "TIMEOUT": "The hotel search service took too long to answer.",
    "NETWORK": "MYMILE couldn't reach the hotel search service.",
    "INVALID_RESPONSE": "The hotel search service sent an unexpected response.",
    "PROVIDER_ERROR": "The hotel search service returned an error.",
}


class HotelApiError(Exception):
    """A failed live lookup. Carries only a code and a fixed, key-free message."""

    def __init__(self, code: str):
        self.code = code
        self.message = ERROR_MESSAGES.get(code, ERROR_MESSAGES["PROVIDER_ERROR"])
        super().__init__(f"{code}: {self.message}")


def api_key() -> str:
    return (settings.HOTEL_API_KEY or "").strip()


def is_enabled() -> bool:
    return bool(api_key())


def ttl_seconds() -> float:
    return max(float(settings.HOTEL_CACHE_TTL_HOURS or 0), 0.0) * 3600


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ guards ---
_blocked: Dict[str, Any] = {"until": 0.0, "code": None}


def _block(code: str) -> None:
    seconds = {"INVALID_API_KEY": BLOCK_SECONDS, "QUOTA_EXHAUSTED": BLOCK_SECONDS,
               "RATE_LIMITED": RATE_LIMIT_BLOCK_SECONDS}.get(code)
    if seconds:
        _blocked.update(until=time.time() + seconds, code=code)


def reset_guards() -> None:
    _blocked.update(until=0.0, code=None)
    _inflight.clear()


def validate_stay(check_in: str, check_out: str) -> Tuple[date, date]:
    try:
        ci, co = date.fromisoformat(str(check_in)), date.fromisoformat(str(check_out))
    except ValueError:
        raise HotelApiError("INVALID_DATES") from None
    today = datetime.now(timezone.utc).date()
    if co <= ci or ci < today - timedelta(days=1):  # 1 day of slack for time zones
        raise HotelApiError("INVALID_DATES")
    return ci, co


# --------------------------------------------------------------- transport ---
def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=float(settings.HOTEL_API_TIMEOUT_SECONDS or 15))


def _classify(status: int, body: Any) -> Optional[str]:
    """None = success. "EMPTY" = a valid answer with no hotels. Otherwise an error code."""
    error = body.get("error") if isinstance(body, dict) else None
    text = str(error or "").lower()
    if status == 200 and isinstance(body, dict) and not error:
        status_meta = str((body.get("search_metadata") or {}).get("status") or "").lower()
        return "PROVIDER_ERROR" if status_meta == "error" else None
    if "hasn't returned any results" in text or "no results" in text:
        return "EMPTY"
    if status == 401 or "invalid api key" in text:
        return "INVALID_API_KEY"
    if "run out of searches" in text or "out of searches" in text or "searches per month" in text:
        return "QUOTA_EXHAUSTED"
    if status == 429:
        return "RATE_LIMITED"
    if status == 200 and not isinstance(body, dict):
        return "INVALID_RESPONSE"
    return "PROVIDER_ERROR"


async def _call(params: Dict[str, Any]) -> dict:
    """One SerpApi request (= one search from the quota). Raises HotelApiError."""
    key = api_key()
    if not key:
        raise HotelApiError("NOT_CONFIGURED")
    if _blocked["until"] > time.time():
        raise HotelApiError(_blocked["code"])
    query = {"engine": "google_hotels", **params, "currency": CURRENCY, "gl": "us", "hl": "en",
             "api_key": key}
    try:
        async with _make_client() as client:
            resp = await client.get(SERPAPI_URL, params=query)
    except httpx.TimeoutException:
        log.warning("SerpApi Google Hotels request timed out")
        raise HotelApiError("TIMEOUT") from None  # `from None`: no chained text with the URL
    except httpx.HTTPError as exc:
        log.warning("SerpApi Google Hotels request failed: %s", type(exc).__name__)
        raise HotelApiError("NETWORK") from None
    try:
        body = resp.json()
    except ValueError:
        body = None
    code = _classify(resp.status_code, body)
    if code == "EMPTY":
        return {"properties": []}
    if code:
        _block(code)
        log.warning("SerpApi Google Hotels request failed: %s (HTTP %s)", code, resp.status_code)
        raise HotelApiError(code)
    return body


# ------------------------------------------------------------------- cache ---
_tables_ready: set = set()


def _db():
    conn = database.connect()
    path = str(database.DB_PATH)
    if path not in _tables_ready:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS hotel_api_cache ("
            " cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, checked_at REAL NOT NULL)"
        )
        conn.commit()
        _tables_ready.add(path)
    return conn


def cache_get(key: str) -> Optional[Tuple[float, Any]]:
    with closing(_db()) as conn:
        row = conn.execute("SELECT payload, checked_at FROM hotel_api_cache WHERE cache_key=?",
                           (key,)).fetchone()
    if not row or time.time() - row["checked_at"] > STALE_KEEP_SECONDS:
        return None
    return row["checked_at"], json.loads(row["payload"])


def _cache_put(key: str, payload: Any, checked_at: float) -> None:
    with closing(_db()) as conn:
        conn.execute("INSERT OR REPLACE INTO hotel_api_cache (cache_key, payload, checked_at) VALUES (?,?,?)",
                     (key, json.dumps(payload), checked_at))
        conn.execute("DELETE FROM hotel_api_cache WHERE checked_at < ?", (time.time() - STALE_KEEP_SECONDS,))
        conn.commit()


_inflight: Dict[str, "asyncio.Future"] = {}


async def _cached(key: str, fetch: Callable[[], Awaitable[Any]]) -> Tuple[Any, float, bool]:
    """(payload, checked_at, stale). Fresh cache -> no request; else one shared request;
    on failure the last cached payload (stale=True) or HotelApiError."""
    hit = cache_get(key)
    if hit and time.time() - hit[0] < ttl_seconds():
        return hit[1], hit[0], False

    task = _inflight.get(key)
    if task is None:
        async def run():
            try:
                payload = await fetch()
            except HotelApiError:
                raise
            except (TypeError, ValueError, AttributeError, KeyError):
                log.warning("SerpApi Google Hotels response could not be parsed")
                raise HotelApiError("INVALID_RESPONSE") from None
            checked = time.time()
            _cache_put(key, payload, checked)
            return payload, checked

        task = asyncio.ensure_future(run())
        _inflight[key] = task
        task.add_done_callback(lambda t, k=key: _inflight.pop(k, None) if _inflight.get(k) is t else None)
    try:
        payload, checked = await asyncio.shield(task)
    except HotelApiError:
        if hit:
            return hit[1], hit[0], True
        raise
    return payload, checked, False


# ----------------------------------------------------------- normalization ---
def _str(value) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def http_url(value) -> Optional[str]:
    """An absolute http(s) URL exactly as given, else None."""
    s = _str(value)
    if not s:
        return None
    parsed = urlparse(s)
    return s if parsed.scheme in ("http", "https") and parsed.netloc else None


def _int(value) -> Optional[int]:
    try:
        n = int(value)
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def _float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_offers(entries) -> List[dict]:
    """Provider offers (featured_prices / prices). One per provider; an entry with
    a URL wins over one without."""
    offers: List[dict] = []
    index: Dict[str, int] = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        provider = _str(entry.get("source"))
        if not provider:
            continue
        rates = _rates(entry) or {}
        free_cancel = entry.get("free_cancellation")
        offer = {
            "provider": provider,
            "url": http_url(entry.get("link")),
            "price_per_night": rates.get("nightly"),
            "total_price": rates.get("total"),
            "currency": CURRENCY,
            "official": entry.get("official") is True,
            "free_cancellation": free_cancel if isinstance(free_cancel, bool) else None,
        }
        k = provider.lower()
        if k in index:
            if offer["url"] and not offers[index[k]]["url"]:
                offers[index[k]] = offer
            continue
        index[k] = len(offers)
        offers.append(offer)
    return offers


def normalize_property(p) -> Optional[dict]:
    if not isinstance(p, dict):
        return None
    name = _str(p.get("name"))
    if not name:
        return None
    rates = _rates(p) or {}
    images: List[str] = []
    for img in p.get("images") or []:
        if isinstance(img, dict):
            url = http_url(img.get("original_image")) or http_url(img.get("thumbnail"))
            if url and url not in images:
                images.append(url)
    gps = p.get("gps_coordinates") if isinstance(p.get("gps_coordinates"), dict) else {}
    nearby = None
    for place in p.get("nearby_places") or []:
        if isinstance(place, dict) and _str(place.get("name")):
            nearby = place["name"].strip()
            moves = [t for t in place.get("transportations") or [] if isinstance(t, dict)]
            if moves and _str(moves[0].get("type")) and _str(moves[0].get("duration")):
                nearby += f" · {moves[0]['duration'].strip()} by {moves[0]['type'].strip().lower()}"
            break
    entries = [*(p.get("featured_prices") or []), *(p.get("prices") or [])]
    return {
        "name": name,
        "property_token": _str(p.get("property_token")),
        "type": _str(p.get("type")),
        "description": _str(p.get("description")),
        "address": _str(p.get("address")),
        "phone": _str(p.get("phone")),
        "website": http_url(p.get("link")),
        "rating": _num(p.get("overall_rating")),
        "reviews": _int(p.get("reviews")),
        "hotel_class": _str(p.get("hotel_class")),
        "extracted_hotel_class": _int(p.get("extracted_hotel_class")),
        "amenities": [a.strip() for a in (p.get("amenities") or []) if _str(a)][:12],
        "images": images[:8],
        "latitude": _float(gps.get("latitude")),
        "longitude": _float(gps.get("longitude")),
        "nearby": nearby,
        "nightly": rates.get("nightly"),
        "total": rates.get("total"),
        "taxes_included": rates.get("taxes_included"),
        "offers": parse_offers(entries),
    }


def parse_search(body: dict) -> List[dict]:
    """A list of properties, or the single property SerpApi returns when the query
    matches one hotel exactly."""
    if isinstance(body.get("properties"), list):
        props = body["properties"]
    elif _str(body.get("name")):
        props = [body]
    else:
        props = []
    return [n for n in (normalize_property(p) for p in props) if n]


def select_offer(offers: List[dict]) -> Optional[dict]:
    """Booking.com when it has a URL; else the cheapest provider with a URL; else the
    first provider with a URL. None when no provider URL was returned."""
    linked = [o for o in offers or [] if o.get("url")]
    for offer in linked:
        if "booking.com" in offer["provider"].lower():
            return offer
    priced = [o for o in linked if o.get("price_per_night")]
    if priced:
        return min(priced, key=lambda o: o["price_per_night"])
    return linked[0] if linked else None


# --------------------------------------------------------------- public API ---
def search_key(q: str, check_in: str, check_out: str, adults: int) -> str:
    return f"search|{' '.join(q.lower().split())}|{check_in}|{check_out}|{int(adults)}|{CURRENCY}"


def details_key(token: str, check_in: str, check_out: str, adults: int) -> str:
    return f"details|{token}|{check_in}|{check_out}|{int(adults)}|{CURRENCY}"


async def search_hotels(q: str, check_in: str, check_out: str, adults: int) -> dict:
    """{"properties": [...], "checked_at": epoch, "stale": bool}. Raises HotelApiError."""
    if not is_enabled():
        raise HotelApiError("NOT_CONFIGURED")
    validate_stay(check_in, check_out)
    adults = max(int(adults or 1), 1)

    async def fetch():
        body = await _call({"q": q, "check_in_date": check_in, "check_out_date": check_out,
                            "adults": adults})
        return parse_search(body)

    props, checked, stale = await _cached(search_key(q, check_in, check_out, adults), fetch)
    return {"properties": props, "checked_at": checked, "stale": stale}


def cached_search(q: str, check_in: str, check_out: str, adults: int) -> Optional[dict]:
    """A previous search from the cache (fresh or stale). Never sends a request."""
    hit = cache_get(search_key(q, check_in, check_out, max(int(adults or 1), 1)))
    if not hit:
        return None
    return {"properties": hit[1], "checked_at": hit[0]}


async def property_details(token: str, q: str, check_in: str, check_out: str, adults: int) -> dict:
    """{"property": normalized|None, "checked_at", "stale"}. Raises HotelApiError."""
    if not is_enabled():
        raise HotelApiError("NOT_CONFIGURED")
    validate_stay(check_in, check_out)
    adults = max(int(adults or 1), 1)

    async def fetch():
        body = await _call({"q": q, "check_in_date": check_in, "check_out_date": check_out,
                            "adults": adults, "property_token": token})
        return normalize_property(body)

    prop, checked, stale = await _cached(details_key(token, check_in, check_out, adults), fetch)
    return {"property": prop, "checked_at": checked, "stale": stale}
