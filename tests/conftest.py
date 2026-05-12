"""Shared pytest fixtures.

Sets env vars BEFORE any app imports so the FastAPI app, SQLAlchemy
engine, and config use the dedicated Postgres test database
(``auction_test``) created by docker-compose's init script. Production
data is never touched.
"""

import os

# Defaults match docker-compose.yml.
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://auction:auction_dev_password@localhost:5433/auction_test",
)
os.environ.setdefault(
    "AUCTION_SECRET_KEY",
    "test-only-secret-key-do-not-use-in-prod",
)
# Tests fire many requests at 127.0.0.1 inside one minute (registration,
# login, deposit) which would trip the production limits. The dedicated
# test ``test_rate_limit_*`` files re-enable it explicitly per-test.
os.environ.setdefault("AUCTION_RATE_LIMIT_ENABLED", "false")

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import update  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

import app.database as _db_module  # noqa: E402
from app import app  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import User  # noqa: E402
from app.services.migrations import seed_categories  # noqa: E402


async def _force_verified(username: str) -> None:
    """Flip ``email_verified`` to True for a freshly-registered fixture
    user. Existing tests pre-date the email-verification gate and would
    otherwise hit 403 on every bid / buy-now / create-auction call; new
    tests that *want* the unverified state use the
    ``unverified_user`` fixture below instead."""
    async with _db_module.SessionLocal() as session:
        await session.execute(
            update(User)
            .where(User.username == username)
            .values(email_verified=True)
        )
        await session.commit()


@pytest_asyncio.fixture(autouse=True)
async def reset_db():
    """Recreate the engine + schema before each test.

    The event loop is shared across the session (``asyncio_default_*_loop_scope =
    session`` in ``pytest.ini``) — asyncpg's pool bindings hate being
    torn down per-test, so we keep one loop alive. Test isolation
    comes from this fixture instead: new engine + ``drop_all`` +
    ``create_all`` between every test, so module-level state (e.g.
    SQLAlchemy's connection pool, identity maps) starts fresh for each
    function."""
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    _db_module.engine = engine
    _db_module.SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await seed_categories()
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def registered_user(client):
    payload = {
        "username": "alice",
        "email": "alice@example.com",
        "password": "password123",
    }
    response = await client.post("/api/register", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    await _force_verified(payload["username"])
    body["user"]["email_verified"] = True
    return {
        "token": body["token"],
        "user": body["user"],
        "headers": {"Authorization": f"Bearer {body['token']}"},
        "password": payload["password"],
    }


@pytest_asyncio.fixture
async def second_user(client):
    payload = {
        "username": "bob",
        "email": "bob@example.com",
        "password": "password123",
    }
    response = await client.post("/api/register", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    await _force_verified(payload["username"])
    body["user"]["email_verified"] = True
    return {
        "token": body["token"],
        "user": body["user"],
        "headers": {"Authorization": f"Bearer {body['token']}"},
    }


@pytest_asyncio.fixture
async def third_user(client):
    payload = {
        "username": "carol",
        "email": "carol@example.com",
        "password": "password123",
    }
    response = await client.post("/api/register", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    await _force_verified(payload["username"])
    body["user"]["email_verified"] = True
    return {
        "token": body["token"],
        "user": body["user"],
        "headers": {"Authorization": f"Bearer {body['token']}"},
    }


@pytest_asyncio.fixture
async def unverified_user(client):
    """Fresh registration with ``email_verified`` still False — for
    tests of the verification gate (write endpoints must 403) and the
    /verify-email flow itself."""
    payload = {
        "username": "dan",
        "email": "dan@example.com",
        "password": "password123",
    }
    response = await client.post("/api/register", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "token": body["token"],
        "user": body["user"],
        "headers": {"Authorization": f"Bearer {body['token']}"},
        "email": payload["email"],
    }
