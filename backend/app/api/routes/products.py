from fastapi import APIRouter, Query
from app.schemas.product_schema import ProductSearchResponse
from app.services.channel3_service import search_channel3_products

router = APIRouter(prefix="/products", tags=["Channel3 E-commerce & Products"])

@router.get("/search", response_model=ProductSearchResponse)
async def search_products(
    destination: str = Query("Kyoto, Japan", description="Trip destination"),
    trip_type: str = Query("Tourism", description="Trip purpose (Tourism, Umrah, Business)"),
    season: str = Query("Spring", description="Season or weather climate"),
    limit: int = Query(6, ge=1, le=12, description="Number of products")
):
    """
    Sponsor Integration: Channel3.
    Retrieves authentic travel essentials, prices, images, and original purchase links.
    Never fabricates prices or fake items.
    """
    return await search_channel3_products(
        destination=destination,
        trip_type=trip_type,
        season=season,
        limit=limit
    )
