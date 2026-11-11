import hashlib
import logging
import math
import re
from typing import List, Optional
from urllib.parse import urlencode
from app.core.destinations import (
    CITY_COUNTRY_CODE, CITY_NAMES, COUNTRY_NAMES, compose_destination, country_code, display_city,
    resolve_trip_location,
)
from app.schemas.hotel_schema import BookingOffer, HotelItem, HotelOffersResponse, HotelSearchResponse
from app.services import serpapi_hotels
from app.services.hotel_matching import detect_intent, explain_match, score_hotel
from app.services.hotel_pricing import apply_live_prices, live_pricing_enabled
from app.services.serpapi_hotels import HotelApiError

log = logging.getLogger(__name__)

REAL_HOTELS_DB = [
    # Kyoto, Japan
    {
        "id": "kyo-01",
        "area": "gion",
        "tags": ["quiet", "landmarks", "museums", "central"],
        "name": "Kyoto Granbell Hotel",
        "destination": "kyoto",
        "country": "JP",
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
        "country": "JP",
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
        "country": "JP",
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
        "country": "JP",
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
        "country": "FR",
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
        "country": "FR",
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
        "country": "FR",
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
        "country": "EG",
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
        "tags": ["landmarks", "famous", "museums", "pool", "family"]
    },
    {
        "id": "cai-02",
        "name": "Steigenberger Hotel El Tahrir",
        "destination": "cairo",
        "country": "EG",
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
        "country": "EG",
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
        "country": "EG",
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
        "country": "EG",
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
        "country": "EG",
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
        "country": "EG",
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
        "country": "EG",
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
        "country": "EG",
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
        "country": "EG",
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
        "country": "EG",
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
    # Alexandria, Egypt
    # price_per_night = estimated USD per room per night; live prices replace it when enabled.
    {
        "id": "alx-01",
        "name": "Four Seasons Hotel Alexandria at San Stefano",
        "destination": "alexandria",
        "country": "EG",
        "area": "san-stefano",
        "location": "El Geish Road, San Stefano, Alexandria",
        "rating": 4.7,
        "reviews_count": 3400,
        "price_per_night": 280.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1541971875076-8f970d573be6?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Private beach", "Mediterranean views", "Infinity pool", "Spa"],
        "distance_to_center": "On the Corniche, about 20 minutes by car to Raml Station",
        "best_match_reason": "Alexandria's top luxury address, with a private beach and wide Mediterranean views.",
        "category": "Luxury hotel",
        "tags": ["beach", "pool", "famous", "quiet", "family", "wifi"]
    },
    {
        "id": "alx-02",
        "name": "Steigenberger Cecil Hotel Alexandria",
        "destination": "alexandria",
        "country": "EG",
        "area": "downtown",
        "location": "Saad Zaghloul Square, Raml Station, Alexandria",
        "rating": 4.4,
        "reviews_count": 2600,
        "price_per_night": 110.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1561501900-3701fa6a0864?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Historic 1929 hotel", "Sea-view rooms", "Free Wi-Fi", "Rooftop restaurant"],
        "distance_to_center": "Raml Station; short ride to the Bibliotheca Alexandrina",
        "best_match_reason": "The legendary 1929 Cecil on Saad Zaghloul Square, right in historic downtown Alexandria.",
        "category": "Boutique hotel",
        "tags": ["famous", "landmarks", "museums", "central", "wifi", "business"]
    },
    {
        "id": "alx-03",
        "name": "Paradise Inn Le Metropole Hotel",
        "destination": "alexandria",
        "country": "EG",
        "area": "downtown",
        "location": "Saad Zaghloul Street, Raml Station, Alexandria",
        "rating": 4.1,
        "reviews_count": 1900,
        "price_per_night": 60.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Historic building", "Sea views", "Free Wi-Fi", "Central location"],
        "distance_to_center": "Raml Station, next to the tram and Corniche",
        "best_match_reason": "A characterful early-1900s hotel in the heart of downtown, at a friendly price.",
        "category": "Budget stay",
        "tags": ["central", "landmarks", "museums", "wifi"]
    },
    {
        "id": "alx-04",
        "name": "Windsor Palace Hotel",
        "destination": "alexandria",
        "country": "EG",
        "area": "downtown",
        "location": "El Shohada Street, Raml Station, Alexandria",
        "rating": 4.0,
        "reviews_count": 1500,
        "price_per_night": 55.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1561501900-3701fa6a0864?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Corniche sea views", "Historic building", "Free Wi-Fi", "Breakfast included"],
        "distance_to_center": "On the Corniche at Raml Station",
        "best_match_reason": "A classic 1906 sea-front hotel on the downtown Corniche, good value for money.",
        "category": "Budget stay",
        "tags": ["central", "landmarks", "wifi"]
    },
    {
        "id": "alx-05",
        "name": "Helnan Palestine Hotel",
        "destination": "alexandria",
        "country": "EG",
        "area": "montaza",
        "location": "Montaza Palace Gardens, Alexandria",
        "rating": 4.3,
        "reviews_count": 2200,
        "price_per_night": 120.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1541971875076-8f970d573be6?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Inside Montaza gardens", "Private beach", "Outdoor pool", "Quiet setting"],
        "distance_to_center": "In the Montaza Palace grounds, east Alexandria",
        "best_match_reason": "A calm seaside stay inside the royal Montaza gardens, with its own beach.",
        "category": "Luxury hotel",
        "tags": ["beach", "quiet", "family", "pool", "landmarks"]
    },
    {
        "id": "alx-06",
        "name": "Hilton Alexandria Corniche",
        "destination": "alexandria",
        "country": "EG",
        "area": "sidi-bishr",
        "location": "El Geish Road, Sidi Bishr, Alexandria",
        "rating": 4.2,
        "reviews_count": 2800,
        "price_per_night": 110.0,
        "currency": "USD",
        "image_url": "https://images.unsplash.com/photo-1561501900-3701fa6a0864?auto=format&fit=crop&w=900&q=80",
        "amenities": ["Sea views", "Outdoor pool", "Business center", "Free Wi-Fi"],
        "distance_to_center": "On the Corniche, about 25 minutes by car to Raml Station",
        "best_match_reason": "A reliable Corniche hotel with sea views, a pool and good work facilities.",
        "category": "Boutique hotel",
        "tags": ["beach", "pool", "business", "wifi", "family"]
    },
    # Makkah (Umrah)
    {
        "id": "mak-01",
        "area": "haram",
        "tags": ["haram", "famous", "landmarks", "family"],
        "name": "Fairmont Makkah Clock Royal Tower",
        "destination": "makkah",
        "country": "SA",
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
        "country": "SA",
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
) -> str:
    """
    Booking.com SEARCH pre-filled with this hotel's name + city/country and the
    trip's dates, guests and rooms.

    We have no verified Booking.com property id or property URL for any curated
    hotel, so we never build a direct property page URL (a guessed slug can open
    the wrong hotel or a 404). The response marks these links as
    booking_link_type="search" so the UI can say exactly what the button does.
    """
    params = _booking_params(check_in, check_out, adults, rooms)
    query = f"{hotel_name}, {city_hint}" if city_hint else hotel_name
    return f"{BOOKING_BASE}/searchresults.html?{urlencode({'ss': query, **params})}"


def _location_verified(hotel: dict, city_key: str, requested_country: Optional[str]) -> bool:
    """A hotel is only recommended if its recorded location is the requested
    destination: same curated city, a country consistent with that city, and the
    country the traveler asked for (when they named one)."""
    if hotel.get("destination") != city_key:
        return False
    if hotel.get("country") != CITY_COUNTRY_CODE.get(city_key):
        return False  # inconsistent data: never show it as being in this city
    if requested_country and hotel.get("country") != requested_country:
        return False
    return True


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
    city: Optional[str] = None,
    country: Optional[str] = None,
) -> HotelSearchResponse:
    """
    Finds stays for the destination.

    - Location: the structured City/Country (or the destination text) decides the
      city. Only hotels whose recorded city AND country match are returned; the
      free-text note never changes the destination, it only ranks hotels within it.
    - Ranking: purpose, priorities, stay preference, the note (e.g. "interview
      downtown") and the budget.
    - Prices: MYMILE estimates per room per night (USD); replaced by a price listed
      for the exact dates/guests when a hotel price API key is configured. The
      total covers every night and every room the group needs.
    - Free Plan: booking_link is None. Premium: a Booking.com search for that hotel
      with the trip's dates and guests (never presented as a direct property page).
    """
    nights = max(int(total_nights or 1), 1)
    adults = max(int(travelers or 1), 1)
    rooms = max(1, math.ceil(adults / GUESTS_PER_ROOM))
    is_premium = plan.lower() == "premium"
    pref = _preference_key(stay_preference)

    if serpapi_hotels.is_enabled():
        # Live Google Hotels results (SerpApi) replace the curated list entirely.
        return await _search_live(destination, city, country, check_in, check_out, nights, adults,
                                  is_premium, pref, budget, stay_preference)

    city_key, requested_country = resolve_trip_location(destination, city, country)
    candidates = [h for h in REAL_HOTELS_DB if h["destination"] == city_key] if city_key else []
    matching = [h for h in candidates if _location_verified(h, city_key, requested_country)]
    if len(matching) != len(candidates):
        log.warning("Dropped %d hotel(s) whose location did not match %s/%s",
                    len(candidates) - len(matching), city_key, requested_country)

    result_items: List[HotelItem] = []
    intent = detect_intent(purpose, priorities or [], notes)
    # If they gave a budget, roughly half of it is a sensible ceiling for the stay.
    nightly_cap = (budget * 0.5 / nights / rooms) if budget else None
    location_by_id = {}

    if matching:
        matching.sort(key=lambda h: score_hotel(h, intent, pref, nightly_cap), reverse=True)
        matching = matching[:6]
        city_name = CITY_NAMES[city_key]
        country_name = COUNTRY_NAMES.get(CITY_COUNTRY_CODE[city_key], "")
        hint = f"{city_name}, {country_name}" if country_name else city_name
        for idx, h in enumerate(matching):
            location_by_id[h["id"]] = hint
            link = build_booking_link(h["name"], hint, check_in, check_out, adults, rooms)
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
                booking_link_type="search" if is_premium else None,
                category=h["category"],
                is_best_match=(idx == 0),
                nights=nights,
                rooms=rooms,
                city=city_name,
                country=h["country"],
                image_is_illustrative=True,  # curated entries use stock photos
            ))
    else:
        # No verified hotel data for this destination: never show another city's
        # hotels, and never present a made-up hotel. This card is a placeholder
        # that offers a Booking.com search for the destination itself.
        nightly = FALLBACK_NIGHTLY[pref]
        place = compose_destination(city, country, destination)
        city_name = (city or "").strip() or display_city(destination)
        link = (
            f"{BOOKING_BASE}/searchresults.html?"
            f"{urlencode({'ss': place, **_booking_params(check_in, check_out, adults, rooms)})}"
        )
        result_items.append(HotelItem(
            id="search-" + (re.sub(r"[^a-z0-9]+", "-", place.lower()).strip("-") or "destination"),
            name=f"{FALLBACK_LABEL[pref]} in {city_name}",
            location=place,
            rating=0,
            reviews_count=0,
            price_per_night=nightly,
            total_price=round(nightly * nights * rooms, 2),
            currency="USD",
            image_url=GENERIC_HOTEL_IMAGE,
            amenities=["Live availability", "Free cancellation options", "Compare prices", "Guest reviews"],
            distance_to_center=None,
            best_match_reason=(
                f"We don't have verified hotels for {city_name} yet. Search Booking.com for "
                f"{(stay_preference or 'hotel').lower()} options for your exact dates."
            ),
            booking_link=link if is_premium else None,
            booking_link_type="search" if is_premium else None,
            category=stay_preference or "Hotel",
            is_best_match=False,
            nights=nights,
            rooms=rooms,
            city=city_name,
            country=requested_country,
            image_is_illustrative=True,
            is_placeholder=True,
        ))

    if matching:
        await apply_live_prices(result_items, location_by_id, check_in, check_out, adults, nights, rooms)

    return HotelSearchResponse(
        destination=compose_destination(city, country, destination),
        check_in=check_in,
        check_out=check_out,
        total_nights=nights,
        hotels=result_items,
        source="MYMILE curated hotels" if matching else "Booking.com search",
    )


# ============================================================================
# Live hotels: SerpApi Google Hotels (enabled when HOTEL_API_KEY is configured)
# ============================================================================
MAX_LIVE_HOTELS = 6


def _live_category(prop: dict) -> str:
    if "vacation" in (prop.get("type") or "").lower():
        return "Vacation rental"
    if (prop.get("extracted_hotel_class") or 0) >= 5:
        return "Luxury hotel"
    return prop.get("hotel_class") or "Hotel"


def _live_reason(prop: dict) -> str:
    """Only facts Google Hotels returned for this property."""
    if prop.get("description"):
        text = prop["description"]
        return text if len(text) <= 240 else text[:237].rstrip() + "..."
    parts = []
    if prop.get("hotel_class"):
        parts.append(prop["hotel_class"])
    if prop.get("rating") and prop.get("reviews"):
        parts.append(f"rated {prop['rating']:.1f}/5 from {prop['reviews']:,} Google reviews")
    elif prop.get("rating"):
        parts.append(f"rated {prop['rating']:.1f}/5 on Google")
    return (" · ".join(parts) + ".") if parts else "Listed on Google Hotels for your dates."


def _rank_live(props: List[dict], pref: str, nightly_cap: Optional[float]) -> List[dict]:
    """Keep Google's relevance order, adjusted for the stay preference and budget."""
    def key(item):
        i, p = item
        price = p.get("nightly")
        over_cap = 1 if (nightly_cap and price and price > nightly_cap) else 0
        if pref == "budget":
            return (0 if price else 1, over_cap, price or 0, i)
        if pref == "luxury":
            return (over_cap, -(p.get("extracted_hotel_class") or 0), -(p.get("rating") or 0), i)
        if pref == "apartment":
            return (over_cap, 0 if "vacation" in (p.get("type") or "").lower() else 1, i)
        return (over_cap, i)
    return [p for _, p in sorted(enumerate(props), key=key)]


def _offer_models(offers: List[dict]) -> List[BookingOffer]:
    return [BookingOffer(**o) for o in offers if o.get("url")]


def _live_item(prop: dict, idx: int, q: str, city_name: str, country_iso: Optional[str], nights: int,
               adults: int, is_premium: bool, checked_at: str, stale: bool) -> HotelItem:
    nightly = prop.get("nightly")
    total, basis = prop.get("total"), None
    if total:
        basis = "listed"
    elif nightly:
        total, basis = nightly * nights, "nightly_x_nights"
    offer = serpapi_hotels.select_offer(prop.get("offers") or []) if is_premium else None
    images = prop.get("images") or []
    ident = prop.get("property_token") or f"{prop['name']}|{q}"
    return HotelItem(
        id="gh-" + hashlib.sha1(ident.encode("utf-8")).hexdigest()[:12],
        name=prop["name"],
        location=prop.get("address") or q,
        rating=prop.get("rating") or 0,
        reviews_count=prop.get("reviews") or 0,
        price_per_night=round(nightly, 2) if nightly else None,
        total_price=round(total, 2) if total else None,
        currency=serpapi_hotels.CURRENCY,
        image_url=images[0] if images else GENERIC_HOTEL_IMAGE,
        images=images,
        image_is_illustrative=not images,
        amenities=prop.get("amenities") or [],
        distance_to_center=prop.get("nearby"),
        best_match_reason=_live_reason(prop),
        booking_link=offer["url"] if offer else None,
        booking_link_type="provider" if offer else None,
        booking_provider=offer["provider"] if offer else None,
        booking_offers=_offer_models(prop.get("offers") or []) if is_premium else [],
        official_website=prop.get("website") if is_premium else None,
        category=_live_category(prop),
        is_best_match=(idx == 0),
        price_source="live",
        price_provider="Google Hotels",
        price_basis="per_night_for_party",
        nights=nights,
        rooms=1,
        adults=adults,
        taxes_included=prop.get("taxes_included"),
        price_checked_at=checked_at,
        total_price_basis=basis,
        city=city_name,
        country=country_iso,
        data_source="serpapi",
        property_token=prop.get("property_token"),
        description=prop.get("description"),
        address=prop.get("address"),
        latitude=prop.get("latitude"),
        longitude=prop.get("longitude"),
        hotel_class=prop.get("hotel_class"),
        results_stale=stale,
    )


def _live_placeholder(q: str, city_name: str, country_iso: Optional[str], nights: int, adults: int,
                      status: str, reason: str, stay_preference: str) -> HotelItem:
    return HotelItem(
        id=f"live-{status}-" + (re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-") or "destination"),
        name="No hotels found for these dates" if status == "empty" else "Live hotel results unavailable",
        location=q,
        rating=0,
        reviews_count=0,
        price_per_night=None,
        total_price=None,
        currency=serpapi_hotels.CURRENCY,
        image_url=GENERIC_HOTEL_IMAGE,
        image_is_illustrative=True,
        amenities=[],
        best_match_reason=reason,
        category=stay_preference or "Hotel",
        is_best_match=False,
        price_source="live",
        price_basis="per_night_for_party",
        nights=nights,
        rooms=1,
        adults=adults,
        city=city_name,
        country=country_iso,
        is_placeholder=True,
        data_source="serpapi",
    )


async def _search_live(destination: str, city: Optional[str], country: Optional[str], check_in: str,
                       check_out: str, nights: int, adults: int, is_premium: bool, pref: str,
                       budget: Optional[float], stay_preference: str) -> HotelSearchResponse:
    q = compose_destination(city, country, destination)
    city_name = (city or "").strip() or display_city(destination)
    country_iso = country_code(country) if country else None
    source = "Google Hotels via SerpApi"

    def respond(items, status, checked=None):
        return HotelSearchResponse(destination=q, check_in=check_in, check_out=check_out,
                                   total_nights=nights, hotels=items, source=source,
                                   results_status=status, checked_at=checked)

    try:
        result = await serpapi_hotels.search_hotels(q, check_in, check_out, adults)
    except HotelApiError as err:
        reason = f"We couldn't load live hotel results for {q} right now: {err.message} Please try again later."
        return respond([_live_placeholder(q, city_name, country_iso, nights, adults, "unavailable",
                                          reason, stay_preference)], "unavailable")

    checked = serpapi_hotels.iso(result["checked_at"])
    props = result["properties"]
    if not props:
        reason = (f"Google Hotels didn't list any hotels for {q} on these dates. "
                  "Try different dates or a nearby city.")
        return respond([_live_placeholder(q, city_name, country_iso, nights, adults, "empty",
                                          reason, stay_preference)], "empty", checked)

    nightly_cap = (budget * 0.5 / nights) if budget else None
    ranked = _rank_live(props, pref, nightly_cap)[:MAX_LIVE_HOTELS]
    items = [_live_item(p, i, q, city_name, country_iso, nights, adults, is_premium, checked, result["stale"])
             for i, p in enumerate(ranked)]
    return respond(items, "cached" if result["stale"] else "live", checked)


async def get_hotel_offers(property_token: str, destination: str, check_in: str, check_out: str,
                           adults: int, city: Optional[str] = None,
                           country: Optional[str] = None) -> Optional[HotelOffersResponse]:
    """Provider booking links for a hotel from a previous live search (callers must
    already have checked Premium). Returns None when the hotel is not part of a
    cached search for exactly these parameters, so arbitrary tokens can't spend quota.

    Uses links already present in the search results when there are any; otherwise
    one property-details request, which is cached like searches."""
    q = compose_destination(city, country, destination)
    adults = max(int(adults or 1), 1)

    def unavailable(message: str) -> HotelOffersResponse:
        return HotelOffersResponse(property_token=property_token, status="unavailable", message=message)

    if not serpapi_hotels.is_enabled():
        return unavailable(serpapi_hotels.ERROR_MESSAGES["NOT_CONFIGURED"])
    search = serpapi_hotels.cached_search(q, check_in, check_out, adults)
    prop = next((p for p in (search or {}).get("properties", []) if p.get("property_token") == property_token),
                None)
    if prop is None:
        return None

    offers = prop.get("offers") or []
    details, checked, stale = None, search["checked_at"], False
    if not any(o.get("url") for o in offers):
        try:
            found = await serpapi_hotels.property_details(property_token, q, check_in, check_out, adults)
        except HotelApiError as err:
            return unavailable(f"Booking links couldn't be loaded right now: {err.message}")
        details, checked, stale = found["property"], found["checked_at"], found["stale"]
        offers = (details or {}).get("offers") or []

    chosen = serpapi_hotels.select_offer(offers)
    info = details or prop
    return HotelOffersResponse(
        property_token=property_token,
        status="ok",
        message=None if chosen else "No booking provider link was listed for this hotel.",
        booking_link=chosen["url"] if chosen else None,
        booking_provider=chosen["provider"] if chosen else None,
        booking_offers=_offer_models(offers),
        official_website=info.get("website") or prop.get("website"),
        address=info.get("address") or prop.get("address"),
        phone=info.get("phone"),
        checked_at=serpapi_hotels.iso(checked),
        stale=stale,
    )
