from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi import UploadFile, File
import cloudinary
import cloudinary.uploader
from sqlalchemy.orm import Session
from catalystsa.database import SessionLocal
from catalystsa.models import Product
from catalystsa.admin_auth import verify_admin_header  # Use existing function
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()

@router.post('/upload-image')
@router.post('/admin/upload-image')
def upload_image(
    file: UploadFile = File(...),
    admin_id: str = Depends(verify_admin_header)
):
    """
    Upload image to Cloudinary (admin only).
    Returns: { "url": "https://...", "public_id": "..." }
    """
    try:
        # Upload with folder and basic transformations
        upload_result = cloudinary.uploader.upload(
            file.file,
            folder="catalystsa",
            transformation=[{"width": 1200, "crop": "limit", "quality": "auto"}],
            resource_type="image"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    return {"url": upload_result.get('secure_url'), "public_id": upload_result.get('public_id')}



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def apply_markup(cost_price: int) -> int:
    """
    Business logic: Apply x1.6 markup and round to nearest R10

    Examples:
    - Cost R100.00 (10000 cents) → R160.00 (16000 cents)
    - Cost R125.00 (12500 cents) → R200.00 (20000 cents)
    - Cost R87.50 (8750 cents) → R140.00 (14000 cents)
    """
    marked_up = cost_price * 1.6
    # Round to nearest 1000 cents (= R10)
    rounded = round(marked_up / 1000) * 1000
    return int(rounded)


# Pydantic schemas
class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    cost_price: int  # in cents - what admin paid
    image_url: Optional[str] = None
    stock: int = 0
    active: bool = True
    weight_kg: Optional[float] = 0.5  # Default: 0.5kg (small item)
    size_category: Optional[str] = "small"  # small/medium/large/bulky


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cost_price: Optional[int] = None  # updating cost recalculates selling price
    image_url: Optional[str] = None
    stock: Optional[int] = None
    active: Optional[bool] = None
    weight_kg: Optional[float] = None
    size_category: Optional[str] = None


class ProductResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    price: int
    image_url: Optional[str]
    stock: int
    active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# Admin Product Management Endpoints
@router.get("/admin/products")
def list_products_admin(
    db: Session = Depends(get_db),
    admin_id: str = Depends(verify_admin_header),
    include_inactive: bool = False
):
    """
    List all products (admin view)
    Shows both cost_price (what you paid) and selling price (with markup)

    Query params:
    - include_inactive: Show inactive products (default: false)
    """
    query = db.query(Product)

    if not include_inactive:
        query = query.filter(Product.active == True)

    products = query.order_by(Product.created_at.desc()).all()

    return {
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "cost_price": p.cost_price,
                "cost_display": f"R{p.cost_price / 100:.2f}",
                "price": p.price,
                "price_display": f"R{p.price / 100:.2f}",
                "markup_percent": ((p.price - p.cost_price) / p.cost_price * 100) if p.cost_price > 0 else 0,
                "image_url": p.image_url,
                "stock": p.stock,
                "active": p.active,
                "weight_kg": p.weight_kg or 0.5,
                "size_category": p.size_category or "small",
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            }
            for p in products
        ],
        "total": len(products)
    }


@router.post("/admin/products")
def create_product(
    product: ProductCreate,
    db: Session = Depends(get_db),
    admin_id: str = Depends(verify_admin_header)
):
    """
    Create new product (admin only)

    Admin enters cost_price, system auto-calculates selling price with x1.6 markup

    Request body:
    {
        "name": "Product Name",
        "description": "Optional description",
        "cost_price": 10000,  // R100.00 in cents
        "image_url": "https://example.com/image.jpg",
        "stock": 10,
        "active": true
    }

    System automatically calculates:
    - price = cost_price * 1.6, rounded to nearest R10
    """
    # Validate cost price
    if product.cost_price < 0:
        raise HTTPException(status_code=400, detail="Cost price cannot be negative")

    if product.stock < 0:
        raise HTTPException(status_code=400, detail="Stock cannot be negative")

    # Apply markup: x1.6 rounded to nearest R10
    selling_price = apply_markup(product.cost_price)

    # Create product
    new_product = Product(
        name=product.name,
        description=product.description,
        cost_price=product.cost_price,
        price=selling_price,  # Auto-calculated
        image_url=product.image_url,
        stock=product.stock,
        active=product.active,
        weight_kg=product.weight_kg or 0.5,
        size_category=product.size_category or "small"
    )

    db.add(new_product)
    db.commit()
    db.refresh(new_product)

    return {
        "message": "Product created successfully",
        "product": {
            "id": new_product.id,
            "name": new_product.name,
            "description": new_product.description,
            "cost_price": new_product.cost_price,
            "cost_display": f"R{new_product.cost_price / 100:.2f}",
            "price": new_product.price,
            "price_display": f"R{new_product.price / 100:.2f}",
            "markup_applied": f"{((new_product.price - new_product.cost_price) / new_product.cost_price * 100):.1f}%",
            "image_url": new_product.image_url,
            "stock": new_product.stock,
            "active": new_product.active,
            "created_at": new_product.created_at.isoformat() if new_product.created_at else None,
        }
    }


@router.put("/admin/products/{product_id}")
def update_product(
    product_id: int,
    product: ProductUpdate,
    db: Session = Depends(get_db),
    admin_id: str = Depends(verify_admin_header)
):
    """
    Update existing product (admin only)

    If cost_price is updated, selling price is automatically recalculated with x1.6 markup
    """
    existing_product = db.query(Product).filter(Product.id == product_id).first()

    if not existing_product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Update fields if provided
    if product.name is not None:
        existing_product.name = product.name
    if product.description is not None:
        existing_product.description = product.description
    if product.cost_price is not None:
        if product.cost_price < 0:
            raise HTTPException(status_code=400, detail="Cost price cannot be negative")
        existing_product.cost_price = product.cost_price
        # Recalculate selling price when cost changes
        existing_product.price = apply_markup(product.cost_price)
    if product.image_url is not None:
        existing_product.image_url = product.image_url
    if product.stock is not None:
        if product.stock < 0:
            raise HTTPException(status_code=400, detail="Stock cannot be negative")
        existing_product.stock = product.stock
    if product.active is not None:
        existing_product.active = product.active
    if product.weight_kg is not None:
        if product.weight_kg < 0:
            raise HTTPException(status_code=400, detail="Weight cannot be negative")
        existing_product.weight_kg = product.weight_kg
    if product.size_category is not None:
        if product.size_category not in ["small", "medium", "large", "bulky"]:
            raise HTTPException(status_code=400, detail="Invalid size category")
        existing_product.size_category = product.size_category

    existing_product.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(existing_product)

    return {
        "message": "Product updated successfully",
        "product": {
            "id": existing_product.id,
            "name": existing_product.name,
            "description": existing_product.description,
            "cost_price": existing_product.cost_price,
            "cost_display": f"R{existing_product.cost_price / 100:.2f}",
            "price": existing_product.price,
            "price_display": f"R{existing_product.price / 100:.2f}",
            "markup_applied": f"{((existing_product.price - existing_product.cost_price) / existing_product.cost_price * 100):.1f}%",
            "image_url": existing_product.image_url,
            "stock": existing_product.stock,
            "active": existing_product.active,
            "updated_at": existing_product.updated_at.isoformat() if existing_product.updated_at else None,
        }
    }


@router.delete("/admin/products/{product_id}")
def delete_product(
    product_id: int,
    hard_delete: bool = False,
    db: Session = Depends(get_db),
    admin_id: str = Depends(verify_admin_header)
):
    """
    Delete product (admin only)

    Query params:
    - hard_delete: Permanently delete from database (default: false = soft delete)

    Default behavior: Soft delete (set active=false) to preserve order history
    """
    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if hard_delete:
        # Hard delete - remove from database
        db.delete(product)
        db.commit()
        return {"message": "Product permanently deleted", "product_id": product_id}
    else:
        # Soft delete - just mark inactive
        product.active = False
        product.updated_at = datetime.utcnow()
        db.commit()
        return {"message": "Product deactivated", "product_id": product_id}


@router.get("/admin/products/{product_id}")
def get_product_admin(
    product_id: int,
    db: Session = Depends(get_db),
    admin_id: str = Depends(verify_admin_header)
):
    """
    Get single product details (admin view)
    """
    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return {
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "cost_price": product.cost_price,
        "cost_display": f"R{product.cost_price / 100:.2f}",
        "price": product.price,
        "price_display": f"R{product.price / 100:.2f}",
        "markup_percent": f"{((product.price - product.cost_price) / product.cost_price * 100):.1f}%",
        "image_url": product.image_url,
        "stock": product.stock,
        "active": product.active,
        "created_at": product.created_at.isoformat() if product.created_at else None,
        "updated_at": product.updated_at.isoformat() if product.updated_at else None,
    }


# Public Product Endpoints (no auth required)
@router.get("/products")
def list_products_public(
    db: Session = Depends(get_db),
    limit: int = 100
):
    """
    Public product catalog
    Returns only active products with stock > 0
    """
    products = db.query(Product).filter(
        Product.active == True,
        Product.stock > 0
    ).order_by(Product.name).limit(limit).all()

    return {
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price": p.price,
                "price_display": f"R{p.price / 100:.2f}",
                "image_url": p.image_url,
                "stock": p.stock,
                "weight_kg": p.weight_kg or 0.5,
                "size_category": p.size_category or "small",
            }
            for p in products
        ]
    }


@router.get("/products/{product_id}")
def get_product_public(
    product_id: int,
    db: Session = Depends(get_db)
):
    """
    Get single product (public view)
    Only returns if active and in stock
    """
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.active == True,
        Product.stock > 0
    ).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found or unavailable")

    return {
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "price": product.price,
        "price_display": f"R{product.price / 100:.2f}",
        "image_url": product.image_url,
        "stock": product.stock,
    }
