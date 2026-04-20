"""Emergency migration endpoint - run once then remove"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from catalystsa.database import SessionLocal
from catalystsa.admin_auth import verify_admin_header

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/admin/migrate-tracking")
def migrate_tracking_columns(
    admin=Depends(verify_admin_header),
    db=Depends(get_db)
):
    """One-time migration to add tracking_number and updated_at columns"""
    try:
        # Add columns if they don't exist
        sql = text("""
            ALTER TABLE orders 
            ADD COLUMN IF NOT EXISTS tracking_number VARCHAR,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

            UPDATE orders 
            SET updated_at = COALESCE(paid_at, created_at)
            WHERE updated_at IS NULL;
        """)

        db.execute(sql)
        db.commit()

        return {
            "success": True,
            "message": "Migration completed: added tracking_number and updated_at columns"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Migration failed: {str(e)}")
