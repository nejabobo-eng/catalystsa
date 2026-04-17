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


# Removed - no longer needed. Yoco sends flat structure with "id" field.


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

    Yoco Checkout API sends flat structure:
    {
      "id": "ch_xxx",
      "status": "successful" | "failed",
      "amount": 27500,
      "currency": "ZAR",
      "metadata": { customer_email, customer_name, ... }
    }

    RULES:
    1. ALWAYS return 200 OK (even on error)
    2. Match by checkout_id ONLY (deterministic)
    3. Log all events for debugging
    4. Idempotent (safe to retry)
    """
    try:
        payload = await request.json()

        logger.info("=" * 60)
        logger.info("YOCO WEBHOOK RECEIVED")
        logger.info("=" * 60)
        logger.info(f"FULL PAYLOAD: {json.dumps(payload, indent=2)}")

        # Extract checkout_id (Yoco Checkout API uses flat "id" field)
        checkout_id = payload.get("id")
        status = payload.get("status")

        if not checkout_id:
            logger.error(f"Webhook missing checkout_id (id field)")
            logger.error(f"Payload: {json.dumps(payload, indent=2)}")
            log_webhook_event(
                db, "unknown", status or "unknown", "failed",
                error_message="missing checkout_id",
                raw_payload=json.dumps(payload)
            )
            return {"status": "received", "error": "missing checkout_id"}

        logger.info(f"Checkout ID: {checkout_id}")
        logger.info(f"Status: {status}")

        # Route based on status
        if status == "successful":
            return await handle_payment_success(payload, checkout_id, db)
        elif status == "failed":
            return await handle_payment_failed(payload, checkout_id, db)
        else:
            logger.info(f"Unknown status: {status}, logging only")
            log_webhook_event(db, checkout_id, status or "unknown", "ignored", raw_payload=json.dumps(payload))
            return {"status": "received", "message": "Status not handled"}

    except Exception as e:
        logger.error(f"CRITICAL: Webhook processing error: {str(e)}", exc_info=True)
        return {"status": "received", "error": "processing error logged"}


async def handle_payment_success(payload: dict, checkout_id: str, db: Session):
    """
    Handle successful payment - DETERMINISTIC matching by checkout_id only

    CRITICAL FLOW:
    1. Extract data from Yoco flat structure
    2. Match order by checkout_id (ONLY - no fallbacks)
    3. If exists → update to paid (idempotent)
    4. If missing → create new order
    5. Trigger emails (non-blocking)
    6. Return 200 OK
    """
    try:
        # Extract from Yoco Checkout API flat structure
        amount = payload.get("amount")
        currency = payload.get("currency", "ZAR")
        metadata = payload.get("metadata", {})

        # Extract customer data
        customer_email = metadata.get("customer_email", "").strip().lower()
        customer_name = metadata.get("customer_name", "").strip()
        phone = metadata.get("phone", "").strip()
        address = metadata.get("address", "").strip()
        city = metadata.get("city", "").strip()
        postal_code = metadata.get("postal_code", "").strip()
        delivery_fee_str = metadata.get("delivery_fee", "0")
        items_str = metadata.get("items", "[]")

        # Validate essential data
        if not amount:
            logger.error(f"Payment success: missing amount")
            logger.error(f"Payload: {json.dumps(payload, indent=2)}")
            return {"status": "received", "error": "missing amount"}

        try:
            delivery_fee_cents = int(float(delivery_fee_str) * 100)
        except (ValueError, TypeError):
            delivery_fee_cents = 0

        logger.info(f"✅ Payment SUCCESS")
        logger.info(f"   Checkout: {checkout_id}")
        logger.info(f"   Amount: {amount} {currency}")
        logger.info(f"   Customer: {customer_name} ({customer_email})")

        # IDEMPOTENCY: Match by checkout_id ONLY (deterministic)
        existing_order = db.query(Order).filter(Order.checkout_id == checkout_id).first()

        if existing_order:
            # Order already exists - update status if needed
            if existing_order.status != "paid":
                existing_order.status = "paid"
                existing_order.paid_at = datetime.utcnow()
                db.commit()
                logger.info(f"   ✅ Updated order #{existing_order.order_number} to paid")
            else:
                logger.info(f"   ✅ Order #{existing_order.order_number} already paid (idempotent)")

            log_webhook_event(
                db, checkout_id, "successful", "duplicate",
                order_created=False,
                order_number=existing_order.order_number,
                raw_payload=json.dumps(payload)
            )
            return {"status": "received", "order_number": existing_order.order_number}

        # NO EXISTING ORDER — CREATE NEW ONE
        logger.info(f"   Creating new order...")
        ensure_sequence_exists(db)

        new_order = Order(
            checkout_id=checkout_id,
            amount=amount,
            currency=currency,
            status="paid",
            paid_at=datetime.utcnow(),
            customer_email=customer_email if customer_email else None,
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

        order_number = get_next_order_number(db)
        new_order.order_number = order_number

        db.commit()
        logger.info(f"✅ Created order #{order_number}")

        log_webhook_event(
            db, checkout_id, "successful", "success",
            order_created=True,
            order_number=order_number,
            raw_payload=json.dumps(payload)
        )

        # Send emails (non-blocking)
        if customer_email:
            order_data = {
                "order_number": order_number,
                "checkout_id": checkout_id,
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

            threading.Thread(
                target=send_customer_order_confirmation,
                args=(order_data,),
                daemon=True
            ).start()

            threading.Thread(
                target=send_admin_order_notification,
                args=(order_data,),
                daemon=True
            ).start()

        return {"status": "received", "order_number": order_number}

    except Exception as e:
        logger.error(f"ERROR in payment success handler: {str(e)}", exc_info=True)
        logger.error(f"Full payload: {json.dumps(payload, indent=2)}")

        log_webhook_event(
            db, checkout_id, "successful", "failed",
            error_message=str(e),
            raw_payload=json.dumps(payload)
        )

        return {"status": "received", "error": "processing error logged"}


async def handle_payment_failed(payload: dict, checkout_id: str, db: Session):
    """
    Handle failed payment - log and mark order as failed
    """
    try:
        logger.error(f"❌ Payment FAILED: {checkout_id}")

        log_webhook_event(
            db, checkout_id, "failed", "failed",
            raw_payload=json.dumps(payload)
        )

        # Update order status if exists
        order = db.query(Order).filter(Order.checkout_id == checkout_id).first()
        if order:
            order.status = "failed"
            db.commit()
            logger.info(f"Marked order #{order.order_number} as failed")

        return {"status": "received", "message": "Payment failure recorded"}

    except Exception as e:
        logger.error(f"Error handling failed payment: {str(e)}", exc_info=True)
        log_webhook_event(
            db, checkout_id, "failed", "error",
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
