from fastapi import APIRouter, Depends
from app.api.routes.auth import require_premium
from app.schemas.budget_schema import BudgetOptimizationRequest, BudgetOptimizationResponse
from app.services.budget_service import optimize_budget

router = APIRouter(prefix="/budget", tags=["Budget & Optimization"])

@router.post("/optimize", response_model=BudgetOptimizationResponse)
async def optimize_travel_budget(req: BudgetOptimizationRequest, plan: str = Depends(require_premium)):
    """
    Sponsor Feature (AG Grid & Premium Plan):
    Takes the traveler's total budget and balances accommodation, dining, transport,
    activities, and essentials.

    Premium only, enforced server-side: guests and Free users get 403
    ("This feature requires an active MYMILE Premium pass.").
    """
    return optimize_budget(
        destination=req.destination,
        duration_days=req.duration_days,
        travelers=req.travelers,
        total_budget=req.total_budget,
        currency="USD",  # all prices and budgets are in US dollars
        selected_hotel_total=req.selected_hotel_price_total,
        stay_preference=req.stay_preference,
        plan=plan,  # verified 'premium' from require_premium (no longer hard-coded)
    )
