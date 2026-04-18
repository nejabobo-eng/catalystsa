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

    # Base64 encode to make it safe for HTTP headers
    import base64
    token_raw = f"{payload_json}:{signature}"
    token_b64 = base64.b64encode(token_raw.encode()).decode('ascii')
    return token_b64


def verify_token(token: str) -> dict:
    try:
        # Decode from base64
        import base64
        token_raw = base64.b64decode(token).decode('utf-8')

        payload_json, signature = token_raw.rsplit(":", 1)
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


def verify_admin_header(authorization: str = None) -> str:
    """
    FastAPI dependency for admin routes
    Extracts and verifies JWT token from Authorization header

    Usage:
        @router.get("/admin/endpoint")
        def endpoint(admin_id: str = Depends(verify_admin_header)):
            # admin_id is returned if token is valid
    """
    from fastapi import Header

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    try:
        # Extract token from "Bearer <token>" format
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization format")

        token = parts[1]
        payload = verify_token(token)
        return payload.get("admin_id", "admin")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")
