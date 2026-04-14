from sqlalchemy.orm import Session
from sqlalchemy import text
from catalystsa.models import OrderSequence
import logging

logger = logging.getLogger(__name__)


def get_next_order_number(db: Session) -> int:
    """
    Get next order number atomically using database locking.
    Guarantees no duplicate order numbers even under concurrent requests.
    
    Uses: UPDATE ... RETURNING pattern to prevent race conditions
    """
    try:
        # Execute atomic increment and return in single operation
        result = db.execute(
            text(
                "UPDATE order_sequence SET last_order_number = last_order_number + 1 "
                "WHERE id = 1 RETURNING last_order_number"
            )
        )
        
        row = result.fetchone()
        if row:
            next_number = 10000 + row[0]
            logger.info(f"Generated order number: #{next_number}")
            return next_number
        else:
            logger.error("Failed to generate order number - sequence row not found")
            # Fallback: try to initialize sequence if it doesn't exist
            db.execute(text("INSERT INTO order_sequence (id, last_order_number) VALUES (1, 0) ON CONFLICT DO NOTHING"))
            db.commit()
            return get_next_order_number(db)
            
    except Exception as e:
        logger.error(f"Error generating order number: {str(e)}")
        db.rollback()
        raise Exception(f"Failed to generate order number: {str(e)}")


def ensure_sequence_exists(db: Session):
    """
    Ensure order_sequence table has the single initialization row
    """
    try:
        # Check if sequence exists
        result = db.execute(text("SELECT id FROM order_sequence WHERE id = 1"))
        if not result.fetchone():
            # Insert if doesn't exist
            db.execute(text("INSERT INTO order_sequence (id, last_order_number) VALUES (1, 0)"))
            db.commit()
            logger.info("Initialized order_sequence table")
    except Exception as e:
        logger.error(f"Error ensuring sequence exists: {str(e)}")
