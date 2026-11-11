import copy
from fastapi import APIRouter, HTTPException, status
from typing import Dict, Any
from app.services.paypal_service import PaymentError, premium_terms

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
        # price / currency / duration are filled from backend settings on every
        # request (see get_plans); never hard-coded here.
        "price": None,
        "billing": "one-time",
        "description": "For travelers who want the best experience balanced within a real budget.",
        "features": [
            "Everything in Free",
            "AI multi-variable budget optimization ($1,500 budget balancing)",
            "AG Grid interactive hotel & budget comparison dashboard",
            "Verified booking links when supplied by provider",
            "Channel3 product suggestions with retailer purchase links",
            "Dynamic recalculation when switching accommodations",
            "Priority AI travel companion guidance"
        ],
        "restrictions": []
    }
}

@router.get("/plans")
async def get_plans() -> Dict[str, Any]:
    """Public plan terms. Premium price/currency/duration come from backend
    settings (the same values PayPal orders are created with)."""
    try:
        terms = premium_terms()
    except PaymentError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.message)
    plans = copy.deepcopy(PLANS_INFO)
    plans["premium"].update({
        "price": terms["price"],            # exact decimal string, e.g. "9.00"
        "currency": terms["currency"],
        "duration_days": terms["duration_days"],
        "billing": "one-time",
        "one_time": True,
        "auto_renew": False,
    })
    return plans


@router.post("/upgrade")
async def upgrade_plan() -> Dict[str, Any]:
    """Removed: it reported a fake upgrade without payment. Premium is only
    granted after a verified PayPal capture (/api/payments/paypal/...)."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="This endpoint has been removed. Purchase Premium through the PayPal checkout.",
    )
