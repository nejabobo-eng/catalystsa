from pydantic import BaseModel


class ProductCreate(BaseModel):
    name: str
    description: str
    cost: float
    category: str
    image: str


class OrderCreate(BaseModel):
    product_id: int
    customer_name: str
    phone: str
    address: str
