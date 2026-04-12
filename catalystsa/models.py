from sqlalchemy import Column, Integer, String, Float, Boolean
from catalystsa.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    description = Column(String)
    cost = Column(Float)
    price = Column(Float)
    category = Column(String)
    image = Column(String)
    in_stock = Column(Boolean, default=True)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer)
    customer_name = Column(String)
    phone = Column(String)
    address = Column(String)
    total = Column(Float)
    status = Column(String, default="pending")
