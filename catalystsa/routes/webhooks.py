from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from catalystsa.database import SessionLocal
from catalystsa.models import Order, WebhookEvent
from catalystsa.order_sequence import get_next_order_number, ensure_sequence_exists
from catalystsa.email_service import send_customer_order_confirmation, send_admin_order_notification
from datetime import datetime
import json
import logging
import threading

logger = logging.getLogger(__name__)
router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def extract_checkout_id(payload: dict) -> str:
    """
    Robustly extract checkout_id from multiple possible Yoco webhook structures

    Yoco may send different structures:
    - {"data": {"id": "ch_xxx"}}
    - {"id": "ch_xxx"}
    - {"checkout_id": "ch_xxx"}
    - {"payload": {"id": "ch_xxx"}}
    """
    # Try direct checkout_id field
    if "checkout_id" in payload:
        return payload["checkout_id"]

    # Try nested data.id (original expected structure)
    if "data" in payload and isinstance(payload["data"], dict):
        if "id" in payload["data"]:
            return payload["data"]["id"]
        if "checkout_id" in payload["data"]:
            return payload["data"]["checkout_id"]

    # Try direct id field
    if "id" in payload:
        return payload["id"]

    # Try nested payload.id
    if "payload" in payload and isinstance(payload["payload"], dict):
        if "id" in payload["payload"]:
            return payload["payload"]["id"]

    return None


def log_webhook_event(db: Session, checkout_id: str, event_type: str, status: str, 
                      error_message: str = None, order_created: bool = False, 
                      order_number: int = None, raw_payload: str = None):
    """
    Log webhook event for transaction safety and debugging
    This is your money flow audit trail
    """
    try:
        event = WebhookEvent(
            checkout_id=checkout_id,
            event_type=event_type,
            status=status,
            error_message=error_message,
            order_created=order_created,
            order_number=order_number,
            raw_payload=raw_payload,
            processed_at=datetime.utcnow()
        )
        db.add(event)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log webhook event: {str(e)}")


@router.post("/webhook")
async def yoco_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Yoco webhook handler — TRANSACTION SAFETY CRITICAL

    RULES (non-negotiable):
    1. ALWAYS return 200 OK (even on error)
    2. NEVER crash publicly
    3. Log all events for debugging
    4. Order creation is IDEMPOTENT (safe to retry)
    5. Email failures do NOT block order creation
    """
    try:
        payload = await request.json()

        logger.info("=" * 60)
        logger.info("YOCO WEBHOOK RECEIVED")
        logger.info("=" * 60)
        logger.info(f"FULL PAYLOAD: {json.dumps(payload, indent=2)}")

        event_type = payload.get("type")
        checkout_id = extract_checkout_id(payload)

        if not checkout_id:
            logger.error(f"Webhook missing checkout_id — cannot process")
            logger.error(f"Payload structure: {json.dumps(payload, indent=2)}")
            log_webhook_event(
                db, "unknown", event_type or "unknown", "failed",
                error_message="missing checkout_id",
                raw_payload=json.dumps(payload)
            )
            return {"status": "received", "error": "missing checkout_id"}

        logger.info(f"Event type: {event_type}, Checkout: {checkout_id}")

        if event_type == "payment.succeeded":
            return await handle_payment_success(payload, db)

        elif event_type == "payment.failed":
            return await handle_payment_failed(payload, db)

        else:
            logger.info(f"Unknown event type: {event_type}, ignoring")
            log_webhook_event(db, checkout_id, event_type, "ignored")
            return {"status": "received", "message": "Event type not handled"}

    except Exception as e:
        logger.error(f"CRITICAL: Webhook processing error: {str(e)}", exc_info=True)
        return {"status": "received", "error": "processing error logged"}


async def handle_payment_success(payload, db: Session):
    """
    Handle successful payment with transaction safety

    PRODUCTION-SAFE MATCHING STRATEGY:
    - Uses metadata (customer_email) as primary business key
    - Does NOT rely on fragile checkout_id/payment_id matching
    - Survives Yoco schema changes
    - Idempotent and transaction-safe

    CRITICAL FLOW:
    1. Extract payment data from MULTIPLE possible structures
    2. Use customer_email to match order (business key)
    3. If exists → return OK (safe to retry)
    4. If missing → create order atomically
    5. Trigger email (non-blocking)
    6. Return 200 OK
    """
    try:
        # Extract from multiple possible Yoco structures
        data = payload.get("data", payload.get("payload", {}))

        # Try multiple ID extraction patterns
        checkout_id = (
            data.get("checkoutId") or 
            data.get("checkout_id") or 
            data.get("id")
        )

        amount = data.get("totalAmount") or data.get("amount")
        currency = data.get("currency", "ZAR")
        metadata = data.get("metadata", {})

        # Extract customer data from metadata
        customer_email = metadata.get("customer_email", "").strip().lower() if metadata else ""
        customer_name = metadata.get("customer_name", "").strip() if metadata else ""
        phone = metadata.get("phone", "").strip() if metadata else ""
        address = metadata.get("address", "").strip() if metadata else ""
        city = metadata.get("city", "").strip() if metadata else ""
        postal_code = metadata.get("postal_code", "").strip() if metadata else ""
        delivery_fee_str = metadata.get("delivery_fee", "0") if metadata else "0"
        items_str = metadata.get("items", "[]") if metadata else "[]"

        # Validate essential data
        if not customer_email:
            logger.error(f"Payment success: missing customer_email in metadata")
            logger.error(f"Payload: {json.dumps(payload, indent=2)}")
            return {"status": "received", "error": "missing customer_email"}

        if not amount:
            logger.error(f"Payment success: missing amount")
            logger.error(f"Payload: {json.dumps(payload, indent=2)}")
            return {"status": "received", "error": "missing amount"}

        try:
            delivery_fee_cents = int(float(delivery_fee_str) * 100)
        except (ValueError, TypeError):
            delivery_fee_cents = 0

        logger.info(f"✅ Payment SUCCESS")
        logger.info(f"   Checkout ID: {checkout_id}")
        logger.info(f"   Amount: {amount} {currency}")
        logger.info(f"   Customer: {customer_name} ({customer_email})")

        # IDEMPOTENCY CHECK: Match by checkout_id first (if available)
        existing_order = None
        if checkout_id:
            existing_order = db.query(Order).filter(Order.checkout_id == checkout_id).first()

        # Fallback: Match by email + amount (recent unpaid order)
        if not existing_order:
            logger.info(f"   No order found by checkout_id, trying email + amount match...")
            existing_order = db.query(Order).filter(
                Order.customer_email == customer_email,
                Order.amount == amount,
                Order.status == "pending"
            ).order_by(Order.created_at.desc()).first()

        if existing_order:
            # Update existing order
            existing_order.status = "paid"
            existing_order.paid_at = datetime.utcnow()
            if checkout_id and not existing_order.checkout_id:
                existing_order.checkout_id = checkout_id

            db.commit()
            logger.info(f"   ✅ Updated existing order #{existing_order.order_number} to paid")

            log_webhook_event(
                db, checkout_id or "email_match", "payment.succeeded", "duplicate",
                order_created=False,
                order_number=existing_order.order_number,
                raw_payload=json.dumps(payload)
            )
            return {"status": "received", "message": "Order updated to paid", "order_number": existing_order.order_number}
        
        # NO EXISTING ORDER — CREATE NEW ONE
        logger.info(f"   Creating new order from webhook payment...")
        ensure_sequence_exists(db)

        new_order = Order(
            checkout_id=checkout_id if checkout_id else None,
            amount=amount,
            currency=currency,
            status="paid",
            paid_at=datetime.utcnow(),
            customer_email=customer_email,
            customer_name=customer_name if customer_name else None,
            phone=phone if phone else None,
            address=address if address else None,
            city=city if city else None,
            postal_code=postal_code if postal_code else None,
            delivery_fee=delivery_fee_cents if delivery_fee_cents > 0 else None,
            items=items_str if items_str else None
        )
        db.add(new_order)
        db.flush()

        # Generate order number
        order_number = get_next_order_number(db)
        new_order.order_number = order_number

        # COMMIT — ORDER NOW EXISTS
        db.commit()
        logger.info(f"✅ Created new order #{order_number}")
        logger.info(f"   Checkout: {checkout_id}")
        logger.info(f"   Email: {customer_email}")

        # LOG SUCCESS
        log_webhook_event(
            db, checkout_id or customer_email, "payment.succeeded", "success",
            order_created=True,
            order_number=order_number,
            raw_payload=json.dumps(payload)
        )

        # TRIGGER EMAILS (non-blocking, failures don't block order)
        order_data = {
            "order_number": order_number,
            "checkout_id": checkout_id or "webhook_created",
            "amount": amount,
            "delivery_fee": delivery_fee_cents,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "phone": phone,
            "address": address,
            "city": city,
            "postal_code": postal_code,
            "items": items_str
        }

        # Send emails asynchronously (non-blocking)
        if customer_email:
            thread1 = threading.Thread(
                target=send_customer_order_confirmation,
                args=(order_data,),
                daemon=True
            )
            thread1.start()

        thread2 = threading.Thread(
            target=send_admin_order_notification,
            args=(order_data,),
            daemon=True
        )
        thread2.start()

        # RETURN 200 OK IMMEDIATELY
        return {"status": "received", "order_number": order_number}
        
    except Exception as e:
        logger.error(f"ERROR in payment success handler: {str(e)}", exc_info=True)
        logger.error(f"Full payload: {json.dumps(payload, indent=2)}")

        # Try to extract any identifier for logging
        data = payload.get("data", payload.get("payload", {}))
        identifier = (
            data.get("checkoutId") or 
            data.get("checkout_id") or 
            data.get("id") or 
            data.get("metadata", {}).get("customer_email") or 
            "unknown"
        )

        log_webhook_event(
            db, identifier, "payment.succeeded", "failed",
            error_message=str(e),
            raw_payload=json.dumps(payload)
        )

        # Still return 200 OK (error is logged, we'll debug)
        return {"status": "received", "error": "processing error logged"}


async def handle_payment_failed(payload, db: Session):
    """
    Handle failed payment
    """
    try:
        data = payload.get("data", {})
        checkout_id = data.get("id")
        
        if not checkout_id:
            logger.error("Payment failed: missing checkout_id")
            return {"status": "received", "error": "missing checkout_id"}
        
        logger.error(f"❌ Payment FAILED: {checkout_id}")
        
        # Log failure
        log_webhook_event(
            db, checkout_id, "payment.failed", "failed",
            raw_payload=json.dumps(payload)
        )
        
        # Update order status to failed if it exists
        order = db.query(Order).filter(Order.checkout_id == checkout_id).first()
        if order:
            order.status = "failed"
            db.commit()
            logger.info(f"Marked order {order.order_number} as failed")

        return {"status": "received", "message": "Payment failure recorded"}
    
    except Exception as e:
        logger.error(f"Error handling failed payment: {str(e)}", exc_info=True)
        checkout_id = payload.get("data", {}).get("id", "unknown")
        log_webhook_event(
            db, checkout_id, "payment.failed", "error",
            error_message=str(e),
            raw_payload=json.dumps(payload)
        )
        return {"status": "received", "error": "processing error logged"}


@router.get("/orders/{email}")
def get_orders(email: str, db: Session = Depends(get_db)):
    """
    [DEPRECATED] Get orders by customer email - returns minimal array
    Use GET /public/orders/{email} instead (proper response shape)
    """
    orders = db.query(Order).filter(
        Order.customer_email == email.lower()
    ).order_by(Order.created_at.desc()).limit(10).all()

    # Return minimal data to prevent scraping
    return [
        {
            "order_number": order.order_number,
            "created_at": order.created_at.isoformat() if order.created_at else None,
        }
        for order in orders
    ]


@router.post("/orders/lookup")
def lookup_order(payload: dict, db: Session = Depends(get_db)):
    """
    Secure order lookup: requires email + order number
    Prevents data scraping

    Request body:
    {
        "email": "customer@example.com",
        "order_number": 10001
    }
    """
    email = payload.get("email", "").strip().lower()
    order_number = payload.get("order_number")

    if not email or not order_number:
        raise HTTPException(status_code=400, detail="Email and order number required")

    order = db.query(Order).filter(
        (Order.customer_email == email) & 
        (Order.order_number == order_number)
    ).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Return full order details
    return {
        "id": order.id,
        "order_number": order.order_number,
        "checkout_id": order.checkout_id,
        "amount": order.amount,
        "delivery_fee": order.delivery_fee,
        "currency": order.currency,
        "status": order.status,
        "customer_name": order.customer_name,
        "customer_email": order.customer_email,
        "phone": order.phone,
        "address": order.address,
        "city": order.city,
        "postal_code": order.postal_code,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
    }


@router.get("/orders/number/{order_number}")
def get_order_by_number(order_number: int, db: Session = Depends(get_db)):
    """
    Get specific order by order number (e.g., #10001)
    """
    order = db.query(Order).filter(Order.order_number == order_number).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "id": order.id,
        "order_number": order.order_number,
        "checkout_id": order.checkout_id,
        "amount": order.amount,
        "delivery_fee": order.delivery_fee,
        "currency": order.currency,
        "status": order.status,
        "customer_name": order.customer_name,
        "customer_email": order.customer_email,
        "phone": order.phone,
        "address": order.address,
        "city": order.city,
        "postal_code": order.postal_code,
        "items": order.items,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
    }
