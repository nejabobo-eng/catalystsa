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
async def yoco_webhook(request: Request):
    """
    Yoco webhook handler — TRANSACTION SAFETY CRITICAL
    
    RULES (non-negotiable):
    1. ALWAYS return 200 OK (even on error)
    2. NEVER crash publicly
    3. Log all events for debugging
    4. Order creation is IDEMPOTENT (safe to retry)
    5. Email failures do NOT block order creation
    """
    db = SessionLocal()
    
    try:
        payload = await request.json()
        
        logger.info("=" * 60)
        logger.info("YOCO WEBHOOK RECEIVED")
        logger.info("=" * 60)
        
        event_type = payload.get("type")
        checkout_id = payload.get("data", {}).get("id")
        
        if not checkout_id:
            logger.error("Webhook missing checkout_id — cannot process")
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
    finally:
        db.close()


async def handle_payment_success(payload, db: Session):
    """
    Handle successful payment with transaction safety
    
    CRITICAL FLOW:
    1. Extract payment data
    2. Check if order already exists (IDEMPOTENCY)
    3. If exists → return OK (safe to retry)
    4. If missing → create order atomically
    5. Trigger email (non-blocking)
    6. Return 200 OK
    """
    try:
        data = payload.get("data", {})
        checkout_id = data.get("id")
        amount = data.get("totalAmount")
        currency = data.get("currency", "ZAR")
        metadata = data.get("metadata", {})
        
        if not checkout_id:
            logger.error("Payment success: missing checkout_id")
            return {"status": "received", "error": "missing checkout_id"}
        
        # Extract customer data
        customer_email = metadata.get("customer_email", "").lower() if metadata else ""
        customer_name = metadata.get("customer_name", "").strip() if metadata else ""
        phone = metadata.get("phone", "").strip() if metadata else ""
        address = metadata.get("address", "").strip() if metadata else ""
        city = metadata.get("city", "").strip() if metadata else ""
        postal_code = metadata.get("postal_code", "").strip() if metadata else ""
        delivery_fee_str = metadata.get("delivery_fee", "0") if metadata else "0"
        items_str = metadata.get("items", "[]") if metadata else "[]"
        
        try:
            delivery_fee_cents = int(float(delivery_fee_str) * 100)
        except (ValueError, TypeError):
            delivery_fee_cents = 0
        
        logger.info(f"✅ Payment SUCCESS: {checkout_id} - {amount} {currency}")
        logger.info(f"   Customer: {customer_name} ({customer_email})")
        
        # CHECK IF ORDER EXISTS (IDEMPOTENCY KEY)
        existing_order = db.query(Order).filter(Order.checkout_id == checkout_id).first()
        
        if existing_order:
            logger.info(f"   Order already exists: #{existing_order.order_number} — idempotent return")
            log_webhook_event(
                db, checkout_id, "payment.succeeded", "duplicate",
                order_created=False,
                order_number=existing_order.order_number,
                raw_payload=json.dumps(payload)
            )
            return {"status": "received", "message": "Order already created"}
        
        # ORDER DOES NOT EXIST — CREATE IT
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
        
        # Generate order number
        order_number = get_next_order_number(db)
        new_order.order_number = order_number
        
        # COMMIT — ORDER NOW EXISTS
        db.commit()
        logger.info(f"✅ Created new order #{order_number} for checkout: {checkout_id}")
        
        # LOG SUCCESS
        log_webhook_event(
            db, checkout_id, "payment.succeeded", "success",
            order_created=True,
            order_number=order_number,
            raw_payload=json.dumps(payload)
        )
        
        # TRIGGER EMAILS (non-blocking, failures don't block order)
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
        
        # Log failure
        checkout_id = payload.get("data", {}).get("id", "unknown")
        log_webhook_event(
            db, checkout_id, "payment.succeeded", "failed",
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
