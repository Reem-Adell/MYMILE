"""
Turns what the traveler typed ("Alexandria, Egypt", "Giza", "مكة") into one of the
cities we have curated data for, or None.

Rules:
1. The city part (before the first comma) is matched first, as whole words.
   "Alexandria, Egypt" -> alexandria, never cairo just because it says "Egypt".
2. A country name only counts when it is the whole destination ("Egypt" -> cairo).
3. Anything else -> None, so callers show general results for that place instead of
   another city's hotels, sights or itinerary.
"""
import re
from typing import Dict, List, Optional, Tuple

CITY_ALIASES: Dict[str, List[str]] = {
    "cairo": ["cairo", "giza", "new cairo", "heliopolis", "القاهرة", "الجيزة"],
    "alexandria": ["alexandria", "alex", "iskandariya", "الإسكندرية", "الاسكندرية", "اسكندرية"],
    "kyoto": ["kyoto", "京都"],
    "paris": ["paris"],
    "makkah": ["makkah", "mecca", "makka", "مكة", "مكه"],
}

# Country words that are allowed after the comma for each city. Any other country
# ("Alexandria, Virginia", "Paris, Texas") means it's a different place.
CITY_COUNTRIES: Dict[str, List[str]] = {
    "cairo": ["egypt", "eg", "مصر"],
    "alexandria": ["egypt", "eg", "مصر"],
    "kyoto": ["japan", "jp"],
    "paris": ["france", "fr"],
    "makkah": ["saudi arabia", "saudi", "ksa", "sa", "السعودية"],
}

# Destination that is only a country -> the city we pick for it.
COUNTRY_DEFAULTS: Dict[str, str] = {
    "egypt": "cairo",
    "مصر": "cairo",
    "japan": "kyoto",
    "france": "paris",
    "saudi arabia": "makkah",
    "ksa": "makkah",
    "السعودية": "makkah",
}

CITY_NAMES = {
    "cairo": "Cairo",
    "alexandria": "Alexandria",
    "kyoto": "Kyoto",
    "paris": "Paris",
    "makkah": "Makkah",
}


# ISO country code of each curated city (used to validate hotel locations).
CITY_COUNTRY_CODE: Dict[str, str] = {
    "cairo": "EG",
    "alexandria": "EG",
    "kyoto": "JP",
    "paris": "FR",
    "makkah": "SA",
}

# What a traveler may type in the Country field -> ISO code.
COUNTRY_CODES: Dict[str, str] = {
    "egypt": "EG", "eg": "EG", "مصر": "EG",
    "japan": "JP", "jp": "JP",
    "france": "FR", "fr": "FR",
    "saudi arabia": "SA", "saudi": "SA", "ksa": "SA", "sa": "SA", "السعودية": "SA",
}

COUNTRY_NAMES: Dict[str, str] = {"EG": "Egypt", "JP": "Japan", "FR": "France", "SA": "Saudi Arabia"}


def country_code(country: Optional[str]) -> Optional[str]:
    """ISO code for a country we know, else None."""
    return COUNTRY_CODES.get((country or "").strip().lower())


def compose_destination(city: Optional[str], country: Optional[str], fallback: str = "") -> str:
    """"City, Country" from the structured Plan a Trip fields (authoritative), else the fallback text."""
    city = (city or "").strip()
    country = (country or "").strip()
    if city and country:
        return f"{city}, {country}"
    return city or (fallback or "").strip()


def resolve_trip_location(destination: str, city: Optional[str] = None,
                          country: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """(curated city key or None, requested ISO country code or None).

    The structured City/Country fields win over the free-text destination. The
    "Anything we should know?" note is never used here: it can only rank hotels
    within the requested destination, never change the destination.
    """
    text = compose_destination(city, country, destination)
    requested_country = country_code(country)
    if requested_country is None and "," in text:
        requested_country = country_code(text.split(",")[-1])
    return resolve_city(text), requested_country


def _contains_word(text: str, word: str) -> bool:
    # \b works for Latin script; for Arabic/CJK a plain substring check is used.
    if word.isascii():
        return re.search(rf"\b{re.escape(word)}\b", text) is not None
    return word in text


def resolve_city(destination: str) -> Optional[str]:
    text = (destination or "").strip().lower()
    if not text:
        return None
    parts = [p.strip() for p in text.split(",") if p.strip()]
    city_part = parts[0]
    country_part = parts[-1] if len(parts) > 1 else ""

    for city, aliases in CITY_ALIASES.items():
        if any(_contains_word(city_part, a) for a in aliases):
            other_place_ok = country_part in CITY_COUNTRIES[city] or any(
                _contains_word(country_part, a) for a in aliases
            )
            if country_part and not other_place_ok:
                return None  # same name, different country
            return city

    if city_part in COUNTRY_DEFAULTS and "," not in text:
        return COUNTRY_DEFAULTS[city_part]
    return None


def display_city(destination: str) -> str:
    """The city name to show in text: curated name if known, otherwise what they typed."""
    city = resolve_city(destination)
    if city:
        return CITY_NAMES[city]
    return (destination or "").split(",")[0].strip() or destination
