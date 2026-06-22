from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.booking import Booking
from app.models.event import Event, EventStatus
from app.models.user import Role, User
from app.schemas.booking import BookingCreate, BookingRead
from app.tasks.notifications import send_booking_confirmation

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post(
    "",
    response_model=BookingRead,
    status_code=status.HTTP_201_CREATED,
    summary="Book tickets (customer only) → sends confirmation",
    description=(
        "Book `quantity` tickets for an active event. The event row is **locked** "
        "(`SELECT … FOR UPDATE`) while availability is checked and decremented, so "
        "concurrent bookings can never oversell. On success **Background Task 1** runs: "
        "a confirmation email is simulated/logged. Requires the **customer** role."
    ),
    response_description="The created booking.",
    responses={
        400: {"description": "Event not active or not enough tickets"},
        403: {"description": "Requires 'customer' role"},
        404: {"description": "Event not found"},
    },
)
def create_booking(
    payload: BookingCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    customer: User = Depends(require_role(Role.customer)),
) -> Booking:
    # Lock the event row for the duration of the transaction so two concurrent
    # bookings can't both pass the availability check and oversell tickets.
    event = db.scalar(
        select(Event).where(Event.id == payload.event_id).with_for_update()
    )
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    if event.status != EventStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Event is not active"
        )
    if payload.quantity > event.available_tickets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only {event.available_tickets} tickets available",
        )

    event.available_tickets -= payload.quantity
    booking = Booking(
        customer_id=customer.id,
        event_id=event.id,
        quantity=payload.quantity,
        total_price=Decimal(str(event.price)) * payload.quantity,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    # Background Task 1: send booking confirmation email (simulated).
    background_tasks.add_task(send_booking_confirmation, booking.id)
    return booking


@router.get(
    "/me",
    response_model=list[BookingRead],
    summary="List my bookings (customer only)",
    description="Return the calling **customer's** own bookings, newest first.",
    response_description="The customer's bookings.",
    responses={403: {"description": "Requires 'customer' role"}},
)
def list_my_bookings(
    db: Session = Depends(get_db),
    customer: User = Depends(require_role(Role.customer)),
) -> list[Booking]:
    stmt = (
        select(Booking)
        .where(Booking.customer_id == customer.id)
        .order_by(Booking.created_at.desc())
    )
    return list(db.scalars(stmt).all())
