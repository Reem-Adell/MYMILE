"""
Trip-aware guidance for Channel3 product discovery. This is NOT a catalog: it holds
no products, prices or links. It turns the Plan a Trip fields into

  * a structured shopping context (season, trip length, quantities, budget level), and
  * suggested product categories with search phrases for the trip's purpose,

which the AI uses to decide its Channel3 searches. Every product shown to a user
still comes from a real Channel3 search and is picked by the AI.

It also holds two server-side safety checks that don't depend on the model:

  * relevance guards: a search for a specific item (a prayer mat, Ihram clothing,
    an abaya, unscented care ...) only keeps products whose own Channel3 text names
    that item, so a yoga mat never answers "prayer mat";
  * claim guard: a recommendation reason may not claim Ihram compliance, halal,
    certification, "unscented" etc. unless the product's own text says so.

Nothing here is a religious ruling: categories are phrased as items commonly packed,
and gender is never assumed (gender-specific categories are labelled "men"/"women").
"""
import datetime
import re
from typing import List, Optional

# ------------------------------------------------------------ guidance ---
# (category, audience, search phrases). audience: "all" | "men" | "women".
_UMRAH = [
    ("Ihram & Clothing", "men", ["men's two piece ihram towel set", "ihram belt with money pouch"]),
    ("Modest Clothing", "women", ["women's abaya and hijab", "hijab with underscarf set", "women's prayer dress"]),
    ("Prayer Essentials", "all", ["travel prayer rug", "travel prayer mat"]),
    ("Footwear", "all", ["comfortable walking sandals"]),
    ("Personal Care", "all", ["unscented travel toiletries", "fragrance-free soap"]),
    ("Travel Bags & Organizers", "all", ["drawstring shoe bag", "small crossbody travel bag", "packing cubes"]),
    ("Travel Accessories", "all", ["reusable insulated water bottle"]),
]
_BUSINESS = [
    ("Formal Clothing", "all", ["wrinkle resistant travel blazer", "non iron dress shirt"]),
    ("Professional Shoes", "all", ["comfortable leather dress shoes"]),
    ("Laptop Bag", "all", ["laptop backpack for business travel"]),
    ("Work Electronics", "all", ["universal travel adapter with usb c", "portable charger power bank"]),
    ("Clothing Care", "all", ["garment bag for suits", "travel steamer"]),
]
_TOURISM = [
    ("Day Bag", "all", ["lightweight daypack", "anti theft crossbody bag"]),
    ("Footwear", "all", ["comfortable walking shoes"]),
    ("Sightseeing Essentials", "all", ["portable charger power bank", "universal travel adapter"]),
    ("Photography", "all", ["phone travel tripod"]),
    ("Travel Bags & Organizers", "all", ["packing cubes"]),
]
_OTHER = [
    ("Travel Accessories", "all", ["universal travel adapter"]),
    ("Travel Bags & Organizers", "all", ["packing cubes"]),
    ("Footwear", "all", ["comfortable walking shoes"]),
]
PURPOSE_GUIDANCE = {"umrah": _UMRAH, "business": _BUSINESS, "tourism": _TOURISM, "other": _OTHER}
# A goal for the AI, not a quota: fewer are shown when fewer are relevant.
TARGET_PRODUCTS = 10


def purpose_key(purpose: Optional[str], notes: Optional[str] = None) -> str:
    """umrah | business | tourism | other, from the purpose the traveler chose (never guessed
    from the description: that is for the AI to read, not to switch purposes)."""
    p = (purpose or "").strip().lower()
    if p in PURPOSE_GUIDANCE:
        return p
    return "umrah" if "umrah" in p else "business" if "business" in p else "tourism" if "touris" in p else "other"


def fallback_categories(purpose: str) -> List[str]:
    """The purpose's usual categories: a hint for when the description leaves searches unused."""
    return [category for category, _, _ in PURPOSE_GUIDANCE[purpose_key(purpose)]]


# ---------------------------------------------------- named products ---
# Products the traveler names in the description -> (category, audience, search phrase).
# Only names: needs implied by the description are inferred by the AI, not by keywords.
REQUESTED_ITEMS = [
    # Work gear people name in their notes ("my mouse broke", "need a keyboard").
    (re.compile(r"\b((computer|wireless|bluetooth|laptop) )?(mouse|mice)\b", re.I),
     ("Computer Mouse", "all", "wireless computer mouse")),
    (re.compile(r"\b(keyboards?)\b", re.I), ("Keyboard", "all", "portable bluetooth keyboard")),
    (re.compile(r"\b(headphones?|earbuds|headsets?|earphones)\b", re.I),
     ("Headphones", "all", "noise cancelling headphones")),
    (re.compile(r"\blaptop (bags?|backpacks?|sleeves?|cases?)\b", re.I),
     ("Laptop Bag", "all", "laptop backpack for business travel")),
    (re.compile(r"\blaptop stands?\b", re.I), ("Work Electronics", "all", "portable laptop stand")),
    # Clothing named in the notes.
    # Only clothing named as formal: "summer/modest/beach outfits" are not formal clothing.
    (re.compile(r"\b((professional|business|formal|work|office) (outfits?|clothes|clothing|attire|wear)|suits?|"
                r"blazers?|dress shirts?)\b", re.I),
     ("Formal Clothing", "all", "wrinkle resistant travel blazer")),
    (re.compile(r"\b((formal|dress|professional|business|oxford|leather) shoes|loafers|heels)\b", re.I),
     ("Professional Shoes", "all", "comfortable leather dress shoes")),
    # Clothing for warm weather, only when described that way ("lightweight clothes", "breathable
    # outfits", "summer clothing"); "formal/business outfits" stay Formal Clothing below.
    (re.compile(r"\b((light[- ]?weight|breathable) (clothes|clothing|outfits?)|summer (clothes|clothing))\b", re.I),
     ("Lightweight Clothing", "all", "lightweight breathable clothing")),
    # Beach and sun items named in the description ("I need a swimsuit and sunglasses").
    (re.compile(r"\b(swim ?suits?|swimwear|bathing suits?|bikinis?|burkinis?|swim(ming)? trunks|board shorts|"
                r"tankinis?|one[- ]piece)\b", re.I), ("Swimwear", "all", "swimsuit")),
    (re.compile(r"\b(sun ?glasses|shades|polari[sz]ed glasses)\b", re.I), ("Sunglasses", "all", "polarized sunglasses")),
    (re.compile(r"\b(sun ?hats?|bucket hats?|beach hats?)\b", re.I), ("Sun Hat", "all", "wide brim sun hat")),
    (re.compile(r"\bbeach towels?\b", re.I), ("Beach Towel", "all", "quick dry beach towel")),
    (re.compile(r"\bbeach (bags?|totes?)\b", re.I), ("Beach Bag", "all", "waterproof beach tote bag")),
    (re.compile(r"\b(coats?|winter jackets?|warm jackets?|parkas?)\b", re.I),
     ("Warm Layers", "all", "packable insulated winter jacket")),
    (re.compile(r"\b(socks)\b", re.I), ("Socks", "all", "merino wool travel socks")),
    (re.compile(r"\b(adapters?|adaptors?|plugs?|converters?)\b", re.I), ("Travel Adapter", "all", "travel plug adapter")),
    (re.compile(r"\b(power ?banks?|chargers?|charging)\b", re.I), ("Power & Charging", "all", "portable power bank")),
    (re.compile(r"\bihram\b", re.I), ("Ihram & Clothing", "men", "men's two piece ihram towel set")),
    (re.compile(r"\b(abayas?|hijabs?|modest)\b", re.I), ("Modest Clothing", "women", "women's abaya and hijab")),
    (re.compile(r"\bprayer (mats?|rugs?)|\bjanamaz\b", re.I), ("Prayer Essentials", "all", "travel prayer rug")),
    (re.compile(r"\b(sandals?|shoes?|footwear|sneakers?)\b", re.I), ("Footwear", "all", "comfortable walking sandals")),
    (re.compile(r"\b(toiletr(y|ies)|unscented|soap|shampoo)\b", re.I),
     ("Personal Care", "all", "unscented travel toiletries")),
    (re.compile(r"\b(umbrellas?|raincoats?|ponchos?)\b", re.I), ("Rain Gear", "all", "compact travel umbrella")),
    (re.compile(r"\bwater bottles?\b", re.I), ("Travel Accessories", "all", "reusable insulated water bottle")),
    (re.compile(r"\b(backpacks?|daypacks?|crossbody|packing cubes?|luggage organi[sz]ers?)\b", re.I),
     ("Travel Bags & Organizers", "all", "packing cubes")),
    (re.compile(r"\b(sunscreen|sunblock)\b", re.I), ("Sun Care", "all", "broad spectrum sunscreen")),
    (re.compile(r"\b(neck pillow|sleep mask|earplugs?)\b", re.I), ("Comfort", "all", "travel neck pillow")),
    (re.compile(r"\b(first aid|medicine kit)\b", re.I), ("Health", "all", "travel first aid kit")),
]


def named_products(description: Optional[str]) -> List[dict]:
    """Products the traveler explicitly names in the trip description, in the order written.
    The server makes sure each one is searched (the AI infers everything else)."""
    found = []
    for pattern, (category, aud, query) in REQUESTED_ITEMS:
        for match in pattern.finditer(description or ""):
            found.append((match.start(), match.end(), {"category": category, "audience": aud, "query": query,
                                                       "explicit": True}))
    # Earlier, then longer matches win; a match inside one already taken ("shoes" in
    # "formal shoes") is the same request, not another one.
    taken, out = [], []
    for start, end, item in sorted(found, key=lambda x: (x[0], -(x[1] - x[0]))):
        if any(start < e and end > s for s, e in taken):
            continue
        taken.append((start, end))
        same = next((o for o in out if same_category(item["category"], o["category"])), None)
        if same is None:
            out.append(item)
        else:
            same["explicit"] = same["explicit"] or item["explicit"]  # named later, still a request
    return out


# ----------------------------------------------------------- shopping audience ---
_GENDER_RE = re.compile(r"\b(men|women|man|woman|male|female|ladies|lady|unisex|boys|girls)('s)?\b", re.I)
_APPAREL_RE = re.compile(r"\b(shoes?|sandals?|boots?|sneakers?|loafers?|heels|jackets?|coats?|parkas?|blazers?|"
                         r"shirts?|dress(es)?|outfits?|suits?|trousers|pants|jeans|socks|sweaters?|hoodies?|"
                         r"swim\w*|abayas?|hijabs?|underwear|leggings|shorts|scarf|scarves|gloves|hats?|beanies?)\b",
                         re.I)
APPAREL_CATEGORIES = {"Formal Clothing", "Professional Shoes", "Footwear", "Warm Layers", "Light Layers",
                      "Activewear", "Socks", "Modest Clothing", "Lightweight Clothing"}
SHOPPING_AUDIENCES = ("men", "women", "all")


def shopping_audience(value) -> Optional[str]:
    """"men" / "women" when the traveler chose one, else None (Everyone / no preference)."""
    v = str(value or "").strip().lower()
    return v if v in ("men", "women") else None


def opposite_audience(value) -> Optional[str]:
    return {"men": "women", "women": "men"}.get(shopping_audience(value) or "")


def audience_query(query: str, audience, category: Optional[str] = None) -> str:
    """Adds "men's"/"women's" to clothing and footwear searches when the traveler shops for
    one audience (never to gear like a mouse, and never twice)."""
    who = shopping_audience(audience)
    if not who or _GENDER_RE.search(query or ""):
        return query
    if category in APPAREL_CATEGORIES or _APPAREL_RE.search(query or ""):
        return f"{who}'s {query}"
    return query


_CATEGORY_TOKEN = re.compile(r"[a-z0-9]+")
_QUERY_STOP = {"and", "the", "for", "with", "a", "an", "of", "travel", "set", "best", "new"}


def category_tokens(name: Optional[str]) -> frozenset:
    return frozenset(t for t in _CATEGORY_TOKEN.findall(str(name or "").lower()) if t not in {"and", "the", "for", "travel"})


# The item a search is really for; two searches sharing one look for the same thing.
_HEAD_NOUNS = {"adapter", "adaptor", "charger", "bank", "umbrella", "jacket", "shoes", "sandals", "backpack",
               "daypack", "tripod", "sunscreen", "bottle", "pillow", "towel", "blazer", "shirt", "stand",
               "mouse", "keyboard", "headphones", "earbuds", "socks", "coat", "loafers", "suit",
               "swimsuit", "swimwear", "bikini", "burkini", "sunglasses", "hat", "tote"}


def overlapping_query(a: Optional[str], b: Optional[str]) -> bool:
    heads = lambda q: set(_TOKEN.findall(str(q or "").lower())) & _HEAD_NOUNS
    return similar_query(a, b) or bool(heads(a) & heads(b))


def similar_query(a: Optional[str], b: Optional[str]) -> bool:
    """Two searches for the same kind of item (e.g. "walking sandals" / "comfortable walking sandals")."""
    stop = _QUERY_STOP | _GENDER_WORDS  # _GENDER_WORDS is defined further down this module
    ta = frozenset(t for t in _TOKEN.findall(str(a or "").lower().replace("'s", "")) if t not in stop)
    tb = frozenset(t for t in _TOKEN.findall(str(b or "").lower().replace("'s", "")) if t not in stop)
    return len(ta & tb) >= 2 and _jaccard(ta, tb) >= 0.5


def search_covers_need(category: Optional[str], query: Optional[str], need: dict) -> bool:
    """Whether a search (its category and query) is for a named need: same category OR an
    overlapping query ("wireless computer mouse ergonomic" under "Work Electronics" covers the
    named "Computer Mouse"). Used both to avoid repeating named searches and to report them."""
    return bool(category and same_category(category, need["category"])) or overlapping_query(query, need["query"])


def same_category(a: Optional[str], b: Optional[str]) -> bool:
    ta, tb = category_tokens(a), category_tokens(b)
    return bool(ta and tb) and (ta <= tb or tb <= ta or _jaccard(ta, tb) >= 0.5)


LIVE_WEATHER_SOURCE = "Open-Meteo Live API"
_UNKNOWN_COORDS = (35.0116, 135.7681)  # the geocoder's fallback (Kyoto) when a place isn't found
def _season_conditions(latitude: float, months: List[str]) -> List[str]:
    """Typical conditions for the latitude and months (no forecast involved)."""
    north = latitude >= 0
    winter = {"December", "January", "February"} if north else {"June", "July", "August"}
    summer = {"June", "July", "August"} if north else {"December", "January", "February"}
    shoulder = {"March", "November"} if north else {"September", "May"}
    band, m = abs(latitude), set(months)
    if band < 23.5:
        return ["hot"]
    if band < 35:
        return ["cool"] if m & winter else ["hot"] if m & summer else []
    if m & winter:
        return ["cold", "wet"]
    return ["cool", "wet"] if m & shoulder else []


def weather_context(weather, check_in: str, check_out: str) -> Optional[dict]:
    """Compact weather facts for product planning: the live forecast for days inside the trip,
    else the season from the destination's latitude, else None. Never invents a forecast
    (the service's offline baseline is not used as one)."""
    if weather is None:
        return None
    source = getattr(weather, "source", None)
    days = [d for d in (getattr(weather, "forecast", None) or [])
            if check_in <= str(getattr(d, "date", "")) <= check_out] if source == LIVE_WEATHER_SOURCE else []
    if days:
        low, high = min(d.temp_min_c for d in days), max(d.temp_max_c for d in days)
        rain = max(int(d.precipitation_prob or 0) for d in days)
        wet_words = any(w in str(d.condition).lower() for d in days for w in ("rain", "drizzle", "shower", "snow", "storm"))
        conditions = (["cold"] if low <= 8 else ["cool"] if low <= 15 else []) + \
            (["wet"] if rain >= 50 or wet_words else []) + (["hot"] if high >= 30 else [])
        return {"basis": "forecast", "conditions": conditions, "temp_c": [round(low), round(high)],
                "max_rain_chance": rain}
    lat, lon = getattr(weather, "latitude", None), getattr(weather, "longitude", None)
    if lat is None or (round(lat, 4), round(lon or 0, 4)) == _UNKNOWN_COORDS and \
            "kyoto" not in str(getattr(weather, "destination", "")).lower():
        return None
    return {"basis": "seasonal", "conditions": _season_conditions(float(lat), _months(check_in, check_out))}


# ------------------------------------------------------------ context ---
def _months(check_in: str, check_out: str) -> List[str]:
    try:
        start = datetime.date.fromisoformat(check_in.strip())
        end = datetime.date.fromisoformat(check_out.strip())
    except (AttributeError, ValueError):
        return []
    months, day = [], start
    while day <= end and len(months) < 3:
        name = day.strftime("%B")
        if name not in months:
            months.append(name)
        day = (day.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
    return months


def budget_level(total_budget: Optional[float], travelers: int, nights: int) -> Optional[dict]:
    """Price sensitivity from the trip budget (only when the user gave one)."""
    if not total_budget or total_budget <= 0:
        return None
    per = total_budget / max(travelers, 1) / max(nights, 1)
    level = "tight" if per < 100 else "moderate" if per < 300 else "comfortable"
    return {"level": level, "per_traveler_per_night_usd": round(per)}


def shopping_context(*, purpose: str, check_in: str, check_out: str, nights: int, travelers: int,
                     description: Optional[str], total_budget: Optional[float], max_searches: int,
                     weather=None, audience=None) -> dict:
    """Compact supporting facts for the AI's product choices. The trip description itself
    (sent once, in the trip) is the primary source; this only adds what the AI can't know."""
    length = "short" if nights <= 3 else "medium" if nights <= 7 else "long"
    ctx = {
        "purpose_type": purpose_key(purpose),
        "travel_months": _months(check_in, check_out),
        "trip_length": f"{length} ({nights} nights)",
        "travelers": travelers,
        "named_products": [{"category": n["category"], "query": n["query"]} for n in named_products(description)],
        "fallback_categories": fallback_categories(purpose),
        "max_searches": max_searches,
        "target_products": TARGET_PRODUCTS,
    }
    budget = budget_level(total_budget, travelers, nights)
    if budget:
        ctx["budget"] = budget
    climate = weather_context(weather, check_in, check_out)
    if climate:
        ctx["weather"] = climate
    if shopping_audience(audience):
        ctx["shopping_for"] = shopping_audience(audience)
    return ctx


# ------------------------------------------------------------- guards ---
# Product text that contradicts modest / religious-trip clothing (checked on the product's
# own title, description and Channel3 category).
_BEACHWEAR = re.compile(r"beach|cover[- ]?ups?\b|swim|bikini|lingerie|costume|halloween|resort ?wear"
                        r"|\bmini (abaya|dress|skirt|kaftan)\b", re.I)

# (search trigger, required terms or None, contradiction or None). A search that matches
# triggers keeps a product only if its own text contains a required term of AT LEAST ONE
# matched trigger (a search for "abaya and hijab" accepts an abaya or a hijab) and none of
# the matched contradictions, so a yoga mat never answers "prayer mat" and a beach
# cover-up never answers "abaya", whatever its title says.
RELEVANCE_GUARDS = [
    (re.compile(r"prayer (mat|rug)|janamaz|sajad", re.I),
     ("prayer", "janamaz", "sajad", "musalla", "namaz", "islamic", "muslim"), None),
    (re.compile(r"\bihram\b", re.I), ("ihram", "ihraam", "ehram"), re.compile(r"costume|halloween", re.I)),
    (re.compile(r"\babaya", re.I), ("abaya",), _BEACHWEAR),
    (re.compile(r"\bhijab|underscarf", re.I), ("hijab", "underscarf", "under scarf", "khimar", "shayla"),
     re.compile(r"swim|burkini|costume|halloween", re.I)),
    (re.compile(r"prayer (dress|outfit|clothes|garment)", re.I), ("prayer",), _BEACHWEAR),
    (re.compile(r"unscented|fragrance[- ]free|scent[- ]free", re.I),
     ("unscented", "fragrance-free", "fragrance free", "scent-free", "scent free", "no fragrance",
      "without fragrance"), None),
    (re.compile(r"\btasbih|misbaha|prayer beads", re.I), ("tasbih", "tasbeeh", "misbaha", "prayer beads"), None),
    # Any search framed for a religious trip: no beachwear, swimwear or costumes.
    (re.compile(r"\b(umrah|hajj|modest|islamic|muslim)\b", re.I), None, _BEACHWEAR),
]

_UNSCENTED = ("unscented", "fragrance-free", "fragrance free", "scent-free", "scent free", "no fragrance",
              "without fragrance")
# Claims a reason may only make when the product's own text supports them:
# (claim pattern in the reason, terms one of which must appear in the product text).
CLAIMS = [
    (re.compile(r"\b(umrah|hajj|pilgrim)", re.I), ("umrah", "hajj", "pilgrim")),
    (re.compile(r"\bmodest", re.I), ("modest",)),
    (re.compile(r"\b(pray|salah|salat|namaz)", re.I),
     ("prayer", "pray", "salah", "salat", "namaz", "janamaz", "musalla", "sajad")),
    (re.compile(r"\b(ihram|ihraam|ehram)", re.I), ("ihram", "ihraam", "ehram")),
    (re.compile(r"\b(islamic|muslim|sharia|religious)", re.I), ("islamic", "muslim", "sharia")),
    (re.compile(r"\bcomplian", re.I), ("compliant",)),
    (re.compile(r"\bpermissible", re.I), ("permissible",)),
    (re.compile(r"\bhalal", re.I), ("halal",)),
    (re.compile(r"\bcertifi", re.I), ("certified",)),
    (re.compile(r"\bapproved", re.I), ("approved",)),
    (re.compile(r"\borganic", re.I), ("organic",)),
    (re.compile(r"\bwaterproof", re.I), ("waterproof",)),
    (re.compile(r"unscented|fragrance[- ]free|scent[- ]free|(without|no) (fragrance|scent)", re.I), _UNSCENTED),
]


def product_text(product: dict) -> str:
    return " ".join(str(product.get(k) or "") for k in ("name", "description", "category")).lower()


# Containers and bags hold toiletries; they aren't scented products, so "unscented" in a
# search doesn't apply to them.
_CONTAINER = re.compile(r"\b(bottles?|containers?|bags?|case|cases|pouch(es)?|organi[sz]ers?|dispensers?|jars?)\b",
                        re.I)
_UNSCENTED_TRIGGER = RELEVANCE_GUARDS[5][0]


def is_relevant(query: str, product: dict) -> bool:
    text = product_text(product)
    required_sets = []
    for trigger, required, contradiction in RELEVANCE_GUARDS:
        if not trigger.search(query or ""):
            continue
        # A contradiction never applies to what the search itself asks for: "modest" rules out
        # beachwear, but a search for a modest swimsuit wants swimwear.
        if contradiction and contradiction.search(text) and not contradiction.search(query or ""):
            return False
        if not required:
            continue
        if trigger is _UNSCENTED_TRIGGER and _CONTAINER.search(f"{product.get('name') or ''} {product.get('category') or ''}"):
            required_sets.append(None)  # satisfied: a container, not a scented product
        else:
            required_sets.append(required)
    if required_sets and not any(req is None or any(t in text for t in req) for req in required_sets):
        return False
    return True


# Items that only belong to one trip purpose. Another purpose's trip never searches them
# unless its own description points there (a Tourism trip "with a wedding" may need a suit).
PURPOSE_ONLY = {
    "umrah": (re.compile(r"\b(ihram|abayas?|hijabs?|prayer (mats?|rugs?)|janamaz|tasbih|misbaha)\b", re.I),
              re.compile(r"\b(umrah|hajj|mosque|pray(er|ing)?|islam\w*|muslim|modest|abaya|hijab|ihram)\b", re.I)),
    "business": (re.compile(r"\b(blazers?|suits?|dress shoes|formal (wear|clothing|shoes|attire)|oxford shoes|"
                            r"briefcases?|laptop (bags?|backpacks?)|business (attire|clothing|shoes)|ties?)\b", re.I),
                 re.compile(r"\b(business|conference|meetings?|clients?|presentations?|interviews?|wedding|gala|"
                            r"formal|office|work|suit|blazer|laptop)\b", re.I)),
}


def purpose_conflict(purpose: str, description: Optional[str], query: str, category: Optional[str] = None) -> bool:
    """True when a search is for another trip purpose's items that this trip's description
    gives no reason for (no Ihram on a business trip, no blazer on a beach holiday)."""
    key = purpose_key(purpose)
    text = f"{query or ''} {category or ''}"
    for other, (items, context) in PURPOSE_ONLY.items():
        if other != key and key != "other" and items.search(text) and not context.search(description or ""):
            return True
    return False


# Words that describe any product; they can't show what a product is.
_GENERIC = {"travel", "best", "comfortable", "lightweight", "light", "packable", "portable", "compact", "small",
            "large", "mini", "set", "kit", "pack", "for", "and", "with", "the", "a", "an", "of", "women", "men",
            "womens", "mens", "kids", "unisex", "new", "premium", "quality", "durable", "essentials", "essential",
            "accessories", "gear", "items", "products", "stuff", "trip", "vacation", "holiday", "summer", "winter"}
# A product matches its search if it names the searched item or a close kind of it.
_KINDS = {
    "mouse": {"mouse", "mice"}, "shoes": {"shoe", "sandal", "sneaker", "loafer", "boot", "oxford", "heel", "slide"},
    "footwear": {"shoe", "sandal", "sneaker", "loafer", "boot", "slide", "slipper"},
    "beachwear": {"swim", "swimsuit", "bikini", "trunk", "board short", "cover", "rash guard", "beach"},
    "swimwear": {"swim", "swimsuit", "bikini", "trunk"}, "rain": {"umbrella", "poncho", "raincoat", "waterproof", "rain"},
    "sunglasses": {"sunglass", "sunglasses", "shades"}, "sunscreen": {"sunscreen", "spf", "sun lotion", "sunblock"},
    "clothing": {"shirt", "blazer", "suit", "dress", "trouser", "pant", "blouse", "skirt", "jacket", "top", "abaya",
                 "hijab", "sweater", "coat", "polo", "jumpsuit"},
    "electronics": {"adapter", "charger", "power bank", "cable", "mouse", "keyboard", "headphone", "earbud", "stand"},
    "laptop": {"laptop", "notebook", "computer"}, "bag": {"bag", "backpack", "daypack", "tote", "pouch", "duffel"},
    "kids": {"kid", "child", "baby", "toddler", "infant", "stroller", "family"},
    "family": {"kid", "child", "baby", "toddler", "infant", "stroller", "family", "first aid"},
    "care": {"toiletr", "soap", "shampoo", "lotion", "cream", "wash", "bottle", "deodorant", "sanitizer", "wipe"},
    "prayer": {"prayer", "janamaz", "sajad", "musalla"}, "layers": {"jacket", "coat", "fleece", "sweater", "parka",
                                                                   "vest", "hoodie", "base layer", "thermal"},
    "sandals": {"sandal", "slide", "flip flop", "slipper"},
    "swimsuit": {"swim", "bikini", "burkini", "tankini", "one piece", "bathing"},
    "swimwear": {"swim", "bikini", "burkini", "tankini", "one piece", "bathing", "trunk"},
    "power": {"adapter", "charger", "power bank", "cable", "battery", "plug"},
    "charging": {"charger", "power bank", "cable", "battery"}, "adapter": {"adapter", "adaptor", "converter", "plug"},
    "bags": {"bag", "backpack", "daypack", "tote", "pouch", "cube", "organizer", "duffel"},
    "organizers": {"organizer", "cube", "pouch", "bag", "case"},
    "comfort": {"pillow", "mask", "plug", "cushion", "sock", "blanket"},
    "hydration": {"bottle", "flask", "mug", "straw", "tumbler", "filter", "electrolyte", "drink"},
    "outdoor": {"hiking", "trail", "camping", "trek"}, "photography": {"camera", "tripod", "lens", "selfie", "gimbal"},
    "ihram": {"ihram", "ihraam", "ehram"}, "modest": {"abaya", "hijab", "modest", "khimar", "jilbab", "underscarf"},
    "personal": {"toiletr", "soap", "shampoo", "lotion", "cream", "wash", "bottle", "deodorant", "care"},
}


def _stem(word: str) -> str:
    for suffix in ("es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def matches_category(query: str, category: Optional[str], product: dict) -> bool:
    """The product's own text names what was searched (or a close kind of it). A search with
    no specific item words (only "travel essentials") can't be checked and passes."""
    words = [w for w in re.findall(r"[a-z]+", f"{query or ''} {category or ''}".lower()) if w not in _GENERIC and len(w) > 2]
    if not words:
        return True
    text = product_text(product)
    for w in words:
        options = {w, _stem(w)} | _KINDS.get(w, set()) | _KINDS.get(_stem(w), set())
        if any(o in text for o in options):
            return True
    return False


def safe_reason(reason: Optional[str], product: dict) -> Optional[str]:
    """The reason, or None when it claims something the product data doesn't say
    (Umrah/prayer suitability, modesty, religious compliance, unscented, halal...)."""
    if not reason:
        return None
    text = product_text(product)
    for claim, support in CLAIMS:
        if claim.search(reason) and not any(term in text for term in support):
            return None
    return reason


# ---------------------------------------------------------- duplicates ---
# Words that don't make two products different: pack sizes, quantities, units, colors.
_DUP_IGNORE = {
    "pack", "packs", "pk", "pcs", "pc", "piece", "pieces", "set", "sets", "count", "ct", "of", "the", "a", "an",
    "and", "with", "for", "in", "x", "size", "oz", "fl", "ml", "l", "g", "kg", "lb", "lbs", "inch", "in",
    "cm", "mm", "new", "black", "white", "grey", "gray", "blue", "navy", "red", "green", "pink", "beige",
    "brown", "tan", "cream", "ivory", "khaki", "olive", "purple", "yellow", "orange", "rose", "dusty", "silver",
    "gold", "multicolor", "assorted",
}
_TOKEN = re.compile(r"[a-z]+")


_GENDER_WORDS = {"women", "womens", "woman", "men", "mens", "man", "ladies", "lady", "female", "male", "unisex",
                 "girls", "boys", "kids", "w", "m"}
_MODEL_CODE = re.compile(r"\b(?=[a-z0-9.\-]*\d)[a-z0-9][a-z0-9.\-]*\b", re.I)


def brand_key(product: dict) -> str:
    return " ".join(_TOKEN.findall(str(product.get("brand") or "").lower()))


def title_tokens(product: dict) -> frozenset:
    """The words that identify a product: no numbers, sizes, quantities, colors, gender words
    or the product's own brand name (retailers add or drop those)."""
    title = str(product.get("name") or "").lower().replace("\u2019", "'").replace("'s", "")
    brand = set(brand_key(product).split())
    return frozenset(t for t in _TOKEN.findall(title)
                     if t not in _DUP_IGNORE and t not in _GENDER_WORDS and t not in brand and len(t) > 1)


def model_codes(product: dict) -> frozenset:
    """Model numbers in the title, e.g. "2.0", "577", "x200" (pack counts like "3-pack" excluded)."""
    title = str(product.get("name") or "").lower()
    return frozenset(c.strip(".-") for c in _MODEL_CODE.findall(title)
                     if not re.fullmatch(r"\d+(-?(pack|pk|pcs|pc|piece|pieces|oz|ml|in|cm))?", c.strip(".-")))


def _jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def same_brand(a: dict, b: dict) -> bool:
    ba, bb = brand_key(a), brand_key(b)
    if ba and bb:
        return ba == bb
    # One side has no brand field: the other's brand written in its title counts.
    known, other = (ba, b) if ba else (bb, a)
    return bool(known) and known in " ".join(_TOKEN.findall(str(other.get("name") or "").lower()))


def is_near_duplicate(a: dict, b: dict, threshold: float = 0.8) -> bool:
    """The same product or model listed again: by another retailer, in another color or pack
    size, or with a reworded title. Different brands are never duplicates (that is real choice,
    limited per category instead)."""
    if a.get("id") and a.get("id") == b.get("id"):
        return True
    ba, bb = brand_key(a), brand_key(b)
    if ba and bb and ba != bb:
        return False
    if {infer_audience(a), infer_audience(b)} == {"men", "women"}:
        return False  # a model's men's and women's versions are different products to recommend
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    score = _jaccard(ta, tb)
    if score >= threshold:
        return True
    if not same_brand(a, b):
        return False
    if score >= 0.6:
        return True
    if model_codes(a) & model_codes(b) and len(ta & tb) >= 2:
        return True
    price_a, price_b = a.get("price"), b.get("price")
    return price_a is not None and price_a == price_b and score >= 0.5


def is_similar(a: dict, b: dict) -> bool:
    """Close variants within a category (e.g. two foldable travel mats): limited to one."""
    return is_near_duplicate(a, b) or _jaccard(title_tokens(a), title_tokens(b)) >= 0.6


# ------------------------------------------------------------ audience ---
_WOMEN = re.compile(r"\b(women'?s|womens|woman|female|ladies|lady'?s|girls'?)\b", re.I)
_MEN = re.compile(r"\b(men'?s|mens|man|male|boys'?|gentlemen'?s)\b", re.I)
_UNISEX = re.compile(r"\bunisex\b", re.I)


def infer_audience(product: dict) -> Optional[str]:
    """Audience stated by the product itself (title and Channel3 category, never images):
    "women" / "men", "all" when unisex or both are named, None when it doesn't say."""
    text = f"{product.get('name') or ''} {product.get('category') or ''}".replace("’", "'")
    if _UNISEX.search(text):
        return "all"
    women, men = bool(_WOMEN.search(text)), bool(_MEN.search(text))
    if women and men:
        return "all"
    return "women" if women else "men" if men else None


AUDIENCES = ("all", "men", "women")


def audience(value) -> Optional[str]:
    v = str(value or "").strip().lower()
    return v if v in AUDIENCES else None


def category_name(value, limit: int = 40) -> Optional[str]:
    text = " ".join(str(value or "").split())[:limit].strip()
    return text or None
