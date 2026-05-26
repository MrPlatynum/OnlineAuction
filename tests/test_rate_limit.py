"""Rate-limit smoke tests.

The shared ``conftest`` disables the limiter so other tests don't trip
themselves on 127.0.0.1. These tests flip it back on for the duration
of the test (and reset its in-memory bucket so prior runs don't bleed
state) to verify that the configured limits actually return 429.
"""

import pytest_asyncio

from app.utils.rate_limit import limiter


@pytest_asyncio.fixture
async def rate_limit_on():
    limiter.reset()
    limiter.enabled = True
    try:
        yield
    finally:
        limiter.enabled = False
        limiter.reset()


async def test_login_returns_429_after_threshold(client, rate_limit_on):
    """``/login`` is capped at 10/minute. The 11th call within one
    minute must be rejected with 429."""
    creds = {"username": "nobody", "password": "wrong"}
    statuses = [
        (await client.post("/api/login", json=creds)).status_code
        for _ in range(11)
    ]
    assert 429 in statuses, statuses


async def test_register_returns_429_after_threshold(client, rate_limit_on):
    """``/register`` is capped at 5/minute."""
    statuses = []
    for i in range(6):
        r = await client.post(
            "/api/register",
            json={
                "username": f"flood{i}",
                "email": f"flood{i}@example.com",
                "password": "password123",
            },
        )
        statuses.append(r.status_code)
    assert 429 in statuses, statuses


async def test_limiter_disabled_in_default_test_env(client):
    """Sanity check: with the limiter disabled (default test env) the
    same flood goes through without 429s, so the rest of the suite is
    safe from rate-limit interference."""
    creds = {"username": "nobody", "password": "wrong"}
    statuses = [
        (await client.post("/api/login", json=creds)).status_code
        for _ in range(15)
    ]
    assert 429 not in statuses, statuses


def test_client_key_falls_back_to_remote_address(monkeypatch):
    """Without ``AUCTION_TRUST_PROXY`` the X-Forwarded-For header is
    ignored - a spoofed value mustn't let a client escape its bucket
    on a direct-internet listener."""
    from starlette.requests import Request

    from app.utils.rate_limit import _client_key

    monkeypatch.delenv("AUCTION_TRUST_PROXY", raising=False)

    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"203.0.113.5")],
        "client": ("10.0.0.1", 12345),
    }
    request = Request(scope)
    assert _client_key(request) == "10.0.0.1"


def test_client_key_uses_xff_when_proxy_trusted(monkeypatch):
    """With ``AUCTION_TRUST_PROXY=true`` the leftmost X-Forwarded-For
    entry wins - without this every request behind a reverse proxy
    would share one bucket keyed on the proxy's own address."""
    from starlette.requests import Request

    from app.utils.rate_limit import _client_key

    monkeypatch.setenv("AUCTION_TRUST_PROXY", "true")

    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"203.0.113.5, 10.0.0.1, 10.0.0.2")],
        "client": ("10.0.0.1", 12345),
    }
    request = Request(scope)
    assert _client_key(request) == "203.0.113.5"
