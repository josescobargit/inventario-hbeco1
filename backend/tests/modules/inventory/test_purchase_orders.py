from datetime import date
from decimal import Decimal
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.infrastructure.models import InventoryPositionModel, Warehouse
from app.modules.invoices.infrastructure.models import Invoice, InvoiceLine
from app.modules.purchase_orders.api.router import (
    LineInput,
    OrderInput,
    audit_value,
    canonical_chain_name,
    detail,
    fulfillment_status,
    validate_line_conversion,
    validate_traceable_line_change,
)
from app.modules.purchase_orders.api import router as purchase_order_router
from app.modules.purchase_orders.infrastructure.models import (
    PurchaseOrder,
    PurchaseOrderLine,
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


def test_purchase_order_detail_accumulates_active_invoices_in_units() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user_id = uuid.uuid4()
    warehouse = Warehouse(code="principal", name="Principal")
    ordered_product = Product(
        sku="BOX-1",
        name="Producto en cajas",
        category="Prueba",
        cost=Decimal("1"),
        units_per_box=12,
    )
    outside_product = Product(
        sku="OUT-1",
        name="Producto fuera de OC",
        category="Prueba",
        cost=Decimal("1"),
        units_per_box=1,
    )
    db.add_all([warehouse, ordered_product, outside_product])
    db.flush()
    db.add_all(
        [
            InventoryPositionModel(
                warehouse_id=warehouse.id,
                product_id=product.id,
                physical_confirmed=1000,
            )
            for product in (ordered_product, outside_product)
        ]
    )
    order = PurchaseOrder(
        chain_name="Cadena",
        customer_name="Cadena",
        order_number="OC-UNIDADES",
        order_date=date(2026, 7, 20),
        status="open",
        created_by_user_id=user_id,
    )
    db.add(order)
    db.flush()
    db.add(
        PurchaseOrderLine(
            purchase_order_id=order.id,
            product_id=ordered_product.id,
            ordered_quantity=300,
            original_quantity=25,
            original_unit="boxes",
            units_per_box=12,
            conversion_confirmed=True,
        )
    )
    invoices = []
    for sequence, status in ((1, "confirmed"), (2, "confirmed"), (3, "cancelled")):
        invoice = Invoice(
            invoice_number=f"001-001-{sequence:09d}",
            invoice_date=date(2026, 7, 21),
            purchase_order_id=order.id,
            source_type="purchase_order",
            customer_name="Cadena",
            chain_name="Cadena",
            administrative_status=status,
            created_by_user_id=user_id,
        )
        db.add(invoice)
        db.flush()
        invoices.append(invoice)
    db.add_all(
        [
            InvoiceLine(
                invoice_id=invoices[0].id,
                product_id=ordered_product.id,
                quantity=120,
            ),
            InvoiceLine(
                invoice_id=invoices[1].id,
                product_id=ordered_product.id,
                quantity=200,
            ),
            InvoiceLine(
                invoice_id=invoices[1].id,
                product_id=outside_product.id,
                quantity=5,
                outside_purchase_order=True,
            ),
            InvoiceLine(
                invoice_id=invoices[2].id,
                product_id=ordered_product.id,
                quantity=100,
            ),
        ]
    )
    db.commit()

    result = detail(db, order)
    by_sku = {line["sku"]: line for line in result["lines"]}

    assert by_sku["BOX-1"]["ordered_quantity"] == 300
    assert by_sku["BOX-1"]["invoiced_quantity"] == 320
    assert by_sku["BOX-1"]["excess_invoice_quantity"] == 20
    assert len(by_sku["BOX-1"]["invoice_breakdown"]) == 2
    assert by_sku["OUT-1"]["billing_comparison_result"] == (
        "Producto facturado no incluido en la OC"
    )
    assert result["billing_summary"]["ordered_units"] == 300
    assert result["billing_summary"]["invoiced_units"] == 325
    assert result["billing_summary"]["excess_units"] == 25
    assert result["billing_summary"]["result"] == (
        "Tiene diferencias que requieren revisión"
    )
    db.close()
