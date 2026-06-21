from tests.conftest import login, register


def test_register_and_login(client):
    resp = register(client, "org@x.com", "password123", "organizer")
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "org@x.com"
    assert body["role"] == "organizer"
    assert "id" in body

    token = login(client, "org@x.com", "password123")
    assert isinstance(token, str) and len(token) > 0


def test_duplicate_email_rejected(client):
    register(client, "dup@x.com", "password123", "customer")
    resp = register(client, "dup@x.com", "password123", "customer")
    assert resp.status_code == 409


def test_login_wrong_password(client):
    register(client, "u@x.com", "password123", "customer")
    resp = client.post("/auth/login", data={"username": "u@x.com", "password": "wrong"})
    assert resp.status_code == 401


def test_protected_route_requires_token(client):
    resp = client.get("/events")
    assert resp.status_code == 401
