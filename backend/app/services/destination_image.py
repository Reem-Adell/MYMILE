"""
A real photo of the trip's destination for the Explore hero.

Source: Wikipedia's public REST page-summary API (no API key needed). Its lead
image comes from Wikimedia Commons. We accept an image only when:
  * the page is a normal article (not a disambiguation page),
  * the article clearly is about the requested place: when a country is given,
    its name must appear in the article's short description or summary text,
  * the image is a photo format (maps/flags are usually SVG and are skipped).
Otherwise we return no image and the frontend shows its branded fallback, never
a random or unrelated picture.

Results (including "no image") are cached in memory, so each destination is
looked up at most once per CACHE_TTL_SECONDS.
"""
import logging
import time
from typing import Dict, Optional, Tuple
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.destinations import COUNTRY_NAMES, country_code

log = logging.getLogger(__name__)

SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
CACHE_TTL_SECONDS = 24 * 60 * 60
HERO_WIDTH = 1600
_cache: Dict[Tuple[str, str], Tuple[float, Optional[dict]]] = {}


def _headers() -> Optional[dict]:
    """Wikimedia's API policy requires contact details in the User-Agent; without
    a configured WIKIMEDIA_CONTACT requests are refused (HTTP 403), so none are made."""
    contact = (settings.WIKIMEDIA_CONTACT or "").strip()
    if not contact:
        return None
    return {"User-Agent": f"MYMILE/1.0 ({contact})", "Accept": "application/json"}


def _country_words(country: str) -> set:
    words = {country.strip().lower()}
    code = country_code(country)
    if code and code in COUNTRY_NAMES:
        words.add(COUNTRY_NAMES[code].lower())
    return {w for w in words if w}


def _hero_url(summary: dict) -> Optional[str]:
    thumb = (summary.get("thumbnail") or {}).get("source")
    original = (summary.get("originalimage") or {}).get("source")
    for url in (thumb, original):
        if url and url.lower().endswith((".svg", ".svg.png")):
            return None  # maps, flags, coats of arms: not a destination photo
    if thumb and "px-" in thumb:
        # Wikimedia thumbnails can be requested at a larger width.
        head, _, tail = thumb.rpartition("/")
        size, _, name = tail.partition("px-")
        if size.isdigit():
            return f"{head}/{HERO_WIDTH}px-{name}"
    return original or thumb


def _accept(summary: dict, country: str) -> Optional[dict]:
    if summary.get("type") == "disambiguation":
        return None
    if country:
        text = f"{summary.get('description', '')} {summary.get('extract', '')}".lower()
        if not any(word in text for word in _country_words(country)):
            return None
    url = _hero_url(summary)
    if not url:
        return None
    page = ((summary.get("content_urls") or {}).get("desktop") or {}).get("page")
    return {
        "url": url,
        "page_url": page,
        "title": summary.get("title"),
        "source": "Wikipedia / Wikimedia Commons",
    }


async def get_destination_image(city: str, country: str = "",
                                client: Optional[httpx.AsyncClient] = None) -> Optional[dict]:
    city = (city or "").strip()
    country = (country or "").strip()
    headers = _headers()
    if not city or headers is None:
        return None
    key = (city.lower(), country.lower())
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    titles = [f"{city}, {country}", city] if country else [city]
    result: Optional[dict] = None
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=6.0, headers=headers, follow_redirects=True)
    try:
        for title in titles:
            try:
                resp = await client.get(SUMMARY_URL.format(title=quote(title.replace(" ", "_"), safe="")))
            except httpx.HTTPError as exc:
                log.warning("Destination image lookup failed: %s", type(exc).__name__)
                return None  # not cached: a network failure may be temporary
            if resp.status_code in (403, 429):
                log.warning("Destination image lookup refused by Wikimedia (HTTP %s)", resp.status_code)
                return None  # policy/rate limit: not cached, so it can recover
            if resp.status_code != 200:
                continue
            result = _accept(resp.json(), country)
            if result:
                break
    finally:
        if own_client:
            await client.aclose()
    _cache[key] = (time.time(), result)
    return result
