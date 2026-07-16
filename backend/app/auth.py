from datetime import datetime, timedelta, timezone
import os
import jwt
from fastapi import Header, HTTPException
from pydantic import BaseModel

ACCESS_CODE = os.getenv("PERSONAL_ACCESS_CODE", "change-me")
TOKEN_SECRET = os.getenv("TOKEN_SECRET", "development-secret-change-me")

class LoginRequest(BaseModel):
    access_code: str

def create_token() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": "personal-owner", "iat": now, "exp": now + timedelta(hours=72)},
        TOKEN_SECRET,
        algorithm="HS256",
    )

def verify_access_code(access_code: str) -> bool:
    return bool(access_code) and access_code == ACCESS_CODE

def require_owner(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing access token.")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return jwt.decode(token, TOKEN_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Access token expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid access token.") from exc
