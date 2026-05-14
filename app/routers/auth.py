from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas import (
    ChangePasswordRequest,
    UserCreate,
    UserLogin,
    UserResponse,
)
from app.services.notifications import (
    send_password_changed_email,
    send_password_reset_email,
    send_verification_email,
)
from app.services.websocket_manager import manager
from app.utils.rate_limit import limiter
from app.utils.security import (
    PASSWORD_RESET_THROTTLE_SECONDS,
    consume_password_verify_time,
    create_user_access_token,
    decode_email_verify_token,
    decode_password_reset_token,
    get_current_user,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.utils.time import utcnow

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/register", response_model=dict)
@limiter.limit("5/minute")
async def register(request: Request, user: UserCreate, db: AsyncSession = Depends(get_db)):
    # Single generic message for both collisions — separate "username taken"
    # vs "email taken" replies let an attacker enumerate registered usernames
    # and emails by probing /register.
    username_taken = (
        await db.execute(select(User.id).where(User.username == user.username))
    ).scalar_one_or_none()
    email_taken = (
        await db.execute(select(User.id).where(User.email == user.email))
    ).scalar_one_or_none()
    if username_taken or email_taken:
        raise HTTPException(
            status_code=400,
            detail="Пользователь с таким username или email уже существует",
        )

    db_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hash_password(user.password),
    )
    db.add(db_user)
    try:
        await db.commit()
    except IntegrityError:
        # Two concurrent /register calls can both pass the pre-check
        # (no row exists yet) and race to insert the same username or
        # email — Postgres unique-constraint enforcement makes the loser
        # see IntegrityError. Return the same generic 400 as the
        # pre-check so the response is timing- and message-stable.
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Пользователь с таким username или email уже существует",
        ) from None
    await db.refresh(db_user)

    # Kick off the verification email after the row is persistent so a
    # later rollback can't leave us mailing a non-existent user; the
    # send itself is fire-and-forget so /register doesn't block on SMTP.
    send_verification_email(db_user)

    token = create_user_access_token(db_user)
    return {"token": token, "user": UserResponse.model_validate(db_user)}


class VerifyEmailRequest(BaseModel):
    token: str


@router.post("/verify-email")
@limiter.limit("20/hour")
async def verify_email(
    request: Request,
    data: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Public — landing page POSTs the token from the email link here.
    Idempotent: a click on an already-consumed link still returns 200 so
    a double-fire (user clicking the link twice, or a link prefetcher
    racing the user) doesn't look like an error."""
    user_id, claimed_email = decode_email_verify_token(data.token)
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        # Don't distinguish "user gone" from "bad token" — the latter
        # branch is more common (expired / typo), and both warrant the
        # same 400 from the user's perspective.
        raise HTTPException(
            status_code=400, detail="Неверная ссылка для подтверждения email"
        )
    # Reject tokens issued before an email change. Without this an old
    # link would still verify the *new* email address.
    if user.email != claimed_email:
        raise HTTPException(
            status_code=400, detail="Неверная ссылка для подтверждения email"
        )
    if not user.email_verified:
        user.email_verified = True
        await db.commit()
    return {"message": "Email подтверждён"}


@router.post("/verify-email/resend")
@limiter.limit("3/hour")
async def resend_verification_email(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Auth-gated so an attacker can't burn another user's daily inbox
    by triggering resends against their email. Already-verified users
    get a 400 instead of silently re-mailing them."""
    if current_user.email_verified:
        raise HTTPException(
            status_code=400, detail="Email уже подтверждён"
        )
    send_verification_email(current_user)
    return {"message": "Письмо отправлено"}


@router.post("/login", response_model=dict)
@limiter.limit("10/minute")
async def login(request: Request, user: UserLogin, db: AsyncSession = Depends(get_db)):
    db_user = (
        await db.execute(select(User).where(User.username == user.username))
    ).scalar_one_or_none()
    if db_user is None:
        # Burn the same CPU a real verify would so we don't leak
        # "username exists" via response timing.
        consume_password_verify_time(user.password)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    if not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    if needs_rehash(db_user.hashed_password):
        db_user.hashed_password = hash_password(user.password)
        await db.commit()
        await db.refresh(db_user)

    token = create_user_access_token(db_user)
    return {"token": token, "user": UserResponse.model_validate(db_user)}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/change-password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
    current_user.hashed_password = hash_password(data.new_password)
    # Bump token_version so every JWT issued before this point fails
    # get_current_user. The caller still has *this* request's token in
    # their browser — return a fresh one so they don't get kicked out
    # of the very session they used to change the password.
    current_user.token_version = (current_user.token_version or 0) + 1
    await db.commit()

    # /ws/notifications verifies token_version only at handshake; without
    # closing existing sockets, a leaked-token connection keeps receiving
    # pushes long after the legitimate user rotates their credentials.
    stale_sockets = list(manager.user_connections.get(current_user.id, []))
    for ws in stale_sockets:
        try:
            await ws.close(code=1008)
        except Exception:
            pass
        manager.disconnect_user(ws, current_user.id)

    new_token = create_user_access_token(current_user)
    return {"message": "Пароль успешно изменён", "token": new_token}


class PasswordResetRequestBody(BaseModel):
    email: EmailStr


class PasswordResetConfirmBody(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


# Generic responses kept identical regardless of whether the address
# corresponds to a registered account — without this, response timing
# or text could be used to enumerate users (the same protection
# /register has had since #33).
_GENERIC_REQUEST_RESPONSE = {
    "message": (
        "Если этот email зарегистрирован, мы отправили на него письмо "
        "со ссылкой для сброса пароля. Ссылка действует 1 час."
    )
}


@router.post("/password-reset/request")
@limiter.limit("3/hour")
async def password_reset_request(
    request: Request,
    data: PasswordResetRequestBody,
    db: AsyncSession = Depends(get_db),
):
    """Public — accepts an email and *if it exists* mails a reset link.
    Always returns 200 with a generic message so the response shape
    can't be used to probe which addresses are registered."""
    user = (
        await db.execute(select(User).where(User.email == data.email))
    ).scalar_one_or_none()
    if user is not None:
        # Per-email floor on top of the per-IP slowapi limit. Without
        # this, an attacker rotating IPs could trickle requests below
        # the IP threshold and flood the target's inbox with reset
        # mail.
        now = utcnow()
        last = user.password_reset_sent_at
        throttle = timedelta(seconds=PASSWORD_RESET_THROTTLE_SECONDS)
        if last is None or (now - last) >= throttle:
            user.password_reset_sent_at = now
            await db.commit()
            await db.refresh(user)
            send_password_reset_email(user)
    return _GENERIC_REQUEST_RESPONSE


@router.post("/password-reset/confirm")
@limiter.limit("10/hour")
async def password_reset_confirm(
    request: Request,
    data: PasswordResetConfirmBody,
    db: AsyncSession = Depends(get_db),
):
    """Public — accepts a token and the new password. Validates the
    token's ``tv`` against the user's current ``token_version`` so a
    second click on the same link (after a successful first reset)
    fails: the first confirm bumped tv, the second's claim no longer
    matches."""
    user_id, claimed_tv = decode_password_reset_token(data.token)
    # Row-lock the user so two concurrent confirms with the same token
    # serialise. Without this, both reads see the original token_version,
    # both pass the check, both bump tv to N+1, both commit — and the
    # link is two-shot instead of one-shot.
    user = (
        await db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if user is None or claimed_tv != user.token_version:
        # Don't distinguish "user gone" from "token superseded" — both
        # branches are equally a "this link doesn't work anymore" 400
        # from the user's perspective.
        raise HTTPException(
            status_code=400, detail="Неверная ссылка для сброса пароля"
        )

    user.hashed_password = hash_password(data.new_password)
    # Bumping tv kills every other JWT this user holds — outstanding
    # auth sessions, other in-flight reset links, all gone. The fresh
    # password forces a re-login on /login (we don't auto-issue a
    # token here: the user typed the new password into the reset
    # form, they should type it again at /login as a confirmation).
    user.token_version = (user.token_version or 0) + 1
    await db.commit()

    # Same WS cleanup as /change-password: any socket authenticated
    # with the now-invalid tv stays connected without it. Close
    # them so the next push doesn't reach the stale session.
    stale_sockets = list(manager.user_connections.get(user.id, []))
    for ws in stale_sockets:
        try:
            await ws.close(code=1008)
        except Exception:
            pass
        manager.disconnect_user(ws, user.id)

    send_password_changed_email(user)
    return {"message": "Пароль успешно сброшен"}
