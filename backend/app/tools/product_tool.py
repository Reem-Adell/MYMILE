from typing import Dict, Any
from app.services.channel3_service import search_channel3_products

async def run_product_tool(
    destination: str,
    trip_type: str = "Tourism",
    season: str = "Spring",
    limit: int = 6
) -> Dict[str, Any]:
    """Retrieves verified travel gear and essentials from Channel3 based on destination, season, and trip type."""
    res = await search_channel3_products(
        destination=destination,
        trip_type=trip_type,
        season=season,
        limit=limit
    )
    return res.model_dump()
