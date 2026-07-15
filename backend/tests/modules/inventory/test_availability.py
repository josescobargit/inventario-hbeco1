import pytest

from app.modules.inventory.domain.availability import (
    InsufficientAvailabilityError,
    InventoryPosition,
)


def test_availability_uses_confirmed_formula() -> None:
    position = InventoryPosition(
        physical_confirmed=100,
        reserved=10,
        invoiced_not_dispatched=20,
        blocked_by_incident=5,
    )

    assert position.available_to_invoice == 65


def test_availability_can_expose_an_inconsistent_negative_balance() -> None:
    position = InventoryPosition(
        physical_confirmed=10,
        reserved=8,
        invoiced_not_dispatched=5,
        blocked_by_incident=0,
    )

    assert position.available_to_invoice == -3
    with pytest.raises(InsufficientAvailabilityError):
        position.require_available(1)


@pytest.mark.parametrize("quantity", [-1, 1.5, True])
def test_position_rejects_invalid_quantities(quantity) -> None:
    with pytest.raises(ValueError):
        InventoryPosition(
            physical_confirmed=quantity,
            reserved=0,
            invoiced_not_dispatched=0,
            blocked_by_incident=0,
        )
