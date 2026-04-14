from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from catalystsa.database import SessionLocal
from catalystsa.models import Order
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


@router.post("/webhook")
async def yoco_webhook(request: Request):
    """
    Yoco sends payment notifications here.
    CRITICAL: Must return fast (<2s) and not block on external calls.
    """
    try:
        payload = await request.json()
        
        logger.info("=" * 60)
        logger.info("YOCO WEBHOOK RECEIVED")
        logger.info("=" * 60)
        logger.info(json.dumps(payload, indent=2))
        
        event_type = payload.get("type")
        
        if event_type == "payment.succeeded":
            return await handle_payment_success(payload)
        
        elif event_type == "payment.failed":
            return await handle_payment_failed(payload)
        
        else:
            logger.info(f"Unknown event type: {event_type}")
            return {"status": "received", "message": "Event type not handled"}
    
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def handle_payment_success(payload):
    """
    Handle successful payment
    
    Flow:
    1. Validate payment with Yoco data
    2. Generate order number (atomic increment)
    3. Save order to database (COMMIT IMMEDIATELY)
    4. Spawn background email tasks (non-blocking)
    5. Return 200 OK to Yoco within 2 seconds
    
    Email failures do NOT affect order creation.
    """
    db = SessionLocal()

    try:
        data = payload.get("data", {})
        checkout_id = data.get("id")
        amount = data.get("totalAmount")  # in cents
        currency = data.get("currency", "ZAR")
        metadata = data.get("metadata", {})
        
        # Extract customer data from metadata
        customer_email = metadata.get("customer_email", "").lower() if metadata else ""
        customer_name = metadata.get("customer_name", "").strip() if metadata else ""
        phone = metadata.get("phone", "").strip() if metadata else ""
        address = metadata.get("address", "").strip() if metadata else ""
        city = metadata.get("city", "").strip() if metadata else ""
        postal_code = metadata.get("postal_code", "").strip() if metadata else ""
        delivery_fee_str = metadata.get("delivery_fee", "0") if metadata else "0"
        items_str = metadata.get("items", "[]") if metadata else "[]"

        # Convert delivery fee string to int (cents)
        try:
            delivery_fee_cents = int(float(delivery_fee_str) * 100)
        except (ValueError, TypeError):
            delivery_fee_cents = 0

        logger.info(f"✅ Payment SUCCESS: {checkout_id} - {amount} {currency}")
        logger.info(f"   Customer: {customer_name} ({customer_email})")
        logger.info(f"   Delivery: R{delivery_fee_cents/100:.2f}")

        # Check if order already exists
        existing_order = db.query(Order).filter(Order.checkout_id == checkout_id).first()

        if existing_order:
            # Update existing order
            existing_order.status = "paid"
            existing_order.paid_at = datetime.utcnow()
            if customer_email:
                existing_order.customer_email = customer_email
            if customer_name:
                existing_order.customer_name = customer_name
            logger.info(f"Updated existing order: {existing_order.id}")
            db.commit()
            order_number = existing_order.order_number

        else:
            # Ensure sequence table exists
            ensure_sequence_exists(db)
            
            # Create new order
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
            db.flush()  # Flush to get the ID
            
            # Generate order number atomically
            order_number = get_next_order_number(db)
            new_order.order_number = order_number
            
            # Commit to database
            db.commit()
            logger.info(f"✅ Created new order #{order_number} for checkout: {checkout_id}")

        # Prepare order data for email
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
            "items": items_str,
            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }

        # Spawn background threads for email (non-blocking)
        # These run AFTER database commit, so order is guaranteed to exist
        email_thread_customer = threading.Thread(
            target=send_customer_order_confirmation,
            args=(order_data,),
            daemon=True
        )
        email_thread_admin = threading.Thread(
            target=send_admin_order_notification,
            args=(order_data,),
            daemon=True
        )
        
        email_thread_customer.start()
        email_thread_admin.start()
        
        logger.info(f"📧 Email tasks spawned for order #{order_number}")

        return {"status": "success", "message": "Payment processed", "order_number": order_number}

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error processing payment: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


async def handle_payment_failed(payload):
    """
    Handle failed payment
    """
    db = SessionLocal()
    
    try:
        data = payload.get("data", {})
        checkout_id = data.get("id")
        
        logger.error(f"❌ Payment FAILED: {checkout_id}")
        
        # Update order status to failed
        order = db.query(Order).filter(Order.checkout_id == checkout_id).first()
        if order:
            order.status = "failed"
            db.commit()
            logger.info(f"Marked order {order.id} as failed")

        return {"status": "received", "message": "Payment failure recorded"}
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error handling failed payment: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/orders")
def get_all_orders(db: Session = Depends(get_db)):
    """
    Get all orders (for admin panel)
    """
    orders = db.query(Order).order_by(Order.created_at.desc()).all()
    
    return [
        {
            "id": order.id,
            "order_number": order.order_number,
            "checkout_id": order.checkout_id,
            "amount": order.amount,
            "currency": order.currency,
            "status": order.status,
            "customer_name": order.customer_name,
            "customer_email": order.customer_email,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        }
        for order in orders
    ]


@router.get("/orders/by-email/{email}")
def get_orders_by_email(email: str, db: Session = Depends(get_db)):
    """
    Get orders by customer email
    """
    orders = db.query(Order).filter(
        Order.customer_email == email.lower()
    ).order_by(Order.created_at.desc()).all()

    return [
        {
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
        for order in orders
    ]


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
