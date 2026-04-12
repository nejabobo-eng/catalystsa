from pydantic import BaseModel
from typing import Optional


class ProductCreate(BaseModel):
    name: str
    description: str
    cost: float
    image: Optional[str] = None
    category: Optional[str] = "general"


class OrderCreate(BaseModel):
    product_id: int
    customer_name: str
    phone: str
    address: str
