from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from catalystsa.database import SessionLocal
from catalystsa.models import Product
from catalystsa.schemas import ProductCreate
from catalystsa.pricing import calculate_price
from catalystsa.admin_auth import verify_token

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_admin_header(authorization: str = Header(None)):
    """
    Verify admin token from Authorization header
    Header format: Authorization: Bearer {token}
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="No authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = parts[1]
    return verify_token(token)


@router.post("/")
def create_product(product: ProductCreate, db: Session = Depends(get_db), admin=Depends(verify_admin_header)):
    """
    Create new product (admin only)
    Requires: Authorization: Bearer {token} header
    """
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
