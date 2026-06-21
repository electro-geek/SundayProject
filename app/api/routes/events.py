from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.cache import (
    cache_get,
    cache_set,
    event_detail_key,
    event_list_key,
    invalidate_event_caches,
)
from app.db.session import get_db
from app.models.booking import Booking
from app.models.event import Event, EventStatus
from app.models.user import Role, User
from app.schemas.booking import BookingRead
from app.schemas.event import EventCreate, EventRead, EventUpdate
from app.tasks.notifications import notify_event_update

router = APIRouter(prefix="/events", tags=["events"])


def _get_owned_event(event_id: int, db: Session, organizer: User) -> Event:
    """Fetch an event and ensure the current organizer owns it (else 403/404)."""
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    if event.organizer_id != organizer.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this event",
        )
    return event


@router.get(
    "",
    response_model=list[EventRead],
    summary="Browse active events",
    description=(
        "List **active** events with pagination (`skip`, `limit`) and optional "
        "case‑insensitive title `search`. Available to any authenticated user "
        "(organizer or customer). Responses are **Redis‑cached** and invalidated on writes."
    ),
    response_description="A page of active events ordered by start time.",
)
def list_events(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, description="Case-insensitive title search"),
    _: User = Depends(get_current_user),
):
    """Browse active events (any authenticated user).

    Read-through cached in Redis; falls back to the DB on a cache miss or if
    Redis is unavailable. Invalidated whenever events change.
    """
    cache_key = event_list_key(skip, limit, search)
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    stmt = select(Event).where(Event.status == EventStatus.active)
    if search:
        stmt = stmt.where(Event.title.ilike(f"%{search}%"))
    stmt = stmt.order_by(Event.start_time).offset(skip).limit(limit)
    events = db.scalars(stmt).all()

    result = [EventRead.model_validate(e).model_dump(mode="json") for e in events]
    cache_set(cache_key, result)
    return result


@router.get(
    "/{event_id}",
    response_model=EventRead,
    summary="Get a single event",
    description=(
        "Fetch one event by id, including live `available_tickets`. Available to any "
        "authenticated user. **Redis‑cached** and invalidated on writes/bookings."
    ),
    response_description="The requested event.",
    responses={404: {"description": "Event not found"}},
)
def get_event(
    event_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    cache_key = event_detail_key(event_id)
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    result = EventRead.model_validate(event).model_dump(mode="json")
    cache_set(cache_key, result)
    return result


@router.post(
    "",
    response_model=EventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an event (organizer only)",
    description=(
        "Create a new event owned by the calling **organizer**. `available_tickets` is "
        "initialized to `total_tickets`. Requires the organizer role (**403** otherwise)."
    ),
    response_description="The newly created event.",
    responses={403: {"description": "Requires 'organizer' role"}},
)
def create_event(
    payload: EventCreate,
    db: Session = Depends(get_db),
    organizer: User = Depends(require_role(Role.organizer)),
) -> Event:
    event = Event(
        organizer_id=organizer.id,
        title=payload.title,
        description=payload.description,
        venue=payload.venue,
        start_time=payload.start_time,
        total_tickets=payload.total_tickets,
        available_tickets=payload.total_tickets,
        price=payload.price,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    # A new active event must appear in cached listings.
    invalidate_event_caches()
    return event


@router.put(
    "/{event_id}",
    response_model=EventRead,
    summary="Update an event (owner only) → notifies attendees",
    description=(
        "Partially update one of **your own** events (only provided fields change). "
        "On success this triggers **Background Task 2**: every customer who booked the "
        "event is notified. Lowering `total_tickets` below the already‑booked count is "
        "rejected with **400**. Non‑owners get **403**."
    ),
    response_description="The updated event.",
    responses={
        400: {"description": "total_tickets below already‑booked count"},
        403: {"description": "Not the owner / not an organizer"},
        404: {"description": "Event not found"},
    },
)
def update_event(
    event_id: int,
    payload: EventUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    organizer: User = Depends(require_role(Role.organizer)),
) -> Event:
    event = _get_owned_event(event_id, db, organizer)

    updates = payload.model_dump(exclude_unset=True)

    # Adjusting total_tickets keeps the already-booked count consistent by
    # shifting available_tickets by the same delta (can't drop below 0).
    if "total_tickets" in updates:
        new_total = updates["total_tickets"]
        booked = event.total_tickets - event.available_tickets
        if new_total < booked:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"total_tickets cannot be less than already booked ({booked})",
            )
        event.available_tickets = new_total - booked

    for field, value in updates.items():
        setattr(event, field, value)

    db.commit()
    db.refresh(event)

    # Event fields changed -> drop stale listings and this event's detail cache.
    invalidate_event_caches(event.id)

    # Background Task 2: notify customers who booked this event.
    background_tasks.add_task(notify_event_update, event.id, list(updates.keys()))
    return event


@router.delete(
    "/{event_id}",
    status_code=status.HTTP_200_OK,
    summary="Cancel an event (owner only) → notifies attendees",
    description=(
        "**Soft‑cancel** one of your own events: its status becomes `cancelled` and it "
        "drops out of active listings (the row is preserved for history). Triggers the "
        "attendee‑notification background task. Non‑owners get **403**."
    ),
    response_description="Confirmation that the event was cancelled.",
    responses={
        403: {"description": "Not the owner / not an organizer"},
        404: {"description": "Event not found"},
    },
)
def cancel_event(
    event_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    organizer: User = Depends(require_role(Role.organizer)),
) -> dict:
    """Soft-cancel an event (status -> cancelled) and notify booked customers."""
    event = _get_owned_event(event_id, db, organizer)
    event.status = EventStatus.cancelled
    db.commit()

    # Cancelled events drop out of the active listings.
    invalidate_event_caches(event.id)

    background_tasks.add_task(notify_event_update, event.id, ["status: cancelled"])
    return {"detail": "Event cancelled"}


@router.get(
    "/{event_id}/bookings",
    response_model=list[BookingRead],
    summary="List attendees for your event (owner only)",
    description=(
        "Return all bookings made for one of **your own** events — the attendee list. "
        "Non‑owners get **403**."
    ),
    response_description="Bookings for the event, oldest first.",
    responses={
        403: {"description": "Not the owner / not an organizer"},
        404: {"description": "Event not found"},
    },
)
def list_event_bookings(
    event_id: int,
    db: Session = Depends(get_db),
    organizer: User = Depends(require_role(Role.organizer)),
) -> list[Booking]:
    """List all bookings for one of the organizer's own events."""
    _get_owned_event(event_id, db, organizer)
    stmt = select(Booking).where(Booking.event_id == event_id).order_by(Booking.created_at)
    return list(db.scalars(stmt).all())
