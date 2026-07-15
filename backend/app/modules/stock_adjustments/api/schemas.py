import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AdjustmentCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    requested_physical_confirmed: int = Field(ge=0)
    reason: str = Field(min_length=5, max_length=1000)


class AdjustmentDecision(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class AdjustmentResponse(BaseModel):
    id: uuid.UUID
    sku: str
    product_name: str
    status: str
    previous_physical_confirmed: int
    requested_physical_confirmed: int
    request_reason: str
    decision_reason: str | None
    requested_at: datetime
    decided_at: datetime | None
