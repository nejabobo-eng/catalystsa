from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from catalystsa.database import SessionLocal
from catalystsa.models import Order, WebhookEvent
from catalystsa.order_sequence import get_next_order_number, ensure_sequence_exists
from catalystsa.email_service import send_customer_order_confirmation, send_admin_order_notification
from datetime import datetime
import json
import logging

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
    Audit log for webhook events (debugging and reconciliation only)
    Never read for business logic - Order table is source of truth
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
    Yoco webhook handler — STRIPE-LEVEL ARCHITECTURE

    Contract (observed from real webhooks):
    {
      "type": "payment.succeeded" | "payment.failed",
      "data": {
        "id": "ch_xxx",
        "totalAmount": 27500,
        "currency": "ZAR",
        "metadata": { customer_email, customer_name, ... }
      }
    }

    ARCHITECTURE:
    - Order table = single source of truth (idempotency)
    - WebhookEvent table = audit log only (never read for logic)
    - checkout_id = deterministic key

    GUARANTEES:
    1. Idempotent - safe for Yoco retries
    2. Never creates duplicate orders
    3. Always returns 200 OK (Yoco requirement)
    """
    try:
        payload = await request.json()

        logger.info("=" * 60)
        logger.info("YOCO WEBHOOK RECEIVED")
        logger.info("=" * 60)
        logger.info(f"FULL PAYLOAD: {json.dumps(payload, indent=2)}")

        # Extract from Yoco structure (supports both test and production formats)
        event_type = payload.get("type")

        # Try production format first: payload.metadata.checkoutId
        data = payload.get("payload", {})
        metadata = data.get("metadata", {})
        checkout_id = metadata.get("checkoutId")

        # Fallback to test format: data.id
        if not checkout_id:
            data = payload.get("data", {})
            checkout_id = data.get("id")

        # Validate essential fields
        if not checkout_id:
            logger.error(f"Missing checkout_id in both payload.metadata.checkoutId and data.id")
            logger.error(f"Payload: {json.dumps(payload, indent=2)}")
            log_webhook_event(
                db, "unknown", event_type or "unknown", "failed",
                error_message="missing checkout_id",
                raw_payload=json.dumps(payload)
            )
            return {"status": "received", "error": "missing checkout_id"}

        if not event_type:
            logger.error(f"Missing event type")
            log_webhook_event(
                db, checkout_id, "unknown", "failed",
                error_message="missing event_type",
                raw_payload=json.dumps(payload)
            )
            return {"status": "received", "error": "missing event_type"}

        logger.info(f"Event: {event_type}")
        logger.info(f"Checkout: {checkout_id}")

        # Route to handler
        if event_type == "payment.succeeded":
            return await handle_payment_success(payload, checkout_id, db)
        elif event_type == "payment.failed":
            return await handle_payment_failed(payload, checkout_id, db)
        else:
            logger.info(f"Unknown event type: {event_type}, logging only")
            log_webhook_event(db, checkout_id, event_type, "ignored", raw_payload=json.dumps(payload))
            return {"status": "received", "message": "event type not handled"}

    except Exception as e:
        logger.error(f"CRITICAL: Webhook processing error: {str(e)}", exc_info=True)
        return {"status": "received", "error": "processing error logged"}


async def handle_payment_success(payload: dict, checkout_id: str, db: Session):
    """
    Handle successful payment - CLEAN STRIPE-STYLE ARCHITECTURE

    IDEMPOTENCY MODEL:
    - checkout_id has UNIQUE constraint in database
    - Attempt insert → if duplicate, DB raises IntegrityError
    - On retry: order already exists, mark paid again (idempotent)

    GUARANTEES:
    - One order per checkout_id (database theorem)
    - Order status always reflects payment state
    - Side effects are best-effort (may duplicate on rare webhook retries)

    TRADE-OFFS ACCEPTED:
    - Email may duplicate on webhook retry (rare, acceptable)
    - Audit logs may duplicate (debugging only, acceptable)
    - System simplicity > perfect deduplication
    """
    try:
        # Extract from Yoco structure (supports both test and production formats)
        # Production format: payload.amount, payload.metadata
        # Test format: data.totalAmount, data.metadata

        data = payload.get("payload", {})
        if not data:
            data = payload.get("data", {})

        amount = data.get("totalAmount") or data.get("amount")
        currency = data.get("currency", "ZAR")
        metadata = data.get("metadata", {})

        # Extract customer data
        customer_email = metadata.get("customer_email", "").strip().lower()
        customer_name = metadata.get("customer_name", "").strip()
        phone = metadata.get("phone", "").strip()
        address = metadata.get("address", "").strip()
        city = metadata.get("city", "").strip()
        postal_code = metadata.get("postal_code", "").strip()
        delivery_fee_str = metadata.get("delivery_fee", "0")
        items_str = metadata.get("items", "[]")

        # Validate critical data
        if not amount:
            logger.error(f"Missing amount in payload")
            logger.error(f"Payload: {json.dumps(payload, indent=2)}")
            log_webhook_event(
                db, checkout_id, "payment.succeeded", "failed",
                error_message="missing amount",
                raw_payload=json.dumps(payload)
            )
            return {"status": "received", "error": "missing amount"}

        try:
            delivery_fee_cents = int(float(delivery_fee_str) * 100)
        except (ValueError, TypeError):
            delivery_fee_cents = 0

        logger.info(f"✅ Payment SUCCESS")
        logger.info(f"   Checkout: {checkout_id}")
        logger.info(f"   Amount: {amount} {currency}")
        logger.info(f"   Customer: {customer_name} ({customer_email})")

        # Check if order already exists (webhook retry)
        existing_order = db.query(Order).filter(Order.checkout_id == checkout_id).first()

        if existing_order:
            # Webhook retry - order already exists
            logger.info(f"   ✅ Order #{existing_order.order_number} already exists (webhook retry)")

            # Ensure status is paid (idempotent)
            if existing_order.status != "paid":
                existing_order.status = "paid"
                existing_order.paid_at = datetime.utcnow()
                db.commit()
                logger.info(f"   Updated order status to paid")

            # Audit log (best effort)
            try:
                log_webhook_event(
                    db, checkout_id, "payment.succeeded", "duplicate",
                    order_created=False,
                    order_number=existing_order.order_number,
                    raw_payload=json.dumps(payload)
                )
            except Exception as e:
                logger.error(f"Failed to log webhook event: {str(e)}")

            # Side effects (best effort - may duplicate on retries)
            send_emails_best_effort(existing_order, delivery_fee_cents)

            return {"status": "received", "order_number": existing_order.order_number, "idempotent": True}

        # CREATE NEW ORDER - Database enforces uniqueness
        logger.info(f"   Creating new order...")
        ensure_sequence_exists(db)

        # CLEAN MODEL: amount = Yoco total, but we store SUBTOTAL only
        # This prevents double-counting delivery in admin/reports
        subtotal_cents = amount - delivery_fee_cents

        logger.info(f"   Payment breakdown:")
        logger.info(f"   - Yoco total: {amount} cents")
        logger.info(f"   - Delivery: {delivery_fee_cents} cents")
        logger.info(f"   - Subtotal (products): {subtotal_cents} cents")

        new_order = Order(
            checkout_id=checkout_id,  # UNIQUE constraint - DB rejects duplicates
            amount=subtotal_cents,  # ✅ SUBTOTAL ONLY (products)
            currency=currency,
            status="paid",
            paid_at=datetime.utcnow(),
            customer_email=customer_email if customer_email else None,
            customer_name=customer_name if customer_name else None,
            phone=phone if phone else None,
            address=address if address else None,
            city=city if city else None,
            postal_code=postal_code if postal_code else None,
            delivery_fee=delivery_fee_cents if delivery_fee_cents > 0 else None,  # ✅ DELIVERY SEPARATE
            items=items_str if items_str else None
        )
        db.add(new_order)
        db.flush()

        order_number = get_next_order_number(db)
        new_order.order_number = order_number

        # Commit order (atomicity: success or rollback)
        try:
            db.commit()
            logger.info(f"✅ Created order #{order_number}")
        except IntegrityError as e:
            # Race condition: another process created order with same checkout_id
            # This is extremely rare but database handles it correctly
            db.rollback()
            logger.warning(f"IntegrityError during commit (rare race condition): {str(e)}")

            # Retrieve the order that won the race
            existing_order = db.query(Order).filter(Order.checkout_id == checkout_id).first()
            if existing_order:
                logger.info(f"   Order #{existing_order.order_number} created by concurrent request")
                send_emails_best_effort(existing_order, delivery_fee_cents)
                return {"status": "received", "order_number": existing_order.order_number, "race_handled": True}
            else:
                # Should never happen - re-raise for investigation
                raise

        # Audit log (best effort)
        try:
            log_webhook_event(
                db, checkout_id, "payment.succeeded", "success",
                order_created=True,
                order_number=order_number,
                raw_payload=json.dumps(payload)
            )
        except Exception as e:
            logger.error(f"Failed to log webhook event: {str(e)}")

        # Side effects (best effort)
        send_emails_best_effort(new_order, delivery_fee_cents)

        # Update sales_count for products referenced in items (best-effort)
        try:
            import ast
            items = ast.literal_eval(items_str) if items_str else []
            for it in items:
                pid = it.get('id') or it.get('product_id') or it.get('id')
                qty = int(it.get('quantity', 1)) if isinstance(it, dict) else 1
                if pid:
                    prod = db.query(Product).filter(Product.id == int(pid)).first()
                    if prod:
                        prod.sales_count = (prod.sales_count or 0) + qty
            db.commit()
        except Exception:
            # Non-critical - don't block order creation
            db.rollback()

        return {"status": "received", "order_number": order_number, "created": True}

    except Exception as e:
        logger.error(f"ERROR in payment handler: {str(e)}", exc_info=True)
        logger.error(f"Payload: {json.dumps(payload, indent=2)}")
        db.rollback()

        # Audit log (best effort)
        try:
            log_webhook_event(
                db, checkout_id, "payment.succeeded", "failed",
                error_message=str(e),
                raw_payload=json.dumps(payload)
            )
        except:
            pass

        # Always return 200 OK (Yoco requirement for retry)
        return {"status": "received", "error": "processing error logged"}


def send_emails_best_effort(order: Order, delivery_fee_cents: int):
    """
    Send emails - best effort, failures are logged but don't block webhook response

    TRADE-OFF: May send duplicate emails on webhook retries (rare, acceptable)
    """
    # Customer email
    if order.customer_email:
        try:
            order_data = {
                "order_number": order.order_number,
                "checkout_id": order.checkout_id,
                "amount": order.amount,
                "delivery_fee": delivery_fee_cents,
                "customer_name": order.customer_name,
                "customer_email": order.customer_email,
                "phone": order.phone,
                "address": order.address,
                "city": order.city,
                "postal_code": order.postal_code,
                "items": order.items
            }
            send_customer_order_confirmation(order_data)
            logger.info(f"   ✅ Customer email sent to {order.customer_email}")
        except Exception as e:
            logger.error(f"   ❌ Failed to send customer email: {str(e)}")

    # Admin email
    try:
        order_data = {
            "order_number": order.order_number,
            "checkout_id": order.checkout_id,
            "amount": order.amount,
            "delivery_fee": delivery_fee_cents,
            "customer_name": order.customer_name,
            "customer_email": order.customer_email,
            "phone": order.phone,
            "address": order.address,
            "city": order.city,
            "postal_code": order.postal_code,
            "items": order.items
        }
        send_admin_order_notification(order_data)
        logger.info(f"   ✅ Admin email sent")
    except Exception as e:
        logger.error(f"   ❌ Failed to send admin email: {str(e)}")


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
