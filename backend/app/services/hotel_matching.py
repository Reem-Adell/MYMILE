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
    ],
    "zamalek": ["zamalek", "gezira", "gezirah", "الزمالك", "الجزيرة"],
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
    "downtown": "in Downtown Cairo",
    "zamalek": "in Zamalek",
    "giza": "by the Pyramids in Giza",
    "airport": "right at Cairo Airport",
}

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
CHEAP_WORDS = ["cheap", "budget", "affordable", "low cost", "رخيص", "اقتصادي"]


def _has_any(text: str, words: List[str]) -> bool:
    return any(w in text for w in words)


@dataclass
class StayIntent:
    area: Optional[str] = None
    wants: Set[str] = field(default_factory=set)  # hotel tags we're looking for
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
    elif is_tourism:
        intent.reason = "tourism"
        intent.wants |= {"museums", "landmarks", "famous", "central"}

    if _has_any(text, QUIET_WORDS) or any("slow pace" in p.lower() for p in priorities or []):
        intent.wants.add("quiet")
    if _has_any(text, WIFI_WORDS):
        intent.wants.add("wifi")
    if _has_any(text, MUSEUM_WORDS) or any("local culture" in p.lower() for p in priorities or []):
        intent.wants.add("museums")
    if _has_any(text, FAMOUS_WORDS):
        intent.wants.add("famous")
    if _has_any(text, FAMILY_WORDS):
        intent.wants |= {"family", "pool"}
        if intent.reason == "trip":
            intent.reason = "family"
    if _has_any(text, NIGHTLIFE_WORDS):
        intent.wants.add("nightlife")
    if _has_any(text, NILE_WORDS):
        intent.wants.add("nile")
    if _has_any(text, POOL_WORDS):
        intent.wants.add("pool")
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
}


def score_hotel(hotel: dict, intent: StayIntent, preference_key: str, nightly_cap: Optional[float]) -> float:
    tags = set(hotel.get("tags", []))
    score = 0.0
    if intent.area:
        score += 60 if hotel.get("area") == intent.area else -25
    score += 10 * len(tags & intent.wants)
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
    matched = [TAG_PHRASES[t] for t in TAG_PHRASES if t in tags and t in intent.wants]
    parts: List[str] = []
    if intent.area and hotel.get("area") == intent.area:
        parts.append(f"{AREA_LABELS.get(intent.area, 'in ' + intent.area)}, where you need to be")
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
