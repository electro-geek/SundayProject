from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.booking import BookingStatus


class BookingCreate(BaseModel):
    event_id: int
    quantity: int = Field(gt=0)


class BookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    event_id: int
    quantity: int
    total_price: float
    status: BookingStatus
    created_at: datetime
