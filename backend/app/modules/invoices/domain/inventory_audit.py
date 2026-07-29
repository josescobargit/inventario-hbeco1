import uuid
from collections import defaultdict
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.inventory.infrastructure.models import InventoryMovement
from app.modules.invoices.infrastructure.models import Invoice, InvoiceLine


STATUS_LABELS = {
    "correct": "Descontado",
    "missing": "Pendiente de descontar",
    "partial": "Parcial",
    "duplicate": "Descuento duplicado",
    "over": "Movimiento superior a la factura",
    "cancelled_correct": "Revertido",
    "cancelled_missing_reversal": "Anulada sin reversión",
    "product_incorrect": "Producto incorrecto",
    "error": "Error",
}


def physical_exit(movement: InventoryMovement) -> int | None:
    if (
        "physical_confirmed" not in movement.before_value
        or "physical_confirmed" not in movement.after_value
    ):
        return None
    return int(movement.before_value["physical_confirmed"]) - int(
        movement.after_value["physical_confirmed"]
    )


def audit_invoices(
    db: Session, invoice_ids: Iterable[uuid.UUID] | None = None
) -> list[dict[str, Any]]:
    ids = list(invoice_ids or [])
    invoice_statement = select(Invoice).order_by(
        Invoice.establishment_number,
        Invoice.emission_point,
        Invoice.sequential_number,
        Invoice.id,
    )
    if ids:
        invoice_statement = invoice_statement.where(Invoice.id.in_(ids))
    invoices = list(db.scalars(invoice_statement).all())
    if not invoices:
        return []
    invoice_ids_loaded = [invoice.id for invoice in invoices]
    lines_by_invoice: dict[uuid.UUID, dict[uuid.UUID, int]] = defaultdict(dict)
    for line in db.scalars(
        select(InvoiceLine).where(InvoiceLine.invoice_id.in_(invoice_ids_loaded))
    ):
        lines_by_invoice[line.invoice_id][line.product_id] = (
            lines_by_invoice[line.invoice_id].get(line.product_id, 0) + line.quantity
        )
    id_lookup = {
        reference: invoice.id
        for invoice in invoices
        for reference in (str(invoice.id), invoice.invoice_number)
    }
    movements_by_invoice: dict[uuid.UUID, list[InventoryMovement]] = defaultdict(list)
    movements = db.scalars(
        select(InventoryMovement)
        .where(
            InventoryMovement.reference_type == "invoice",
            InventoryMovement.reference_id.in_(list(id_lookup)),
            InventoryMovement.status == "confirmed",
        )
        .order_by(InventoryMovement.occurred_at, InventoryMovement.id)
    ).all()
    for movement in movements:
        invoice_id = id_lookup.get(movement.reference_id or "")
        if invoice_id:
            movements_by_invoice[invoice_id].append(movement)

    audited: list[dict[str, Any]] = []
    for invoice in invoices:
        expected_by_product = lines_by_invoice[invoice.id]
        invoice_movements = movements_by_invoice[invoice.id]
        net_by_product: dict[uuid.UUID, int] = defaultdict(int)
        positive_count: dict[uuid.UUID, int] = defaultdict(int)
        gross_exit = 0
        gross_reversal = 0
        physical_movements = []
        for movement in invoice_movements:
            delta = physical_exit(movement)
            if delta is None:
                continue
            physical_movements.append(movement)
            net_by_product[movement.product_id] += delta
            if delta > 0:
                positive_count[movement.product_id] += 1
                gross_exit += delta
            elif delta < 0:
                gross_reversal += -delta
        expected_total = sum(expected_by_product.values())
        discounted_total = sum(net_by_product.values())
        product_differences = [
            {
                "product_id": product_id,
                "expected": expected_by_product.get(product_id, 0),
                "discounted": net_by_product.get(product_id, 0),
                "difference": expected_by_product.get(product_id, 0)
                - net_by_product.get(product_id, 0),
                "outbound_movements": positive_count.get(product_id, 0),
                "movement_ids": [
                    movement.id
                    for movement in physical_movements
                    if movement.product_id == product_id
                ],
            }
            for product_id in set(expected_by_product) | set(net_by_product)
        ]
        if invoice.administrative_status == "cancelled":
            if gross_exit == 0 or (
                all(value == 0 for value in net_by_product.values())
                and gross_reversal >= gross_exit
            ):
                status = "cancelled_correct"
            else:
                status = "cancelled_missing_reversal"
        elif not expected_by_product:
            status = "error"
        elif any(
            item["expected"] == 0 and item["discounted"] != 0
            for item in product_differences
        ):
            status = "product_incorrect"
        elif any(item["discounted"] > item["expected"] for item in product_differences):
            status = (
                "duplicate"
                if any(
                    item["discounted"] > item["expected"]
                    and item["outbound_movements"] > 1
                    for item in product_differences
                )
                else "over"
            )
        elif all(item["difference"] == 0 for item in product_differences):
            status = "correct"
        elif discounted_total == 0:
            status = "missing"
        elif all(item["difference"] >= 0 for item in product_differences):
            status = "partial"
        else:
            status = "error"
        discount_dates = [
            movement.occurred_at
            for movement in physical_movements
            if (physical_exit(movement) or 0) > 0
        ]
        audited.append(
            {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.invoice_date,
                "administrative_status": invoice.administrative_status,
                "invoiced_units": expected_total,
                "discounted_units": discounted_total,
                "difference": expected_total - discounted_total,
                "status": status,
                "status_label": STATUS_LABELS[status],
                "discounted_at": max(discount_dates) if discount_dates else None,
                "movement_ids": [movement.id for movement in physical_movements],
                "movement_count": len(physical_movements),
                "inventory_last_error": invoice.inventory_last_error,
                "inventory_attempts": invoice.inventory_attempts,
                "product_differences": product_differences,
            }
        )
    return audited


def audit_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "reviewed": len(items),
        "correct": sum(item["status"] == "correct" for item in items),
        "missing": sum(item["status"] == "missing" for item in items),
        "partial": sum(item["status"] == "partial" for item in items),
        "duplicate": sum(item["status"] == "duplicate" for item in items),
        "over": sum(item["status"] == "over" for item in items),
        "cancelled_correct": sum(
            item["status"] == "cancelled_correct" for item in items
        ),
        "cancelled_missing_reversal": sum(
            item["status"] == "cancelled_missing_reversal" for item in items
        ),
        "product_incorrect": sum(
            item["status"] == "product_incorrect" for item in items
        ),
        "errors": sum(item["status"] == "error" for item in items),
    }


def stored_inventory_status(audit_status: str) -> str:
    return {
        "correct": "discounted",
        "missing": "pending",
        "partial": "partial",
        "cancelled_correct": "reverted",
    }.get(audit_status, "error")
