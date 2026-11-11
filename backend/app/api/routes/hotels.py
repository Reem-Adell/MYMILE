from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from app.api.routes.auth import get_effective_plan
from app.schemas.hotel_schema import HotelOffersResponse, HotelSearchResponse
from app.services.hotel_service import get_hotel_offers, search_hotels

router = APIRouter(prefix="/hotels", tags=["Hotels & Accommodations"])

@router.get("/search", response_model=HotelSearchResponse)
async def search_accommodations(
    destination: str = Query(..., description="Destination city"),
    check_in: str = Query("2026-04-08", description="Check-in date (YYYY-MM-DD)"),
    check_out: str = Query("2026-04-15", description="Check-out date (YYYY-MM-DD)"),
    nights: int = Query(7, ge=1, description="Number of nights"),
    stay_preference: str = Query("Boutique hotel", description="Preferred accommodation style"),
    travelers: int = Query(2, ge=1, description="Number of adult travelers"),
    purpose: str = Query("Tourism", description="Trip purpose: Tourism, Business, Umrah, Other"),
    notes: Optional[str] = Query(None, description="Free-text needs, e.g. 'interview downtown'"),
    city: Optional[str] = Query(None, description="Structured destination city (authoritative)"),
    country: Optional[str] = Query(None, description="Structured destination country (authoritative)"),
    # Server-verified from the Bearer token (guests -> 'free'). A `plan` query
    # parameter sent by the client is ignored.
    plan: str = Depends(get_effective_plan),
):
    """
    Searches verified hotels. Free plan (and guests): external booking links are omitted.
    Premium: booking links and full comparison features are included.
    The plan is determined by the server from the caller's account, never from the request.
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
        city=city,
        country=country,
    )


@router.get("/offers", response_model=HotelOffersResponse)
async def hotel_booking_offers(
    property_token: str = Query(..., min_length=1, max_length=512, description="Google Hotels property token"),
    destination: str = Query(..., description="Destination used for the trip's hotel search"),
    check_in: str = Query(..., description="Check-in date (YYYY-MM-DD)"),
    check_out: str = Query(..., description="Check-out date (YYYY-MM-DD)"),
    adults: int = Query(2, ge=1, le=30, description="Number of adult travelers"),
    city: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    plan: str = Depends(get_effective_plan),
):
    """
    Booking-provider links (Booking.com, Expedia, ...) for one hotel from the trip's
    live Google Hotels search. Premium only, like every external booking link.
    Only hotels from a previous search with the same parameters are accepted, so
    this endpoint can't be used to spend the SerpApi quota on arbitrary lookups.
    """
    if plan != "premium":
        raise HTTPException(status_code=403, detail={"code": "PREMIUM_REQUIRED",
                                                     "message": "Booking links are a Premium feature."})
    result = await get_hotel_offers(property_token, destination, check_in, check_out, adults,
                                    city=city, country=country)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "HOTEL_NOT_IN_SEARCH",
                                                     "message": "This hotel isn't part of a recent search. "
                                                                "Re-open the trip to refresh hotel results."})
    return result
