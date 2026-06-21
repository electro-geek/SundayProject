"""Importing this package registers all ORM models on ``Base.metadata`` so that
Alembic autogenerate and ``Base.metadata.create_all`` see every table.
"""

from app.models.booking import Booking
from app.models.event import Event
from app.models.user import User

__all__ = ["User", "Event", "Booking"]
