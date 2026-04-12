from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Order, Product
from schemas import OrderCreate

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/")
def create_order(order: OrderCreate, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == order.product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    new_order = Order(
        product_id=product.id,
        customer_name=order.customer_name,
        phone=order.phone,
        address=order.address,
        total=product.price,
        status="pending"
    )

    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    return new_order
