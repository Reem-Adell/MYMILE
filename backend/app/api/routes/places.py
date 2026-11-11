from fastapi import APIRouter, Query
from app.schemas.places_schema import PlacesSearchResponse
from app.services.places_service import search_places
from app.services.destination_image import get_destination_image

router = APIRouter(prefix="/places", tags=["Tourist Places & Landmarks"])

@router.get("/search", response_model=PlacesSearchResponse)
async def search_landmarks(
    destination: str = Query(..., description="Destination city or country")
):
    """
    Retrieves top cultural, historical, and sightseeing attractions.
    """
    return search_places(destination)


@router.get("/destination-image")
async def destination_image(
    city: str = Query(..., min_length=1, max_length=100, description="Destination city"),
    country: str = Query("", max_length=100, description="Destination country"),
):
    """
    A real photo of the destination for the Explore hero (Wikipedia / Wikimedia
    Commons lead image, verified against the country). `image` is null when no
    verified photo is available; the frontend then shows its own fallback.
    Cached server-side, no API key involved.
    """
    return {"image": await get_destination_image(city, country)}
