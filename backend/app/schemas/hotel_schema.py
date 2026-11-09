from typing import List, Optional
from pydantic import BaseModel

class HotelItem(BaseModel):
    id: str
    name: str
    location: str
    rating: float
    reviews_count: Optional[int] = 0
    price_per_night: float
    total_price: float
    currency: str = "USD"
    image_url: str
    amenities: List[str]
    distance_to_center: Optional[str] = None
    best_match_reason: str
    booking_link: Optional[str] = None  # Gated to Premium users
    category: Optional[str] = "Boutique"  # Boutique, Luxury, Budget, Apartment
    is_best_match: bool = False
    price_source: str = "estimate"  # "estimate" or "live"
    price_provider: Optional[str] = None  # e.g. "Booking.com" when the price is live

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
