"""
Channel3 product search (official API: https://channel3.ai/docs).

    POST {CHANNEL3_BASE_URL}/v1/search          (base: https://api.trychannel3.com)
    header  x-api-key: <CHANNEL3_API_KEY>
    body    {"query": str, "limit": int (max 30), "config": {"currency": "USD", "country": "US"}}
    200 ->  {"products": [Product], "next_page_token": str | null}

A Product has id, title, description, brands[{id, name}], images[{url, is_main_image}],
category{title}, ratings{value, count}, variants{options[{name, values[{label, available}]}]}
and offers[{url, domain, price{price, compare_at_price, currency}, availability}].
There is no top-level price or link: those come from the offers.

Errors: 401 invalid/missing key, 402 credits used up, 422 invalid request,
429 rate limited (Retry-After), 5xx/504 service errors; body {"detail": ...}.

Rules:
  * Only data Channel3 returned is used. Missing fields stay None; nothing is invented.
  * Every search costs a credit: results are cached (CHANNEL3_CACHE_TTL_HOURS), identical
    searches in flight share one request, and limits are strict.
  * Failures raise Channel3Error with a fixed, key-free message. A failed refresh falls back
    to the last cached result. There is no fake catalog.
  * Purchase links are Premium-only (apply_purchase_link_policy), decided server-side.
"""
import asyncio
import json
import logging
import time
from contextlib import closing
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from app.core import database
from app.core.config import settings
from app.schemas.product_schema import ProductItem, ProductOffer, ProductSearchResponse

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.trychannel3.com"
# Earlier, undocumented guesses. Requests to them can't work, so they're replaced.
LEGACY_BASE_URLS = {"https://api.channel3.ai/v1", "https://api.channel3.ai"}
SEARCH_PATH = "/v1/search"
MAX_RESULTS_PER_QUERY = 10           # hard cap, whatever the configuration says
DEFAULT_RESULTS_PER_QUERY = 5        # enough candidates for ~10 products over 6 searches
MAX_QUERIES_PER_TRIP = 6             # hard cap on unique searches (= credits) per trip plan, follow-ups included
MAX_QUERY_LENGTH = 120
STALE_KEEP_SECONDS = 14 * 24 * 3600
LOCALE = {"currency": "USD", "country": "US"}

ERROR_MESSAGES = {
    "NOT_CONFIGURED": "Product search is not configured (CHANNEL3_API_KEY is empty).",
    "INVALID_API_KEY": "Channel3 rejected the configured API key.",
    "CREDITS_EXHAUSTED": "The Channel3 search credits have been used up.",
    "RATE_LIMITED": "Channel3 is rate limiting requests. Please try again shortly.",
    "INVALID_REQUEST": "Channel3 couldn't process this search.",
    "TIMEOUT": "Channel3 took too long to answer.",
    "NETWORK": "MYMILE couldn't reach Channel3.",
    "SERVICE_ERROR": "Channel3 returned an error. Please try again later.",
    "INVALID_RESPONSE": "Channel3 sent a response MYMILE couldn't read.",
}


class Channel3Error(Exception):
    def __init__(self, code: str):
        self.code = code
        self.message = ERROR_MESSAGES.get(code, ERROR_MESSAGES["SERVICE_ERROR"])
        super().__init__(f"{code}: {self.message}")


def api_key() -> str:
    return (settings.CHANNEL3_API_KEY or "").strip()


def is_enabled() -> bool:
    return bool(api_key())


def base_url() -> str:
    url = (settings.CHANNEL3_BASE_URL or "").strip().rstrip("/")
    if not url or url in LEGACY_BASE_URLS:
        if url:
            log.warning("CHANNEL3_BASE_URL %s is not Channel3's documented API; using %s", url, DEFAULT_BASE_URL)
        return DEFAULT_BASE_URL
    return url


def results_per_query() -> int:
    return max(1, min(int(settings.CHANNEL3_RESULTS_PER_QUERY or DEFAULT_RESULTS_PER_QUERY), MAX_RESULTS_PER_QUERY))


def max_queries_per_trip() -> int:
    return max(1, min(int(settings.CHANNEL3_MAX_QUERIES_PER_TRIP or MAX_QUERIES_PER_TRIP), MAX_QUERIES_PER_TRIP))


def clean_query(query: str) -> str:
    return " ".join(str(query or "").split())[:MAX_QUERY_LENGTH]


# ------------------------------------------------------------ normalization ---
def _http_url(value) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    p = urlparse(value.strip())
    return value.strip() if p.scheme in ("http", "https") and p.netloc else None


def _num(value) -> Optional[float]:
    try:
        n = float(value)
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def _text(value) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _offers(raw) -> List[dict]:
    out = []
    for o in raw if isinstance(raw, list) else []:
        if not isinstance(o, dict) or not _text(o.get("domain")):
            continue
        price = o.get("price") if isinstance(o.get("price"), dict) else {}
        availability = o.get("availability")
        out.append({
            "retailer": o["domain"].strip(),
            "url": _http_url(o.get("url")),
            "price": _num(price.get("price")),
            "compare_at_price": _num(price.get("compare_at_price")),
            "currency": _text(price.get("currency")),
            "availability": availability if availability in ("InStock", "OutOfStock") else None,
        })
    return out


def _main_offer(offers: List[dict]) -> Optional[dict]:
    """In-stock before out-of-stock, then the lowest listed price; offers without a price last."""
    if not offers:
        return None
    return sorted(offers, key=lambda o: (o["availability"] != "InStock", o["price"] is None, o["price"] or 0))[0]


def normalize_product(raw: Any, query: str) -> Optional[dict]:
    if not isinstance(raw, dict) or not _text(raw.get("id")) or not _text(raw.get("title")):
        return None
    images = [i for i in raw.get("images") or [] if isinstance(i, dict) and _http_url(i.get("url"))]
    main_image = next((i for i in images if i.get("is_main_image")), images[0] if images else None)
    brands = [b.get("name").strip() for b in raw.get("brands") or [] if isinstance(b, dict) and _text(b.get("name"))]
    category = raw.get("category") if isinstance(raw.get("category"), dict) else {}
    ratings = raw.get("ratings") if isinstance(raw.get("ratings"), dict) else {}
    variants = []
    options = (raw.get("variants") or {}).get("options") if isinstance(raw.get("variants"), dict) else None
    for opt in (options or [])[:3]:
        if not isinstance(opt, dict) or not _text(opt.get("name")):
            continue
        labels = [v["label"] for v in opt.get("values") or []
                  if isinstance(v, dict) and _text(v.get("label")) and v.get("available", True) is not False][:6]
        if labels:
            variants.append(f"{opt['name'].strip()}: {', '.join(labels)}")
    offers = _offers(raw.get("offers"))
    main = _main_offer(offers)
    count = ratings.get("count")
    return {
        "id": raw["id"].strip(),
        "name": raw["title"].strip(),
        "description": _text(raw.get("description")),
        "brand": brands[0] if brands else None,
        "image_url": _http_url(main_image.get("url")) if main_image else None,
        "category": _text(category.get("title")),
        "rating": _num(ratings.get("value")),
        "rating_count": int(count) if isinstance(count, (int, float)) and count >= 0 else None,
        "variants": variants,
        "offers": offers,
        "price": main["price"] if main else None,
        "compare_at_price": main["compare_at_price"] if main else None,
        "currency": main["currency"] if main else None,
        "retailer": main["retailer"] if main else None,
        "purchase_url": main["url"] if main else None,
        "in_stock": (main["availability"] == "InStock") if main and main["availability"] else None,
        "search_query": query,
    }


def to_item(product: dict, reason: Optional[str] = None) -> ProductItem:
    data = {**product, "offers": [ProductOffer(**o) for o in product.get("offers") or []]}
    if reason:
        data["reason"] = reason
    return ProductItem(**data)


# ---------------------------------------------------------------- transport ---
def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=float(settings.CHANNEL3_TIMEOUT_SECONDS or 15))


def _classify(status: int) -> str:
    return {401: "INVALID_API_KEY", 403: "INVALID_API_KEY", 402: "CREDITS_EXHAUSTED", 429: "RATE_LIMITED",
            400: "INVALID_REQUEST", 422: "INVALID_REQUEST", 504: "TIMEOUT"}.get(
        status, "SERVICE_ERROR" if status >= 500 else "INVALID_RESPONSE")


async def _post_search(query: str, limit: int) -> list:
    """One Channel3 search request (= 1 credit). Raises Channel3Error."""
    key = api_key()
    if not key:
        raise Channel3Error("NOT_CONFIGURED")
    body = {"query": query, "limit": limit, "config": dict(LOCALE)}
    try:
        async with _make_client() as client:
            resp = await client.post(base_url() + SEARCH_PATH, json=body,
                                     headers={"x-api-key": key, "Content-Type": "application/json"})
    except httpx.TimeoutException:
        log.warning("Channel3 search timed out")
        raise Channel3Error("TIMEOUT") from None
    except (httpx.HTTPError, OSError) as exc:
        log.warning("Channel3 search failed: %s", type(exc).__name__)
        raise Channel3Error("NETWORK") from None
    except Exception as exc:  # any other transport failure: a clear error, never a 500
        log.warning("Channel3 search failed: %s", type(exc).__name__)
        raise Channel3Error("SERVICE_ERROR") from None
    if resp.status_code != 200:
        code = _classify(resp.status_code)
        log.warning("Channel3 search failed: %s (HTTP %s)", code, resp.status_code)
        raise Channel3Error(code)
    try:
        data = resp.json()
    except ValueError:
        raise Channel3Error("INVALID_RESPONSE") from None
    if not isinstance(data, dict) or not isinstance(data.get("products"), list):
        raise Channel3Error("INVALID_RESPONSE")
    return data["products"]


# -------------------------------------------------------------------- cache ---
_table_ready: set = set()
_inflight: Dict[str, "asyncio.Future"] = {}


def _db():
    conn = database.connect()
    path = str(database.DB_PATH)
    if path not in _table_ready:
        conn.execute("CREATE TABLE IF NOT EXISTS channel3_cache ("
                     " cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, checked_at REAL NOT NULL)")
        conn.commit()
        _table_ready.add(path)
    return conn


def _cache_get(key: str) -> Optional[tuple]:
    try:
        with closing(_db()) as conn:
            row = conn.execute("SELECT payload, checked_at FROM channel3_cache WHERE cache_key=?", (key,)).fetchone()
    except Exception as exc:  # the cache is an optimisation: never fail a search because of it
        log.warning("Channel3 cache unavailable: %s", type(exc).__name__)
        return None
    if not row or time.time() - row["checked_at"] > STALE_KEEP_SECONDS:
        return None
    return row["checked_at"], json.loads(row["payload"])


def _cache_put(key: str, payload: list, checked: float) -> None:
    try:
        with closing(_db()) as conn:
            conn.execute("INSERT OR REPLACE INTO channel3_cache (cache_key, payload, checked_at) VALUES (?,?,?)",
                         (key, json.dumps(payload), checked))
            conn.execute("DELETE FROM channel3_cache WHERE checked_at < ?", (time.time() - STALE_KEEP_SECONDS,))
            conn.commit()
    except Exception as exc:
        log.warning("Channel3 cache unavailable: %s", type(exc).__name__)


def reset_inflight() -> None:
    _inflight.clear()


async def search(query: str, limit: Optional[int] = None) -> dict:
    """{"products": [normalized dict], "checked_at": epoch, "stale": bool}. Raises Channel3Error."""
    if not is_enabled():
        raise Channel3Error("NOT_CONFIGURED")
    query = clean_query(query)
    if len(query) < 2:
        raise Channel3Error("INVALID_REQUEST")
    limit = max(1, min(int(limit or results_per_query()), results_per_query()))
    key = f"search|{query.lower()}|{limit}|{LOCALE['currency']}|{LOCALE['country']}"
    hit = _cache_get(key)
    ttl = max(float(settings.CHANNEL3_CACHE_TTL_HOURS or 0), 0.0) * 3600
    if hit and time.time() - hit[0] < ttl:
        return {"products": hit[1], "checked_at": hit[0], "stale": False}

    task = _inflight.get(key)
    if task is None:
        async def run():
            raw = await _post_search(query, limit)
            products = [p for p in (normalize_product(r, query) for r in raw) if p][:limit]
            checked = time.time()
            _cache_put(key, products, checked)
            return products, checked

        task = asyncio.ensure_future(run())
        _inflight[key] = task
        task.add_done_callback(lambda t, k=key: _inflight.pop(k, None) if _inflight.get(k) is t else None)
    try:
        products, checked = await asyncio.shield(task)
    except Channel3Error:
        if hit:
            return {"products": hit[1], "checked_at": hit[0], "stale": True}
        raise
    return {"products": products, "checked_at": checked, "stale": False}


# ------------------------------------------------------------------- policy ---
def apply_purchase_link_policy(response: ProductSearchResponse, plan: str) -> ProductSearchResponse:
    """External purchase links are a Premium feature.

    Premium: unchanged. Anyone else (guests, Free, expired): products keep all their
    details, but `purchase_url` and every offer `url` are None. Works on copies.
    `plan` must be the server-verified plan.
    """
    if plan == "premium":
        return response
    return response.model_copy(update={"products": [
        p.model_copy(update={"purchase_url": None,
                             "offers": [o.model_copy(update={"url": None}) for o in p.offers]})
        for p in response.products
    ]})


async def search_products_response(query: str, limit: Optional[int] = None,
                                   plan: str = "free", audience: Optional[str] = None) -> ProductSearchResponse:
    """A direct search (GET /api/products/search). Closed by default: no links unless plan == 'premium'.
    `audience` ("men"/"women") adds that word to clothing/footwear searches and drops products
    stated for the other audience; nothing else is added to the user's query."""
    from app.services import trip_shopping  # local import: trip_shopping is independent of this module

    query = trip_shopping.audience_query(clean_query(query), audience)
    other = trip_shopping.opposite_audience(audience)
    try:
        found = await search(query, limit)
    except Channel3Error as err:
        status = "not_configured" if err.code == "NOT_CONFIGURED" else "unavailable"
        return ProductSearchResponse(query_context=query, products=[], status=status, message=err.message)
    items = [to_item(p) for p in found["products"] if not (other and trip_shopping.infer_audience(p) == other)]
    response = ProductSearchResponse(query_context=query, products=items, status="ok" if items else "empty",
                                     message=None if items else "Channel3 found no products for this search.")
    return apply_purchase_link_policy(response, plan)
