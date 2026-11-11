"""
Works out what kind of stay a traveler needs and ranks hotels against it.

Signals come from three places on the planner form:
- purpose ("Tourism", "Business", "Umrah", ...)
- priorities ("Work & Productivity", "Family friendly", "Nightlife", ...)
- the free-text note ("I have an interview downtown, need a quiet room")

Everything is keyword based so it works without an LLM key. English and common
Egyptian Arabic phrasings are both recognised.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

# Area id -> words that mean the traveler wants to be there.
AREA_KEYWORDS: Dict[str, List[str]] = {
    "downtown": [
        "downtown", "down town", "city center", "city centre", "tahrir", "garden city",
        "talaat harb", "abdeen", "abdin", "wust el balad", "wust al balad", "west el balad",
        "وسط البلد", "التحرير", "جاردن سيتي", "قصر النيل",
        # Alexandria downtown
        "raml station", "raml", "saad zaghloul", "manshia", "mansheya", "bibliotheca",
        "library of alexandria", "محطة الرمل", "سعد زغلول", "المنشية", "مكتبة الإسكندرية",
    ],
    "zamalek": ["zamalek", "gezira", "gezirah", "الزمالك", "الجزيرة"],
    "montaza": ["montaza", "montazah", "maamoura", "المنتزه", "المعمورة"],
    "san-stefano": ["san stefano", "سان ستيفانو"],
    "sidi-bishr": ["sidi bishr", "سيدي بشر"],
    "giza": [
        "giza", "pyramid", "pyramids", "grand egyptian museum", "gem ", "sphinx",
        "الجيزة", "الهرم", "الأهرام", "الاهرامات", "المتحف المصري الكبير",
    ],
    "airport": [
        "airport", "heliopolis", "terminal", "layover", "transit", "early flight",
        "المطار", "مصر الجديدة",
    ],
}

# Human-friendly names used in the explanation shown to the traveler.
AREA_LABELS = {
    "downtown": "in downtown {city}",
    "zamalek": "in Zamalek",
    "giza": "by the Pyramids in Giza",
    "airport": "right at {city} Airport",
    "montaza": "by the Montaza gardens",
    "san-stefano": "in San Stefano on the Corniche",
    "sidi-bishr": "in Sidi Bishr on the Corniche",
}

CITY_LABELS = {"cairo": "Cairo", "alexandria": "Alexandria"}

WORK_WORDS = [
    "interview", "meeting", "work", "business", "conference", "office", "job", "client",
    "presentation", "laptop", "remote work", "zoom", "exhibition", "training", "embassy",
    "مقابلة", "انترفيو", "شغل", "عمل", "اجتماع", "مؤتمر", "السفارة",
]
QUIET_WORDS = ["quiet", "calm", "peaceful", "good sleep", "sleep well", "هادئ", "هادي", "هدوء"]
WIFI_WORDS = ["wifi", "wi-fi", "internet", "انترنت", "واي فاي"]
MUSEUM_WORDS = [
    "museum", "museums", "history", "historic", "antiquities", "pharaoh", "tutankhamun",
    "sightseeing", "landmark", "متحف", "المتحف", "آثار", "اثار",
]
FAMOUS_WORDS = ["famous", "iconic", "landmark hotel", "historic hotel", "legendary", "مشهور"]
FAMILY_WORDS = ["family", "kids", "children", "child", "baby", "أطفال", "اطفال", "عائلة"]
NIGHTLIFE_WORDS = ["nightlife", " bars", "party", "night out", "سهر"]
NILE_WORDS = ["nile", "النيل", "river view"]
POOL_WORDS = ["pool", "swim", "حمام سباحة", "مسبح"]
BEACH_WORDS = ["beach", "seaside", "sea view", "by the sea", "mediterranean", "شاطئ", "بحر", "البحر"]
CHEAP_WORDS = ["cheap", "budget", "affordable", "low cost", "رخيص", "اقتصادي"]


def _has_any(text: str, words: List[str]) -> bool:
    return any(w in text for w in words)


@dataclass
class StayIntent:
    area: Optional[str] = None
    wants: Set[str] = field(default_factory=set)  # hotel tags we're looking for
    # Tags the traveler asked for themselves (note / priorities). These outweigh the
    # general defaults that come from the trip purpose alone.
    explicit: Set[str] = field(default_factory=set)
    reason: str = "trip"  # "work", "tourism", "umrah", "family", "trip"
    cheap: bool = False


def detect_intent(purpose: str, priorities: List[str], notes: Optional[str]) -> StayIntent:
    text = " ".join([purpose or "", " ".join(priorities or []), notes or ""]).lower()
    note = (notes or "").lower()
    intent = StayIntent()

    # Area: the note wins (it's the most specific), then anything else in the form.
    for source in (note, text):
        for area, words in AREA_KEYWORDS.items():
            if _has_any(source, words):
                intent.area = area
                break
        if intent.area:
            break

    purpose_l = (purpose or "").lower()
    is_work = "business" in purpose_l or _has_any(text, WORK_WORDS) or any(
        "work" in p.lower() for p in priorities or []
    )
    is_umrah = "umrah" in purpose_l
    is_tourism = "tourism" in purpose_l or _has_any(text, MUSEUM_WORDS)

    if is_umrah:
        intent.reason = "umrah"
        intent.wants |= {"haram", "family"}
    elif is_work:
        intent.reason = "work"
        intent.wants |= {"business", "wifi", "quiet", "central"}
        if _has_any(note, WORK_WORDS) or any("work" in p.lower() for p in priorities or []):
            intent.explicit |= {"business", "wifi", "quiet"}
    elif is_tourism:
        intent.reason = "tourism"
        intent.wants |= {"museums", "landmarks", "famous", "central"}

    def want(tag: str) -> None:
        intent.wants.add(tag)
        intent.explicit.add(tag)

    if _has_any(text, QUIET_WORDS) or any("slow pace" in p.lower() for p in priorities or []):
        want("quiet")
    if _has_any(text, WIFI_WORDS):
        want("wifi")
    if _has_any(text, MUSEUM_WORDS) or any("local culture" in p.lower() for p in priorities or []):
        want("museums")
    if _has_any(text, FAMOUS_WORDS):
        want("famous")
    if _has_any(text, FAMILY_WORDS):
        want("family"); want("pool")
        if intent.reason == "trip":
            intent.reason = "family"
    if _has_any(text, NIGHTLIFE_WORDS):
        want("nightlife")
    if _has_any(text, NILE_WORDS):
        want("nile")
    if _has_any(text, POOL_WORDS):
        want("pool")
    if _has_any(text, BEACH_WORDS) or any("beach" in p.lower() for p in priorities or []):
        want("beach")
    if _has_any(text, CHEAP_WORDS):
        intent.cheap = True

    return intent


# Explanation phrases for each tag, used to build "why we picked this".
TAG_PHRASES = {
    "business": "business-friendly services",
    "wifi": "reliable Wi-Fi",
    "quiet": "quiet rooms",
    "central": "a central location",
    "museums": "walking distance to major museums",
    "landmarks": "iconic sights on the doorstep",
    "famous": "one of the city's best-known hotels",
    "family": "family-friendly facilities",
    "pool": "a pool",
    "nightlife": "restaurants and nightlife nearby",
    "nile": "Nile views",
    "haram": "steps from the Haram",
    "beach": "beach access",
}


def score_hotel(hotel: dict, intent: StayIntent, preference_key: str, nightly_cap: Optional[float]) -> float:
    tags = set(hotel.get("tags", []))
    score = 0.0
    if intent.area:
        score += 60 if hotel.get("area") == intent.area else -25
    score += 8 * len(tags & intent.wants)
    score += 16 * len(tags & intent.explicit)
    if preference_key and preference_key in hotel.get("category", "").lower():
        # A budget traveler really means it; for other styles it's a softer preference.
        score += 45 if preference_key == "budget" else 18
    if intent.cheap or preference_key == "budget":
        score -= hotel["price_per_night"] / 8
    if nightly_cap and hotel["price_per_night"] > nightly_cap:
        score -= 20
    score += hotel.get("rating", 0) * 3
    return score


def explain_match(hotel: dict, intent: StayIntent) -> str:
    tags = set(hotel.get("tags", []))
    # What they asked for themselves comes first in the explanation.
    order = sorted(TAG_PHRASES, key=lambda t: t not in intent.explicit)
    matched = [TAG_PHRASES[t] for t in order if t in tags and t in intent.wants]
    parts: List[str] = []
    if intent.area and hotel.get("area") == intent.area:
        city = CITY_LABELS.get(hotel.get("destination", ""), "the city")
        label = AREA_LABELS.get(intent.area, "in " + intent.area).format(city=city)
        parts.append(f"{label}, where you need to be")
    parts.extend(matched[:3])

    if not parts:
        return hotel["best_match_reason"]

    lead = {
        "work": "Picked for your work trip",
        "tourism": "Picked for sightseeing",
        "umrah": "Picked for your Umrah",
        "family": "Picked for your family trip",
    }.get(intent.reason, "Picked for you")

    if len(parts) == 1:
        joined = parts[0]
    else:
        joined = ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"{lead}: {joined}. {hotel['best_match_reason']}"
