from tests.conftest import auth_header, login, register

EVENT = {
    "title": "Jazz Night",
    "description": "Live jazz",
    "venue": "Blue Note",
    "start_time": "2030-01-01T20:00:00Z",
    "price": 25.0,
    "total_tickets": 100,
}


def _organizer_token(client, email="org@x.com"):
    register(client, email, "password123", "organizer")
    return login(client, email, "password123")


def test_organizer_creates_event(client):
    token = _organizer_token(client)
    resp = client.post("/events", json=EVENT, headers=auth_header(token))
    assert resp.status_code == 201
    body = resp.json()
    assert body["available_tickets"] == 100
    assert body["status"] == "active"


def test_browse_and_search_events(client):
    token = _organizer_token(client)
    client.post("/events", json=EVENT, headers=auth_header(token))

    cust_token = _register_customer(client)
    resp = client.get("/events", headers=auth_header(cust_token))
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.get("/events?search=jazz", headers=auth_header(cust_token))
    assert len(resp.json()) == 1
    resp = client.get("/events?search=nothing", headers=auth_header(cust_token))
    assert resp.json() == []


def test_non_owner_cannot_update(client):
    token_a = _organizer_token(client, "a@x.com")
    event_id = client.post("/events", json=EVENT, headers=auth_header(token_a)).json()["id"]

    token_b = _organizer_token(client, "b@x.com")
    resp = client.put(
        f"/events/{event_id}", json={"venue": "Hijack"}, headers=auth_header(token_b)
    )
    assert resp.status_code == 403


def _register_customer(client, email="cust@x.com"):
    register(client, email, "password123", "customer")
    return login(client, email, "password123")
