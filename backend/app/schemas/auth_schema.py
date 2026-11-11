from typing import Optional
from pydantic import BaseModel

class UserRegister(BaseModel):
    name: str
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class UserOut(BaseModel):
    id: str
    name: str
    email: str
    plan: str = "free"  # EFFECTIVE plan ("free" or "premium"), see app/core/premium.py
    created_at: str
    premium_until: Optional[str] = None  # stored Premium expiry (ISO-8601 UTC) or null

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class SubscriptionUpgrade(BaseModel):
    plan: str  # "premium" or "free"
    payment_method: Optional[str] = "hackathon_demo"
