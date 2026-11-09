from fastapi import APIRouter, Query
from app.schemas.places_schema import PlacesSearchResponse
from app.services.places_service import search_places

router = APIRouter(prefix="/places", tags=["Tourist Places & Landmarks"])

@router.get("/search", response_model=PlacesSearchResponse)
async def search_landmarks(
    destination: str = Query(..., description="Destination city or country")
):
    """
    Retrieves top cultural, historical, and sightseeing attractions.
    """
    return search_places(destination)
