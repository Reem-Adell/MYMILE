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
    # Structured Plan a Trip fields. When present they are the authoritative
    # location for weather, hotels and the itinerary ("destination" is kept for
    # older clients). The free-text `notes` never changes the destination.
    destination_city: Optional[str] = None
    destination_country: Optional[str] = None
    departure_date: str  # YYYY-MM-DD
    return_date: str     # YYYY-MM-DD
    travelers: int = 2
    purpose: str = "Tourism"  # Tourism, Business, Umrah, Other
    stay_preference: str = "Boutique hotel"
    priorities: List[str] = Field(default_factory=lambda: ["Local culture", "Great food", "Slow pace"])
    notes: Optional[str] = None
    # No `plan` field on purpose: the plan is verified server-side from the
    # caller's account. A `plan` sent by a client is an unknown field and ignored.
    total_budget: Optional[float] = None  # Used for Premium optimization; always USD

class AgentInfo(BaseModel):
    """Who produced the itinerary and explanations. Never claims AI when it wasn't used."""
    generated_by: str = "rules"  # "gemini" | "rules" (template, AI unavailable)
    model: Optional[str] = None
    tools_used: List[str] = Field(default_factory=list)  # tools Gemini actually executed
    cached: bool = False  # AI result reused for an identical request
    notice: Optional[str] = None  # why AI wasn't used, when it wasn't


class EssentialsInfo(BaseModel):
    """State of the travel-product suggestions (Channel3 products picked by Gemini)."""
    status: str = "unavailable"  # ok | empty | not_configured | ai_unavailable | unavailable
    message: Optional[str] = None
    queries: List[str] = Field(default_factory=list)  # Channel3 searches Gemini asked for


class TripPlanResponse(BaseModel):
    trip_id: str
    destination: str
    destination_city: Optional[str] = None
    destination_country: Optional[str] = None
    departure_date: str
    return_date: str
    total_days: int
    travelers: int
    purpose: str
    stay_preference: str
    plan_tier: str  # "free" or "premium"
    match_score: Optional[int] = None  # no fabricated score
    destination_summary: str
    why_recommended: str
    weather: WeatherResponse
    recommended_hotel: HotelItem
    all_hotels: List[HotelItem]
    itinerary: List[ItineraryDay]
    # Premium only (Budget Snapshot / Estimated Cost). None for Free and guests,
    # so the data is not sent to accounts that may not see it.
    budget_breakdown: Optional[BudgetBreakdown] = None
    travel_essentials: List[ProductItem]
    is_premium: bool = False
    ai: AgentInfo = Field(default_factory=AgentInfo)
    essentials: EssentialsInfo = Field(default_factory=EssentialsInfo)
    source_attribution: Dict[str, str] = Field(default_factory=lambda: {
        "weather": "Open-Meteo Live API",
        "products": "Channel3 product search",
        "comparison": "AG Grid Enterprise Ready Grid",
    })

class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str

class ChatContextActivity(BaseModel):
    time: Optional[str] = None
    title: str = Field(max_length=200)
    location: Optional[str] = Field(default=None, max_length=200)
    cost_estimate: Optional[float] = None

class ChatContextDay(BaseModel):
    day_number: int
    theme: Optional[str] = Field(default=None, max_length=200)
    activities: List[ChatContextActivity] = Field(default_factory=list, max_length=10)

class ChatContextHotel(BaseModel):
    id: Optional[str] = None
    name: str = Field(max_length=200)
    price_per_night: Optional[float] = None
    total_price: Optional[float] = None

class ChatTripContext(BaseModel):
    """The trip the user is looking at. Used only as context and to fix the tools'
    destination/dates; it never grants plan features (the plan is server-verified)."""
    destination: str = Field(max_length=200)
    destination_city: Optional[str] = Field(default=None, max_length=100)
    destination_country: Optional[str] = Field(default=None, max_length=100)
    departure_date: str = Field(max_length=10)
    return_date: str = Field(max_length=10)
    travelers: int = Field(default=2, ge=1, le=30)
    purpose: str = Field(default="Tourism", max_length=60)
    stay_preference: str = Field(default="Boutique hotel", max_length=60)
    priorities: List[str] = Field(default_factory=list, max_length=10)
    notes: Optional[str] = Field(default=None, max_length=1000)
    total_budget: Optional[float] = None
    recommended_hotel: Optional[ChatContextHotel] = None
    itinerary: List[ChatContextDay] = Field(default_factory=list, max_length=31)

class TripChatRequest(BaseModel):
    message: str = Field(max_length=2000)
    history: List[ChatMessage] = Field(default_factory=list)
    # Structured trip (new clients) or a loose dict (older clients; ignored by the AI tools).
    current_trip_context: Optional[Dict[str, Any]] = None
    # No `plan` field: verified server-side (see TripPlanRequest).
    budget: Optional[float] = None

class TripChatResponse(BaseModel):
    reply: str
    suggestions: List[str]
    tools_called: List[str] = Field(default_factory=list)  # tools actually executed this turn
    updated_plan_patch: Optional[Dict[str, Any]] = None
    generated_by: str = "unavailable"  # "gemini" | "unavailable"
    model: Optional[str] = None
    # Validated changes the user can apply to the current plan.
    updated_itinerary_days: List[ItineraryDay] = Field(default_factory=list)
    hotel_options: List[HotelItem] = Field(default_factory=list)
    suggested_hotel_id: Optional[str] = None
