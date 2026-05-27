"""Identity and credential flows.

Covers registration, login, the current-user probe (``/me``), the
post-register email-verification handshake, the password-change and
password-reset flows, plus the token-version bump that invalidates
already-issued JWTs after a credential rotation.
"""

import asyncio
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from sqlalchemy.exc import IntegrityError
from app.schemas import (
    ChangePasswordRequest,
    PasswordResetConfirmBody,
    PasswordResetRequestBody,
    UserCreate,
    UserLogin,
    UserResponse,
    VerifyEmailRequest,
)
from app.services.notifications import (
    send_password_changed_email,
    send_password_reset_email,
    send_verification_email,
)
from app.services.websocket_manager import manager
from app.utils.rate_limit import limiter
from app.utils.security import (
    PASSWORD_RESET_REQUEST_FLOOR_SECONDS,
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

# Single generic message for both pre-check and IntegrityError branches in
# /register - separate "username taken" vs "email taken" wording would let
# an attacker enumerate registered usernames and emails by probing.
_USER_EXISTS_DETAIL = "Пользователь с таким username или email уже существует"


async def _invalidate_user_sessions(user: User) -> None:
    """Bump ``user.token_version`` and close every open notification WS
    for this user. Used after credential-rotating events
    (/change-password, /password-reset/confirm) so leaked tokens and
    in-flight sockets both stop working. Caller is responsible for
    committing the tv bump."""
    user.token_version = (user.token_version or 0) + 1
    for ws in list(manager.user_connections.get(user.id, [])):
        try:
            await ws.close(code=1008)
        except Exception:
            pass
        manager.disconnect_user(ws, user.id)


@router.post("/register", response_model=dict)
@limiter.limit("5/minute")
async def register(request: Request, user: UserCreate, db: AsyncSession = Depends(get_db)):
    # Single generic message for both collisions - separate "username taken"
    # vs "email taken" replies let an attacker enumerate registered usernames
    # and emails by probing /register.
    username_taken = (
        await db.execute(select(User.id).where(User.username == user.username))
    ).scalar_one_or_none()
    email_taken = (
        await db.execute(select(User.id).where(User.email == user.email))
    ).scalar_one_or_none()
    if username_taken or email_taken:
        raise HTTPException(status_code=400, detail=_USER_EXISTS_DETAIL)

    db_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hash_password(user.password),
    )
    db.add(db_user)
    # Flush populates db_user.id + token_version so create_email_verify_token
    # has the fully-formed user row to sign, but no transaction has committed
    # yet - the verify-email outbox row enrols in the same session and
    # commits atomically with the user row below. A race-loser unique-
    # constraint violation rolls back BOTH rows together, so we never mail a
    # verification link to a user that doesn't exist (and we never persist a
    # user without their verification mail enqueued). The unique violation
    # may surface on either the flush (when the INSERT statement reaches PG)
    # or the commit (deferred constraints), so the catch wraps both.
    try:
        await db.flush()
        await send_verification_email(db_user, db=db)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail=_USER_EXISTS_DETAIL) from None
    await db.refresh(db_user)

    token = create_user_access_token(db_user)
    return {"token": token, "user": UserResponse.model_validate(db_user)}


@router.post("/verify-email")
@limiter.limit("20/hour")
async def verify_email(
    request: Request,
    data: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Public - landing page POSTs the token from the email link here.
    Idempotent: a click on an already-consumed link still returns 200 so
    a double-fire (user clicking the link twice, or a link prefetcher
    racing the user) doesn't look like an error."""
    user_id, claimed_email = decode_email_verify_token(data.token)
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        # Don't distinguish "user gone" from "bad token" - the latter
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
    db: AsyncSession = Depends(get_db),
):
    """Auth-gated so an attacker can't burn another user's daily inbox
    by triggering resends against their email. Already-verified users
    get a 400 instead of silently re-mailing them."""
    if current_user.email_verified:
        raise HTTPException(
            status_code=400, detail="Email уже подтверждён"
        )
    # Re-send verify-email: the user already exists, so the outbox row
    # need not be atomic with anything - reuse the session for the
    # INSERT (no separate connection acquisition) and let the commit
    # land on its own.
    await send_verification_email(current_user, db=db)
    await db.commit()
    return {"message": "Письмо отправлено"}


_LOGIN_LOCKOUT_TIERS: tuple[tuple[int, timedelta], ...] = (
    (20, timedelta(hours=1)),
    (15, timedelta(minutes=15)),
    (10, timedelta(minutes=5)),
    (5,  timedelta(minutes=1)),
)


def _lockout_for_failures(count: int) -> timedelta | None:
    """Per-account credential-stuffing defence. The slowapi limiter caps
    /login at 10/min per IP, but a botnet can amortise that across a /16
    and still grind one specific username. Stack an exponential per-
    *account* lockout on top: 5 failures → 1 min, 10 → 5 min, 15 → 15
    min, 20+ → 1 hour. Successful login resets the count."""
    for threshold, window in _LOGIN_LOCKOUT_TIERS:
        if count >= threshold:
            return window
    return None


@router.post("/login", response_model=dict)
@limiter.limit("10/minute")
async def login(request: Request, user: UserLogin, db: AsyncSession = Depends(get_db)):
    db_user = (
        await db.execute(
            select(User)
            .where(User.username == user.username)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if db_user is None:
        # Burn the same CPU a real verify would so we don't leak
        # "username exists" via response timing.
        consume_password_verify_time(user.password)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    now = utcnow()
    if db_user.locked_until and db_user.locked_until > now:
        # Don't reveal exactly when the lock expires - that gives an
        # attacker a precise retry signal. Same generic 401 the
        # bad-password path returns so the locked-state isn't a
        # username-enumeration oracle either.
        consume_password_verify_time(user.password)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    if not verify_password(user.password, db_user.hashed_password):
        db_user.failed_login_count = (db_user.failed_login_count or 0) + 1
        window = _lockout_for_failures(db_user.failed_login_count)
        if window is not None:
            db_user.locked_until = now + window
        await db.commit()
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    # Successful login - clear the failure streak so the next bad
    # attempt starts from zero again.
    if db_user.failed_login_count or db_user.locked_until:
        db_user.failed_login_count = 0
        db_user.locked_until = None

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
    # Take a row-level lock on the user before mutating credentials. A
    # concurrent /ws/notifications handshake reads the user row to
    # validate the JWT's tv claim against the persisted token_version;
    # without this lock the handshake's read can land between our
    # pre-bump read (via get_current_user) and the commit below, so
    # the new socket sees the old tv, accepts a stolen JWT, and
    # survives the credential rotation. ``populate_existing`` refreshes
    # the existing ORM copy so subsequent attribute writes target the
    # locked row.
    locked = (
        await db.execute(
            select(User)
            .where(User.id == current_user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    locked.hashed_password = hash_password(data.new_password)
    # Bump tv + close in-flight WS in one step. The caller still has
    # *this* request's token in their browser - return a fresh one so
    # they don't get kicked out of the very session they used to
    # change the password.
    await _invalidate_user_sessions(locked)
    await db.commit()

    new_token = create_user_access_token(locked)
    return {"message": "Пароль успешно изменён", "token": new_token}


# Generic responses kept identical regardless of whether the address
# corresponds to a registered account - without this, response timing
# or text could be used to enumerate users (same anti-enumeration
# guarantee /register makes).
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
    """Public - accepts an email and *if it exists* mails a reset link.
    Always returns 200 with a generic message so the response shape
    can't be used to probe which addresses are registered."""
    # Without time padding the three branches are distinguishable via
    # response latency: unknown email (SELECT only, ~5ms) / throttled
    # existing (SELECT only, ~5ms) / fresh existing (SELECT + UPDATE +
    # COMMIT + REFRESH + enqueue, ~30-50ms). Floor every response to
    # the same minimum so the gap drops below network noise.
    deadline = asyncio.get_running_loop().time() + PASSWORD_RESET_REQUEST_FLOOR_SECONDS
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
            # The reset-link outbox row commits together with the
            # password_reset_sent_at bump, so a transient DB blip can't
            # land the throttle update without the link being enqueued
            # (or vice versa).
            await send_password_reset_email(user, db=db)
            await db.commit()
            await db.refresh(user)
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining > 0:
        await asyncio.sleep(remaining)
    return _GENERIC_REQUEST_RESPONSE


@router.post("/password-reset/confirm")
@limiter.limit("10/hour")
async def password_reset_confirm(
    request: Request,
    data: PasswordResetConfirmBody,
    db: AsyncSession = Depends(get_db),
):
    """Public - accepts a token and the new password. Validates the
    token's ``tv`` against the user's current ``token_version`` so a
    second click on the same link (after a successful first reset)
    fails: the first confirm bumped tv, the second's claim no longer
    matches."""
    user_id, claimed_tv = decode_password_reset_token(data.token)
    # Row-lock the user so two concurrent confirms with the same token
    # serialise. Without this, both reads see the original token_version,
    # both pass the check, both bump tv to N+1, both commit - and the
    # link is two-shot instead of one-shot.
    user = (
        await db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if user is None or claimed_tv != user.token_version:
        # Don't distinguish "user gone" from "token superseded" - both
        # branches are equally a "this link doesn't work anymore" 400
        # from the user's perspective.
        raise HTTPException(
            status_code=400, detail="Неверная ссылка для сброса пароля"
        )

    user.hashed_password = hash_password(data.new_password)
    # Bumping tv kills every other JWT this user holds - outstanding
    # auth sessions, other in-flight reset links, all gone. The fresh
    # password forces a re-login on /login (we don't auto-issue a
    # token here: the user typed the new password into the reset
    # form, they should type it again at /login as a confirmation).
    await _invalidate_user_sessions(user)
    # Password change + tv bump + "your password was changed" outbox
    # row all commit together. A DB failure on the commit rolls back
    # the password change AND drops the security-notice mail, which is
    # the right pair: if the password didn't actually rotate we don't
    # want to alarm the user, and if it did we never want them to miss
    # the audit trail.
    await send_password_changed_email(user, db=db)
    await db.commit()
    return {"message": "Пароль успешно сброшен"}
