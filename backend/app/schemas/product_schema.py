from typing import List, Optional
from pydantic import BaseModel


class ProductOffer(BaseModel):
    """One retailer's offer, as returned by Channel3 (offers[])."""
    retailer: str                        # offer.domain, e.g. "rei.com"
    url: Optional[str] = None            # buy link; Premium only (None for guests/Free)
    price: Optional[float] = None
    compare_at_price: Optional[float] = None
    currency: Optional[str] = None
    availability: Optional[str] = None   # "InStock" | "OutOfStock"


class ProductItem(BaseModel):
    """A product found by Channel3. Fields Channel3 didn't return stay None/empty: nothing is invented."""
    id: str
    name: str
    price: Optional[float] = None        # from the main offer
    compare_at_price: Optional[float] = None
    currency: Optional[str] = None
    image_url: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    # Main offer's buy link on the retailer site. Premium only: null for guests and
    # Free users (enforced server-side by apply_purchase_link_policy).
    purchase_url: Optional[str] = None
    brand: Optional[str] = None
    retailer: Optional[str] = None
    reason: Optional[str] = None         # the AI's short reason, only facts from the product data
    group: Optional[str] = None          # trip-specific display category chosen by the AI, e.g. "Prayer Essentials"
    audience: Optional[str] = None       # "all" | "men" | "women" (never assumed: labelled options)
    per_traveler: Optional[bool] = None  # one needed per traveler (True) or shared (False); None = unknown
    in_stock: Optional[bool] = None      # None = unknown
    variants: List[str] = []             # e.g. "Size: S, M, L"
    offers: List[ProductOffer] = []
    search_query: Optional[str] = None   # the search that found it
    provider: str = "Channel3"


class ProductSearchResponse(BaseModel):
    query_context: str
    products: List[ProductItem]
    source: str = "Channel3"
    status: str = "ok"                   # ok | empty | not_configured | unavailable
    message: Optional[str] = None


class CartItem(BaseModel):
    product: ProductItem
    quantity: int = 1


class CartSummary(BaseModel):
    items: List[CartItem]
    subtotal: float
    currency: str = "USD"
    total_items: int
