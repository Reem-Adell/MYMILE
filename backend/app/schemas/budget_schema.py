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
    remaining_balance: Optional[float] = None  # = unallocated_budget for Premium allocations
    currency: str = "USD"
    status: str = "balanced"  # balanced, under_budget, over_budget, estimated
    # Clear terms for the dashboard (the numbers above are unchanged):
    #   "allocated": a Premium budget split into planned limits per category (not a spending forecast)
    #   "estimated": baseline cost estimates when no budget was given
    allocation_mode: Optional[str] = None
    allocated_total: Optional[float] = None      # hotel + category allocations
    unallocated_budget: Optional[float] = None   # budget - allocated (negative = over-allocated)
    fully_allocated: Optional[bool] = None
    allocation_note: Optional[str] = None

class BudgetOptimizationRequest(BaseModel):
    destination: str
    duration_days: int
    travelers: int = 1
    total_budget: float  # always USD
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
