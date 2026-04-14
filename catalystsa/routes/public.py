"""
Public API routes for customers
No authentication required
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from catalystsa.database import SessionLocal
from catalystsa.models import Order
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
          "status": "paid",
          "total": 500,
          "created_at": "2024-04-14T..."
        }
      ]
    }
    """
    try:
        normalized_email = email.strip().lower()

        logger.info(f"Looking up orders for email: {normalized_email}")

        orders = db.query(Order).filter(
            Order.customer_email == normalized_email
        ).order_by(Order.created_at.desc()).limit(10).all()

        logger.info(f"Found {len(orders)} orders for {normalized_email}")

        # Build response with safe serialization
        order_list = []
        for order in orders:
            try:
                order_dict = {
                    "order_number": order.order_number,
                    "status": order.status,
                    "total": int(order.amount) if order.amount else 0,  # Ensure int
                    "created_at": order.created_at.isoformat() if order.created_at else None,
                }
                order_list.append(order_dict)
            except Exception as e:
                logger.error(f"Error serializing order {order.id}: {str(e)}", exc_info=True)
                continue

        return {
            "email": normalized_email,
            "orders": order_list
        }
    except Exception as e:
        logger.error(f"Error in get_public_orders: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
