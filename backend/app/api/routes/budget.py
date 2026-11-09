from fastapi import APIRouter
from app.schemas.budget_schema import BudgetOptimizationRequest, BudgetOptimizationResponse
from app.services.budget_service import optimize_budget

router = APIRouter(prefix="/budget", tags=["Budget & Optimization"])

@router.post("/optimize", response_model=BudgetOptimizationResponse)
async def optimize_travel_budget(req: BudgetOptimizationRequest):
    """
    Sponsor Feature (AG Grid & Premium Plan):
    Takes the traveler's total budget and balances accommodation, dining, transport,
    activities, and essentials.
    """
    return optimize_budget(
        destination=req.destination,
        duration_days=req.duration_days,
        travelers=req.travelers,
        total_budget=req.total_budget,
        currency=req.currency,
        selected_hotel_total=req.selected_hotel_price_total,
        stay_preference=req.stay_preference,
        plan="premium"
    )
