"""
Public API routes for customers
No authentication required
Single source of truth for order lookup
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from catalystsa.database import SessionLocal
from catalystsa.models import Order, WebhookEvent

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/debug/all-orders")
def debug_all_orders(db: Session = Depends(get_db)):
    """
    DIAGNOSTIC ENDPOINT: Show all orders in database
    Use to check if webhook is actually creating orders
    """
    all_orders = db.query(Order).order_by(Order.created_at.desc()).all()

    return {
        "total_orders": len(all_orders),
        "orders": [
            {
                "id": order.id,
                "order_number": order.order_number,
                "checkout_id": order.checkout_id,
                "customer_email": order.customer_email,
                "status": order.status,
                "amount": order.amount,
                "created_at": order.created_at.isoformat() if order.created_at else None,
            }
            for order in all_orders
        ]
    }


@router.get("/debug/webhook-events")
def debug_webhook_events(db: Session = Depends(get_db)):
    """
    DIAGNOSTIC ENDPOINT: Show webhook events
    Use to check if Yoco is sending webhooks at all
    """
    events = db.query(WebhookEvent).order_by(WebhookEvent.received_at.desc()).limit(20).all()

    return {
        "total_events": len(events),
        "events": [
            {
                "checkout_id": event.checkout_id,
                "event_type": event.event_type,
                "status": event.status,
                "order_created": event.order_created,
                "order_number": event.order_number,
                "received_at": event.received_at.isoformat() if event.received_at else None,
                "error_message": event.error_message,
            }
            for event in events
        ]
    }


@router.get("/public/orders/{email}")
def get_public_orders(email: str, db: Session = Depends(get_db)):
    """
    Get orders by customer email - PUBLIC ENDPOINT

    Single source of truth for order lookup.

    Request: GET /public/orders/{email}
    Response: {
      "email": "customer@example.com",
      "orders": [
        {
          "order_number": 10001,
          "status": "paid"
        }
      ]
    }
    """
    normalized_email = email.strip().lower()

    orders = db.query(Order).filter(
        Order.customer_email == normalized_email
    ).order_by(Order.created_at.desc()).limit(10).all()

    return {
        "email": normalized_email,
        "orders": [
            {
                "order_number": order.order_number,
                "status": order.status,
            }
            for order in orders
        ]
    }
