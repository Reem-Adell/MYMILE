from typing import Optional

from fastapi import APIRouter, Depends, Query
from app.api.routes.auth import get_effective_plan
from app.schemas.product_schema import ProductSearchResponse
from app.services import channel3_service

router = APIRouter(prefix="/products", tags=["Products (Channel3)"])


@router.get("/search", response_model=ProductSearchResponse)
async def search_products(
    query: str = Query(..., min_length=2, max_length=channel3_service.MAX_QUERY_LENGTH,
                       description="Product search, e.g. 'packable rain jacket'"),
    limit: int = Query(4, ge=1, le=channel3_service.MAX_RESULTS_PER_QUERY, description="Number of products"),
    audience: Optional[str] = Query(None, pattern="^(men|women|all)$",
                                    description="Shopping audience for clothing/footwear searches"),
    # Server-verified from the Bearer token (guests -> 'free'). A `plan` query
    # parameter sent by the client is ignored.
    plan: str = Depends(get_effective_plan),
):
    """
    Searches real products through Channel3 (cached; 1 credit per new search).
    Everyone sees product details; the retailer `purchase_url` and offer URLs are
    Premium only (null for guests and Free users), decided server-side.
    """
    return await channel3_service.search_products_response(query, limit, plan=plan, audience=audience)
