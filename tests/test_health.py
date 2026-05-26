"""Health endpoint + security-headers middleware."""


async def test_health_returns_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    # 503 path is hard to trigger without breaking the connection;
    # what matters is that /health never echoes ``str(exc)`` back -
    # check the success body has no ``detail`` field carrying a DSN.
    assert "detail" not in body


async def test_security_headers_present(client):
    r = await client.get("/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in r.headers
    # HSTS opt-in: not enabled in tests
    assert "Strict-Transport-Security" not in r.headers
