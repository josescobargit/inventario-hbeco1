import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.catalog.infrastructure.models import Product
from app.modules.deliveries.infrastructure.models import DeliveryLine
from app.modules.dispatches.infrastructure.models import DispatchLine
from app.modules.invoices.infrastructure.models import Invoice, InvoiceLine
from app.modules.purchase_orders.infrastructure.models import (
    PurchaseOrder,
    PurchaseOrderLine,
)


router = APIRouter(prefix="/comparisons", tags=["Comparativos"])


@dataclass
class ComparisonAccumulator:
    chain_name: str | None
    customer_name: str | None
    order_number: str | None
    order_date: date | None
    source_type: str
    sku: str
    product_name: str
    ordered_quantity: int = 0
    invoiced_quantity: int = 0
    dispatched_quantity: int = 0
    delivered_quantity: int = 0
    rejected_delivery_quantity: int = 0
    missing_quantity: int = 0
    invoice_numbers: set[str] = field(default_factory=set)
    delivery_statuses: set[str] = field(default_factory=set)
    outside_purchase_order: bool = False


def status_for(row: ComparisonAccumulator) -> str:
    if row.missing_quantity > 0:
        return "with_incident"
    if row.ordered_quantity and row.invoiced_quantity < row.ordered_quantity:
        return "pending_invoice"
    if row.invoiced_quantity and (
        row.dispatched_quantity + row.missing_quantity < row.invoiced_quantity
    ):
        return "pending_dispatch"
    if row.dispatched_quantity and (
        row.delivered_quantity + row.rejected_delivery_quantity
        < row.dispatched_quantity
    ):
        return "pending_delivery"
    if row.outside_purchase_order:
        return "outside_purchase_order"
    return "ok"


def serialize(row: ComparisonAccumulator) -> dict:
    pending_to_invoice = max(row.ordered_quantity - row.invoiced_quantity, 0)
    pending_to_dispatch = max(
        row.invoiced_quantity - row.dispatched_quantity - row.missing_quantity, 0
    )
    pending_to_deliver = max(
        row.dispatched_quantity
        - row.delivered_quantity
        - row.rejected_delivery_quantity,
        0,
    )
    return {
        "chain_name": row.chain_name,
        "customer_name": row.customer_name,
        "order_number": row.order_number,
        "order_date": row.order_date,
        "source_type": row.source_type,
        "sku": row.sku,
        "product_name": row.product_name,
        "ordered_quantity": row.ordered_quantity,
        "invoiced_quantity": row.invoiced_quantity,
        "dispatched_quantity": row.dispatched_quantity,
        "delivered_quantity": row.delivered_quantity,
        "rejected_delivery_quantity": row.rejected_delivery_quantity,
        "missing_quantity": row.missing_quantity,
        "pending_to_invoice": pending_to_invoice,
        "pending_to_dispatch": pending_to_dispatch,
        "pending_to_deliver": pending_to_deliver,
        "invoice_numbers": sorted(row.invoice_numbers),
        "delivery_statuses": sorted(row.delivery_statuses),
        "outside_purchase_order": row.outside_purchase_order,
        "status": status_for(row),
    }


@router.get("")
def list_comparisons(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[str | None, Query(max_length=120)] = None,
    chain: Annotated[str | None, Query(max_length=160)] = None,
    status: Annotated[str | None, Query(max_length=40)] = None,
) -> list[dict]:
    rows: dict[tuple[uuid.UUID | str, uuid.UUID], ComparisonAccumulator] = {}

    order_lines = db.execute(
        select(PurchaseOrder, PurchaseOrderLine, Product)
        .join(
            PurchaseOrderLine, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id
        )
        .join(Product, Product.id == PurchaseOrderLine.product_id)
        .order_by(PurchaseOrder.created_at.desc(), Product.sku)
    ).all()
    for order, line, product in order_lines:
        rows[(order.id, product.id)] = ComparisonAccumulator(
            chain_name=order.chain_name,
            customer_name=order.customer_name,
            order_number=order.order_number,
            order_date=order.order_date,
            source_type="purchase_order",
            sku=product.sku,
            product_name=product.name,
            ordered_quantity=line.ordered_quantity,
        )

    dispatch_totals: dict[uuid.UUID, tuple[int, int]] = {}
    for invoice_line_id, dispatched, missing in db.execute(
        select(
            DispatchLine.invoice_line_id,
            DispatchLine.dispatched_quantity,
            DispatchLine.missing_quantity,
        )
    ).all():
        previous_dispatched, previous_missing = dispatch_totals.get(
            invoice_line_id, (0, 0)
        )
        dispatch_totals[invoice_line_id] = (
            previous_dispatched + dispatched,
            previous_missing + missing,
        )

    delivery_totals: dict[uuid.UUID, tuple[int, int]] = {}
    for invoice_line_id, delivered, rejected in db.execute(
        select(
            DeliveryLine.invoice_line_id,
            DeliveryLine.delivered_quantity,
            DeliveryLine.rejected_quantity,
        )
    ).all():
        previous_delivered, previous_rejected = delivery_totals.get(
            invoice_line_id, (0, 0)
        )
        delivery_totals[invoice_line_id] = (
            previous_delivered + delivered,
            previous_rejected + rejected,
        )

    invoice_lines = db.execute(
        select(Invoice, InvoiceLine, Product)
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .join(Product, Product.id == InvoiceLine.product_id)
        .order_by(Invoice.created_at.desc(), Product.sku)
    ).all()
    for invoice, line, product in invoice_lines:
        key: tuple[uuid.UUID | str, uuid.UUID]
        if invoice.purchase_order_id:
            key = (invoice.purchase_order_id, product.id)
        else:
            key = (f"invoice:{invoice.id}", product.id)
        if key not in rows:
            rows[key] = ComparisonAccumulator(
                chain_name=invoice.chain_name,
                customer_name=invoice.customer_name,
                order_number=None,
                order_date=None,
                source_type=invoice.source_type,
                sku=product.sku,
                product_name=product.name,
                outside_purchase_order=bool(invoice.purchase_order_id),
            )
        row = rows[key]
        row.invoiced_quantity += line.quantity
        row.invoice_numbers.add(invoice.invoice_number)
        row.delivery_statuses.add(invoice.delivery_status)
        row.outside_purchase_order = (
            row.outside_purchase_order or line.outside_purchase_order
        )
        dispatched, missing = dispatch_totals.get(line.id, (0, 0))
        row.dispatched_quantity += dispatched
        row.missing_quantity += missing
        delivered, rejected = delivery_totals.get(line.id, (0, 0))
        row.delivered_quantity += delivered
        row.rejected_delivery_quantity += rejected

    result = [serialize(row) for row in rows.values()]
    if search and search.strip():
        term = search.strip().lower()
        result = [
            row
            for row in result
            if term in row["sku"].lower()
            or term in row["product_name"].lower()
            or term in (row["order_number"] or "").lower()
            or any(term in number.lower() for number in row["invoice_numbers"])
        ]
    if chain and chain.strip():
        term = chain.strip().lower()
        result = [row for row in result if term in (row["chain_name"] or "").lower()]
    if status and status.strip():
        result = [row for row in result if row["status"] == status.strip()]

    return sorted(
        result,
        key=lambda row: (
            row["chain_name"] or "",
            row["order_number"] or "",
            row["sku"],
        ),
    )
