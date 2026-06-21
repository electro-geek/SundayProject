from tests.conftest import auth_header, login, register

EVENT = {
    "title": "Show",
    "venue": "Hall",
    "start_time": "2030-01-01T20:00:00Z",
    "price": 10.0,
    "total_tickets": 50,
}


def test_customer_cannot_create_event(client):
    register(client, "cust@x.com", "password123", "customer")
    token = login(client, "cust@x.com", "password123")
    resp = client.post("/events", json=EVENT, headers=auth_header(token))
    assert resp.status_code == 403


def test_organizer_cannot_book(client):
    register(client, "org@x.com", "password123", "organizer")
    token = login(client, "org@x.com", "password123")
    resp = client.post(
        "/bookings", json={"event_id": 1, "quantity": 1}, headers=auth_header(token)
    )
    assert resp.status_code == 403


def test_customer_cannot_list_event_bookings(client):
    register(client, "org@x.com", "password123", "organizer")
    org = login(client, "org@x.com", "password123")
    eid = client.post("/events", json=EVENT, headers=auth_header(org)).json()["id"]

    register(client, "cust@x.com", "password123", "customer")
    cust = login(client, "cust@x.com", "password123")
    resp = client.get(f"/events/{eid}/bookings", headers=auth_header(cust))
    assert resp.status_code == 403
