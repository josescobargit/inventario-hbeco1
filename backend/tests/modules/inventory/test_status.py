from app.modules.inventory.api.router import visual_status
from app.modules.inventory.domain.availability import InventoryPosition


def position(available: int, blocked: int = 0) -> InventoryPosition:
    return InventoryPosition(
        physical_confirmed=available + blocked,
        reserved=0,
        invoiced_not_dispatched=0,
        blocked_by_incident=blocked,
    )


def test_blocked_status_has_priority() -> None:
    assert visual_status(position(24, blocked=2), units_per_box=12) == "blocked"


def test_zero_availability_is_out_of_stock() -> None:
    assert visual_status(position(0), units_per_box=12) == "out_of_stock"


def test_one_box_or_less_is_low_stock() -> None:
    assert visual_status(position(12), units_per_box=12) == "low_stock"


def test_more_than_one_box_is_available() -> None:
    assert visual_status(position(13), units_per_box=12) == "available"


def test_configured_threshold_can_mark_two_boxes_as_low_stock() -> None:
    assert (
        visual_status(position(20), units_per_box=12, low_stock_units=24) == "low_stock"
    )
