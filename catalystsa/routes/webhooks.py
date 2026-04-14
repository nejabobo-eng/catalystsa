from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from catalystsa.database import SessionLocal
from catalystsa.models import Order
from datetime import datetime
import json

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
    Yoco sends payment notifications here
    """
    try:
        payload = await request.json()
        
        print("=" * 60)
        print("YOCO WEBHOOK RECEIVED")
        print("=" * 60)
        print(json.dumps(payload, indent=2))
        print("=" * 60)
        
        event_type = payload.get("type")
        
        if event_type == "payment.succeeded":
            return await handle_payment_success(payload)
        
        elif event_type == "payment.failed":
            return await handle_payment_failed(payload)
        
        else:
            print(f"Unknown event type: {event_type}")
            return {"status": "received", "message": "Event type not handled"}
    
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def handle_payment_success(payload):
    """
    Handle successful payment
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
        items_str = metadata.get("items", "{}") if metadata else "{}"

        # Convert delivery fee string to int (cents)
        try:
            delivery_fee_cents = int(float(delivery_fee_str) * 100)
        except (ValueError, TypeError):
            delivery_fee_cents = 0

        print(f"✅ Payment SUCCESS: {checkout_id} - {amount} {currency}")
        print(f"   Customer: {customer_name} ({customer_email})")
        print(f"   Address: {address}, {city}")

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
            print(f"Updated existing order: {existing_order.id}")
        else:
            # Generate order number: base 10000 + id
            # First, create the order to get an ID, then update with order_number
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
            db.flush()  # Flush to get the ID without committing

            # Generate order number
            order_number = 10000 + new_order.id
            new_order.order_number = order_number

            print(f"Created new order #{order_number} for checkout: {checkout_id}")

        db.commit()

        return {"status": "success", "message": "Payment processed"}

    except Exception as e:
        db.rollback()
        print(f"Error processing payment: {str(e)}")
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
        
        print(f"❌ Payment FAILED: {checkout_id}")
        
        # Update order status to failed
        order = db.query(Order).filter(Order.checkout_id == checkout_id).first()
        if order:
            order.status = "failed"
            db.commit()
            print(f"Marked order {order.id} as failed")
        
        return {"status": "received", "message": "Payment failure recorded"}
    
    except Exception as e:
        db.rollback()
        print(f"Error handling failed payment: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/orders")
def get_all_orders(db: Session = Depends(get_db)):
    """
    Get all orders (for admin panel)
    """
    orders = db.query(Order).order_by(Order.created_at.desc()).all()
    
    # Convert to dict to avoid Pydantic serialization issues
    return [
        {
            "id": order.id,
            "checkout_id": order.checkout_id,
            "amount": order.amount,
            "currency": order.currency,
            "status": order.status,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        }
        for order in orders
    ]


@router.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    """
    Get specific order details
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "id": order.id,
        "checkout_id": order.checkout_id,
        "amount": order.amount,
        "currency": order.currency,
        "status": order.status,
        "customer_name": order.customer_name,
        "customer_email": order.customer_email,
        "phone": order.phone,
        "address": order.address,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
    }


@router.get("/orders/{email}")
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
