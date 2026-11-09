from typing import List, Optional
from pydantic import BaseModel

class ProductItem(BaseModel):
    id: str
    name: str
    price: float
    currency: str = "USD"
    image_url: str
    description: str
    category: str  # Clothing, Gear, Tech, Accessories, Religious/Umrah
    rating: float = 4.8
    purchase_url: str  # Direct purchase link on partner site
    brand: Optional[str] = None
    reason: str  # Explanation why this fits destination/season
    in_stock: bool = True
    provider: str = "Channel3 AI Commerce"

class ProductSearchRequest(BaseModel):
    destination: str
    trip_type: str = "Tourism"  # Tourism, Business, Umrah, Adventure
    season_or_month: Optional[str] = "Spring"
    weather_condition: Optional[str] = "Mild"
    preferences: Optional[List[str]] = None
    limit: int = 6

class ProductSearchResponse(BaseModel):
    query_context: str
    products: List[ProductItem]
    source: str = "Channel3 Product Discovery Engine"

class CartItem(BaseModel):
    product: ProductItem
    quantity: int = 1

class CartSummary(BaseModel):
    items: List[CartItem]
    subtotal: float
    currency: str = "USD"
    total_items: int
