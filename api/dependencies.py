import os
from typing import Optional

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from api.models.database import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def optional_api_key(x_api_key: Optional[str] = Header(None)):
    """Allow unauthenticated access for public endpoints; validate key if provided."""
    expected = os.getenv("API_KEY", "")
    if x_api_key and expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
