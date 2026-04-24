from fastapi import APIRouter, HTTPException, Header, Depends
from sqlalchemy.orm import Session
from catalystsa.database import SessionLocal, get_db
from catalystsa.models import Order
from catalystsa.admin_auth import create_token, verify_token, ADMIN_PASSWORD
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()


# Use centralized get_db from catalystsa.database for consistent rollback behavior


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

    logger.info(f"Admin orders query - Total: {total}, Returned: {len(orders)}, Skip: {skip}, Limit: {limit}")
    if orders:
        logger.info(f"Sample order: #{orders[0].order_number}, Email: {orders[0].customer_email}")

    return {
        "orders": [
            {
                "id": order.id,
                "order_number": order.order_number,
                "customer_name": order.customer_name or "N/A",
                "email": order.customer_email or "N/A",
                "status": order.status,
                "total": ((order.amount or 0) + (order.delivery_fee or 0)) / 100,  # amount=subtotal, delivery_fee=shipping
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
    """
    Get full order details with financial integrity validation

    CRITICAL: Backend owns financial truth, not stored totals
    Always calculates total from subtotal + delivery (never trusts stored value)
    """
    order = db.query(Order).filter(Order.order_number == order_number).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # FINANCIAL INTEGRITY: Always calculate in cents, convert to rands only for display
    subtotal_cents = order.amount or 0
    delivery_cents = order.delivery_fee or 0
    calculated_total_cents = subtotal_cents + delivery_cents

    # Detect financial inconsistencies (legacy data warning)
    is_legacy_pricing = False
    if delivery_cents == 80000:  # Old R800 delivery
        is_legacy_pricing = True
    elif delivery_cents != 9900 and delivery_cents != 0:  # Not R99 or R0
        logger.warning(f"Order #{order_number} has unusual delivery fee: {delivery_cents} cents")
        is_legacy_pricing = True

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
        "tracking_number": order.tracking_number,
        "items": order.items or "[]",

        # FINANCIAL DATA: All values in cents internally, converted to rands for display
        "subtotal": subtotal_cents / 100,  # cents → rands
        "delivery_fee": delivery_cents / 100,  # cents → rands
        "total": calculated_total_cents / 100,  # CALCULATED, not stored
        "currency": order.currency or "ZAR",

        # Integrity flags
        "is_legacy_pricing": is_legacy_pricing,  # Flag old pricing for UI warning

        "created_at": order.created_at.isoformat() if order.created_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


@router.patch("/admin/orders/{order_number}")
def update_order_status(
    order_number: int,
    payload: dict,
    admin=Depends(verify_admin_header),
    db: Session = Depends(get_db)
):
    """
    Update order status with workflow validation

    Status flow:
    - paid → processing
    - processing → shipped
    - shipped → delivered
    """
    ALLOWED_STATUSES = ["paid", "processing", "shipped", "delivered"]

    # Status transition rules (forward flow only)
    STATUS_FLOW = {
        "paid": ["processing"],
        "processing": ["shipped"],
        "shipped": ["delivered"],
        "delivered": []  # Final state
    }

    new_status = payload.get("status", "").strip().lower()
    tracking_number = payload.get("tracking_number", "").strip()

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

    # Validate status transition
    allowed_next = STATUS_FLOW.get(order.status, [])
    if new_status not in allowed_next and new_status != order.status:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot change status from '{order.status}' to '{new_status}'. Allowed: {', '.join(allowed_next) if allowed_next else 'none (final state)'}"
        )

    old_status = order.status
    order.status = new_status

    # Update tracking number if provided (usually when marking as shipped)
    if tracking_number:
        order.tracking_number = tracking_number

    db.commit()
    db.refresh(order)

    logger.info(f"Order #{order_number} status updated: {old_status} -> {new_status}" + 
                (f" (tracking: {tracking_number})" if tracking_number else ""))

    return {
        "order_number": order.order_number,
        "status": order.status,
        "tracking_number": order.tracking_number,
        "updated_at": order.updated_at.isoformat() if order.updated_at else datetime.utcnow().isoformat()
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


@router.get("/admin/financial-audit")
def financial_audit(
    admin=Depends(verify_admin_header),
    db: Session = Depends(get_db)
):
    """
    Financial integrity audit endpoint

    Detects:
    - Orders with inconsistent pricing
    - Legacy delivery fees
    - Unusual amounts

    Returns list of orders requiring review
    """
    all_orders = db.query(Order).all()

    issues = []
    for order in all_orders:
        order_issues = []

        # Check for legacy R800 delivery
        if order.delivery_fee == 80000:
            order_issues.append("LEGACY_DELIVERY_R800")

        # Check for unusual delivery (not R0, R99, or R800)
        elif order.delivery_fee not in [0, 9900, 80000] and order.delivery_fee is not None:
            order_issues.append(f"UNUSUAL_DELIVERY_{order.delivery_fee}_CENTS")

        # Check for zero amounts
        if order.amount == 0 or order.amount is None:
            order_issues.append("ZERO_SUBTOTAL")

        if order_issues:
            issues.append({
                "order_number": order.order_number,
                "customer_email": order.customer_email,
                "status": order.status,
                "subtotal_cents": order.amount,
                "delivery_cents": order.delivery_fee,
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "issues": order_issues
            })

    return {
        "total_orders": len(all_orders),
        "orders_with_issues": len(issues),
        "issues": issues
    }


def _verify_password(provided: str, expected: str) -> bool:
    """Constant-time password comparison"""
    import hmac
    return hmac.compare_digest(provided, expected)
