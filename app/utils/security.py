import hashlib
import secrets
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    ACCESS_TOKEN_EXPIRE_HOURS,
    ALGORITHM,
    LEGACY_PASSWORD_KEYS,
    SECRET_KEY,
)
from app.database import get_db
from app.models import User
from app.utils.time import utcnow

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def is_modern_password_hash(hashed_password: str) -> bool:
    return pwd_context.identify(hashed_password) is not None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if is_modern_password_hash(hashed_password):
        return pwd_context.verify(plain_password, hashed_password)
    keys_to_check = [SECRET_KEY, *LEGACY_PASSWORD_KEYS]
    for key in keys_to_check:
        legacy_hash = hashlib.sha256((plain_password + key).encode()).hexdigest()
        if secrets.compare_digest(legacy_hash, hashed_password):
            return True
    return False


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    token = credentials.credentials
    payload = decode_token(token)
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
