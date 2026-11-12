from typing import Dict, List, Literal, Optional, Any
from pydantic import BaseModel, Field, field_validator
from app.schemas.weather_schema import WeatherResponse
from app.schemas.hotel_schema import HotelItem
from app.schemas.product_schema import ProductItem
from app.schemas.budget_schema import BudgetBreakdown

class TripPlanRequest(BaseModel):
    destination: str
    # Structured Plan a Trip fields. When present they are the authoritative
    # location for weather and hotels ("destination" is kept for
    # older clients). The free-text `notes` never changes the destination.
    destination_city: Optional[str] = None
    destination_country: Optional[str] = None
    departure_date: str  # YYYY-MM-DD
    return_date: str     # YYYY-MM-DD
    travelers: int = 2
    purpose: str = "Tourism"  # Tourism, Business, Umrah, Other
    stay_preference: str = "Boutique hotel"
    priorities: List[str] = Field(default_factory=lambda: ["Local culture", "Great food", "Slow pace"])
    # "Tell us about your trip": required, 1-500 characters after trimming. The primary
    # source for product recommendations (and context for the hotel choice).
    notes: str = Field(..., max_length=600)
    # No `plan` field on purpose: the plan is verified server-side from the
    # caller's account. A `plan` sent by a client is an unknown field and ignored.
    total_budget: Optional[float] = None  # Used for Premium optimization; always USD
    # Who the travel products are for (a shopping preference, not the traveler's identity).
    # Absent / "all" = everyone; older clients don't send it.
    shopping_audience: Optional[Literal["men", "women", "all"]] = None

    @field_validator("notes")
    @classmethod
    def _trip_description(cls, value: str) -> str:
        value = " ".join(str(value or "").split())
        if not value:
            raise ValueError("Tell us about your trip (required).")
        if len(value) > 500:
            raise ValueError("The trip description can be at most 500 characters.")
        return value

class AgentInfo(BaseModel):
    """Who produced the plan's text and picks. Never claims AI when it wasn't used."""
    generated_by: str = "rules"  # "groq" | "gemini" (AI provider) | "rules" (template, AI unavailable)
    model: Optional[str] = None
    tools_used: List[str] = Field(default_factory=list)  # tools Gemini actually executed
    cached: bool = False  # AI result reused for an identical request
    notice: Optional[str] = None  # why AI wasn't used, when it wasn't


class MissingNeed(BaseModel):
    """A trip need without a shown product, and why: "not_searched" (no search ran for it),
    "not_found" (searched, nothing passed the filters) or "not_selected" (relevant products
    were found, the AI chose none)."""
    category: str
    state: str


class EssentialsInfo(BaseModel):
    """State of the travel-product suggestions (Channel3 products picked by the AI)."""
    status: str = "unavailable"  # ok | empty | not_configured | ai_unavailable | unavailable
    message: Optional[str] = None
    queries: List[str] = Field(default_factory=list)  # Channel3 searches the AI ran
    # Categories the trip needed that have no product shown (names; see missing_detail for why).
    missing: List[str] = Field(default_factory=list)
    missing_detail: List[MissingNeed] = Field(default_factory=list)


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
    shopping_audience: Optional[str] = None  # "men" | "women" | None (everyone); echoed from the request
    plan_tier: str  # "free" or "premium"
    match_score: Optional[int] = None  # no fabricated score
    destination_summary: str
    why_recommended: str
    weather: WeatherResponse
    recommended_hotel: HotelItem
    all_hotels: List[HotelItem]
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
    generated_by: str = "unavailable"  # "groq" | "gemini" | "unavailable"
    model: Optional[str] = None
    # Validated hotel options the user can apply to the current plan.
    hotel_options: List[HotelItem] = Field(default_factory=list)
    suggested_hotel_id: Optional[str] = None
