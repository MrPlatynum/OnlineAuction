from fastapi import APIRouter, Depends, HTTPException
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
from app.utils.security import (
    create_access_token,
    get_current_user,
    hash_password,
    is_modern_password_hash,
    verify_password,
)

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/register", response_model=dict)
async def register(user: UserCreate, db: AsyncSession = Depends(get_db)):
    if (await db.execute(select(User).where(User.username == user.username))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")
    if (await db.execute(select(User).where(User.email == user.email))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already exists")

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
async def login(user: UserLogin, db: AsyncSession = Depends(get_db)):
    db_user = (
        await db.execute(select(User).where(User.username == user.username))
    ).scalar_one_or_none()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not is_modern_password_hash(db_user.hashed_password):
        db_user.hashed_password = hash_password(user.password)
        await db.commit()
        await db.refresh(db_user)

    token = create_access_token({"user_id": db_user.id})
    return {"token": token, "user": UserResponse.model_validate(db_user)}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Новый пароль должен быть не менее 6 символов")
    current_user.hashed_password = hash_password(data.new_password)
    await db.commit()
    return {"message": "Пароль успешно изменён"}
