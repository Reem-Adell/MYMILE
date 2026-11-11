from typing import List, Optional
from pydantic import BaseModel


class BookingOffer(BaseModel):
    """One booking site's offer for a hotel, exactly as Google Hotels listed it."""
    provider: str                       # e.g. "Booking.com", "Expedia"
    url: Optional[str] = None           # the provider URL returned by SerpApi; never constructed
    price_per_night: Optional[float] = None
    total_price: Optional[float] = None
    currency: str = "USD"
    official: bool = False              # the hotel's own booking site
    free_cancellation: Optional[bool] = None


class HotelItem(BaseModel):
    id: str
    name: str
    location: str
    rating: float
    reviews_count: Optional[int] = 0
    # None = no price listed (live results only; never invented).
    price_per_night: Optional[float] = None
    total_price: Optional[float] = None
    currency: str = "USD"
    image_url: str
    amenities: List[str]
    distance_to_center: Optional[str] = None
    best_match_reason: str
    booking_link: Optional[str] = None  # Gated to Premium users
    category: Optional[str] = "Boutique"  # Boutique, Luxury, Budget, Apartment
    is_best_match: bool = False
    # "estimate" = MYMILE's typical rate; "live" = a price currently listed for
    # these exact dates/guests by a booking site (via Google Hotels). Neither is
    # a confirmed, bookable rate.
    price_source: str = "estimate"
    price_provider: Optional[str] = None  # e.g. "Booking.com" when the price is listed
    price_basis: str = "per_room_per_night"  # what price_per_night means
    nights: int = 1
    rooms: int = 1
    taxes_included: Optional[bool] = None  # None = unknown
    price_checked_at: Optional[str] = None  # ISO time a listed price was fetched
    # Structured, validated location of the hotel.
    city: Optional[str] = None
    country: Optional[str] = None  # ISO code, e.g. "EG"
    # "search" = Booking.com search pre-filled with this hotel + trip (not a direct
    # property page). "property" only when a verified property URL exists.
    booking_link_type: Optional[str] = None
    image_is_illustrative: bool = False  # stock photo, not of this property
    is_placeholder: bool = False  # not a hotel: "no verified hotels here yet"

    # ---- Live Google Hotels data (SerpApi). All optional; never invented. ----
    data_source: str = "curated"  # "curated" (MYMILE list) | "serpapi" (Google Hotels)
    property_token: Optional[str] = None  # Google Hotels id, used to look up provider links
    description: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    hotel_class: Optional[str] = None  # e.g. "4-star hotel"
    images: List[str] = []
    adults: Optional[int] = None  # live prices are listed for this many adults
    # "listed" = provider's total for the stay; "nightly_x_nights" = computed from the nightly rate.
    total_price_basis: Optional[str] = None
    # Premium only: the chosen provider (booking_link) and all offers with a URL.
    booking_provider: Optional[str] = None
    booking_offers: List[BookingOffer] = []
    official_website: Optional[str] = None  # hotel's own website: NOT a booking provider link
    results_stale: bool = False  # live lookup failed; these are cached results from price_checked_at

class HotelSearchRequest(BaseModel):
    destination: str
    check_in: str
    check_out: str
    travelers: int = 2
    budget: Optional[float] = None
    stay_preference: Optional[str] = "Boutique hotel"
    plan: str = "free"

class HotelSearchResponse(BaseModel):
    destination: str
    check_in: str
    check_out: str
    total_nights: int
    hotels: List[HotelItem]
    source: str = "MYMILE Verified Accommodations Provider"
    # Live results only: "live" | "cached" (live failed, cached shown) | "empty" | "unavailable".
    results_status: Optional[str] = None
    checked_at: Optional[str] = None


class HotelOffersResponse(BaseModel):
    """Provider booking links for one hotel from a previous live search (Premium)."""
    property_token: str
    status: str  # "ok" | "unavailable"
    message: Optional[str] = None
    booking_link: Optional[str] = None
    booking_provider: Optional[str] = None
    booking_offers: List[BookingOffer] = []
    official_website: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    checked_at: Optional[str] = None
    stale: bool = False
