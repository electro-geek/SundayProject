"""Lightweight Redis cache for the read-heavy event endpoints.

Design goal: **degrade gracefully**. If Redis is unconfigured, unreachable, or
errors mid-request, every helper turns into a no-op (writes) or a cache miss
(reads), and the caller transparently falls back to the database. A small
circuit breaker keeps a dead Redis from adding latency to every request: after
a failure we skip Redis entirely for a cooldown window.
"""

import json
import logging
import time
from typing import Any

import redis

from app.core.config import settings

logger = logging.getLogger("event_booking.cache")

_client: redis.Redis | None = None
_circuit_open_until = 0.0
_CIRCUIT_COOLDOWN = 30.0  # seconds to bypass Redis after a failure

EVENT_LIST_PREFIX = "events:list:"


def _get_client() -> redis.Redis | None:
    global _client
    if not settings.REDIS_URL:
        return None
    if _client is None:
        # Short timeouts: a missing/slow Redis fails fast instead of blocking.
        _client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
    return _client


def _available() -> redis.Redis | None:
    """Return a client only if Redis is configured and the circuit is closed."""
    if time.monotonic() < _circuit_open_until:
        return None
    return _get_client()


def _trip_circuit(exc: Exception) -> None:
    global _circuit_open_until
    _circuit_open_until = time.monotonic() + _CIRCUIT_COOLDOWN
    logger.warning(
        "Redis unavailable; bypassing cache for %ss: %s", _CIRCUIT_COOLDOWN, exc
    )


def cache_get(key: str) -> Any | None:
    client = _available()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except redis.RedisError as exc:
        _trip_circuit(exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    client = _available()
    if client is None:
        return
    try:
        client.set(
            key,
            json.dumps(value, default=str),
            ex=ttl if ttl is not None else settings.CACHE_TTL_SECONDS,
        )
    except redis.RedisError as exc:
        _trip_circuit(exc)


def cache_delete_pattern(pattern: str) -> None:
    client = _available()
    if client is None:
        return
    try:
        keys = list(client.scan_iter(match=pattern, count=200))
        if keys:
            client.delete(*keys)
    except redis.RedisError as exc:
        _trip_circuit(exc)


# ---- event-specific keys & invalidation ---------------------------------

def event_list_key(skip: int, limit: int, search: str | None) -> str:
    return f"{EVENT_LIST_PREFIX}skip={skip}:limit={limit}:search={search or ''}"


def event_detail_key(event_id: int) -> str:
    return f"event:{event_id}"


def invalidate_event_caches(event_id: int | None = None) -> None:
    """Drop cached event listings (and one event's detail) after a write.

    Called whenever ``available_tickets`` or event fields change: create,
    update, cancel, and booking. Listings are wiped wholesale (cheap, and
    correctness matters more than a few extra misses); a specific event's
    detail key is dropped when we know its id.
    """
    cache_delete_pattern(f"{EVENT_LIST_PREFIX}*")
    if event_id is not None:
        cache_delete_pattern(event_detail_key(event_id))


# ---- helpers for tests / diagnostics ------------------------------------

def ping() -> bool:
    client = _available()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except redis.RedisError as exc:
        _trip_circuit(exc)
        return False


def reset_client() -> None:
    """Force a fresh client and close the circuit (used by tests)."""
    global _client, _circuit_open_until
    _client = None
    _circuit_open_until = 0.0
