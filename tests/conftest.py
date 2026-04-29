"""Shared pytest fixtures.

Sets env vars BEFORE any app imports so the FastAPI app, SQLAlchemy
engine, and config use the dedicated Postgres test database
(``auction_test``) created by docker-compose's init script. Production
data is never touched.
"""

import os

# Defaults match docker-compose.yml. Override TEST_DATABASE_URL if you
# run Postgres elsewhere.
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://auction:auction_dev_password@localhost:5433/auction_test",
)
os.environ.setdefault(
    "AUCTION_SECRET_KEY",
    "test-only-secret-key-do-not-use-in-prod",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.services.migrations import seed_categories  # noqa: E402


@pytest.fixture(autouse=True)
def reset_db():
    """Drop and recreate all tables before each test, then re-seed
    reference data, so tests are independent."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_categories()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def registered_user(client):
    """Register a default user and return token + headers."""
    payload = {
        "username": "alice",
        "email": "alice@example.com",
        "password": "password123",
    }
    response = client.post("/api/register", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "token": body["token"],
        "user": body["user"],
        "headers": {"Authorization": f"Bearer {body['token']}"},
        "password": payload["password"],
    }


@pytest.fixture
def second_user(client):
    """Second registered user, useful for bidding scenarios."""
    payload = {
        "username": "bob",
        "email": "bob@example.com",
        "password": "password123",
    }
    response = client.post("/api/register", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "token": body["token"],
        "user": body["user"],
        "headers": {"Authorization": f"Bearer {body['token']}"},
    }
