import uuid
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import utc_now
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.auth.infrastructure.models import User
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
    invoice_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=5, max_length=500)


PENDING_STATUS_LABELS = {
    "pending_complete": "Pendiente completa",
    "pending_partial": "Pendiente parcial",
    "error": "Error al descontar",
    "processing": "En procesamiento",
}


def _public_audit(item: dict) -> dict:
    return {key: value for key, value in item.items() if key != "product_differences"}


def _pending_status(invoice: Invoice, audit: dict) -> str:
    if invoice.inventory_status == "processing":
        return "processing"
    if (
        invoice.inventory_status == "error"
        or invoice.inventory_last_error
        or audit["status"] in {"error", "duplicate", "over", "product_incorrect"}
    ):
        return "error"
    if audit["status"] == "missing":
        return "pending_complete"
    return "pending_partial"


@router.get("/inventory-audit")
def invoice_inventory_audit(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    chain: Annotated[str | None, Query(max_length=160)] = None,
    product: Annotated[str | None, Query(max_length=160)] = None,
    status: Annotated[str | None, Query(max_length=40)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    problems_only: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=10, le=100)] = 25,
) -> dict:
    items = audit_invoices(db)
    product_ids = {
        difference["product_id"]
        for item in items
        for difference in item["product_differences"]
    }
    products = {
        product.id: product
        for product in db.scalars(
            select(Product).where(Product.id.in_(product_ids))
        ).all()
    }
    position_rows = db.execute(
        select(InventoryPositionModel)
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(
            InventoryPositionModel.product_id.in_(product_ids),
            Warehouse.code == "principal",
        )
    ).scalars()
    positions = {position.product_id: position for position in position_rows}
    invoice_ids = [item["id"] for item in items]
    metadata_rows = db.execute(
        select(Invoice, PurchaseOrder.order_number)
        .outerjoin(PurchaseOrder, PurchaseOrder.id == Invoice.purchase_order_id)
        .where(Invoice.id.in_(invoice_ids))
    ).all()
    metadata = {
        invoice.id: (invoice, order_number) for invoice, order_number in metadata_rows
    }
    movement_ids = {
        movement_id
        for item in items
        for difference in item["product_differences"]
        for movement_id in difference["movement_ids"]
    }
    movement_rows = (
        db.execute(
            select(InventoryMovement, User)
            .outerjoin(User, User.id == InventoryMovement.actor_user_id)
            .where(InventoryMovement.id.in_(movement_ids))
        ).all()
        if movement_ids
        else []
    )
    movements = {
        movement.id: {
            "id": movement.id,
            "occurred_at": movement.occurred_at,
            "responsible": user.full_name if user else "Usuario no disponible",
            "movement_type": movement.movement_type,
            "reason": movement.reason,
            "quantity": movement.quantity,
            "net_inventory_effect": (
                int(movement.after_value.get("physical_confirmed", 0))
                - int(movement.before_value.get("physical_confirmed", 0))
            ),
        }
        for movement, user in movement_rows
    }

    enriched = []
    for item in items:
        invoice, order_number = metadata[item["id"]]
        product_rows = []
        for difference in item["product_differences"]:
            catalog_product = products.get(difference["product_id"])
            if difference["expected"] == 0 and difference["discounted"] != 0:
                product_status = "product_incorrect"
            elif difference["difference"] == 0:
                product_status = "correct"
            elif difference["discounted"] == 0:
                product_status = "missing"
            elif difference["discounted"] > difference["expected"]:
                product_status = (
                    "duplicate" if difference["outbound_movements"] > 1 else "over"
                )
            else:
                product_status = "quantity_incorrect"
            product_rows.append(
                {
                    **difference,
                    "product_name": (
                        catalog_product.name
                        if catalog_product
                        else "Producto no disponible"
                    ),
                    "sku": catalog_product.sku if catalog_product else "—",
                    "expected_movement": -difference["expected"],
                    "found_movement": -difference["discounted"],
                    "pending_units": max(0, difference["difference"]),
                    "excess_units": max(0, -difference["difference"]),
                    "status": product_status,
                    "status_label": {
                        "correct": "Correcto",
                        "missing": "Sin descontar",
                        "quantity_incorrect": "Cantidad incorrecta",
                        "over": "Descuento excesivo",
                        "duplicate": "Movimiento duplicado",
                        "product_incorrect": "Producto incorrecto",
                    }[product_status],
                    "movements": [
                        movements[movement_id]
                        for movement_id in difference["movement_ids"]
                        if movement_id in movements
                    ],
                    "inventory_current": (
                        positions[difference["product_id"]].physical_confirmed
                        if difference["product_id"] in positions
                        else None
                    ),
                }
            )
        enriched.append(
            {
                **_public_audit(item),
                "customer_name": invoice.customer_name,
                "chain_name": invoice.chain_name,
                "purchase_order_id": invoice.purchase_order_id,
                "purchase_order_number": order_number,
                "dispatch_status": invoice.dispatch_status,
                "product_count": len(
                    [row for row in product_rows if row["expected"] > 0]
                ),
                "pending_units": sum(row["pending_units"] for row in product_rows),
                "excess_units": sum(row["excess_units"] for row in product_rows),
                "products": product_rows,
            }
        )

    if search and search.strip():
        value = search.strip().lower()
        enriched = [
            item
            for item in enriched
            if value in item["invoice_number"].lower()
            or value in (item["purchase_order_number"] or "").lower()
        ]
    if chain and chain.strip():
        value = chain.strip().lower()
        enriched = [
            item
            for item in enriched
            if value in (item["chain_name"] or item["customer_name"] or "").lower()
        ]
    if product and product.strip():
        value = product.strip().lower()
        enriched = [
            item
            for item in enriched
            if any(
                value in row["product_name"].lower() or value in row["sku"].lower()
                for row in item["products"]
            )
        ]
    if status:
        enriched = [item for item in enriched if item["status"] == status]
    if date_from:
        enriched = [item for item in enriched if item["invoice_date"] >= date_from]
    if date_to:
        enriched = [item for item in enriched if item["invoice_date"] <= date_to]
    if problems_only:
        enriched = [
            item
            for item in enriched
            if item["status"] not in {"correct", "cancelled_correct"}
        ]

    all_invoice_references = {
        reference
        for invoice, _ in metadata_rows
        for reference in (str(invoice.id), invoice.invoice_number)
    }
    orphan_rows = db.execute(
        select(InventoryMovement, Product, User)
        .join(Product, Product.id == InventoryMovement.product_id)
        .outerjoin(User, User.id == InventoryMovement.actor_user_id)
        .where(
            InventoryMovement.reference_type == "invoice",
            InventoryMovement.status == "confirmed",
        )
    ).all()
    orphan_movements = [
        {
            "id": movement.id,
            "reference": movement.reference_id,
            "occurred_at": movement.occurred_at,
            "product_name": catalog_product.name,
            "sku": catalog_product.sku,
            "responsible": user.full_name if user else "Usuario no disponible",
            "net_inventory_effect": (
                int(movement.after_value.get("physical_confirmed", 0))
                - int(movement.before_value.get("physical_confirmed", 0))
            ),
            "status": "movement_without_invoice",
            "status_label": "Movimiento sin factura",
        }
        for movement, catalog_product, user in orphan_rows
        if (movement.reference_id or "") not in all_invoice_references
    ]
    summary = audit_summary(enriched)
    summary.update(
        {
            "problem_invoices": sum(
                item["status"] not in {"correct", "cancelled_correct"}
                for item in enriched
            ),
            "excess_or_duplicate": sum(
                item["status"] in {"over", "duplicate"} for item in enriched
            ),
            "cancelled_incorrect": sum(
                item["status"] == "cancelled_missing_reversal" for item in enriched
            ),
            "requires_review": sum(
                item["status"] in {"error", "product_incorrect"} for item in enriched
            )
            + len(orphan_movements),
            "pending_units": sum(item["pending_units"] for item in enriched),
            "excess_units": sum(item["excess_units"] for item in enriched),
            "orphan_movements": len(orphan_movements),
        }
    )
    total = len(enriched)
    start = (page - 1) * page_size
    return {
        "summary": summary,
        "items": enriched[start : start + page_size],
        "total": total,
        "page": page,
        "pages": max(1, (total + page_size - 1) // page_size),
        "orphan_movements": orphan_movements,
        "read_only": True,
        "generated_at": datetime.now(timezone.utc),
    }


@router.get("/inventory-pending")
def pending_inventory_invoices(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    sequence: Annotated[str | None, Query(max_length=30)] = None,
    purchase_order: Annotated[str | None, Query(max_length=100)] = None,
    chain: Annotated[str | None, Query(max_length=160)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: Literal[
        "pending_complete",
        "pending_partial",
        "error",
        "processing",
    ]
    | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=10, le=100)] = 25,
) -> dict:
    candidate_statement = (
        select(Invoice.id)
        .outerjoin(PurchaseOrder, PurchaseOrder.id == Invoice.purchase_order_id)
        .where(Invoice.administrative_status != "cancelled")
        .order_by(
            Invoice.establishment_number,
            Invoice.emission_point,
            Invoice.sequential_number,
            Invoice.id,
        )
    )
    if search and search.strip():
        candidate_statement = candidate_statement.where(
            Invoice.invoice_number.ilike(f"%{search.strip()}%")
        )
    if sequence and sequence.strip():
        candidate_statement = candidate_statement.where(
            Invoice.invoice_number.ilike(f"%{sequence.strip()}%")
        )
    if purchase_order and purchase_order.strip():
        candidate_statement = candidate_statement.where(
            PurchaseOrder.order_number.ilike(f"%{purchase_order.strip()}%")
        )
    if chain and chain.strip():
        candidate_statement = candidate_statement.where(
            Invoice.chain_name.ilike(f"%{chain.strip()}%")
        )
    if date_from:
        candidate_statement = candidate_statement.where(
            Invoice.invoice_date >= date_from
        )
    if date_to:
        candidate_statement = candidate_statement.where(Invoice.invoice_date <= date_to)
    candidate_ids = list(db.scalars(candidate_statement).all())
    audited = audit_invoices(db, candidate_ids) if candidate_ids else []
    pending_audits = [
        item
        for item in audited
        if item["administrative_status"] != "cancelled"
        and any(
            difference["difference"] > 0 for difference in item["product_differences"]
        )
    ]
    metadata_rows = (
        db.execute(
            select(Invoice, PurchaseOrder.order_number)
            .outerjoin(PurchaseOrder, PurchaseOrder.id == Invoice.purchase_order_id)
            .where(Invoice.id.in_([item["id"] for item in pending_audits]))
        ).all()
        if pending_audits
        else []
    )
    metadata = {
        invoice.id: (invoice, order_number) for invoice, order_number in metadata_rows
    }
    product_ids = {
        difference["product_id"]
        for item in pending_audits
        for difference in item["product_differences"]
        if difference["expected"] > 0
    }
    products = {
        product.id: product
        for product in db.scalars(
            select(Product).where(Product.id.in_(product_ids))
        ).all()
    }
    items = []
    for audit in pending_audits:
        invoice, order_number = metadata[audit["id"]]
        pending_status = _pending_status(invoice, audit)
        if status and pending_status != status:
            continue
        lines = []
        for difference in audit["product_differences"]:
            if difference["expected"] <= 0:
                continue
            product = products.get(difference["product_id"])
            discounted = max(
                0,
                min(difference["expected"], difference["discounted"]),
            )
            lines.append(
                {
                    "product_id": difference["product_id"],
                    "product_name": product.name
                    if product
                    else "Producto no disponible",
                    "sku": product.sku if product else "—",
                    "invoiced_units": difference["expected"],
                    "discounted_units": discounted,
                    "pending_units": difference["expected"] - discounted,
                }
            )
        pending_units = sum(line["pending_units"] for line in lines)
        invoiced_units = sum(line["invoiced_units"] for line in lines)
        items.append(
            {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.invoice_date,
                "chain_name": invoice.chain_name or invoice.customer_name,
                "purchase_order_id": invoice.purchase_order_id,
                "purchase_order_number": order_number,
                "invoiced_units": invoiced_units,
                "discounted_units": invoiced_units - pending_units,
                "pending_units": pending_units,
                "status": pending_status,
                "status_label": PENDING_STATUS_LABELS[pending_status],
                "error": invoice.inventory_last_error,
                "attempts": invoice.inventory_attempts,
                "lines": lines,
            }
        )
    total = len(items)
    start = (page - 1) * page_size
    duplicate_findings = [
        _public_audit(item)
        for item in audited
        if item["status"] in {"duplicate", "over"}
    ]
    error_findings = [item for item in items if item["status"] == "error"]
    return {
        "summary": {
            "pending_invoices": total,
            "pending_complete": sum(
                item["status"] == "pending_complete" for item in items
            ),
            "pending_partial": sum(
                item["status"] == "pending_partial" for item in items
            ),
            "errors": sum(item["status"] == "error" for item in items),
            "processing": sum(item["status"] == "processing" for item in items),
            "pending_units": sum(item["pending_units"] for item in items),
        },
        "items": items[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
        "findings": {
            "possible_duplicates": duplicate_findings,
            "errors": [
                {
                    "id": item["id"],
                    "invoice_number": item["invoice_number"],
                    "error": item["error"],
                }
                for item in error_findings
            ],
        },
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
        if (
            item["status"] in {"missing", "partial"}
            and item["administrative_status"] != "cancelled"
        )
        or (
            item["status"] == "cancelled_missing_reversal"
            and all(
                0 <= difference["discounted"] <= difference["expected"]
                for difference in item["product_differences"]
            )
        )
        or (
            item["status"] == "over"
            and all(
                difference["outbound_movements"] <= 1
                for difference in item["product_differences"]
            )
        )
    ]
    blocked = [
        item
        for item in audited
        if item["status"] in {"duplicate", "error", "product_incorrect"}
        or (
            item["status"] == "over"
            and any(
                difference["outbound_movements"] > 1
                for difference in item["product_differences"]
            )
        )
        or (
            item["status"] == "cancelled_missing_reversal"
            and any(
                difference["discounted"] < 0
                or difference["discounted"] > difference["expected"]
                for difference in item["product_differences"]
            )
        )
    ]
    return {
        "correctable": [
            {
                **_public_audit(item),
                "units_to_discount": sum(
                    (
                        max(0, difference["discounted"])
                        if item["status"] == "cancelled_missing_reversal"
                        else max(0, -difference["difference"])
                        if item["status"] == "over"
                        else max(0, difference["difference"])
                    )
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
        is_reversal = fresh["status"] == "cancelled_missing_reversal" and all(
            0 <= item["discounted"] <= item["expected"]
            for item in fresh["product_differences"]
        )
        is_excess_reversal = fresh["status"] == "over" and all(
            item["outbound_movements"] <= 1 for item in fresh["product_differences"]
        )
        if (
            fresh["status"] not in {"missing", "partial"}
            and not is_reversal
            and not is_excess_reversal
        ) or invoice.inventory_status == "processing":
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
            {
                **item,
                "difference": (
                    item["discounted"]
                    if is_reversal
                    else -item["difference"]
                    if is_excess_reversal
                    else item["difference"]
                ),
            }
            for item in fresh["product_differences"]
            if (
                item["discounted"]
                if is_reversal
                else -item["difference"]
                if is_excess_reversal
                else item["difference"]
            )
            > 0
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
                or (
                    not is_reversal
                    and not is_excess_reversal
                    and positions[item["product_id"]][1].physical_confirmed
                    < item["difference"]
                )
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
                    "invoiced_not_dispatched": position.invoiced_not_dispatched,
                    "version": position.version,
                }
                position.physical_confirmed += (
                    difference["difference"]
                    if is_reversal or is_excess_reversal
                    else -difference["difference"]
                )
                if is_reversal:
                    position.invoiced_not_dispatched = max(
                        0,
                        position.invoiced_not_dispatched - difference["expected"],
                    )
                else:
                    position.invoiced_not_dispatched += difference["difference"]
                position.version += 1
                movement = InventoryMovement(
                    warehouse_id=warehouse.id,
                    product_id=product.id,
                    purchase_order_id=invoice.purchase_order_id,
                    actor_user_id=user.id,
                    movement_type=(
                        "invoice_cancelled"
                        if is_reversal
                        else "invoice_inventory_correction"
                    ),
                    reference_type="invoice",
                    reference_id=str(invoice.id),
                    idempotency_key=(
                        f"invoice-{'audit-reversal' if is_reversal else 'excess-reversal' if is_excess_reversal else 'correction'}:"
                        f"{invoice.id}:{product.id}:"
                        f"{difference['expected']}"
                    ),
                    quantity=difference["difference"],
                    reason=(
                        f"Reversión auditada de factura anulada: {payload.reason}"
                        if is_reversal
                        else f"Reversión auditada de exceso: {payload.reason}"
                        if is_excess_reversal
                        else f"Corrección auditada: {payload.reason}"
                    ),
                    before_value=before,
                    after_value={
                        "physical_confirmed": position.physical_confirmed,
                        "invoiced_not_dispatched": position.invoiced_not_dispatched,
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
                            - position.blocked_by_incident
                        ),
                    }
                )
            invoice.inventory_status = "reverted" if is_reversal else "discounted"
            invoice.inventory_discounted_quantity = (
                0 if is_reversal else fresh["invoiced_units"]
            )
            if is_reversal:
                invoice.inventory_reversed_at = utc_now()
            else:
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
                        "status": ("cancelled_correct" if is_reversal else "correct"),
                        "discounted_units": (
                            0 if is_reversal else fresh["invoiced_units"]
                        ),
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
        except SQLAlchemyError as caught:
            invoice_id = candidate["id"]
            invoice_number = candidate["invoice_number"]
            db.rollback()
            detail = str(caught)[:1000]
            failed_invoice = db.get(Invoice, invoice_id)
            if failed_invoice is not None:
                failed_invoice.inventory_status = "error"
                failed_invoice.inventory_last_error = detail
                failed_invoice.inventory_attempts += 1
                db.commit()
            results.append(
                {
                    "id": invoice_id,
                    "invoice_number": invoice_number,
                    "status": "error",
                    "detail": detail,
                }
            )
    return {
        "results": results,
        "processed": len(results),
        "corrected": sum(item["status"] == "corrected" for item in results),
        "errors": sum(item["status"] == "error" for item in results),
        "skipped": sum(item["status"] == "skipped" for item in results),
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
    sort: Literal["sequence", "sequence_desc", "recent"] = "sequence",
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
        "sequence_desc": (
            Invoice.establishment_number.desc(),
            Invoice.emission_point.desc(),
            Invoice.sequential_number.desc(),
            Invoice.id.desc(),
        ),
        "recent": (Invoice.invoice_date.desc(), Invoice.created_at.desc()),
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
        if inventory_status:
            accepted_statuses = (
                {
                    "error",
                    "duplicate",
                    "over",
                    "product_incorrect",
                    "cancelled_missing_reversal",
                }
                if inventory_status == "error"
                else {inventory_status}
            )
            if audit["status"] not in accepted_statuses:
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
    complete_audit = (
        list(audited.values())
        if not inventory_status and page == 1 and total <= page_size
        else audit_invoices(db)
    )
    active_audit = [
        item for item in complete_audit if item["administrative_status"] != "cancelled"
    ]
    return {
        "items": page_items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
        "missing_sequences": missing[:200],
        "summary": {
            "invoices": len(complete_audit),
            "missing": sum(item["status"] == "missing" for item in active_audit),
            "partial": sum(item["status"] == "partial" for item in active_audit),
            "errors": sum(
                item["status"] in {"error", "duplicate", "over", "product_incorrect"}
                for item in active_audit
            ),
            "discounted": sum(item["status"] == "correct" for item in active_audit),
            "cancelled": sum(
                item["administrative_status"] == "cancelled" for item in complete_audit
            ),
            "pending_units": sum(
                max(0, difference["difference"])
                for item in active_audit
                for difference in item["product_differences"]
            ),
        },
    }
