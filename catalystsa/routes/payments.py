from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import requests
import os

router = APIRouter()

YOCO_SECRET_KEY = os.getenv("YOCO_SECRET_KEY")


class CheckoutRequest(BaseModel):
    amount: int  # in rands
    currency: str = "ZAR"
    successUrl: str
    cancelUrl: str


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

    data = {
        "amount": payload.amount * 100,  # Convert rands to cents
        "currency": payload.currency,
        "successUrl": payload.successUrl,
        "cancelUrl": payload.cancelUrl,
        "metadata": {
            "source": "catalystsa-store"
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
