from fastapi import APIRouter, Depends, HTTPException, Request
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
from app.utils.rate_limit import limiter
from app.utils.security import (
    consume_password_verify_time,
    create_user_access_token,
    get_current_user,
    hash_password,
    needs_rehash,
    verify_password,
)

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

    token = create_user_access_token(db_user)
    return {"token": token, "user": UserResponse.model_validate(db_user)}


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
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

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
    new_token = create_user_access_token(current_user)
    return {"message": "Пароль успешно изменён", "token": new_token}
