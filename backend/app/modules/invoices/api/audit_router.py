import uuid
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import utc_now
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.infrastructure.models import (
    InventoryMovement,
    InventoryPositionModel,
    Warehouse,
)
from app.modules.invoices.domain.inventory_audit import (
    audit_invoices,
    audit_summary,
    stored_inventory_status,
)
from app.modules.invoices.infrastructure.models import Invoice, InvoiceLine
from app.modules.purchase_orders.infrastructure.models import PurchaseOrder


router = APIRouter(prefix="/invoices", tags=["Auditoría de facturas"])


class CorrectionInput(BaseModel):
    confirmation: Literal["CORREGIR"]
    invoice_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    reason: str = Field(min_length=5, max_length=500)


def _public_audit(item: dict) -> dict:
    return {key: value for key, value in item.items() if key != "product_differences"}


@router.get("/inventory-audit")
def invoice_inventory_audit(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    items = audit_invoices(db)
    return {
        "summary": audit_summary(items),
        "items": [_public_audit(item) for item in items],
        "read_only": True,
        "generated_at": datetime.now(timezone.utc),
    }


@router.get("/inventory-audit/correction-preview")
def correction_preview(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    audited = audit_invoices(db)
    safe = [
        item
        for item in audited
        if item["status"] in {"missing", "partial"}
        and item["administrative_status"] != "cancelled"
    ]
    blocked = [
        item
        for item in audited
        if item["status"]
        in {"duplicate", "over", "cancelled_missing_reversal", "error"}
    ]
    return {
        "correctable": [
            {
                **_public_audit(item),
                "units_to_discount": sum(
                    max(0, difference["difference"])
                    for difference in item["product_differences"]
                ),
            }
            for item in safe
        ],
        "blocked": [_public_audit(item) for item in blocked],
        "will_change_inventory": bool(safe),
    }


@router.post("/inventory-audit/corrections")
def correct_pending_movements(
    payload: CorrectionInput,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    requested_ids = set(payload.invoice_ids)
    candidates = audit_invoices(db, requested_ids or None)
    results = []
    inventory_affected: list[dict] = []
    for candidate in candidates:
        if requested_ids and candidate["id"] not in requested_ids:
            continue
        invoice = db.scalar(
            select(Invoice).where(Invoice.id == candidate["id"]).with_for_update()
        )
        if invoice is None:
            continue
        fresh = audit_invoices(db, [invoice.id])[0]
        invoice.inventory_attempts += 1
        if (
            fresh["status"] not in {"missing", "partial"}
            or invoice.administrative_status == "cancelled"
        ):
            invoice.inventory_status = stored_inventory_status(fresh["status"])
            invoice.inventory_last_error = (
                None
                if fresh["status"] in {"correct", "cancelled_correct"}
                else "La auditoría actual no permite una corrección automática."
            )
            db.commit()
            results.append(
                {
                    "id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "status": "skipped",
                    "detail": fresh["status_label"],
                }
            )
            continue
        differences = [
            item for item in fresh["product_differences"] if item["difference"] > 0
        ]
        product_ids = [item["product_id"] for item in differences]
        position_rows = db.execute(
            select(Product, InventoryPositionModel, Warehouse)
            .join(
                InventoryPositionModel,
                InventoryPositionModel.product_id == Product.id,
            )
            .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
            .where(
                Product.id.in_(product_ids),
                Warehouse.code == "principal",
            )
            .with_for_update(of=InventoryPositionModel)
        ).all()
        positions = {
            product.id: (product, position, warehouse)
            for product, position, warehouse in position_rows
        }
        unavailable = next(
            (
                item
                for item in differences
                if item["product_id"] not in positions
                or positions[item["product_id"]][1].physical_confirmed
                < item["difference"]
            ),
            None,
        )
        if unavailable:
            available = (
                positions[unavailable["product_id"]][1].physical_confirmed
                if unavailable["product_id"] in positions
                else 0
            )
            invoice.inventory_status = "error"
            invoice.inventory_last_error = (
                f"Se requieren {unavailable['difference']} unidades y hay "
                f"{available} disponibles para la corrección."
            )
            db.commit()
            results.append(
                {
                    "id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "status": "error",
                    "detail": invoice.inventory_last_error,
                }
            )
            continue
        created_movements = []
        candidate_effects = []
        try:
            for difference in differences:
                product, position, warehouse = positions[difference["product_id"]]
                before = {
                    "physical_confirmed": position.physical_confirmed,
                    "version": position.version,
                }
                position.physical_confirmed -= difference["difference"]
                position.version += 1
                movement = InventoryMovement(
                    warehouse_id=warehouse.id,
                    product_id=product.id,
                    purchase_order_id=invoice.purchase_order_id,
                    actor_user_id=user.id,
                    movement_type="invoice_inventory_correction",
                    reference_type="invoice",
                    reference_id=str(invoice.id),
                    idempotency_key=(
                        f"invoice-correction:{invoice.id}:{product.id}:"
                        f"{difference['expected']}"
                    ),
                    quantity=difference["difference"],
                    reason=f"Corrección auditada: {payload.reason}",
                    before_value=before,
                    after_value={
                        "physical_confirmed": position.physical_confirmed,
                        "version": position.version,
                    },
                )
                db.add(movement)
                db.flush()
                created_movements.append(movement)
                candidate_effects.append(
                    {
                        "sku": product.sku,
                        "physical_confirmed": position.physical_confirmed,
                        "available_to_invoice": (
                            position.physical_confirmed
                            - position.reserved
                            - position.invoiced_not_dispatched
                            - position.blocked_by_incident
                        ),
                    }
                )
            invoice.inventory_status = "discounted"
            invoice.inventory_discounted_quantity = fresh["invoiced_units"]
            invoice.inventory_applied_at = invoice.inventory_applied_at or utc_now()
            invoice.inventory_movement_id = (
                created_movements[0].id
                if created_movements
                else invoice.inventory_movement_id
            )
            invoice.inventory_last_error = None
            db.add(
                AuditLog(
                    actor_user_id=user.id,
                    action="invoice_inventory_corrected",
                    entity_type="invoice",
                    entity_id=str(invoice.id),
                    reason=payload.reason,
                    previous_value={
                        "status": fresh["status"],
                        "discounted_units": fresh["discounted_units"],
                    },
                    new_value={
                        "status": "correct",
                        "discounted_units": fresh["invoiced_units"],
                        "movement_ids": [
                            str(movement.id) for movement in created_movements
                        ],
                    },
                )
            )
            db.commit()
            inventory_affected.extend(candidate_effects)
            results.append(
                {
                    "id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "status": "corrected",
                    "units_discounted": sum(
                        movement.quantity or 0 for movement in created_movements
                    ),
                }
            )
        except IntegrityError:
            invoice_id = candidate["id"]
            invoice_number = candidate["invoice_number"]
            db.rollback()
            results.append(
                {
                    "id": invoice_id,
                    "invoice_number": invoice_number,
                    "status": "skipped",
                    "detail": "La corrección ya había sido aplicada.",
                }
            )
    return {
        "results": results,
        "corrected": sum(item["status"] == "corrected" for item in results),
        "errors": sum(item["status"] == "error" for item in results),
        "inventory_affected": inventory_affected,
    }


@router.get("/listing")
def invoice_listing(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    purchase_order: Annotated[str | None, Query(max_length=100)] = None,
    chain: Annotated[str | None, Query(max_length=160)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: Annotated[str | None, Query(max_length=30)] = None,
    inventory_status: Annotated[str | None, Query(max_length=40)] = None,
    sort: Literal["sequence", "recent", "oldest"] = "sequence",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=10, le=100)] = 25,
) -> dict:
    line_totals = (
        select(
            InvoiceLine.invoice_id.label("invoice_id"),
            func.count(InvoiceLine.id).label("product_count"),
            func.coalesce(func.sum(InvoiceLine.quantity), 0).label("units"),
        )
        .group_by(InvoiceLine.invoice_id)
        .subquery()
    )
    statement = (
        select(
            Invoice,
            PurchaseOrder.order_number,
            func.coalesce(line_totals.c.product_count, 0),
            func.coalesce(line_totals.c.units, 0),
        )
        .outerjoin(PurchaseOrder, PurchaseOrder.id == Invoice.purchase_order_id)
        .outerjoin(line_totals, line_totals.c.invoice_id == Invoice.id)
    )
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Invoice.invoice_number.ilike(term),
                Invoice.customer_name.ilike(term),
                Invoice.chain_name.ilike(term),
            )
        )
    if purchase_order and purchase_order.strip():
        statement = statement.where(
            PurchaseOrder.order_number.ilike(f"%{purchase_order.strip()}%")
        )
    if chain and chain.strip():
        statement = statement.where(Invoice.chain_name == chain.strip())
    if date_from:
        statement = statement.where(Invoice.invoice_date >= date_from)
    if date_to:
        statement = statement.where(Invoice.invoice_date <= date_to)
    if status and status.strip():
        statement = statement.where(Invoice.administrative_status == status.strip())
    ordering = {
        "sequence": (
            Invoice.establishment_number,
            Invoice.emission_point,
            Invoice.sequential_number,
            Invoice.id,
        ),
        "recent": (Invoice.invoice_date.desc(), Invoice.created_at.desc()),
        "oldest": (Invoice.invoice_date, Invoice.created_at),
    }[sort]
    if inventory_status:
        rows = list(db.execute(statement.order_by(*ordering)).all())
    else:
        total = (
            db.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        rows = list(
            db.execute(
                statement.order_by(*ordering)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
    audited = {
        item["id"]: item for item in audit_invoices(db, [row[0].id for row in rows])
    }
    enriched = []
    for invoice, order_number, product_count, units in rows:
        audit = audited[invoice.id]
        if inventory_status and audit["status"] != inventory_status:
            continue
        enriched.append(
            {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.invoice_date,
                "chain_name": invoice.chain_name,
                "customer_name": invoice.customer_name,
                "purchase_order_id": invoice.purchase_order_id,
                "purchase_order_number": order_number,
                "product_count": product_count,
                "units": units,
                "administrative_status": invoice.administrative_status,
                "dispatch_status": invoice.dispatch_status,
                "delivery_status": invoice.delivery_status,
                "inventory": _public_audit(audit),
            }
        )
    all_sequences = db.execute(
        select(
            Invoice.establishment_number,
            Invoice.emission_point,
            Invoice.sequential_number,
        ).order_by(
            Invoice.establishment_number,
            Invoice.emission_point,
            Invoice.sequential_number,
        )
    ).all()
    missing = []
    previous_by_prefix: dict[tuple[str, str], int] = {}
    for establishment, emission, sequential in all_sequences:
        prefix = (establishment, emission)
        previous = previous_by_prefix.get(prefix)
        if previous is not None and sequential > previous + 1:
            missing.extend(
                f"{establishment}-{emission}-{value:09d}"
                for value in range(previous + 1, sequential)
            )
        previous_by_prefix[prefix] = sequential
    if inventory_status:
        total = len(enriched)
        start = (page - 1) * page_size
        page_items = enriched[start : start + page_size]
    else:
        page_items = enriched
    return {
        "items": page_items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
        "missing_sequences": missing[:200],
    }
