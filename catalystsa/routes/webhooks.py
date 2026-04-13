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
        
        print(f"✅ Payment SUCCESS: {checkout_id} - {amount} {currency}")
        
        # Check if order already exists
        existing_order = db.query(Order).filter(Order.checkout_id == checkout_id).first()
        
        if existing_order:
            # Update existing order
            existing_order.status = "paid"
            existing_order.paid_at = datetime.utcnow()
            print(f"Updated existing order: {existing_order.id}")
        else:
            # Create new order
            new_order = Order(
                checkout_id=checkout_id,
                amount=amount,
                currency=currency,
                status="paid",
                paid_at=datetime.utcnow()
            )
            db.add(new_order)
            print(f"Created new order for checkout: {checkout_id}")
        
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
