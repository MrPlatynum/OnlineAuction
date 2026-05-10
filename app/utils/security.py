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

# argon2id is the primary scheme for new hashes; bcrypt stays in the
# verifier chain so existing accounts still log in. Tunables follow the
# OWASP cheat sheet (2024) for argon2id: m = 19 MiB, t = 2, p = 1.
# ``deprecated="auto"`` flags non-primary schemes (i.e. bcrypt) so
# ``needs_rehash`` returns True on a successful login and the row gets
# rotated to argon2id transparently.
pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated="auto",
    argon2__time_cost=2,
    argon2__memory_cost=19456,
    argon2__parallelism=1,
)
security = HTTPBearer()

# Defensive cap on raw password input. Pydantic enforces max_length=128
# on register / change-password, but UserLogin.password is unbounded —
# without this cap a multi-MB password input would let an attacker
# spend our CPU on argon2/bcrypt verification.
PASSWORD_INPUT_LIMIT = 1024


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > PASSWORD_INPUT_LIMIT:
        raise ValueError("Password input exceeds limit")
    return pwd_context.hash(password)


def is_modern_password_hash(hashed_password: str) -> bool:
    return pwd_context.identify(hashed_password) is not None


def needs_rehash(hashed_password: str) -> bool:
    """True if the stored hash should be rotated on the next successful
    login — either it's the legacy SHA256+key format from before passlib
    was wired up, or it's a deprecated scheme (bcrypt now that argon2id
    is primary)."""
    if not is_modern_password_hash(hashed_password):
        return True
    return pwd_context.needs_update(hashed_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # An over-cap input can never be a valid credential — we never
    # accept it for hashing — so reject without spending CPU.
    if len(plain_password.encode("utf-8")) > PASSWORD_INPUT_LIMIT:
        return False
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
        raise HTTPException(status_code=401, detail="Token expired") from None
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token") from None


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
