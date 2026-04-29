def test_register_creates_user_and_returns_token(client):
    response = client.post("/api/register", json={
        "username": "newuser",
        "email": "new@example.com",
        "password": "secret123",
    })
    assert response.status_code == 200
    body = response.json()
    assert "token" in body
    assert body["user"]["username"] == "newuser"
    assert body["user"]["email"] == "new@example.com"
    assert body["user"]["balance"] == 1000.0


def test_register_duplicate_username_rejected(client, registered_user):
    response = client.post("/api/register", json={
        "username": registered_user["user"]["username"],
        "email": "different@example.com",
        "password": "whatever",
    })
    assert response.status_code == 400
    assert "Username" in response.json()["detail"]


def test_register_duplicate_email_rejected(client, registered_user):
    response = client.post("/api/register", json={
        "username": "different",
        "email": registered_user["user"]["email"],
        "password": "whatever",
    })
    assert response.status_code == 400
    assert "Email" in response.json()["detail"]


def test_login_with_correct_password(client, registered_user):
    response = client.post("/api/login", json={
        "username": registered_user["user"]["username"],
        "password": registered_user["password"],
    })
    assert response.status_code == 200
    assert "token" in response.json()


def test_login_with_wrong_password_returns_401(client, registered_user):
    response = client.post("/api/login", json={
        "username": registered_user["user"]["username"],
        "password": "wrong-password",
    })
    assert response.status_code == 401


def test_me_returns_current_user(client, registered_user):
    response = client.get("/api/me", headers=registered_user["headers"])
    assert response.status_code == 200
    assert response.json()["username"] == registered_user["user"]["username"]


def test_me_without_token_rejected(client):
    response = client.get("/api/me")
    assert response.status_code == 403  # HTTPBearer returns 403 when no token
