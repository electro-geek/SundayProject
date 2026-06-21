import pytest

from app.core import cache as cache_module
from tests.conftest import auth_header, login, register

EVENT = {
    "title": "Cached Gig",
    "venue": "Hall",
    "start_time": "2030-01-01T20:00:00Z",
    "price": 10.0,
    "total_tickets": 50,
}


def _organizer(client, email="org@x.com"):
    register(client, email, "password123", "organizer")
    return login(client, email, "password123")


def _customer(client, email="cust@x.com"):
    register(client, email, "password123", "customer")
    return login(client, email, "password123")


def test_endpoints_work_when_redis_unavailable(client, monkeypatch):
    """Graceful fallback: point cache at a dead Redis; everything still works."""
    monkeypatch.setattr(cache_module.settings, "REDIS_URL", "redis://localhost:6399/0")
    cache_module.reset_client()

    token = _organizer(client)
    client.post("/events", json=EVENT, headers=auth_header(token))

    resp = client.get("/events", headers=auth_header(token))
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    detail = client.get("/events/1", headers=auth_header(token))
    assert detail.status_code == 200

    cache_module.reset_client()  # restore for subsequent tests


def test_list_cache_is_populated_and_invalidated(client):
    if not cache_module.ping():
        pytest.skip("Redis not available")

    token = _organizer(client)
    eid = client.post("/events", json=EVENT, headers=auth_header(token)).json()["id"]

    # First browse populates the cache.
    client.get("/events", headers=auth_header(token))
    list_key = cache_module.event_list_key(0, 20, None)
    assert cache_module.cache_get(list_key) is not None

    # An update must invalidate the cached listing.
    client.put(f"/events/{eid}", json={"venue": "New Hall"}, headers=auth_header(token))
    assert cache_module.cache_get(list_key) is None


def test_booking_invalidates_event_detail_cache(client):
    if not cache_module.ping():
        pytest.skip("Redis not available")

    org = _organizer(client)
    eid = client.post("/events", json=EVENT, headers=auth_header(org)).json()["id"]
    cust = _customer(client)

    # Cache the detail (50 available).
    client.get(f"/events/{eid}", headers=auth_header(cust))
    detail_key = cache_module.event_detail_key(eid)
    assert cache_module.cache_get(detail_key)["available_tickets"] == 50

    # Booking changes availability and must drop the stale cache.
    client.post(
        "/bookings",
        json={"event_id": eid, "quantity": 5},
        headers=auth_header(cust),
    )
    assert cache_module.cache_get(detail_key) is None

    # Re-fetch reflects the new count.
    fresh = client.get(f"/events/{eid}", headers=auth_header(cust)).json()
    assert fresh["available_tickets"] == 45
