from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey
from datetime import datetime
from catalystsa.database import Base


class Product(Base):
    """
    Product catalog - MVP with automatic markup pricing + logistics

    Business logic:
    - Admin enters cost_price (what you paid)
    - System calculates price = cost_price * 1.6 (rounded to nearest R10)
    - Customer sees only the final selling price

    Logistics (weight-based delivery):
    - weight_kg: actual weight for shipping calculation
    - size_category: small/medium/large/bulky (affects delivery cost)

    Design principles:
    - Both prices stored in cents (consistent with Order model)
    - Stock tracking for inventory management
    - Active flag for soft delete (preserve order history)
    - No variants/categories for MVP simplicity
    """
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    cost_price = Column(Integer, nullable=False)  # in cents - what admin paid
    price = Column(Integer, nullable=False)  # in cents - selling price (cost * 1.6)
    image_url = Column(String, nullable=True)
    stock = Column(Integer, default=0)
    active = Column(Boolean, default=True)  # soft delete - preserve order references
    # Keep model minimal for stability: don't rely on optional analytic/logistics fields

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    status = Column(String, default="paid")  # paid, processing, shipped, delivered
    customer_name = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    delivery_fee = Column(Integer, nullable=True)  # in cents
    items = Column(String, nullable=True)  # JSON string of cart items
    payment_method = Column(String, nullable=True)
    tracking_number = Column(String, nullable=True)  # for shipped orders
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)





class WebhookEvent(Base):
    """
    Transaction safety log: tracks every webhook event for debugging and reconciliation

    Purpose:
    - Debug payment→order flow issues
    - Detect duplicate or missing events
    - Provide audit trail for money flow
    """
    __tablename__ = "webhook_events"

    id = Column(Integer, primary_key=True, index=True)
    webhook_event_id = Column(String, unique=True, index=True, nullable=True)  # From Yoco (if provided)
    checkout_id = Column(String, index=True)  # Reference to payment/order
    event_type = Column(String, index=True)  # e.g., "payment.succeeded", "payment.failed"
    status = Column(String, index=True)  # "success", "failed", "duplicate", "invalid"
    error_message = Column(Text, nullable=True)  # Detailed error if failed
    order_created = Column(Boolean, default=False)  # Did this event create an order?
    order_number = Column(Integer, nullable=True, index=True)  # Reference to created order
    raw_payload = Column(Text, nullable=True)  # Full webhook payload for debugging
    received_at = Column(DateTime, default=datetime.utcnow, index=True)
    processed_at = Column(DateTime, nullable=True)

