import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.routes import auth, bookings, events

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)

API_DESCRIPTION = """
## Event Booking System API

A backend for an event‑ticketing platform with **role‑based access control**,
**JWT authentication**, **PostgreSQL** persistence, and two **background tasks**.

### 👥 Two user roles
| Role | Can do |
|------|--------|
| **Organizer** | Create, update, and cancel *their own* events; view attendees for their events. |
| **Customer**  | Browse active events and book tickets; view their own bookings. |

Access is enforced per‑endpoint — a customer calling an organizer route (or vice‑versa)
gets **403**, and organizers may only modify events they own.

### 🔐 Authentication (how to use this page)
1. **`POST /auth/register`** — create an account, choosing a `role` of `organizer` or `customer`.
2. **`POST /auth/login`** — log in with email + password to receive a **JWT access token**.
3. Click the green **Authorize 🔓** button (top‑right), paste the token, and every
   protected request below will be sent with `Authorization: Bearer <token>`.

### ⚙️ Background tasks (fire after the HTTP response)
- **Booking Confirmation** — when a customer books, a confirmation "email" is simulated
  and logged: `[EMAIL] Booking #… confirmed for …`.
- **Event Update Notification** — when an organizer updates or cancels an event, every
  customer who booked it is notified: `[NOTIFY] Emailing … : Event '…' was updated …`.

### 🛡️ Reliability features
- **Anti‑oversell** — bookings lock the event row (`SELECT … FOR UPDATE`) so concurrent
  requests can never sell more tickets than exist.

### 🖥️ Interactive console
A full visual client for these endpoints is served at the API root **[`/`](/)**.
"""

tags_metadata = [
    {
        "name": "auth",
        "description": "Registration and login. **Public** endpoints that issue JWT "
        "access tokens carrying the user id and role.",
    },
    {
        "name": "events",
        "description": "Browse events (any signed‑in user) and manage them "
        "(**organizer‑only**, owner‑scoped). Updates and cancellations trigger the "
        "attendee‑notification background task.",
    },
    {
        "name": "bookings",
        "description": "Ticket booking and history (**customer‑only**). Booking is "
        "oversell‑safe and triggers the confirmation‑email background task.",
    },
    {"name": "health", "description": "Liveness probe for uptime checks."},
]

app = FastAPI(
    title="Event Booking System",
    version="1.0.0",
    description=API_DESCRIPTION,
    openapi_tags=tags_metadata,
    contact={"name": "Event Booking System"},
    license_info={"name": "MIT"},
)

# Allow the bundled frontend (or any origin during development) to call the API.
# Tokens are sent via the Authorization header (not cookies), so credentials are
# disabled and a wildcard origin is safe.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(events.router)
app.include_router(bookings.router)

STATIC_DIR = Path(__file__).parent / "static"


@app.get(
    "/health",
    tags=["health"],
    summary="Liveness probe",
    description="Returns `{\"status\": \"ok\"}` when the API process is up. "
    "Used by load balancers / the frontend status pill.",
    response_description="Service is alive.",
)
def health() -> dict:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the bundled paper-brutalist API console (same-origin, no CORS needed)."""
    return FileResponse(STATIC_DIR / "index.html")
