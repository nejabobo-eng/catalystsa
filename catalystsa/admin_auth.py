import os
import hmac
import hashlib
import json
from datetime import datetime, timedelta
from fastapi import HTTPException

SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "your-secret-key-change-this")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
TOKEN_EXPIRY_HOURS = 24


def create_token(admin_id: str = "admin") -> str:
    payload = {
        "admin_id": admin_id,
        "iat": datetime.utcnow().isoformat(),
        "exp": (datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)).isoformat()
    }
    
    payload_json = json.dumps(payload, sort_keys=True)
    signature = hmac.new(
        SECRET_KEY.encode(),
        payload_json.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return f"{payload_json}:{signature}"


def verify_token(token: str) -> dict:
    try:
        payload_json, signature = token.rsplit(":", 1)
        expected_signature = hmac.new(
            SECRET_KEY.encode(),
            payload_json.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_signature):
            raise HTTPException(status_code=401, detail="Invalid token")
        
        payload = json.loads(payload_json)
        exp_time = datetime.fromisoformat(payload["exp"])
        if datetime.utcnow() > exp_time:
            raise HTTPException(status_code=401, detail="Token expired")
        
        return payload
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Invalid token format")
