from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Product
from schemas import ProductCreate
from pricing import calculate_price

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/")
def create_product(product: ProductCreate, db: Session = Depends(get_db)):
    try:
        price = calculate_price(product.cost)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    new_product = Product(
        name=product.name,
        description=product.description,
        cost=product.cost,
        price=price,
        category=product.category,
        image=product.image
    )

    db.add(new_product)
    db.commit()
    db.refresh(new_product)

    return new_product


@router.get("/")
def get_products(db: Session = Depends(get_db)):
    return db.query(Product).all()
