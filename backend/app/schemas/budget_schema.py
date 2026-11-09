from typing import Dict, List, Optional
from pydantic import BaseModel

class BudgetCategoryDetail(BaseModel):
    category: str
    allocated_amount: float
    percentage_of_total: float
    description: str
    is_flexible: bool = True

class BudgetBreakdown(BaseModel):
    accommodation: float
    transportation: float
    food: float
    activities: float
    travel_essentials: float
    contingency_and_other: float
    total_estimated: float
    user_budget: Optional[float] = None
    remaining_balance: Optional[float] = None
    currency: str = "USD"
    status: str = "balanced"  # balanced, under_budget, over_budget

class BudgetOptimizationRequest(BaseModel):
    destination: str
    duration_days: int
    travelers: int = 1
    total_budget: float
    currency: str = "USD"
    stay_preference: str = "Boutique hotel"
    trip_purpose: str = "Tourism"
    selected_hotel_price_total: Optional[float] = None

class BudgetOptimizationResponse(BaseModel):
    plan_tier: str = "premium"
    total_budget: float
    currency: str = "USD"
    breakdown: BudgetBreakdown
    categories: List[BudgetCategoryDetail]
    trade_off_analysis: str
    savings_tips: List[str]
    comfort_score: int  # 1 to 100
