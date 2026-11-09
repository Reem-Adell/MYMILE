from typing import List, Optional
from pydantic import BaseModel

class PlaceItem(BaseModel):
    id: str
    name: str
    category: str  # Historical, Culture, Nature, Food, Landmark
    description: str
    rating: float
    estimated_duration_hours: float
    estimated_ticket_price: float
    currency: str = "USD"
    image_url: str
    best_time_to_visit: Optional[str] = "Morning"
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class PlacesSearchResponse(BaseModel):
    destination: str
    places: List[PlaceItem]
    source: str = "MYMILE Tourist Places Provider"
