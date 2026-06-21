import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Point the app at a dedicated test database before importing app modules.
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5433/events_test",
)
os.environ["DATABASE_URL"] = TEST_DB_URL

from app.core import cache as cache_module  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

engine = create_engine(TEST_DB_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def _setup_db():
    """Fresh schema + clean cache for every test (cache may persist across tests)."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    cache_module.reset_client()
    cache_module.cache_delete_pattern("event*")
    yield
    Base.metadata.drop_all(bind=engine)
    cache_module.cache_delete_pattern("event*")


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---- helpers -------------------------------------------------------------

def register(client, email, password, role, full_name="Test User"):
    return client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": full_name, "role": role},
    )


def login(client, email, password):
    resp = client.post("/auth/login", data={"username": email, "password": password})
    return resp.json()["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}
