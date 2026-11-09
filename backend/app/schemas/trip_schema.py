from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from app.schemas.weather_schema import WeatherResponse
from app.schemas.hotel_schema import HotelItem
from app.schemas.product_schema import ProductItem
from app.schemas.budget_schema import BudgetBreakdown

class ItineraryActivity(BaseModel):
    time: str  # e.g. "09:00 AM"
    title: str
    description: str
    location: Optional[str] = None
    icon: Optional[str] = "pin"  # pin, hotel, route, clock, spark, bag
    cost_estimate: float = 0.0

class ItineraryDay(BaseModel):
    day_number: int
    date_str: str  # e.g. "Wednesday, Apr 8"
    theme: str  # e.g. "Arrival & Gion exploration"
    activities: List[ItineraryActivity]

class TripPlanRequest(BaseModel):
    destination: str
    departure_date: str  # YYYY-MM-DD
    return_date: str     # YYYY-MM-DD
    travelers: int = 2
    purpose: str = "Tourism"  # Tourism, Business, Umrah, Other
    stay_preference: str = "Boutique hotel"
    priorities: List[str] = Field(default_factory=lambda: ["Local culture", "Great food", "Slow pace"])
    notes: Optional[str] = None
    plan: str = "free"  # "free" or "premium"
    total_budget: Optional[float] = None  # Mandatory for Premium optimization
    currency: str = "USD"

class TripPlanResponse(BaseModel):
    trip_id: str
    destination: str
    departure_date: str
    return_date: str
    total_days: int
    travelers: int
    purpose: str
    stay_preference: str
    plan_tier: str  # "free" or "premium"
    match_score: int = 98
    destination_summary: str
    why_recommended: str
    weather: WeatherResponse
    recommended_hotel: HotelItem
    all_hotels: List[HotelItem]
    itinerary: List[ItineraryDay]
    budget_breakdown: BudgetBreakdown
    travel_essentials: List[ProductItem]
    is_premium: bool = False
    source_attribution: Dict[str, str] = Field(default_factory=lambda: {
        "weather": "Open-Meteo Live API",
        "products": "Channel3 Product AI",
        "comparison": "AG Grid Enterprise Ready Grid",
        "api_spec": "APIMatic Standard OpenAPI 3.0"
    })

class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str

class TripChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = Field(default_factory=list)
    current_trip_context: Optional[Dict[str, Any]] = None
    plan: str = "free"
    budget: Optional[float] = None

class TripChatResponse(BaseModel):
    reply: str
    suggestions: List[str]
    tools_called: List[str] = Field(default_factory=list)
    updated_plan_patch: Optional[Dict[str, Any]] = None
