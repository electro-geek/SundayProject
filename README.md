# Event Booking System — FastAPI Backend

Backend APIs for an event booking platform with **role-based access control** for
two user types:

- **Event Organizers** — create, update, and cancel events; view bookings for their events.
- **Customers** — browse events and book tickets.

Two asynchronous **background tasks** are triggered by the system:

1. **Booking Confirmation** — when a customer successfully books tickets, a confirmation
   "email" is simulated via a log statement.
2. **Event Update Notification** — when an organizer updates an event, every customer who
   booked that event is notified (simulated via log statements).

---

## Feature Checklist (mapped to the assignment)

| Requirement | Where it lives |
|---|---|
| Two user roles (Organizer, Customer) | `app/models/user.py` (`Role` enum) |
| Role-based API access control | `app/api/deps.py` (`require_role`) |
| Organizers manage events | `app/api/routes/events.py` |
| Customers browse & book | `app/api/routes/events.py`, `app/api/routes/bookings.py` |
| Background Task 1: booking confirmation | `app/tasks/notifications.py::send_booking_confirmation` |
| Background Task 2: event update notification | `app/tasks/notifications.py::notify_event_update` |
| Background processing mechanism | FastAPI `BackgroundTasks` |
| Design decisions documented | this README |

---

## Tech Stack

| Concern | Choice |
|---|---|
| Web framework | **FastAPI** + Uvicorn |
| ORM | **SQLAlchemy 2.0** (typed `Mapped[]` models) |
| Migrations | **Alembic** |
| Database | **PostgreSQL 16** (via `psycopg` 3) |
| Validation / settings | **Pydantic v2** + pydantic-settings |
| Auth | **JWT** (`python-jose`) + **bcrypt** password hashing (`passlib`) |
| Background jobs | **FastAPI `BackgroundTasks`** |
| Tests | **pytest** + Starlette `TestClient` |

---

## Architecture

```
                 ┌──────────────────────────────────────────┐
   HTTP client   │                 FastAPI                   │
  ───────────►   │  routes/auth   routes/events  routes/bookings
                 │      │              │              │       │
                 │      ▼              ▼              ▼       │
                 │   deps.py: get_current_user / require_role │  ◄── JWT decode + RBAC
                 │      │              │              │       │
                 │      ▼              ▼              ▼       │
                 │            SQLAlchemy ORM session          │
                 │                    │                       │
                 │       BackgroundTasks.add_task(...)        │
                 └──────────┬───────────────────────┬────────┘
                            ▼                        ▼
                    PostgreSQL              tasks/notifications.py
                     (events)               (own short-lived DB session)
                                            [EMAIL] / [NOTIFY] logs
```

### Project structure

```
app/
  main.py                 # FastAPI app, logging, router wiring, /health
  core/
    config.py             # Settings from env/.env (DB URL, JWT)
    security.py           # bcrypt hashing + JWT encode/decode
  db/
    base.py               # DeclarativeBase
    session.py            # engine, SessionLocal, get_db dependency
  models/                 # SQLAlchemy models: user, event, booking
  schemas/                # Pydantic request/response models + token
  api/
    deps.py               # get_current_user, require_role (RBAC core)
    routes/               # auth, events, bookings
  tasks/
    notifications.py      # the two background tasks
alembic/                  # migration environment + versions
tests/                    # pytest suite
docker-compose.yml        # PostgreSQL service
.env.example              # configuration template
```

---

## Data Model

```
User (id, email*, hashed_password, full_name, role[organizer|customer], created_at)
  │ 1                                   │ 1
  │ organizes                           │ makes
  │ N                                   │ N
Event (id, organizer_id→User, title, description, venue, start_time,
       total_tickets, available_tickets, price, status[active|cancelled],
       created_at, updated_at)
  │ 1
  │ has
  │ N
Booking (id, customer_id→User, event_id→Event, quantity, total_price,
         status[confirmed|cancelled], created_at)
```

`* = unique`. `available_tickets` starts equal to `total_tickets` and is decremented
atomically on each booking.

---

## API Reference

Auth uses **OAuth2 password bearer**. Send `Authorization: Bearer <token>` on protected routes.

| Method | Path | Access | Description |
|---|---|---|---|
| POST | `/auth/register` | Public | Register a user with a `role` (organizer/customer) |
| POST | `/auth/login` | Public | Login (form: `username`=email, `password`) → JWT |
| GET  | `/events` | Any authed user | Browse active events (`skip`, `limit`, `search`) |
| GET  | `/events/{id}` | Any authed user | Get one event |
| POST | `/events` | Organizer | Create an event |
| PUT  | `/events/{id}` | Organizer (owner) | Update event → triggers **notification** task |
| DELETE | `/events/{id}` | Organizer (owner) | Soft-cancel event → triggers notification task |
| GET  | `/events/{id}/bookings` | Organizer (owner) | List bookings for own event |
| POST | `/bookings` | Customer | Book tickets → triggers **confirmation** task |
| GET  | `/bookings/me` | Customer | List the caller's bookings |
| GET  | `/health` | Public | Liveness probe |

Interactive docs (Swagger UI) are available at **`/docs`** when the server runs.

---

## Setup & Run

### Prerequisites
- Python 3.10+
- Docker + Docker Compose (for PostgreSQL)

### 1. Start PostgreSQL
```bash
docker compose up -d
```
> The host port is remapped to avoid clashing with a Postgres you may already run:
> **Postgres 5433 → 5432**. The URL in `.env.example` matches this.

### 2. Configure environment
```bash
cp .env.example .env          # adjust JWT_SECRET etc. if you like
```

### 3. Install dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Apply database migrations
```bash
alembic upgrade head
```

### 5. Run the API
```bash
uvicorn app.main:app --reload
```
Open <http://127.0.0.1:8000/docs>.

---

## Demo Walkthrough (and where to see the background-task logs)

The two background tasks print to the **server console** (the terminal running
`uvicorn`). Watch that terminal while running the flow below.

```bash
BASE=http://127.0.0.1:8000

# 1. Register an organizer and a customer
curl -X POST $BASE/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"alice@org.com","password":"password123","full_name":"Alice","role":"organizer"}'
curl -X POST $BASE/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"bob@cust.com","password":"password123","full_name":"Bob","role":"customer"}'

# 2. Log in to get JWTs
ORG=$(curl -s -X POST $BASE/auth/login -d 'username=alice@org.com&password=password123' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
CUST=$(curl -s -X POST $BASE/auth/login -d 'username=bob@cust.com&password=password123' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 3. Organizer creates an event
curl -X POST $BASE/events -H "Authorization: Bearer $ORG" -H 'Content-Type: application/json' \
  -d '{"title":"Jazz Night","venue":"Blue Note","start_time":"2030-01-01T20:00:00Z","price":25.0,"total_tickets":100}'

# 4. Customer browses events
curl $BASE/events -H "Authorization: Bearer $CUST"

# 5. Customer books 2 tickets  → server logs:  [EMAIL] Booking #1 confirmed for bob@cust.com — 2x 'Jazz Night' = $50.00
curl -X POST $BASE/bookings -H "Authorization: Bearer $CUST" -H 'Content-Type: application/json' \
  -d '{"event_id":1,"quantity":2}'

# 6. Organizer updates the event → server logs:  [NOTIFY] Emailing bob@cust.com: Event 'Jazz Night' was updated (venue).
curl -X PUT $BASE/events/1 -H "Authorization: Bearer $ORG" -H 'Content-Type: application/json' \
  -d '{"venue":"Madison Square Garden"}'
```

Example console output:
```
... | INFO | event_booking.tasks | [EMAIL] Booking #1 confirmed for bob@cust.com — 2x 'Jazz Night' = $50.00
... | INFO | event_booking.tasks | [NOTIFY] Emailing bob@cust.com: Event 'Jazz Night' was updated (venue).
```

---

## Running Tests

The suite uses a separate `events_test` database on the same Postgres instance.

```bash
# one-time: create the test database
docker exec event_booking_postgres psql -U postgres -c "CREATE DATABASE events_test;"

source .venv/bin/activate
pytest -q
```

Coverage: registration/login, JWT auth, RBAC (organizer-only / customer-only / owner-only),
event CRUD + search, booking with ticket decrement, overselling rejection, and assertions that
**both background tasks are enqueued** (via mocking).

---

## Design Decisions & Rationale

**PostgreSQL + SQLAlchemy + Alembic.**
A relational DB is the natural fit: events, users, and bookings are highly relational
with strong integrity needs (foreign keys, ticket counts). PostgreSQL also gives us real
row-level locking, which the booking flow relies on (see below). Alembic provides versioned,
reproducible schema migrations rather than `create_all` magic.

**JWT auth with bcrypt hashing.**
Stateless JWT bearer tokens keep the API horizontally scalable (no server-side session
store). Passwords are hashed with bcrypt via passlib. The token carries the user id (`sub`)
and `role` claim. `bcrypt` is pinned to `4.0.1` because passlib 1.7.4 is incompatible with
bcrypt ≥ 4.1 (it can't read the version and raises spurious errors).

**Role-based access control via a dependency factory.**
`require_role(Role.organizer)` / `require_role(Role.customer)` in `app/api/deps.py` is a
reusable FastAPI dependency that returns **403** when the role doesn't match. Ownership
checks (an organizer may only modify their own events) are enforced separately in the route
via `_get_owned_event`. This keeps authz declarative and close to each endpoint.

**FastAPI `BackgroundTasks` for async work (vs a broker-backed queue).**
The assignment only requires a simulated side effect (a log) that runs after the response.
FastAPI's built-in `BackgroundTasks` does exactly this with **zero extra infrastructure** —
no broker, no worker process — which keeps the project trivial to clone, run, and demo.
A Celery/broker setup would add operational overhead with no benefit at this scope. The code is
structured so the task functions could later be swapped to `.delay()` calls behind a queue
with minimal change. *(Trade-off: BackgroundTasks run in the same process and aren't durable
across restarts — acceptable for notifications; a real email pipeline would use a broker.)*

**Background tasks open their own DB session.**
Tasks run *after* the request completes, so the request-scoped session is already closed.
Each task therefore accepts only ids and re-queries inside its own short-lived
`SessionLocal()` (`app/tasks/notifications.py`). This avoids using a detached/closed session.

**Atomic ticket decrement with `SELECT … FOR UPDATE` (anti-oversell).**
The booking handler locks the event row (`with_for_update()`) before checking and decrementing
`available_tickets`, all in one transaction. This guarantees two concurrent bookings can't
both pass the availability check and oversell the event.

**Soft-cancel instead of hard-delete.**
`DELETE /events/{id}` sets `status = cancelled` rather than removing the row, preserving
booking history and referential integrity, and lets us notify affected customers.

**`logging` instead of bare `print`.**
A `print` is sufficient per the brief, but the tasks use Python's `logging` (configured in
`main.py`) for timestamped, leveled output — cleaner to read in the demo and closer to real
practice. The log lines are clearly tagged `[EMAIL]` and `[NOTIFY]`.

---

## Assumptions & Possible Improvements

**Assumptions**
- A customer may book the same event multiple times (no unique constraint); quantity is tracked per booking.
- `role` is chosen at registration (no admin approval flow).
- Notifications/emails are simulated; no real mail provider is integrated.

**Future improvements**
- Booking cancellation that returns tickets to inventory.
- Pagination metadata (total counts) on list endpoints.
- Refresh tokens / token revocation.
- Durable job queue (Celery/RQ/Arq) + real email provider for production.
- Rate limiting and structured request logging.
```
