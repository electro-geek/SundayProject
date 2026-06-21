from unittest.mock import patch

from tests.conftest import auth_header, login, register

EVENT = {
    "title": "Concert",
    "venue": "Arena",
    "start_time": "2030-01-01T20:00:00Z",
    "price": 20.0,
    "total_tickets": 5,
}


def _setup_event(client):
    register(client, "org@x.com", "password123", "organizer")
    org = login(client, "org@x.com", "password123")
    event_id = client.post("/events", json=EVENT, headers=auth_header(org)).json()["id"]
    register(client, "cust@x.com", "password123", "customer")
    cust = login(client, "cust@x.com", "password123")
    return org, cust, event_id


def test_booking_decrements_tickets_and_triggers_email(client):
    org, cust, event_id = _setup_event(client)

    with patch("app.api.routes.bookings.send_booking_confirmation") as mock_email:
        resp = client.post(
            "/bookings",
            json={"event_id": event_id, "quantity": 2},
            headers=auth_header(cust),
        )
    assert resp.status_code == 201
    booking = resp.json()
    assert booking["quantity"] == 2
    assert float(booking["total_price"]) == 40.0
    mock_email.assert_called_once()  # Background Task 1 enqueued

    # available_tickets dropped from 5 to 3
    event = client.get(f"/events/{event_id}", headers=auth_header(org)).json()
    assert event["available_tickets"] == 3


def test_cannot_oversell(client):
    _, cust, event_id = _setup_event(client)
    resp = client.post(
        "/bookings",
        json={"event_id": event_id, "quantity": 6},
        headers=auth_header(cust),
    )
    assert resp.status_code == 400
    assert "available" in resp.json()["detail"]


def test_event_update_triggers_notification(client):
    org, cust, event_id = _setup_event(client)
    client.post(
        "/bookings",
        json={"event_id": event_id, "quantity": 1},
        headers=auth_header(cust),
    )

    with patch("app.api.routes.events.notify_event_update") as mock_notify:
        resp = client.put(
            f"/events/{event_id}",
            json={"venue": "New Arena"},
            headers=auth_header(org),
        )
    assert resp.status_code == 200
    assert resp.json()["venue"] == "New Arena"
    mock_notify.assert_called_once()  # Background Task 2 enqueued


def test_my_bookings(client):
    _, cust, event_id = _setup_event(client)
    client.post(
        "/bookings",
        json={"event_id": event_id, "quantity": 1},
        headers=auth_header(cust),
    )
    resp = client.get("/bookings/me", headers=auth_header(cust))
    assert resp.status_code == 200
    assert len(resp.json()) == 1
