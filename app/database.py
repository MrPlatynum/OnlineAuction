from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from app.config import DATABASE_URL

engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
    # asyncpg defaults to no client-side timeout, so a TCP black-hole
    # to Postgres (LB silently dropping packets, dead replica) used to
    # park the request coroutine indefinitely and only release on
    # uvicorn shutdown. ``timeout`` caps the initial connect; SQL
    # statements are bounded per-call via ``command_timeout`` so a
    # runaway query can't hold the connection forever either.
    connect_args={"timeout": 10, "command_timeout": 30},
)
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)
Base = declarative_base()


async def get_db():
    async with SessionLocal() as db:
        yield db
