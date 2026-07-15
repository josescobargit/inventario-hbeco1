import pytest
from pydantic import ValidationError

from app.modules.reservations.api.schemas import ReservationCreate


def test_customer_reservation_requires_customer() -> None:
    with pytest.raises(ValidationError):
        ReservationCreate(
            purpose="customer",
            reason="Reserva comercial",
            lines=[{"sku": "AE001", "quantity": 2}],
        )


def test_operational_reservation_accepts_multiple_products() -> None:
    reservation = ReservationCreate(
        purpose="operational",
        reason="Separación para revisión interna",
        lines=[{"sku": "AE001", "quantity": 2}, {"sku": "AE002", "quantity": 3}],
    )
    assert sum(line.quantity for line in reservation.lines) == 5
