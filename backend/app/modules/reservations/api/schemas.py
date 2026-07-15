import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ReservationLineInput(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    quantity: int = Field(gt=0)


class ReservationCreate(BaseModel):
    purpose: Literal[
        "customer", "purchase_order", "seller", "pending_order", "operational"
    ]
    customer_name: str | None = Field(default=None, max_length=160)
    purchase_order_reference: str | None = Field(default=None, max_length=100)
    responsible_name: str | None = Field(default=None, max_length=160)
    reason: str = Field(min_length=5, max_length=1000)
    lines: list[ReservationLineInput] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_reference(self):
        if self.purpose == "customer" and not self.customer_name:
            raise ValueError("Indica el cliente de la reserva.")
        if self.purpose == "purchase_order" and not self.purchase_order_reference:
            raise ValueError("Indica la OC relacionada.")
        return self


class ReservationRelease(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class ReservationLineResponse(BaseModel):
    sku: str
    product_name: str
    quantity: int
    remaining_quantity: int


class ReservationResponse(BaseModel):
    id: uuid.UUID
    purpose: str
    customer_name: str | None
    purchase_order_reference: str | None
    responsible_name: str | None
    reason: str
    status: str
    release_reason: str | None
    created_at: datetime
    lines: list[ReservationLineResponse]
