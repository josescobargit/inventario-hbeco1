from app.modules.inventory.domain.availability import InventoryPosition
from app.modules.reports.api.router import status_for


def test_report_status_marks_blocked_first() -> None:
    status = status_for(
        InventoryPosition(
            physical_confirmed=20,
            reserved=0,
            invoiced_not_dispatched=0,
            blocked_by_incident=2,
        ),
        units_per_box=6,
    )

    assert status == "blocked"


def test_report_status_marks_low_stock_by_box_threshold() -> None:
    status = status_for(
        InventoryPosition(
            physical_confirmed=5,
            reserved=0,
            invoiced_not_dispatched=0,
            blocked_by_incident=0,
        ),
        units_per_box=6,
    )

    assert status == "low_stock"


def test_report_status_uses_configured_low_stock_units() -> None:
    status = status_for(
        InventoryPosition(
            physical_confirmed=10,
            reserved=0,
            invoiced_not_dispatched=0,
            blocked_by_incident=0,
        ),
        units_per_box=6,
        low_stock_units=12,
    )

    assert status == "low_stock"
