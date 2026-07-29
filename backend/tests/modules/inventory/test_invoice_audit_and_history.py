import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.router import api_router  # noqa: F401
from app.core.database import Base
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.api.router import inventory_at_date
from app.modules.inventory.api.router import historical_product_movements
from app.modules.inventory.infrastructure.models import (
    InventoryMovement,
    InventoryPositionModel,
    Warehouse,
)
from app.modules.invoices.api.audit_router import (
    CorrectionInput,
    correct_pending_movements,
    correction_preview,
    invoice_inventory_audit,
    invoice_listing,
    pending_inventory_invoices,
)
from app.modules.invoices.api.router import (
    InvoiceInput,
    cancel_invoice,
    register_invoice,
)
from app.modules.invoices.domain.inventory_audit import audit_invoices
from app.modules.invoices.infrastructure.models import Invoice


def database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = SimpleNamespace(id=uuid.uuid4())
    warehouse = Warehouse(code="principal", name="Principal")
    product = Product(
        sku="AUD-1",
        name="Producto auditado",
        category="Auditoría",
        cost=Decimal("1"),
        units_per_box=1,
    )
    db.add_all([warehouse, product])
    db.flush()
    position = InventoryPositionModel(
        warehouse_id=warehouse.id,
        product_id=product.id,
        physical_confirmed=500,
        reserved=0,
        invoiced_not_dispatched=0,
        blocked_by_incident=0,
    )
    db.add(position)
    db.commit()
    return engine, db, user, warehouse, product, position


def payload(number: int, quantity: int = 10) -> InvoiceInput:
    return InvoiceInput(
        invoice_number=f"001-001-{number:09d}",
        invoice_date=date(2026, 6, 17),
        source_type="other",
        customer_name="Cliente",
        chain_name="Cadena",
        lines=[{"sku": "AUD-1", "quantity": quantity}],
    )


def movement_for(db: Session, invoice_id: uuid.UUID, kind: str):
    return db.scalar(
        select(InventoryMovement).where(
            InventoryMovement.reference_id == str(invoice_id),
            InventoryMovement.movement_type == kind,
        )
    )


def test_audit_classifies_correct_missing_partial_and_duplicate() -> None:
    _engine, db, user, warehouse, product, position = database()
    correct = register_invoice(payload(1), user, db, "audit-1")
    missing = register_invoice(payload(2), user, db, "audit-2")
    partial = register_invoice(payload(3), user, db, "audit-3")
    duplicate = register_invoice(payload(4), user, db, "audit-4")

    db.execute(
        delete(InventoryMovement).where(
            InventoryMovement.reference_id == str(missing["id"])
        )
    )
    partial_movement = movement_for(db, partial["id"], "invoice_registered")
    partial_movement.after_value = {
        **partial_movement.after_value,
        "physical_confirmed": partial_movement.before_value["physical_confirmed"] - 4,
    }
    db.add(
        InventoryMovement(
            warehouse_id=warehouse.id,
            product_id=product.id,
            actor_user_id=user.id,
            movement_type="invoice_registered",
            reference_type="invoice",
            reference_id=str(duplicate["id"]),
            quantity=10,
            reason="Duplicado simulado",
            before_value={"physical_confirmed": 460},
            after_value={"physical_confirmed": 450},
        )
    )
    db.commit()

    by_number = {item["invoice_number"]: item["status"] for item in audit_invoices(db)}
    assert by_number[correct["invoice_number"]] == "correct"
    assert by_number[missing["invoice_number"]] == "missing"
    assert by_number[partial["invoice_number"]] == "partial"
    assert by_number[duplicate["invoice_number"]] == "duplicate"
    db.close()


def test_complete_audit_detects_wrong_product_and_orphan_movement_read_only() -> None:
    _engine, db, user, warehouse, product, position = database()
    other = Product(
        sku="AUD-2",
        name="Producto equivocado",
        category="Auditoría",
        cost=Decimal("1"),
        units_per_box=1,
    )
    db.add(other)
    db.flush()
    db.add(
        InventoryPositionModel(
            warehouse_id=warehouse.id,
            product_id=other.id,
            physical_confirmed=100,
            reserved=0,
            invoiced_not_dispatched=0,
            blocked_by_incident=0,
        )
    )
    created = register_invoice(payload(30), user, db, "audit-wrong-product")
    movement = movement_for(db, created["id"], "invoice_registered")
    movement.product_id = other.id
    db.add(
        InventoryMovement(
            warehouse_id=warehouse.id,
            product_id=product.id,
            actor_user_id=user.id,
            movement_type="invoice_registered",
            reference_type="invoice",
            reference_id=str(uuid.uuid4()),
            quantity=3,
            reason="Movimiento huérfano simulado",
            before_value={"physical_confirmed": 500},
            after_value={"physical_confirmed": 497},
        )
    )
    db.commit()
    movement_count = len(db.scalars(select(InventoryMovement)).all())
    physical_before = position.physical_confirmed

    result = invoice_inventory_audit(user, db)

    db.refresh(position)
    audited = next(item for item in result["items"] if item["id"] == created["id"])
    assert result["read_only"] is True
    assert audited["status"] == "product_incorrect"
    assert {item["status"] for item in audited["products"]} == {
        "missing",
        "product_incorrect",
    }
    assert result["summary"]["orphan_movements"] == 1
    assert result["orphan_movements"][0]["status"] == "movement_without_invoice"
    assert len(db.scalars(select(InventoryMovement)).all()) == movement_count
    assert position.physical_confirmed == physical_before
    db.close()


def test_exact_visible_invoice_number_links_legacy_movement() -> None:
    _engine, db, user, _warehouse, _product, _position = database()
    created = register_invoice(payload(31), user, db, "audit-visible-reference")
    movement = movement_for(db, created["id"], "invoice_registered")
    movement.reference_id = created["invoice_number"]
    db.commit()

    result = invoice_inventory_audit(user, db)

    audited = next(item for item in result["items"] if item["id"] == created["id"])
    assert audited["status"] == "correct"
    assert result["summary"]["orphan_movements"] == 0
    db.close()


def test_cancelled_invoice_requires_and_recognizes_reversal() -> None:
    _engine, db, user, _warehouse, _product, _position = database()
    corrected = register_invoice(payload(5), user, db, "audit-5")
    missing_reversal = register_invoice(payload(6), user, db, "audit-6")
    cancel_invoice(corrected["id"], user, db)
    cancel_invoice(missing_reversal["id"], user, db)
    db.execute(
        delete(InventoryMovement).where(
            InventoryMovement.reference_id == str(missing_reversal["id"]),
            InventoryMovement.movement_type == "invoice_cancelled",
        )
    )
    db.commit()

    by_number = {item["invoice_number"]: item["status"] for item in audit_invoices(db)}
    assert by_number[corrected["invoice_number"]] == "cancelled_correct"
    assert by_number[missing_reversal["invoice_number"]] == "cancelled_missing_reversal"
    db.close()


def test_audit_correction_reverses_cancelled_invoice_once() -> None:
    _engine, db, user, _warehouse, _product, position = database()
    created = register_invoice(payload(9, 10), user, db, "audit-9")
    cancel_invoice(created["id"], user, db)
    db.execute(
        delete(InventoryMovement).where(
            InventoryMovement.reference_id == str(created["id"]),
            InventoryMovement.movement_type == "invoice_cancelled",
        )
    )
    position.physical_confirmed -= 10
    db.commit()

    preview = correction_preview(user, db)
    assert preview["correctable"][0]["units_to_discount"] == 10
    first = correct_pending_movements(
        CorrectionInput(
            confirmation="CORREGIR",
            invoice_ids=[created["id"]],
            reason="Reponer factura anulada histórica",
        ),
        user,
        db,
    )
    second = correct_pending_movements(
        CorrectionInput(
            confirmation="CORREGIR",
            invoice_ids=[created["id"]],
            reason="Reintento de reversión histórica",
        ),
        user,
        db,
    )

    db.refresh(position)
    assert first["corrected"] == 1
    assert second["corrected"] == 0
    assert position.physical_confirmed == 500
    assert audit_invoices(db, [created["id"]])[0]["status"] == "cancelled_correct"
    db.close()


def test_correction_preview_and_execution_are_idempotent() -> None:
    _engine, db, user, _warehouse, _product, position = database()
    created = register_invoice(payload(7, 12), user, db, "audit-7")
    db.execute(
        delete(InventoryMovement).where(
            InventoryMovement.reference_id == str(created["id"])
        )
    )
    position.physical_confirmed += 12
    db.commit()

    preview = correction_preview(user, db)
    assert preview["correctable"][0]["units_to_discount"] == 12
    first = correct_pending_movements(
        CorrectionInput(
            confirmation="CORREGIR",
            invoice_ids=[created["id"]],
            reason="Corrección de prueba",
        ),
        user,
        db,
    )
    second = correct_pending_movements(
        CorrectionInput(
            confirmation="CORREGIR",
            invoice_ids=[created["id"]],
            reason="Reintento de prueba",
        ),
        user,
        db,
    )
    db.refresh(position)
    assert first["corrected"] == 1
    assert first["inventory_affected"] == [
        {
            "sku": "AUD-1",
            "physical_confirmed": 488,
            "available_to_invoice": 488,
        }
    ]
    assert second["corrected"] == 0
    assert position.physical_confirmed == 488
    assert audit_invoices(db, [created["id"]])[0]["status"] == "correct"
    db.close()


def test_partial_correction_applies_only_delta_and_audit_preview_is_read_only() -> None:
    _engine, db, user, _warehouse, _product, position = database()
    created = register_invoice(payload(8, 12), user, db, "audit-8")
    movement = movement_for(db, created["id"], "invoice_registered")
    movement.after_value = {
        **movement.after_value,
        "physical_confirmed": movement.before_value["physical_confirmed"] - 5,
    }
    position.physical_confirmed += 7
    db.commit()
    movement_count = len(db.scalars(select(InventoryMovement)).all())

    audited = audit_invoices(db, [created["id"]])
    preview = correction_preview(user, db)

    db.refresh(position)
    assert audited[0]["status"] == "partial"
    assert preview["correctable"][0]["units_to_discount"] == 7
    assert position.physical_confirmed == 495
    assert len(db.scalars(select(InventoryMovement)).all()) == movement_count

    result = correct_pending_movements(
        CorrectionInput(
            confirmation="CORREGIR",
            invoice_ids=[created["id"]],
            reason="Completar descuento parcial",
        ),
        user,
        db,
    )
    db.refresh(position)
    assert result["results"][0]["units_discounted"] == 7
    assert position.physical_confirmed == 488
    assert audit_invoices(db, [created["id"]])[0]["status"] == "correct"
    db.close()


def test_confirmed_excess_is_reversed_only_after_explicit_confirmation() -> None:
    _engine, db, user, _warehouse, _product, position = database()
    created = register_invoice(payload(32, 10), user, db, "audit-excess")
    movement = movement_for(db, created["id"], "invoice_registered")
    movement.after_value = {
        **movement.after_value,
        "physical_confirmed": movement.before_value["physical_confirmed"] - 15,
    }
    position.physical_confirmed -= 5
    db.commit()

    preview = correction_preview(user, db)
    proposed = next(
        item for item in preview["correctable"] if item["id"] == created["id"]
    )
    assert proposed["units_to_discount"] == 5
    assert position.physical_confirmed == 485

    first = correct_pending_movements(
        CorrectionInput(
            confirmation="CORREGIR",
            invoice_ids=[created["id"]],
            reason="Revertir exceso confirmado",
        ),
        user,
        db,
    )
    second = correct_pending_movements(
        CorrectionInput(
            confirmation="CORREGIR",
            invoice_ids=[created["id"]],
            reason="Reintento sin duplicar reversión",
        ),
        user,
        db,
    )

    db.refresh(position)
    assert first["corrected"] == 1
    assert second["corrected"] == 0
    assert position.physical_confirmed == 490
    assert audit_invoices(db, [created["id"]])[0]["status"] == "correct"
    db.close()


def test_pending_inventory_view_classifies_and_details_only_positive_differences() -> (
    None
):
    _engine, db, user, _warehouse, _product, position = database()
    register_invoice(payload(20), user, db, "pending-correct")
    missing = register_invoice(payload(21), user, db, "pending-missing")
    partial = register_invoice(payload(22), user, db, "pending-partial")
    failed = register_invoice(payload(23), user, db, "pending-error")
    processing = register_invoice(payload(24), user, db, "pending-processing")
    cancelled = register_invoice(payload(25), user, db, "pending-cancelled")
    cancel_invoice(cancelled["id"], user, db)

    db.execute(
        delete(InventoryMovement).where(
            InventoryMovement.reference_id.in_(
                [str(missing["id"]), str(failed["id"]), str(processing["id"])]
            )
        )
    )
    partial_movement = movement_for(db, partial["id"], "invoice_registered")
    partial_movement.after_value = {
        **partial_movement.after_value,
        "physical_confirmed": partial_movement.before_value["physical_confirmed"] - 4,
    }
    failed_invoice = db.get(Invoice, failed["id"])
    failed_invoice.inventory_status = "error"
    failed_invoice.inventory_last_error = "No se pudo guardar el movimiento"
    processing_invoice = db.get(Invoice, processing["id"])
    processing_invoice.inventory_status = "processing"
    position.physical_confirmed += 36
    db.commit()
    position_before = position.physical_confirmed
    movement_count = len(db.scalars(select(InventoryMovement)).all())

    result = pending_inventory_invoices(
        user,
        db,
        search=None,
        sequence=None,
        purchase_order=None,
        chain=None,
        date_from=None,
        date_to=None,
        status=None,
        page=1,
        page_size=25,
    )
    by_number = {item["invoice_number"]: item for item in result["items"]}

    assert result["read_only"] is True
    assert result["summary"] == {
        "pending_invoices": 4,
        "pending_complete": 1,
        "pending_partial": 1,
        "errors": 1,
        "processing": 1,
        "pending_units": 36,
    }
    assert set(by_number) == {
        missing["invoice_number"],
        partial["invoice_number"],
        failed["invoice_number"],
        processing["invoice_number"],
    }
    assert by_number[missing["invoice_number"]]["status"] == "pending_complete"
    assert by_number[partial["invoice_number"]]["status"] == "pending_partial"
    assert by_number[partial["invoice_number"]]["lines"][0]["pending_units"] == 6
    assert by_number[failed["invoice_number"]]["error"] == (
        "No se pudo guardar el movimiento"
    )
    assert by_number[processing["invoice_number"]]["status"] == "processing"
    db.refresh(position)
    assert position.physical_confirmed == position_before
    assert len(db.scalars(select(InventoryMovement)).all()) == movement_count
    db.close()


def test_listing_orders_numeric_sequence_keeps_void_and_reports_gap() -> None:
    engine, db, user, _warehouse, _product, _position = database()
    register_invoice(payload(10), user, db, "sequence-10")
    void = Invoice(
        invoice_number="001-001-000000011",
        invoice_date=date(2026, 6, 17),
        source_type="other",
        customer_name="Cliente",
        chain_name="Cadena",
        administrative_status="cancelled",
        dispatch_status="not_applicable",
        delivery_status="not_applicable",
        inventory_status="not_applicable",
        created_by_user_id=user.id,
    )
    db.add(void)
    db.commit()
    register_invoice(payload(12), user, db, "sequence-12")
    register_invoice(payload(14), user, db, "sequence-14")
    query_count = 0

    def count_query(*_args):
        nonlocal query_count
        query_count += 1

    event.listen(engine, "before_cursor_execute", count_query)
    result = invoice_listing(
        user,
        db,
        search=None,
        purchase_order=None,
        chain=None,
        date_from=None,
        date_to=None,
        status=None,
        inventory_status=None,
        sort="sequence",
        page=1,
        page_size=25,
    )
    event.remove(engine, "before_cursor_execute", count_query)
    assert [item["invoice_number"] for item in result["items"]] == [
        "001-001-000000010",
        "001-001-000000011",
        "001-001-000000012",
        "001-001-000000014",
    ]
    assert result["items"][1]["administrative_status"] == "cancelled"
    assert result["missing_sequences"] == ["001-001-000000013"]
    assert query_count <= 6
    descending = invoice_listing(
        user,
        db,
        search=None,
        purchase_order=None,
        chain=None,
        date_from=None,
        date_to=None,
        status=None,
        inventory_status=None,
        sort="sequence_desc",
        page=1,
        page_size=25,
    )
    assert [item["invoice_number"] for item in descending["items"]] == [
        "001-001-000000014",
        "001-001-000000012",
        "001-001-000000011",
        "001-001-000000010",
    ]
    db.close()


def test_historical_inventory_uses_only_confirmed_movements_before_cutoff() -> None:
    _engine, db, user, warehouse, product, position = database()
    db.add_all(
        [
            InventoryMovement(
                warehouse_id=warehouse.id,
                product_id=product.id,
                actor_user_id=user.id,
                movement_type="bulk_physical_count",
                status="confirmed",
                quantity=100,
                reason="Saldo inicial",
                before_value={"physical_confirmed": 0},
                after_value={"physical_confirmed": 100},
                occurred_at=datetime(2026, 6, 17, 13, tzinfo=timezone.utc),
            ),
            InventoryMovement(
                warehouse_id=warehouse.id,
                product_id=product.id,
                actor_user_id=user.id,
                movement_type="invoice_registered",
                status="confirmed",
                quantity=10,
                reason="Salida",
                before_value={"physical_confirmed": 100},
                after_value={"physical_confirmed": 90},
                occurred_at=datetime(2026, 6, 18, 2, tzinfo=timezone.utc),
            ),
            InventoryMovement(
                warehouse_id=warehouse.id,
                product_id=product.id,
                actor_user_id=user.id,
                movement_type="physical_adjustment",
                status="confirmed",
                quantity=10,
                reason="Después del corte",
                before_value={"physical_confirmed": 90},
                after_value={"physical_confirmed": 80},
                occurred_at=datetime(2026, 6, 18, 6, tzinfo=timezone.utc),
            ),
        ]
    )
    position.physical_confirmed = 80
    db.commit()

    result = inventory_at_date(
        user,
        db,
        cutoff_date=date(2026, 6, 17),
        search="AUD-1",
        category=None,
        show_zero=True,
        show_negative=False,
        page=1,
        page_size=25,
    )
    item = result["items"][0]
    assert item["inventory_at_cutoff"] == 90
    assert item["current_inventory"] == 80
    assert item["difference"] == -10
    assert result["theoretical"] is True
    db.close()


def test_historical_inventory_accumulates_same_day_entries_adjustments_and_returns() -> (
    None
):
    _engine, db, user, warehouse, product, position = database()
    occurred_at = datetime(2026, 6, 17, 15, tzinfo=timezone.utc)
    movements = [
        InventoryMovement(
            id=uuid.UUID(int=index),
            warehouse_id=warehouse.id,
            product_id=product.id,
            actor_user_id=user.id,
            movement_type=movement_type,
            status=status,
            quantity=abs(after - before),
            reason=movement_type,
            before_value={"physical_confirmed": before},
            after_value={"physical_confirmed": after},
            occurred_at=occurred_at,
        )
        for index, movement_type, status, before, after in [
            (1, "bulk_physical_count", "confirmed", 0, 100),
            (2, "supplier_invoice_registered", "confirmed", 100, 130),
            (3, "invoice_registered", "confirmed", 130, 110),
            (4, "physical_adjustment", "confirmed", 110, 105),
            (5, "customer_return", "confirmed", 105, 108),
            (6, "general_exit", "pending", 108, 1),
        ]
    ]
    db.add_all(movements)
    position.physical_confirmed = 108
    db.commit()

    result = inventory_at_date(
        user,
        db,
        cutoff_date=date(2026, 6, 17),
        search="AUD-1",
        category=None,
        show_zero=True,
        show_negative=False,
        page=1,
        page_size=25,
    )
    ledger = historical_product_movements(
        product.id,
        user,
        db,
        cutoff_date=date(2026, 6, 17),
    )

    assert result["items"][0]["inventory_at_cutoff"] == 108
    assert result["items"][0]["difference"] == 0
    assert result["items"][0]["confirmed_physical_count"] == 100
    assert result["items"][0]["difference_vs_physical_count"] == 8
    assert [item["balance"] for item in ledger["items"]] == [
        100,
        130,
        110,
        105,
        108,
    ]
    assert [item["id"] for item in ledger["items"]] == [
        uuid.UUID(int=value) for value in range(1, 6)
    ]
    db.close()
