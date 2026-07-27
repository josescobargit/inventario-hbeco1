import pytest
from pydantic import ValidationError
from app.modules.invoices.api.router import (
    BulkInvoiceInput,
    InvoiceInput,
    QuickInvoiceInput,
)


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


def test_void_invoice_keeps_number_without_products() -> None:
    payload = QuickInvoiceInput(
        invoice_number="001-001-000000688",
        invoice_date="2026-07-06",
        purchase_order_id="00000000-0000-0000-0000-000000000001",
        is_void=True,
        lines=[],
    )
    assert payload.is_void
    assert payload.lines == []


def test_active_invoice_requires_products_and_void_rejects_them() -> None:
    common = {
        "invoice_number": "001-001-000000689",
        "invoice_date": "2026-07-06",
        "purchase_order_id": "00000000-0000-0000-0000-000000000001",
    }
    with pytest.raises(ValidationError):
        QuickInvoiceInput(**common, lines=[])
    with pytest.raises(ValidationError):
        QuickInvoiceInput(
            **common, is_void=True, lines=[{"sku": "AE001", "quantity": 1}]
        )


def test_bulk_accepts_duplicate_candidates_for_per_item_idempotency_results() -> (
    None
):
    po_id = "00000000-0000-0000-0000-000000000001"
    first = {
        "invoice_number": "001-001-000000690",
        "invoice_date": "2026-07-06",
        "purchase_order_id": po_id,
        "lines": [{"sku": "AE001", "quantity": 1}],
    }
    second = {**first, "invoice_number": "001-001-000000691"}
    payload = BulkInvoiceInput(invoices=[first, second])
    assert (
        payload.invoices[0].purchase_order_id == payload.invoices[1].purchase_order_id
    )
    retry_payload = BulkInvoiceInput(invoices=[first, first])
    assert len(retry_payload.invoices) == 2
