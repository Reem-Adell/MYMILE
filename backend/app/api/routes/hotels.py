from fastapi import APIRouter, Query
from typing import Optional
from app.schemas.hotel_schema import HotelSearchResponse
from app.services.hotel_service import search_hotels

router = APIRouter(prefix="/hotels", tags=["Hotels & Accommodations"])

@router.get("/search", response_model=HotelSearchResponse)
async def search_accommodations(
    destination: str = Query(..., description="Destination city"),
    check_in: str = Query("2026-04-08", description="Check-in date (YYYY-MM-DD)"),
    check_out: str = Query("2026-04-15", description="Check-out date (YYYY-MM-DD)"),
    nights: int = Query(7, ge=1, description="Number of nights"),
    stay_preference: str = Query("Boutique hotel", description="Preferred accommodation style"),
    plan: str = Query("free", description="User plan: 'free' or 'premium'"),
    travelers: int = Query(2, ge=1, description="Number of adult travelers"),
    purpose: str = Query("Tourism", description="Trip purpose: Tourism, Business, Umrah, Other"),
    notes: Optional[str] = Query(None, description="Free-text needs, e.g. 'interview downtown'"),
):
    """
    Searches verified hotels. If user has 'free' plan, external booking links are omitted.
    If 'premium', booking links and full comparison features are included.
    """
    return await search_hotels(
        destination=destination,
        check_in=check_in,
        check_out=check_out,
        total_nights=nights,
        stay_preference=stay_preference,
        plan=plan,
        travelers=travelers,
        purpose=purpose,
        notes=notes,
    )
