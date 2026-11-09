import math
import re
from typing import List, Optional
from urllib.parse import urlencode
from app.schemas.hotel_schema import HotelItem, HotelSearchResponse
from app.services.hotel_matching import detect_intent, explain_match, score_hotel
from app.services.hotel_pricing import apply_live_prices, live_pricing_enabled

REAL_HOTELS_DB = [
    # Kyoto, Japan
    {
        "id": "kyo-01",
        "area": "gion",
        "tags": ["quiet", "landmarks", "museums", "central"],
        "name": "Kyoto Granbell Hotel",
        "destination": "kyoto",
        "location": "Gion, Kyoto · 5 min walk to Hanamikoji",
        "rating": 4.8,
        "reviews_count": 1240,
        "price_per_night": 204.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Traditional Onsen Bath", "Free High-Speed Wi-Fi", "Japanese & Western Breakfast", "Zen Garden Lounge", "Cocktail Bar"],
        "distance_to_center": "0.4 km from Gion-Shijo Station",
        "best_match_reason": "A quiet, design-led stay in historic Gion—perfect for slow mornings, cultural walks, and tea houses.",
        "category": "Boutique hotel"
    },
    {
        "id": "kyo-02",
        "area": "station",
        "tags": ["business", "wifi", "central", "famous"],
        "name": "The Thousand Kyoto",
        "destination": "kyoto",
        "location": "Shimogyo Ward, Kyoto · 2 min from Kyoto Station",
        "rating": 4.9,
        "reviews_count": 2180,
        "price_per_night": 295.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Luxury Wellness Spa", "Tea Ceremony Corner", "Concierge Service", "Fine Dining Italian & Japanese", "Fitness Center"],
        "distance_to_center": "0.1 km from Kyoto Central Station",
        "best_match_reason": "High-end comfort with architectural minimalism and zero transit friction for day trips.",
        "category": "Luxury hotel"
    },
    {
        "id": "kyo-03",
        "area": "downtown",
        "tags": ["nightlife"],
        "name": "Piece Hostel Sanjo",
        "destination": "kyoto",
        "location": "Nakagyo Ward, Kyoto · Central shopping arcade",
        "rating": 4.7,
        "reviews_count": 3410,
        "price_per_night": 68.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1590490360182-c33d57733427?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Private En-suite Rooms", "Communal Kitchen", "Terrace Cafe", "Free Breakfast", "Bicycle Rental"],
        "distance_to_center": "0.8 km from Nishiki Market",
        "best_match_reason": "Ultra-clean budget design stay with friendly social lounge and walkability to food markets.",
        "category": "Budget stay"
    },
    {
        "id": "kyo-04",
        "area": "station",
        "tags": ["family", "wifi"],
        "name": "MIMARU Kyoto Station",
        "destination": "kyoto",
        "location": "Minami Ward, Kyoto",
        "rating": 4.8,
        "reviews_count": 920,
        "price_per_night": 185.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Full Kitchenette", "In-room Dining Table", "Family Bunk Beds", "Coin Laundry", "Living Area"],
        "distance_to_center": "0.5 km from Kyoto Station",
        "best_match_reason": "Spacious apartment-style suites ideal for families and travelers wanting home comforts and self-catering.",
        "category": "Apartment"
    },
    # Paris, France
    {
        "id": "par-01",
        "area": "oberkampf",
        "tags": ["quiet", "nightlife", "wifi"],
        "name": "Hôtel Fabric Paris",
        "destination": "paris",
        "location": "11th Arrondissement, Oberkampf, Paris",
        "rating": 4.9,
        "reviews_count": 1870,
        "price_per_night": 230.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1549294413-26f195200c16?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Hammam Spa", "Artisan Bakery Breakfast", "Honesty Bar", "Fitness Room", "Designer Bath Products"],
        "distance_to_center": "1.2 km from Place des Vosges / Marais",
        "best_match_reason": "Former textile factory turned boutique haven, located steps from world-class patisseries and bistros.",
        "category": "Boutique hotel"
    },
    {
        "id": "par-02",
        "area": "gare-de-lyon",
        "tags": ["business", "wifi", "central"],
        "name": "CitizenM Paris Gare de Lyon",
        "destination": "paris",
        "location": "12th Arrondissement, Paris",
        "rating": 4.7,
        "reviews_count": 4200,
        "price_per_night": 165.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1578683010236-d716f9a3f461?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Rooftop Cloud Bar", "Smart Room Tablet Control", "Rain Shower", "Workspaces", "24/7 Food & Drinks"],
        "distance_to_center": "0.2 km from Gare de Lyon Metro",
        "best_match_reason": "High-tech comfort with panoramic skyline views and effortless metro transit across Paris.",
        "category": "Boutique hotel"
    },
    {
        "id": "par-03",
        "area": "canal",
        "tags": ["nightlife"],
        "name": "Generator Paris",
        "destination": "paris",
        "location": "10th Arrondissement, Canal Saint-Martin, Paris",
        "rating": 4.5,
        "reviews_count": 5100,
        "price_per_night": 75.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Rooftop Cafe with Sacré-Cœur Views", "Private Rooms Available", "Underground Lounge", "Lockers"],
        "distance_to_center": "0.3 km from Colonel Fabien Metro",
        "best_match_reason": "Vibrant budget social hub near romantic Canal Saint-Martin with lively cafes and budget-friendly private rooms.",
        "category": "Budget stay"
    },
    # Cairo & Giza, Egypt
    # price_per_night = estimated USD per room per night; live prices replace it when enabled.
    {
        "id": "cai-01",
        "name": "Marriott Mena House, Cairo",
        "destination": "cairo",
        "area": "giza",
        "location": "Pyramids Road, Giza, Cairo",
        "rating": 4.7,
        "reviews_count": 3120,
        "price_per_night": 230.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1541971875076-8f970d573be6?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Great Pyramid views", "Historic palace gardens", "Outdoor pool", "Spa"],
        "distance_to_center": "Faces the Great Pyramid of Giza",
        "best_match_reason": "A legendary 19th-century palace hotel with the Great Pyramid right outside.",
        "category": "Luxury hotel",
        "tags": ["landmarks", "famous", "museums", "pool", "family"],
        "booking_slug": "eg/mena-house-oberoi"
    },
    {
        "id": "cai-02",
        "name": "Steigenberger Hotel El Tahrir",
        "destination": "cairo",
        "area": "downtown",
        "location": "Tahrir Square, Downtown Cairo",
        "rating": 4.5,
        "reviews_count": 2840,
        "price_per_night": 95.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1561501900-3701fa6a0864?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Free Wi-Fi", "Rooftop pool", "Fitness center", "Next to Tahrir metro"],
        "distance_to_center": "Short walk to the Egyptian Museum",
        "best_match_reason": "Modern rooms right on Tahrir Square, a few minutes' walk from the Egyptian Museum.",
        "category": "Boutique hotel",
        "tags": ["central", "museums", "wifi", "business"]
    },
    {
        "id": "cai-03",
        "name": "The Nile Ritz-Carlton, Cairo",
        "destination": "cairo",
        "area": "downtown",
        "location": "Corniche El Nil, Tahrir, Cairo",
        "rating": 4.7,
        "reviews_count": 5200,
        "price_per_night": 260.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1541971875076-8f970d573be6?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Nile views", "Outdoor pool", "Spa", "Free Wi-Fi"],
        "distance_to_center": "Next door to the Egyptian Museum",
        "best_match_reason": "Cairo's landmark Nile-front hotel beside the Egyptian Museum and Tahrir Square.",
        "category": "Luxury hotel",
        "tags": ["famous", "museums", "landmarks", "central", "nile", "pool", "wifi", "business"]
    },
    {
        "id": "cai-04",
        "name": "Kempinski Nile Hotel Garden City",
        "destination": "cairo",
        "area": "downtown",
        "location": "Corniche El Nil, Garden City, Cairo",
        "rating": 4.6,
        "reviews_count": 2100,
        "price_per_night": 190.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1561501900-3701fa6a0864?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Free Wi-Fi", "Quiet boutique floors", "Rooftop pool", "Spa"],
        "distance_to_center": "About 10 minutes' walk to Tahrir Square",
        "best_match_reason": "A smaller, calm Nile-side hotel in leafy Garden City, minutes from Downtown offices.",
        "category": "Boutique hotel",
        "tags": ["quiet", "wifi", "business", "central", "nile"]
    },
    {
        "id": "cai-05",
        "name": "InterContinental Cairo Semiramis",
        "destination": "cairo",
        "area": "downtown",
        "location": "Corniche El Nil, Garden City, Cairo",
        "rating": 4.4,
        "reviews_count": 4300,
        "price_per_night": 150.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1561501900-3701fa6a0864?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Business center", "Free Wi-Fi", "Meeting rooms", "Outdoor pool"],
        "distance_to_center": "A few minutes' walk to Tahrir Square",
        "best_match_reason": "A long-standing business hotel on the Nile with a full business center, close to Tahrir.",
        "category": "Boutique hotel",
        "tags": ["business", "wifi", "central", "nile", "pool"]
    },
    {
        "id": "cai-06",
        "name": "Four Seasons Hotel Cairo at Nile Plaza",
        "destination": "cairo",
        "area": "downtown",
        "location": "Corniche El Nil, Garden City, Cairo",
        "rating": 4.8,
        "reviews_count": 3900,
        "price_per_night": 330.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1541971875076-8f970d573be6?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Nile views", "Spa", "Outdoor pool", "Free Wi-Fi"],
        "distance_to_center": "About 15 minutes' walk to Tahrir Square",
        "best_match_reason": "Top-tier service and calm, spacious rooms overlooking the Nile in Garden City.",
        "category": "Luxury hotel",
        "tags": ["quiet", "wifi", "business", "nile", "famous", "pool"]
    },
    {
        "id": "cai-07",
        "name": "Pension Roma",
        "destination": "cairo",
        "area": "downtown",
        "location": "Mohamed Farid Street, Downtown Cairo",
        "rating": 4.3,
        "reviews_count": 1500,
        "price_per_night": 30.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Historic building", "Simple clean rooms", "Central location", "Breakfast available"],
        "distance_to_center": "Walk to Talaat Harb and the Egyptian Museum",
        "best_match_reason": "A characterful, very affordable old Downtown guesthouse within walking distance of everything.",
        "category": "Budget stay",
        "tags": ["central", "museums"]
    },
    {
        "id": "cai-08",
        "name": "Cairo Marriott Hotel & Omar Khayyam Casino",
        "destination": "cairo",
        "area": "zamalek",
        "location": "Saray El Gezira Street, Zamalek, Cairo",
        "rating": 4.5,
        "reviews_count": 6100,
        "price_per_night": 160.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1541971875076-8f970d573be6?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Historic palace", "Garden terrace", "Outdoor pool", "Many restaurants"],
        "distance_to_center": "Zamalek island, about 10 minutes by car to Downtown",
        "best_match_reason": "Built around a 19th-century royal palace on Zamalek, with gardens, pool and lively restaurants.",
        "category": "Luxury hotel",
        "tags": ["famous", "landmarks", "pool", "family", "nightlife", "nile"]
    },
    {
        "id": "cai-09",
        "name": "Sofitel Cairo Nile El Gezirah",
        "destination": "cairo",
        "area": "zamalek",
        "location": "El Gezira, Zamalek, Cairo",
        "rating": 4.6,
        "reviews_count": 3300,
        "price_per_night": 170.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1541971875076-8f970d573be6?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Nile on three sides", "Spa", "Outdoor pool", "Free Wi-Fi"],
        "distance_to_center": "Southern tip of Gezira island, near the Cairo Opera House",
        "best_match_reason": "A round tower on the tip of Gezira island with sweeping Nile views and a calm atmosphere.",
        "category": "Luxury hotel",
        "tags": ["nile", "quiet", "pool", "nightlife", "wifi"]
    },
    {
        "id": "cai-10",
        "name": "Steigenberger Pyramids Cairo",
        "destination": "cairo",
        "area": "giza",
        "location": "Alexandria Desert Road, Giza",
        "rating": 4.4,
        "reviews_count": 2700,
        "price_per_night": 110.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1561501900-3701fa6a0864?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Large pool area", "Family rooms", "Free Wi-Fi", "Restaurants on site"],
        "distance_to_center": "Close to the Pyramids and the Grand Egyptian Museum",
        "best_match_reason": "Good-value resort-style base near the Pyramids and the Grand Egyptian Museum.",
        "category": "Boutique hotel",
        "tags": ["landmarks", "museums", "pool", "family", "wifi"]
    },
    {
        "id": "cai-11",
        "name": "Le Méridien Cairo Airport",
        "destination": "cairo",
        "area": "airport",
        "location": "Cairo International Airport, Heliopolis",
        "rating": 4.3,
        "reviews_count": 2400,
        "price_per_night": 140.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Connected to Terminal 3", "Soundproofed rooms", "Free Wi-Fi", "24h dining"],
        "distance_to_center": "At Cairo International Airport",
        "best_match_reason": "Walk straight from Terminal 3 to your room: ideal for short stays and early flights.",
        "category": "Boutique hotel",
        "tags": ["quiet", "wifi", "business"]
    },
    # Makkah (Umrah)
    {
        "id": "mak-01",
        "area": "haram",
        "tags": ["haram", "famous", "landmarks", "family"],
        "name": "Fairmont Makkah Clock Royal Tower",
        "destination": "makkah",
        "location": "Abraj Al Bait Complex, Makkah",
        "rating": 4.9,
        "reviews_count": 4890,
        "price_per_night": 280.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1580418827493-f2b22c0a76cb?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Direct Haram Views", "Direct Haram Elevator Access", "Audio Broadcast from Holy Kaaba", "Multiple Restaurants", "VIP Butler Service"],
        "distance_to_center": "50 meters from King Abdulaziz Gate",
        "best_match_reason": "Closest access to the Holy Mosque with breathtaking panoramic Kaaba views and maximum spiritual comfort.",
        "category": "Luxury hotel"
    },
    {
        "id": "mak-02",
        "area": "haram",
        "tags": ["haram", "family"],
        "name": "Swissôtel Al Maqam Makkah",
        "destination": "makkah",
        "location": "Ibrahim Al Khalil St, Makkah",
        "rating": 4.8,
        "reviews_count": 3670,
        "price_per_night": 195.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1512958789358-4dacac72a912?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Direct Al Masjid Al Haram Access", "Buffet Restaurant", "Express Check-in", "Family Suites"],
        "distance_to_center": "100 meters from Grand Mosque courtyard",
        "best_match_reason": "Smooth hospitality with direct indoor access to the prayer halls for effortless Umrah performance.",
        "category": "Boutique hotel"
    }
]

# Words in the destination text that map to a city in REAL_HOTELS_DB.
DESTINATION_ALIASES = {
    "kyoto": ["kyoto", "japan"],
    "paris": ["paris", "france"],
    "cairo": ["cairo", "giza", "egypt"],
    "makkah": ["makkah", "mecca", "makka"],
}

# Typical nightly rate per room (USD) used when we have no hotel data for a city.
FALLBACK_NIGHTLY = {"luxury": 260.0, "boutique": 150.0, "budget": 70.0, "apartment": 120.0}

FALLBACK_LABEL = {
    "luxury": "Luxury hotels",
    "boutique": "Boutique hotels",
    "budget": "Budget stays",
    "apartment": "Apartments",
}

GENERIC_HOTEL_IMAGE = (
    "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=900&q=80"
)

BOOKING_BASE = "https://www.booking.com"
GUESTS_PER_ROOM = 2


def _match_city(destination: str) -> Optional[str]:
    dest = destination.lower()
    for city, words in DESTINATION_ALIASES.items():
        if any(w in dest for w in words):
            return city
    return None


def _preference_key(text: str) -> str:
    t = (text or "").lower()
    for key in ("luxury", "boutique", "budget", "apartment"):
        if key in t:
            return key
    return "boutique"


def _booking_params(check_in: str, check_out: str, adults: int, rooms: int) -> dict:
    return {
        "checkin": check_in,
        "checkout": check_out,
        "group_adults": adults,
        "group_children": 0,
        "no_rooms": rooms,
        "selected_currency": "USD",
    }


def build_booking_link(
    hotel_name: str,
    city_hint: str,
    check_in: str,
    check_out: str,
    adults: int,
    rooms: int,
    slug: Optional[str] = None,
) -> str:
    """
    Booking.com link with the trip's dates and guests filled in, so the page shows the
    live price for this exact stay.
    - With a confirmed hotel slug: opens that hotel's page directly.
    - Without one: opens a Booking.com search for the hotel name + city. This always
      resolves (no "Page Not Found") and lists the hotel at the top.
    """
    params = _booking_params(check_in, check_out, adults, rooms)
    if slug:
        return f"{BOOKING_BASE}/hotel/{slug}.html?{urlencode(params)}"
    query = f"{hotel_name}, {city_hint}" if city_hint else hotel_name
    return f"{BOOKING_BASE}/searchresults.html?{urlencode({'ss': query, **params})}"


async def search_hotels(
    destination: str,
    check_in: str = "2026-04-08",
    check_out: str = "2026-04-15",
    total_nights: int = 7,
    stay_preference: str = "Boutique hotel",
    plan: str = "free",
    budget: Optional[float] = None,
    travelers: int = 2,
    purpose: str = "Tourism",
    priorities: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> HotelSearchResponse:
    """
    Finds stays for the destination.
    - Hotels are ranked against what the traveler needs: the area named in their note
      (e.g. "interview downtown"), the trip purpose (work -> quiet, Wi-Fi, business;
      tourism -> famous, near museums), their priorities and their stay preference.
    - Live prices replace the estimates when a hotel price API key is configured.
    - Prices are estimates per room per night; the total covers every room the group needs.
    - Free Plan: booking_link is None (external booking links gated).
    - Premium Plan: booking_link opens Booking.com with the trip's dates and guests filled in.
    """
    nights = max(int(total_nights or 1), 1)
    adults = max(int(travelers or 1), 1)
    rooms = max(1, math.ceil(adults / GUESTS_PER_ROOM))
    is_premium = plan.lower() == "premium"
    pref = _preference_key(stay_preference)

    city = _match_city(destination)
    matching = [h for h in REAL_HOTELS_DB if h["destination"] == city] if city else []

    result_items: List[HotelItem] = []

    intent = detect_intent(purpose, priorities or [], notes)
    # If they gave a budget, roughly half of it is a sensible ceiling for the stay.
    nightly_cap = (budget * 0.5 / nights / rooms) if budget else None
    city_by_id = {}

    if matching:
        matching.sort(key=lambda h: score_hotel(h, intent, pref, nightly_cap), reverse=True)
        matching = matching[:6]
        for idx, h in enumerate(matching):
            city_by_id[h["id"]] = h["location"].split(",")[-1].strip()
            city_hint = h["location"].split(",")[-1].strip()
            link = build_booking_link(
                h["name"], city_hint, check_in, check_out, adults, rooms, h.get("booking_slug")
            )
            result_items.append(HotelItem(
                id=h["id"],
                name=h["name"],
                location=h["location"],
                rating=h["rating"],
                reviews_count=h["reviews_count"],
                price_per_night=h["price_per_night"],
                total_price=round(h["price_per_night"] * nights * rooms, 2),
                currency=h["currency"],
                image_url=h["image_url"],
                amenities=h["amenities"],
                distance_to_center=h["distance_to_center"],
                best_match_reason=explain_match(h, intent),
                booking_link=link if is_premium else None,
                category=h["category"],
                is_best_match=(idx == 0),
            ))
    else:
        # No hotel data for this city: never show another city's hotels.
        # Offer a Booking.com search for the destination instead.
        nightly = FALLBACK_NIGHTLY[pref]
        city_name = destination.split(",")[0].strip() or destination
        link = (
            f"{BOOKING_BASE}/searchresults.html?"
            f"{urlencode({'ss': destination, **_booking_params(check_in, check_out, adults, rooms)})}"
        )
        result_items.append(HotelItem(
            id="search-" + re.sub(r"[^a-z0-9]+", "-", destination.lower()).strip("-"),
            name=f"{FALLBACK_LABEL[pref]} in {city_name}",
            location=destination,
            rating=0,
            reviews_count=0,
            price_per_night=nightly,
            total_price=round(nightly * nights * rooms, 2),
            currency="USD",
            image_url=GENERIC_HOTEL_IMAGE,
            amenities=["Live availability", "Free cancellation options", "Compare prices", "Guest reviews"],
            distance_to_center=None,
            best_match_reason=(
                f"We don't have handpicked hotels for {city_name} yet. Open Booking.com to see live "
                f"{(stay_preference or 'hotel').lower()} options for your exact dates."
            ),
            booking_link=link if is_premium else None,
            category=stay_preference or "Hotel",
            is_best_match=True,
        ))

    if matching:
        await apply_live_prices(result_items, city_by_id, check_in, check_out, adults, nights, rooms)

    return HotelSearchResponse(
        destination=destination,
        check_in=check_in,
        check_out=check_out,
        total_nights=nights,
        hotels=result_items,
        source="MYMILE Verified Accommodations Provider" if matching else "Booking.com search",
    )
