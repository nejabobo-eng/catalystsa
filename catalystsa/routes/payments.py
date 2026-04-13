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
        "cancelUrl": payload.cancelUrl
    }

    try:
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Yoco API error: {str(e)}")
