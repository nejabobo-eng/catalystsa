"""
Public API routes for customers
No authentication required
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from catalystsa.database import SessionLocal
from catalystsa.models import Order

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
                "total": order.amount,
                "created_at": order.created_at.isoformat() if order.created_at else None,
            }
            for order in orders
        ]
    }
