"""Admin endpoint to create test order for workflow testing"""
from fastapi import APIRouter, Depends
from catalystsa.database import SessionLocal
from catalystsa.models import Order
from catalystsa.order_sequence import get_next_order_number
from catalystsa.admin_auth import verify_admin_header
from datetime import datetime

router_test = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router_test.post("/admin/create-test-order")
def create_test_order(
    admin=Depends(verify_admin_header),
    db=Depends(get_db)
):
    """Create a test order for workflow testing - REMOVE IN PRODUCTION"""
    order_number = get_next_order_number(db)

    test_order = Order(
        order_number=order_number,
        customer_name="Workflow Test Customer",
        customer_email=f"test-{order_number}@workflow.test",
        phone="0123456789",
        address="123 Test Street",
        city="Johannesburg",
        postal_code="2000",
        items='[{"name":"Test Product","quantity":1,"price":10000}]',
        amount=10000,
        delivery_fee=5000,
        currency="ZAR",
        status="paid",
        created_at=datetime.utcnow(),
        paid_at=datetime.utcnow()
    )

    db.add(test_order)
    db.commit()
    db.refresh(test_order)

    return {
        "order_number": test_order.order_number,
        "status": test_order.status,
        "customer_email": test_order.customer_email,
        "message": "Test order created successfully"
    }
