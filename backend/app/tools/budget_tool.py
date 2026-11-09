from typing import Dict, Any, Optional
from app.services.budget_service import optimize_budget

def run_budget_tool(
    destination: str,
    duration_days: int,
    travelers: int = 1,
    total_budget: Optional[float] = None,
    currency: str = "USD",
    selected_hotel_total: Optional[float] = None,
    stay_preference: str = "Boutique hotel",
    plan: str = "free"
) -> Dict[str, Any]:
    """Optimizes budget distribution across stays, dining, transport, activities, and gear."""
    res = optimize_budget(
        destination=destination,
        duration_days=duration_days,
        travelers=travelers,
        total_budget=total_budget,
        currency=currency,
        selected_hotel_total=selected_hotel_total,
        stay_preference=stay_preference,
        plan=plan
    )
    return res.model_dump()
