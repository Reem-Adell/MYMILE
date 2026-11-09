from typing import Dict, Any, Optional
from app.services.hotel_service import search_hotels

async def run_hotel_tool(
    destination: str,
    check_in: str = "2026-04-08",
    check_out: str = "2026-04-15",
    total_nights: int = 7,
    stay_preference: str = "Boutique hotel",
    plan: str = "free",
    budget: Optional[float] = None,
    travelers: int = 2,
    purpose: str = "Tourism",
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Searches for verified hotels matching the traveler's preference and plan."""
    res = await search_hotels(
        destination=destination,
        check_in=check_in,
        check_out=check_out,
        total_nights=total_nights,
        stay_preference=stay_preference,
        plan=plan,
        budget=budget,
        travelers=travelers,
        purpose=purpose,
        notes=notes,
    )
    return res.model_dump()
