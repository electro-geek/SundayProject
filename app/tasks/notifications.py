"""Background tasks.

These run *after* the HTTP response has been sent (via FastAPI's
``BackgroundTasks``). The request-scoped DB session is already closed by then,
so each task opens its own short-lived ``SessionLocal`` and re-queries by id.

For this assignment the "email"/"notification" actions are simulated with log
statements rather than a real mail provider.
"""

import logging

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.booking import Booking, BookingStatus
from app.models.event import Event
from app.models.user import User

logger = logging.getLogger("event_booking.tasks")


def send_booking_confirmation(booking_id: int) -> None:
    """Background Task 1: simulate sending a booking confirmation email."""
    with SessionLocal() as db:
        booking = db.get(Booking, booking_id)
        if booking is None:
            logger.warning("[EMAIL] Booking %s not found; skipping.", booking_id)
            return
        customer = db.get(User, booking.customer_id)
        event = db.get(Event, booking.event_id)
        logger.info(
            "[EMAIL] Booking #%s confirmed for %s — %sx '%s' = $%.2f",
            booking.id,
            customer.email if customer else "unknown",
            booking.quantity,
            event.title if event else "unknown event",
            float(booking.total_price),
        )


def notify_event_update(event_id: int, changed_fields: list[str]) -> None:
    """Background Task 2: notify all customers who booked an updated event."""
    with SessionLocal() as db:
        event = db.get(Event, event_id)
        if event is None:
            logger.warning("[NOTIFY] Event %s not found; skipping.", event_id)
            return

        # Distinct customers with a confirmed booking for this event.
        customers = db.scalars(
            select(User)
            .join(Booking, Booking.customer_id == User.id)
            .where(
                Booking.event_id == event_id,
                Booking.status == BookingStatus.confirmed,
            )
            .distinct()
        ).all()

        if not customers:
            logger.info(
                "[NOTIFY] Event '%s' updated, but no customers to notify.",
                event.title,
            )
            return

        changes = ", ".join(changed_fields) if changed_fields else "details"
        for customer in customers:
            logger.info(
                "[NOTIFY] Emailing %s: Event '%s' was updated (%s).",
                customer.email,
                event.title,
                changes,
            )
