import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.router import api_router  # noqa: F401 - registers every model
from app.core.database import Base
from app.modules.catalog.infrastructure.models import Product
from app.modules.deliveries.api.router import (
    DeliveryInput,
    DeliveryLineInput,
    register_delivery,
)
from app.modules.dispatches.api.router import (
    DispatchInput,
    DispatchLineInput,
    confirm_dispatch,
)
from app.modules.inventory.infrastructure.models import (
    InventoryMovement,
    InventoryPositionModel,
    Warehouse,
)
from app.modules.invoices.api.router import (
    BulkInvoiceInput,
    InvoiceInput,
    QuickInvoiceInput,
    cancel_invoice,
    register_bulk_invoices,
    register_invoice,
    update_invoice,
)
from app.modules.invoices.api.trace_router import traceability
from app.modules.invoices.infrastructure.models import Invoice, InvoiceLine
from app.modules.purchase_orders.infrastructure.models import (
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.modules.returns.api.router import (
    LineInput as ReturnLineInput,
)
from app.modules.returns.api.router import ReturnInput, register_return


def invoice_payload(number: int, quantity: int) -> InvoiceInput:
    return InvoiceInput(
        invoice_number=f"001-001-{number:09d}",
        invoice_date=date(2026, 7, 28),
        source_type="other",
        customer_name="Cliente de prueba",
        lines=[{"sku": "SKU-1", "quantity": quantity}],
    )


@pytest.fixture
def inventory_db() -> tuple[Session, SimpleNamespace, Product, InventoryPositionModel]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = SimpleNamespace(id=uuid.uuid4())
    warehouse = Warehouse(code="principal", name="Bodega principal")
    product = Product(
        sku="SKU-1",
        name="Producto de prueba",
        category="Pruebas",
        cost=Decimal("1.00"),
        units_per_box=1,
    )
    db.add_all([warehouse, product])
    db.flush()
    position = InventoryPositionModel(
        warehouse_id=warehouse.id,
        product_id=product.id,
        physical_confirmed=100,
        reserved=0,
        invoiced_not_dispatched=0,
        blocked_by_incident=0,
    )
    db.add(position)
    db.commit()
    yield db, user, product, position
    db.close()


def test_confirmed_invoice_deducts_once_and_retry_is_idempotent(
    inventory_db,
) -> None:
    db, user, product, position = inventory_db
    payload = invoice_payload(1, 12)

    created = register_invoice(payload, user, db, "request-1")
    retried = register_invoice(payload, user, db, "request-1")
    db.refresh(position)
    movements = db.scalars(
        select(InventoryMovement).where(
            InventoryMovement.product_id == product.id,
            InventoryMovement.movement_type == "invoice_registered",
        )
    ).all()

    assert position.physical_confirmed == 88
    assert position.invoiced_not_dispatched == 12
    assert created["delivery_status"] == "pending"
    assert created["inventory_affected"][0]["physical_confirmed"] == 88
    assert retried["duplicate"] is True
    assert len(movements) == 1
    assert movements[0].quantity == 12
    assert movements[0].reason == "Salida por factura"


def test_partial_and_multiple_invoices_only_deduct_their_own_units(
    inventory_db,
) -> None:
    db, user, _product, position = inventory_db

    register_invoice(invoice_payload(2, 30), user, db, "request-2")
    register_invoice(invoice_payload(3, 20), user, db, "request-3")
    db.refresh(position)

    assert position.physical_confirmed == 50
    assert db.scalar(select(func.sum(InvoiceLine.quantity))) == 50


def test_edit_applies_only_difference_and_keeps_compensating_movements(
    inventory_db,
) -> None:
    db, user, product, position = inventory_db
    created = register_invoice(invoice_payload(4, 10), user, db, "request-4")

    update_invoice(created["id"], invoice_payload(4, 15), user, db)
    db.refresh(position)
    assert position.physical_confirmed == 85

    update_invoice(created["id"], invoice_payload(4, 8), user, db)
    db.refresh(position)
    corrections = db.scalars(
        select(InventoryMovement)
        .where(
            InventoryMovement.product_id == product.id,
            InventoryMovement.movement_type == "invoice_edited",
        )
        .order_by(InventoryMovement.occurred_at)
    ).all()

    assert position.physical_confirmed == 92
    assert [movement.quantity for movement in corrections] == [5, 7]
    assert [movement.reason for movement in corrections] == [
        "Salida adicional por edición de factura",
        "Entrada compensatoria por edición de factura",
    ]


def test_cancel_reverses_once_and_preserves_original_movement(inventory_db) -> None:
    db, user, product, position = inventory_db
    created = register_invoice(invoice_payload(5, 18), user, db, "request-5")

    cancelled = cancel_invoice(created["id"], user, db)
    repeated = cancel_invoice(created["id"], user, db)
    db.refresh(position)
    movements = db.scalars(
        select(InventoryMovement).where(InventoryMovement.product_id == product.id)
    ).all()

    assert position.physical_confirmed == 100
    assert cancelled["duplicate"] is False
    assert repeated["duplicate"] is True
    assert {movement.movement_type for movement in movements} == {
        "invoice_registered",
        "invoice_cancelled",
    }


def test_dispatch_and_later_delivery_do_not_deduct_again(inventory_db) -> None:
    db, user, _product, position = inventory_db
    created = register_invoice(invoice_payload(6, 10), user, db, "request-6")

    dispatch = confirm_dispatch(
        DispatchInput(
            invoice_id=created["id"],
            responsible_name="Responsable",
            lines=[
                DispatchLineInput(
                    sku="SKU-1",
                    dispatched_quantity=10,
                    missing_quantity=0,
                )
            ],
        ),
        user,
        db,
    )
    delivery = register_delivery(
        DeliveryInput(
            invoice_id=created["id"],
            delivered_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
            delivery_type="confirmed",
            notes="Dos unidades no fueron recibidas",
            lines=[
                DeliveryLineInput(
                    sku="SKU-1",
                    delivered_quantity=8,
                    rejected_quantity=2,
                    notes="No recibidas por el cliente",
                )
            ],
        ),
        user,
        db,
    )
    db.refresh(position)
    trace = traceability(created["id"], user, db)

    assert dispatch["dispatch_status"] == "complete"
    assert delivery["delivery_status"] == "delivered_confirmed"
    assert position.physical_confirmed == 90
    assert position.invoiced_not_dispatched == 0
    assert trace["lines"][0]["pending_confirmation"] == 2
    assert trace["lines"][0]["delivery_difference"] == -2
    assert (
        db.scalar(
            select(func.count(InventoryMovement.id)).where(
                InventoryMovement.movement_type == "dispatch_confirmed"
            )
        )
        == 0
    )


def test_return_creates_its_own_entry_related_to_delivery(inventory_db) -> None:
    db, user, _product, position = inventory_db
    created = register_invoice(invoice_payload(7, 10), user, db, "request-7")
    confirm_dispatch(
        DispatchInput(
            invoice_id=created["id"],
            responsible_name="Responsable",
            lines=[
                DispatchLineInput(
                    sku="SKU-1", dispatched_quantity=10, missing_quantity=0
                )
            ],
        ),
        user,
        db,
    )
    delivered = register_delivery(
        DeliveryInput(
            invoice_id=created["id"],
            delivery_type="confirmed",
            lines=[
                DeliveryLineInput(
                    sku="SKU-1", delivered_quantity=10, rejected_quantity=0
                )
            ],
        ),
        user,
        db,
    )

    register_return(
        ReturnInput(
            invoice_id=created["id"],
            delivery_id=delivered["id"],
            reason="Producto devuelto por el cliente",
            lines=[
                ReturnLineInput(
                    sku="SKU-1",
                    quantity=2,
                    disposition="available_warehouse",
                )
            ],
        ),
        user,
        db,
    )
    db.refresh(position)
    movement = db.scalar(
        select(InventoryMovement).where(
            InventoryMovement.movement_type == "customer_return"
        )
    )

    assert position.physical_confirmed == 92
    assert movement is not None
    assert movement.quantity == 2
    assert movement.reason == "Producto devuelto por el cliente"


def test_insufficient_inventory_and_movement_failure_are_atomic(
    inventory_db,
) -> None:
    db, user, _product, position = inventory_db
    with pytest.raises(HTTPException) as insufficient:
        register_invoice(invoice_payload(8, 101), user, db, "request-8")
    db.rollback()
    assert insufficient.value.status_code == 409
    assert db.scalar(select(func.count(Invoice.id))) == 0

    def fail_movement(_mapper, _connection, _target) -> None:
        raise RuntimeError("movement unavailable")

    event.listen(InventoryMovement, "before_insert", fail_movement)
    try:
        with pytest.raises(RuntimeError, match="movement unavailable"):
            register_invoice(invoice_payload(9, 10), user, db, "request-9")
        db.rollback()
    finally:
        event.remove(InventoryMovement, "before_insert", fail_movement)

    db.refresh(position)
    assert position.physical_confirmed == 100
    assert db.scalar(select(func.count(Invoice.id))) == 0


def test_bulk_is_atomic_per_invoice_and_retry_does_not_duplicate(inventory_db) -> None:
    db, user, product, position = inventory_db
    order = PurchaseOrder(
        chain_name="Cadena",
        customer_name="Cadena",
        order_number="OC-LOTE-1",
        order_date=date(2026, 7, 28),
        status="open",
        created_by_user_id=user.id,
    )
    db.add(order)
    db.flush()
    db.add(
        PurchaseOrderLine(
            purchase_order_id=order.id,
            product_id=product.id,
            ordered_quantity=200,
        )
    )
    db.commit()
    payload = BulkInvoiceInput(
        batch_id=uuid.uuid4(),
        invoices=[
            QuickInvoiceInput(
                invoice_number="001-001-000000010",
                invoice_date=date(2026, 7, 28),
                purchase_order_id=order.id,
                lines=[{"sku": "SKU-1", "quantity": 25}],
            ),
            QuickInvoiceInput(
                invoice_number="001-001-000000011",
                invoice_date=date(2026, 7, 28),
                purchase_order_id=order.id,
                lines=[{"sku": "SKU-1", "quantity": 90}],
            ),
        ],
    )

    first = register_bulk_invoices(payload, user, db)
    retry = register_bulk_invoices(payload, user, db)
    db.refresh(position)
    movement = db.scalar(
        select(InventoryMovement).where(
            InventoryMovement.movement_type == "invoice_registered"
        )
    )

    assert first["summary"] == {"saved": 1, "duplicates": 0, "errors": 1}
    assert first["invoices"][0]["inventory_affected"][0]["quantity"] == 25
    assert retry["summary"] == {"saved": 0, "duplicates": 1, "errors": 1}
    assert position.physical_confirmed == 75
    assert movement is not None
    assert movement.purchase_order_id == order.id
    assert movement.batch_id == payload.batch_id
    assert movement.actor_user_id == user.id
