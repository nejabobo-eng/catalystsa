from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import requests
import os

router = APIRouter()

YOCO_SECRET_KEY = os.getenv("YOCO_SECRET_KEY")


class CheckoutRequest(BaseModel):
    amount: float  # in rands (subtotal before delivery)
    currency: str = "ZAR"
    successUrl: str
    cancelUrl: str
    email: str = None  # customer email
    name: str = None  # customer name
    phone: str = None  # customer phone
    address: str = None  # street address
    city: str = None  # city
    postal_code: str = None  # postal code
    items: list = None  # cart items [{name, quantity, price}, ...]
    delivery_fee: float = 0  # in rands


@router.post("/checkout")
def create_checkout(payload: CheckoutRequest):
    if not YOCO_SECRET_KEY:
        print("ERROR: YOCO_SECRET_KEY not configured")
        raise HTTPException(status_code=500, detail="Yoco key not configured")

    url = "https://payments.yoco.com/api/checkouts"

    headers = {
        "Authorization": f"Bearer {YOCO_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    # Validate amount
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    # Convert rands to cents (round to nearest cent)
    amount_cents = int(round(payload.amount * 100))
    delivery_fee_cents = int(round(payload.delivery_fee * 100)) if payload.delivery_fee else 0
    total_cents = amount_cents + delivery_fee_cents

    data = {
        "amount": total_cents,
        "currency": payload.currency,
        "successUrl": payload.successUrl,
        "cancelUrl": payload.cancelUrl,
        "webhookUrl": "https://catalystsa.onrender.com/yoco/webhook",  # ⚡ CRITICAL
        "metadata": {
            "source": "catalystsa-store",
            "customer_email": payload.email or "",
            "customer_name": payload.name or "",
            "phone": payload.phone or "",
            "address": payload.address or "",
            "city": payload.city or "",
            "postal_code": payload.postal_code or "",
            "delivery_fee": payload.delivery_fee or 0,
            "items": str(payload.items) if payload.items else ""
        }
    }

    print(f"=== YOCO REQUEST ===")
    print(f"URL: {url}")
    print(f"Headers: Authorization Bearer {YOCO_SECRET_KEY[:10]}...")
    print(f"Data: {data}")

    try:
        response = requests.post(url, json=data, headers=headers)
        
        print(f"=== YOCO RESPONSE ===")
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.text}")
        
        if response.status_code != 200 and response.status_code != 201:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Yoco API error: {response.text}"
            )
        
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"=== REQUEST EXCEPTION ===")
        print(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Yoco API error: {str(e)}")
