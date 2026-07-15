import pytest
from pydantic import ValidationError

from app.modules.deliveries.api.router import DeliveryInput


def test_delivery_line_rejection_requires_reason() -> None:
    with pytest.raises(ValidationError):
        DeliveryInput(
            invoice_id="00000000-0000-0000-0000-000000000001",
            delivery_type="with_issue",
            recipient="CD Cliente",
            notes="El cliente reportó diferencia.",
            lines=[
                {
                    "sku": "SKU-1",
                    "delivered_quantity": 5,
                    "rejected_quantity": 1,
                }
            ],
        )


def test_delivery_accepts_received_quantities_by_sku() -> None:
    payload = DeliveryInput(
        invoice_id="00000000-0000-0000-0000-000000000001",
        delivery_type="confirmed",
        recipient="CD Cliente",
        lines=[
            {
                "sku": "SKU-1",
                "delivered_quantity": 5,
                "rejected_quantity": 0,
            }
        ],
    )

    assert payload.lines[0].delivered_quantity == 5
