from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
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
    create_access_token,
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
    await db.commit()
    await db.refresh(db_user)

    token = create_access_token({"user_id": db_user.id})
    return {"token": token, "user": UserResponse.model_validate(db_user)}


@router.post("/login", response_model=dict)
@limiter.limit("10/minute")
async def login(request: Request, user: UserLogin, db: AsyncSession = Depends(get_db)):
    db_user = (
        await db.execute(select(User).where(User.username == user.username))
    ).scalar_one_or_none()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if needs_rehash(db_user.hashed_password):
        db_user.hashed_password = hash_password(user.password)
        await db.commit()
        await db.refresh(db_user)

    token = create_access_token({"user_id": db_user.id})
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
    await db.commit()
    return {"message": "Пароль успешно изменён"}
