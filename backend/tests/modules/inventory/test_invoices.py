import pytest
from pydantic import ValidationError
from app.modules.invoices.api.router import InvoiceInput


def test_invoice_number_requires_ecuadorian_sequence_format() -> None:
    with pytest.raises(ValidationError):
        InvoiceInput(
            invoice_number="686",
            invoice_date="2026-07-06",
            source_type="other",
            customer_name="Interno",
            lines=[{"sku": "AE001", "quantity": 1}],
        )


def test_invoice_without_po_requires_exception_category() -> None:
    with pytest.raises(ValidationError):
        InvoiceInput(
            invoice_number="001-001-000000686",
            invoice_date="2026-07-06",
            source_type="purchase_order",
            customer_name="Cadena",
            lines=[{"sku": "AE001", "quantity": 1}],
        )


def test_invoice_accepts_quantity_difference_for_incident_tracking() -> None:
    payload = InvoiceInput(
        invoice_number="001-001-000000687",
        invoice_date="2026-07-06",
        source_type="purchase_order",
        purchase_order_id="00000000-0000-0000-0000-000000000001",
        customer_name="Cadena",
        lines=[{"sku": "AE001", "quantity": 999}],
    )
    assert payload.lines[0].quantity == 999
