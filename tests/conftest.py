"""Shared pytest fixtures.

Sets env vars BEFORE any app imports, so the FastAPI app, SQLAlchemy
engine, and config use a throwaway test database — production
auction.db is never touched.
"""

import os
import tempfile

# Test DB lives in a temp file for the whole pytest session.
_db_fd, _db_path = tempfile.mkstemp(suffix="_test.db")
os.close(_db_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path.replace(os.sep, '/')}"

# Without this, app/config.py raises at import time.
os.environ.setdefault(
    "AUCTION_SECRET_KEY",
    "test-only-secret-key-do-not-use-in-prod",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.services.migrations import seed_categories  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    """Delete the temp DB file when pytest finishes."""
    try:
        os.unlink(_db_path)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def reset_db():
    """Drop all rows and reseed categories before each test, so tests
    are independent of each other."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_categories()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def registered_user(client):
    """Register a default user and return {token, user, headers}."""
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
    """A second registered user, useful for bidding scenarios."""
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
