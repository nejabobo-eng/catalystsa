from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from datetime import datetime
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
    checkout_id = Column(String, unique=True, index=True)
    amount = Column(Integer)  # in cents
    currency = Column(String, default="ZAR")
    status = Column(String, default="pending")  # pending, paid, failed
    customer_name = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    payment_method = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)
