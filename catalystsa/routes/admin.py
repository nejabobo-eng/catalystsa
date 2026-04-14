from fastapi import APIRouter, HTTPException, Header, Depends
from sqlalchemy.orm import Session
from catalystsa.database import SessionLocal
from catalystsa.models import Order
from catalystsa.admin_auth import create_token, verify_token, ADMIN_PASSWORD
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_admin_header(authorization: str = Header(None)):
    """Verify admin token from Authorization header"""
    if not authorization:
        raise HTTPException(status_code=401, detail="No authorization header")
    
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    token = parts[1]
    return verify_token(token)


@router.post("/admin/login")
def admin_login(payload: dict):
    """Admin login endpoint"""
    password = payload.get("password", "").strip()
    
    if not password:
        raise HTTPException(status_code=400, detail="Password required")
    
    if not _verify_password(password, ADMIN_PASSWORD):
        logger.warning("Failed admin login attempt")
        raise HTTPException(status_code=401, detail="Invalid password")
    
    token = create_token()
    logger.info("Admin logged in successfully")
    
    return {
        "token": token,
        "expires_in": 24 * 3600
    }


@router.get("/admin/orders")
def get_orders(
    skip: int = 0,
    limit: int = 50,
    status_filter: str = None,
    search: str = None,
    admin=Depends(verify_admin_header),
    db: Session = Depends(get_db)
):
    """Get all orders (paginated, newest first)"""
    query = db.query(Order).order_by(Order.created_at.desc())
    
    if status_filter:
        query = query.filter(Order.status == status_filter)
    
    if search:
        try:
            order_num = int(search)
            query = query.filter(
                (Order.order_number == order_num) |
                (Order.customer_email.ilike(f"%{search}%"))
            )
        except ValueError:
            query = query.filter(Order.customer_email.ilike(f"%{search}%"))
    
    total = query.count()
    orders = query.offset(skip).limit(limit).all()
    
    return {
        "orders": [
            {
                "id": order.id,
                "order_number": order.order_number,
                "customer_name": order.customer_name or "N/A",
                "email": order.customer_email or "N/A",
                "status": order.status,
                "total": (order.amount + (order.delivery_fee or 0)) / 100,
                "created_at": order.created_at.isoformat() if order.created_at else None,
            }
            for order in orders
        ],
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/admin/orders/{order_number}")
def get_order_detail(
    order_number: int,
    admin=Depends(verify_admin_header),
    db: Session = Depends(get_db)
):
    """Get full order details"""
    order = db.query(Order).filter(Order.order_number == order_number).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    return {
        "id": order.id,
        "order_number": order.order_number,
        "customer_name": order.customer_name or "N/A",
        "email": order.customer_email or "N/A",
        "phone": order.phone or "N/A",
        "address": order.address or "N/A",
        "city": order.city or "N/A",
        "postal_code": order.postal_code or "N/A",
        "status": order.status,
        "items": order.items or "[]",
        "subtotal": (order.amount / 100) if order.amount else 0,
        "delivery_fee": (order.delivery_fee / 100) if order.delivery_fee else 0,
        "total": ((order.amount + (order.delivery_fee or 0)) / 100),
        "currency": order.currency or "ZAR",
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
    }


@router.patch("/admin/orders/{order_number}")
def update_order_status(
    order_number: int,
    payload: dict,
    admin=Depends(verify_admin_header),
    db: Session = Depends(get_db)
):
    """Update order status only"""
    ALLOWED_STATUSES = ["pending", "paid", "processing", "shipped", "delivered"]
    
    new_status = payload.get("status", "").strip().lower()
    
    if not new_status:
        raise HTTPException(status_code=400, detail="Status required")
    
    if new_status not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid status. Allowed: {', '.join(ALLOWED_STATUSES)}"
        )
    
    order = db.query(Order).filter(Order.order_number == order_number).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    old_status = order.status
    order.status = new_status
    db.commit()
    db.refresh(order)
    
    logger.info(f"Order #{order_number} status updated: {old_status} -> {new_status}")
    
    return {
        "order_number": order.order_number,
        "status": order.status,
        "updated_at": datetime.utcnow().isoformat()
    }


@router.post("/admin/verify-token")
def verify_admin_token(authorization: str = Header(None)):
    """Verify if admin token is valid"""
    if not authorization:
        return {"valid": False}
    
    try:
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return {"valid": False}
        
        token = parts[1]
        verify_token(token)
        return {"valid": True}
    except:
        return {"valid": False}


def _verify_password(provided: str, expected: str) -> bool:
    """Constant-time password comparison"""
    import hmac
    return hmac.compare_digest(provided, expected)
