from fastapi import APIRouter
from typing import Dict, Any
from app.schemas.auth_schema import SubscriptionUpgrade

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])

PLANS_INFO = {
    "free": {
        "id": "free",
        "name": "Free Plan",
        "price": 0,
        "billing": "forever",
        "description": "For curious travelers ready to turn ideas into a clear plan.",
        "features": [
            "AI travel planning",
            "Hotel recommendations & estimated rates",
            "Real-time weather insights",
            "Travel essentials discovery",
            "Basic daily itinerary",
            "Baseline estimated trip costs"
        ],
        "restrictions": [
            "No direct hotel booking links",
            "No custom budget optimization",
            "No AG Grid interactive comparison dashboard"
        ]
    },
    "premium": {
        "id": "premium",
        "name": "Premium Plan",
        "price": 100,
        "billing": "per month",
        "description": "For travelers who want the best experience balanced within a real budget.",
        "features": [
            "Everything in Free",
            "AI multi-variable budget optimization ($1,500 budget balancing)",
            "AG Grid interactive hotel & budget comparison dashboard",
            "Verified booking links when supplied by provider",
            "Channel3 travel gear with verified partner checkout links",
            "Dynamic recalculation when switching accommodations",
            "Priority AI travel companion guidance"
        ],
        "restrictions": []
    }
}

@router.get("/plans")
async def get_plans() -> Dict[str, Any]:
    return PLANS_INFO

@router.post("/upgrade")
async def upgrade_plan(req: SubscriptionUpgrade) -> Dict[str, Any]:
    new_plan = req.plan.lower()
    if new_plan not in ["free", "premium"]:
        new_plan = "premium"
    return {
        "status": "success",
        "new_plan": new_plan,
        "message": f"Successfully activated MYMILE {new_plan.capitalize()} Plan!",
        "unlocked_features": [
            "AG Grid Hotel Comparison Table",
            "AG Grid Budget Breakdown Table",
            "Custom Budget Constraint Balancing",
            "Verified Hotel Booking Links"
        ] if new_plan == "premium" else []
    }
