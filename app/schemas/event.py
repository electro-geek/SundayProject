from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.event import EventStatus


class EventBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    venue: str = Field(min_length=1, max_length=255)
    start_time: datetime
    price: float = Field(ge=0)


class EventCreate(EventBase):
    total_tickets: int = Field(gt=0)


class EventUpdate(BaseModel):
    """All fields optional; only provided fields are updated."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    venue: str | None = Field(default=None, min_length=1, max_length=255)
    start_time: datetime | None = None
    price: float | None = Field(default=None, ge=0)
    total_tickets: int | None = Field(default=None, gt=0)


class EventRead(EventBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organizer_id: int
    total_tickets: int
    available_tickets: int
    status: EventStatus
    created_at: datetime
    updated_at: datetime
