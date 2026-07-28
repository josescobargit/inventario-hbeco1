from datetime import date
import uuid

import pytest
from fastapi import HTTPException

from app.modules.purchase_orders.api.router import (
    LineInput,
    OrderInput,
    audit_value,
    canonical_chain_name,
    fulfillment_status,
    validate_line_conversion,
    validate_traceable_line_change,
)
from app.modules.purchase_orders.api import router as purchase_order_router
from app.modules.purchase_orders.infrastructure.models import (
    PurchaseOrderSourceDocument,
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


def test_edit_allows_quantity_above_every_related_operation() -> None:
    validate_traceable_line_change(
        "AE001",
        121,
        invoiced=120,
        dispatched=80,
        delivered=60,
        reserved=20,
    )


def test_edit_blocks_quantity_below_invoiced_amount_with_real_reason() -> None:
    with pytest.raises(HTTPException) as error:
        validate_traceable_line_change(
            "AE001",
            100,
            invoiced=120,
            dispatched=80,
            delivered=60,
            reserved=20,
        )
    assert error.value.status_code == 409
    assert error.value.detail == (
        "No puedes reducir AE001 a 100 unidades porque ya se facturaron 120."
    )


def test_new_purchase_order_documents_allow_metadata_without_binary() -> None:
    assert PurchaseOrderSourceDocument.__table__.c.content.nullable is True


def test_temporary_purchase_order_file_is_deleted_on_discard(
    tmp_path, monkeypatch
) -> None:
    token = uuid.uuid4()
    monkeypatch.setattr(purchase_order_router, "PREVIEW_DIRECTORY", tmp_path)

    purchase_order_router.write_preview(token, b"%PDF-temporal")
    assert purchase_order_router.preview_path(token).read_bytes() == b"%PDF-temporal"

    purchase_order_router.delete_preview(token)
    assert not purchase_order_router.preview_path(token).exists()


def test_edit_blocks_removing_dispatched_product() -> None:
    with pytest.raises(HTTPException) as error:
        validate_traceable_line_change(
            "AE001",
            None,
            invoiced=10,
            dispatched=8,
            delivered=4,
            reserved=0,
        )
    assert error.value.status_code == 409
    assert "No puedes eliminar AE001" in error.value.detail


def test_edit_revalidates_box_conversion() -> None:
    with pytest.raises(HTTPException) as error:
        validate_line_conversion(
            LineInput(
                sku="AE001",
                quantity=100,
                original_quantity=10,
                original_unit="boxes",
                units_per_box=12,
            )
        )
    assert error.value.status_code == 422
    assert "Cajas × UxC" in error.value.detail


def test_audit_history_serializes_dates() -> None:
    assert audit_value(date(2026, 7, 27)) == "2026-07-27"
