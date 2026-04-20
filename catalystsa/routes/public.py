"""
Public API routes for customers
No authentication required
Single source of truth for order lookup
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from catalystsa.database import SessionLocal
from catalystsa.models import Order, WebhookEvent
from pydantic import BaseModel
import json

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class TrackOrderRequest(BaseModel):
    order_number: int
    email: str


@router.post("/orders/track")
def track_order(payload: TrackOrderRequest, db: Session = Depends(get_db)):
    """
    Customer order tracking (public endpoint)

    Security: Requires BOTH order_number AND email to match
    This prevents data leaks while allowing customer self-service

    Returns:
    - Order details
    - Current status
    - Tracking number (if shipped)
    - Timeline (basic version - will be enhanced with audit logs)
    """
    # Normalize email (case-insensitive lookup)
    normalized_email = payload.email.strip().lower()

    # Dual-key verification: both order_number AND email must match
    order = db.query(Order).filter(
        Order.order_number == payload.order_number,
        Order.customer_email == normalized_email
    ).first()

    if not order:
        # Generic error - don't reveal if order exists or email is wrong (security)
        raise HTTPException(
            status_code=404, 
            detail="ORDER_NOT_FOUND"
        )

    # Parse items JSON
    try:
        items = json.loads(order.items) if order.items else []
    except:
        items = []

    # Build basic timeline (will be replaced with audit logs later)
    timeline = []
    if order.created_at:
        timeline.append({
            "status": "created",
            "timestamp": order.created_at.isoformat()
        })
    if order.paid_at:
        timeline.append({
            "status": "paid",
            "timestamp": order.paid_at.isoformat()
        })
    if order.updated_at and order.status in ["processing", "shipped", "delivered"]:
        timeline.append({
            "status": order.status,
            "timestamp": order.updated_at.isoformat()
        })

    return {
        "order_number": order.order_number,
        "status": order.status,
        "tracking_number": order.tracking_number,
        "customer_name": order.customer_name,
        "delivery_address": {
            "address": order.address,
            "city": order.city,
            "postal_code": order.postal_code
        },
        "subtotal": (order.amount / 100) if order.amount else 0,
        "delivery_fee": (order.delivery_fee / 100) if order.delivery_fee else 0,
        "total": ((order.amount or 0) + (order.delivery_fee or 0)) / 100,
        "currency": order.currency or "ZAR",
        "items": items,
        "timeline": timeline,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None
    }


@router.get("/debug/all-orders")
def debug_all_orders(db: Session = Depends(get_db)):
    """
    DIAGNOSTIC ENDPOINT: Show all orders in database
    Use to check if webhook is actually creating orders
    """
    try:
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
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"ERROR in debug_all_orders: {str(e)}")
        print(error_trace)
        return {
            "total_orders": 0,
            "orders": [],
            "error": str(e),
            "traceback": error_trace
        }


@router.get("/debug/webhook-events")
def debug_webhook_events(db: Session = Depends(get_db)):
    """
    DIAGNOSTIC ENDPOINT: Show webhook events
    Use to check if Yoco is sending webhooks at all
    """
    try:
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
                    "raw_payload": event.raw_payload,  # Include raw payload for debugging
                }
                for event in events
            ]
        }
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"ERROR in debug_webhook_events: {str(e)}")
        print(error_trace)
        return {
            "total_events": 0,
            "events": [],
            "error": str(e),
            "traceback": error_trace
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
    try:
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
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"ERROR in get_public_orders: {str(e)}")
        print(error_trace)
        return {
            "email": email,
            "orders": [],
            "error": str(e),
            "debug": "Check backend logs for full traceback"
        }
