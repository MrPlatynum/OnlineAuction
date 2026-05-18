"""Credential primitives: password hashing, JWT issuance and decode,
plus the FastAPI dependency that pulls the current user out of an
incoming Authorization header. New passwords use Argon2id; legacy
bcrypt hashes (from before the migration) are verified by ``passlib``
and re-hashed transparently on the next successful login.
"""

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

# Precomputed argon2id hash of a constant string used to keep /login
# timing stable when the supplied username doesn't exist. Without this
# the handler short-circuits before verify_password and "user-doesn't-
# exist" returns in microseconds while a real-but-wrong password takes
# ~50 ms — trivial to distinguish over the network. We verify against
# this hash instead so both branches spend the same CPU. Hash is
# evaluated lazily on first /login so the import-time cost stays zero.
_DUMMY_HASH: str | None = None


def _dummy_password_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = pwd_context.hash("timing-stability-dummy")
    return _DUMMY_HASH


def consume_password_verify_time(password: str) -> None:
    """Run the password verifier against a precomputed dummy hash and
    discard the result. Used by /login when the username doesn't exist
    so the response time matches the user-exists-but-wrong-password
    branch."""
    if len(password.encode("utf-8")) > PASSWORD_INPUT_LIMIT:
        return
    pwd_context.verify(password, _dummy_password_hash())


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
    # Legacy SHA256 verification is microsecond-fast; without this argon2
    # warmup on the dummy hash a /login against a legacy account would
    # return in µs while a modern-account login takes ~50 ms (argon2)
    # and an unknown-user login takes ~50 ms (consume_password_verify_time).
    # The timing split distinguishes "legacy", "modern", and "no such
    # user" branches over the wire.
    pwd_context.verify(plain_password, _dummy_password_hash())
    keys_to_check = [SECRET_KEY, *LEGACY_PASSWORD_KEYS]
    for key in keys_to_check:
        legacy_hash = hashlib.sha256((plain_password + key).encode()).hexdigest()
        if secrets.compare_digest(legacy_hash, hashed_password):
            return True
    return False


def create_access_token(claims: dict) -> str:
    """Sign a JWT carrying ``claims`` plus a fixed expiry. Callers pass
    in domain-specific fields (``user_id``, ``tv``, …); this function
    only adds ``exp`` so the expiry policy stays in one place."""
    payload = claims.copy()
    payload["exp"] = utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_user_access_token(user: "User") -> str:
    """Issue a token bound to the user's current ``token_version``.
    A future bump (e.g. /change-password) invalidates this token at
    get_current_user even though it hasn't expired yet."""
    return create_access_token({"user_id": user.id, "tv": user.token_version})


EMAIL_VERIFY_PURPOSE = "email_verify"
EMAIL_VERIFY_TOKEN_TTL_HOURS = 24

PASSWORD_RESET_PURPOSE = "password_reset"
PASSWORD_RESET_TOKEN_TTL_HOURS = 1
PASSWORD_RESET_THROTTLE_SECONDS = 60
# Минимальная длительность отклика /password-reset/request — гарантирует
# что unknown-email / throttled-existing / fresh-existing ветки невозможно
# различить по latency. 100 мс заметно больше любой из трёх веток без падинга.
PASSWORD_RESET_REQUEST_FLOOR_SECONDS = 0.1


def create_email_verify_token(user: "User") -> str:
    """Issue a stateless JWT carrying ``user.email`` as a claim. If the
    user later changes their email the token's claim no longer matches
    the row, so old verification links auto-invalidate without a
    server-side revocation list. Signed with ``AUCTION_SECRET_KEY``
    (same as auth tokens), but the ``purpose`` claim makes them
    distinguishable so an auth token can't be replayed at /verify-email
    and vice versa."""
    expire = utcnow() + timedelta(hours=EMAIL_VERIFY_TOKEN_TTL_HOURS)
    payload = {
        "user_id": user.id,
        "email": user.email,
        "purpose": EMAIL_VERIFY_PURPOSE,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_password_reset_token(user: "User") -> str:
    """Issue a stateless JWT carrying ``user.token_version`` so a
    successful reset (which bumps tv) auto-invalidates any other
    outstanding reset link for the same account. Signed with
    ``AUCTION_SECRET_KEY`` (same as auth tokens), distinguished by
    the ``purpose`` claim so an auth token can't be replayed at
    /password-reset/confirm and vice versa."""
    expire = utcnow() + timedelta(hours=PASSWORD_RESET_TOKEN_TTL_HOURS)
    payload = {
        "user_id": user.id,
        "tv": user.token_version,
        "purpose": PASSWORD_RESET_PURPOSE,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_password_reset_token(token: str) -> tuple[int, int]:
    """Returns ``(user_id, token_version)`` from a valid reset JWT.
    400 on expiry / bad signature / wrong purpose — verification
    failures are user-facing form errors, not session-auth failures
    (where 401 would be correct)."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=400, detail="Ссылка для сброса пароля истекла"
        ) from None
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=400, detail="Неверная ссылка для сброса пароля"
        ) from None
    if payload.get("purpose") != PASSWORD_RESET_PURPOSE:
        raise HTTPException(
            status_code=400, detail="Неверная ссылка для сброса пароля"
        )
    user_id = payload.get("user_id")
    tv = payload.get("tv")
    if not isinstance(user_id, int) or not isinstance(tv, int):
        raise HTTPException(
            status_code=400, detail="Неверная ссылка для сброса пароля"
        )
    return user_id, tv


def decode_email_verify_token(token: str) -> tuple[int, str]:
    """Returns ``(user_id, email)`` from a valid email-verify JWT.
    Raises ``HTTPException(400)`` on expiry, bad signature, or wrong
    purpose — verification failures are user-facing input errors, not
    auth failures, so they get 400 instead of decode_token's 401."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=400, detail="Ссылка для подтверждения email истекла"
        ) from None
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=400, detail="Неверная ссылка для подтверждения email"
        ) from None
    if payload.get("purpose") != EMAIL_VERIFY_PURPOSE:
        raise HTTPException(
            status_code=400, detail="Неверная ссылка для подтверждения email"
        )
    user_id = payload.get("user_id")
    email = payload.get("email")
    if not isinstance(user_id, int) or not isinstance(email, str):
        raise HTTPException(
            status_code=400, detail="Неверная ссылка для подтверждения email"
        )
    return user_id, email


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
    # Tokens issued before a password change carry the old token_version
    # and must be rejected. Old tokens missing the claim default to 0,
    # which matches the column default — so pre-migration tokens stay
    # valid for their original 24 h lifetime instead of every existing
    # user being kicked the moment this PR ships.
    token_version = payload.get("tv", 0)
    if token_version != user.token_version:
        raise HTTPException(status_code=401, detail="Token invalidated")
    return user


async def require_verified_user(
    current_user: "User" = Depends(get_current_user),
) -> "User":
    """Gate for write actions that require a confirmed email: place bid,
    buy now, create auction. Verified users pass through unchanged;
    unverified get a 403 with a hint pointing at the resend endpoint."""
    if not current_user.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Подтвердите email прежде чем выполнить это действие",
        )
    return current_user
