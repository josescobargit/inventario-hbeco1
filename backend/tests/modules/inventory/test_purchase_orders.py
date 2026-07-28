import pytest

from app.modules.purchase_orders.api.router import (
    LineInput,
    OrderInput,
    canonical_chain_name,
    fulfillment_status,
)


def test_purchase_order_accepts_multiple_lines() -> None:
    order = OrderInput(
        chain_name="Cadena ejemplo",
        order_number="OC-100",
        lines=[LineInput(sku="AE001", quantity=10), LineInput(sku="AE002", quantity=5)],
    )
    assert sum(line.quantity for line in order.lines) == 15


@pytest.mark.parametrize("source", ["TUTI", "Tuti", "tuti", "Tiendas Tuti"])
def test_tuti_aliases_share_one_chain_identity(source: str) -> None:
    assert canonical_chain_name(source) == "TUTI"


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ((10, 0, 0, 0, 0, False), "not_processed"),
        ((10, 4, 0, 0, 0, False), "invoicing_partial"),
        ((10, 10, 3, 0, 0, False), "dispatch_partial"),
        ((10, 10, 10, 4, 0, False), "delivery_partial"),
        ((10, 10, 10, 10, 0, False), "delivered_complete"),
        ((10, 12, 12, 12, 0, False), "delivered_excess"),
        ((10, 10, 10, 10, 2, False), "with_return"),
        ((10, 10, 3, 0, 0, True), "with_incident"),
    ],
)
def test_purchase_order_fulfillment_states(
    values: tuple[int, int, int, int, int, bool], expected: str
) -> None:
    assert fulfillment_status(*values) == expected
