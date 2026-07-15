from app.modules.purchase_orders.api.router import LineInput, OrderInput


def test_purchase_order_accepts_multiple_lines() -> None:
    order = OrderInput(
        chain_name="Cadena ejemplo",
        order_number="OC-100",
        lines=[LineInput(sku="AE001", quantity=10), LineInput(sku="AE002", quantity=5)],
    )
    assert sum(line.quantity for line in order.lines) == 15
