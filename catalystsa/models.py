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


class OrderSequence(Base):
    __tablename__ = "order_sequence"

    id = Column(Integer, primary_key=True, index=True, default=1)
    last_order_number = Column(Integer, default=0)  # Tracks highest order number issued


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(Integer, unique=True, index=True, nullable=True)  # e.g., 10001, 10002
    checkout_id = Column(String, unique=True, index=True)
    amount = Column(Integer)  # in cents (total after delivery)
    currency = Column(String, default="ZAR")
    status = Column(String, default="paid")  # pending, paid, processing, shipped, delivered, failed
    customer_name = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    delivery_fee = Column(Integer, nullable=True)  # in cents
    items = Column(String, nullable=True)  # JSON string of cart items
    payment_method = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)
