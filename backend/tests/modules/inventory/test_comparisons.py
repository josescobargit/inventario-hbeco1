from app.modules.comparisons.api.router import (
    ComparisonAccumulator,
    serialize,
    status_for,
)


def test_comparison_marks_pending_invoice() -> None:
    row = ComparisonAccumulator(
        chain_name="Favorita",
        customer_name=None,
        order_number="OC-1",
        order_date=None,
        source_type="purchase_order",
        sku="SKU-1",
        product_name="Producto",
        ordered_quantity=10,
        invoiced_quantity=6,
    )

    assert status_for(row) == "pending_invoice"
    assert serialize(row)["pending_to_invoice"] == 4


def test_comparison_marks_pending_dispatch() -> None:
    row = ComparisonAccumulator(
        chain_name="Favorita",
        customer_name=None,
        order_number="OC-1",
        order_date=None,
        source_type="purchase_order",
        sku="SKU-1",
        product_name="Producto",
        ordered_quantity=10,
        invoiced_quantity=10,
        dispatched_quantity=7,
    )

    assert status_for(row) == "pending_dispatch"
    assert serialize(row)["pending_to_dispatch"] == 3


def test_comparison_prioritizes_incident() -> None:
    row = ComparisonAccumulator(
        chain_name="Favorita",
        customer_name=None,
        order_number="OC-1",
        order_date=None,
        source_type="purchase_order",
        sku="SKU-1",
        product_name="Producto",
        ordered_quantity=10,
        invoiced_quantity=10,
        dispatched_quantity=8,
        missing_quantity=2,
    )

    assert status_for(row) == "with_incident"


def test_comparison_marks_pending_delivery() -> None:
    row = ComparisonAccumulator(
        chain_name="Favorita",
        customer_name=None,
        order_number="OC-1",
        order_date=None,
        source_type="purchase_order",
        sku="SKU-1",
        product_name="Producto",
        ordered_quantity=10,
        invoiced_quantity=10,
        dispatched_quantity=10,
        delivered_quantity=6,
    )

    assert status_for(row) == "pending_delivery"
    assert serialize(row)["pending_to_deliver"] == 4
