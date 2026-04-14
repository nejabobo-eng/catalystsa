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


@router.get("/debug/schema")
def debug_schema(db: Session = Depends(get_db)):
    """
    Debug endpoint: show actual orders table schema
    """
    try:
        # Query information_schema to see what columns actually exist
        query = text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'orders'
            ORDER BY ordinal_position
        """)

        result = db.execute(query)
        columns = result.fetchall()

        return {
            "table": "orders",
            "columns": [{"name": col[0], "type": col[1]} for col in columns]
        }
    except Exception as e:
        logger.error(f"Error getting schema: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/public/orders/{email}")
def get_public_orders(email: str, db: Session = Depends(get_db)):
    """
    Get orders by customer email - PUBLIC ENDPOINT

    Uses minimal columns that we know exist.
    """
    try:
        normalized_email = email.strip().lower()

        logger.info(f"Looking up orders for email: {normalized_email}")

        # Query only order_number and status (safest columns)
        query = text("""
            SELECT id, order_number, status
            FROM orders
            WHERE LOWER(customer_email) = :email
            ORDER BY id DESC
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
                    "order_number": row[1],
                    "status": row[2] if row[2] else "unknown",
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
