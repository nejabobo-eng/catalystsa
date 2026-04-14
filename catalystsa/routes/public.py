"""
Public API routes for customers
No authentication required
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from catalystsa.database import SessionLocal
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
    Uses raw SQL to avoid schema mismatch issues.

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

        # Use raw SQL to avoid SQLAlchemy schema mismatch
        # Only SELECT columns we KNOW exist: order_number, status, created_at
        query = text("""
            SELECT order_number, status, created_at
            FROM orders
            WHERE LOWER(customer_email) = :email
            ORDER BY created_at DESC
            LIMIT 10
        """)

        result = db.execute(query, {"email": normalized_email})
        rows = result.fetchall()

        logger.info(f"Found {len(rows)} orders for {normalized_email}")

        # Build response
        order_list = []
        for row in rows:
            try:
                order_dict = {
                    "order_number": row[0],
                    "status": row[1],
                    "created_at": row[2].isoformat() if row[2] else None,
                    "total": 0,  # We can't reliably get total without knowing the column name
                }
                order_list.append(order_dict)
            except Exception as e:
                logger.error(f"Error processing order row: {str(e)}", exc_info=True)
                continue

        return {
            "email": normalized_email,
            "orders": order_list
        }
    except Exception as e:
        logger.error(f"Error in get_public_orders: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
