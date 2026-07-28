import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.catalog.infrastructure.models import Product
from app.modules.deliveries.infrastructure.models import Delivery, DeliveryLine
from app.modules.dispatches.infrastructure.models import Dispatch, DispatchLine
from app.modules.documents.infrastructure.models import InvoiceAdjustment
from app.modules.incidents.infrastructure.models import Incident
from app.modules.invoices.infrastructure.models import (
    Invoice,
    InvoiceAlert,
    InvoiceLine,
)
from app.modules.purchase_orders.infrastructure.models import (
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.modules.returns.infrastructure.models import Return, ReturnLine

router = APIRouter(prefix="/invoices", tags=["Centro de Facturas"])


@router.get("/{invoice_id}/traceability")
def traceability(
    invoice_id: uuid.UUID, _user: CurrentUser, db: Annotated[Session, Depends(get_db)]
):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="No encontramos la factura.")
    po = (
        db.get(PurchaseOrder, invoice.purchase_order_id)
        if invoice.purchase_order_id
        else None
    )
    ordered = (
        {
            p.sku: line.ordered_quantity
            for line, p in db.execute(
                select(PurchaseOrderLine, Product)
                .join(Product, Product.id == PurchaseOrderLine.product_id)
                .where(PurchaseOrderLine.purchase_order_id == invoice.purchase_order_id)
            )
        }
        if po
        else {}
    )
    lines = []
    for line, product in db.execute(
        select(InvoiceLine, Product)
        .join(Product, Product.id == InvoiceLine.product_id)
        .where(InvoiceLine.invoice_id == invoice.id)
    ):
        dispatched, missing = db.execute(
            select(
                func.coalesce(func.sum(DispatchLine.dispatched_quantity), 0),
                func.coalesce(func.sum(DispatchLine.missing_quantity), 0),
            )
            .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
            .where(
                Dispatch.invoice_id == invoice.id,
                DispatchLine.invoice_line_id == line.id,
            )
        ).one()
        returned = db.scalar(
            select(func.coalesce(func.sum(ReturnLine.quantity), 0))
            .join(Return, Return.id == ReturnLine.return_id)
            .where(
                Return.invoice_id == invoice.id,
                ReturnLine.invoice_line_id == line.id,
            )
        )
        delivered, rejected = db.execute(
            select(
                func.coalesce(func.sum(DeliveryLine.delivered_quantity), 0),
                func.coalesce(func.sum(DeliveryLine.rejected_quantity), 0),
            )
            .join(Delivery, Delivery.id == DeliveryLine.delivery_id)
            .where(
                Delivery.invoice_id == invoice.id,
                DeliveryLine.invoice_line_id == line.id,
            )
        ).one()
        lines.append(
            {
                "sku": product.sku,
                "product_name": product.name,
                "ordered": ordered.get(product.sku),
                "invoiced": line.quantity,
                "dispatched": dispatched,
                "missing": missing,
                "delivered": delivered,
                "rejected_delivery": rejected,
                "returned": returned,
                "returnable": delivered - returned,
                "pending_dispatch": line.quantity - dispatched - missing,
                "pending_delivery": dispatched - delivered - rejected,
                "pending_confirmation": line.quantity - delivered,
                "delivery_difference": delivered - line.quantity,
                "outside_purchase_order": line.outside_purchase_order,
            }
        )
    adjustments = db.scalars(
        select(InvoiceAdjustment)
        .where(InvoiceAdjustment.invoice_id == invoice.id)
        .order_by(InvoiceAdjustment.document_date, InvoiceAdjustment.created_at)
    ).all()
    returns = []
    for item in db.scalars(
        select(Return)
        .where(Return.invoice_id == invoice.id)
        .order_by(Return.returned_at)
    ):
        return_lines = []
        for return_line, invoice_line, product in db.execute(
            select(ReturnLine, InvoiceLine, Product)
            .join(InvoiceLine, InvoiceLine.id == ReturnLine.invoice_line_id)
            .join(Product, Product.id == InvoiceLine.product_id)
            .where(ReturnLine.return_id == item.id)
        ):
            return_lines.append(
                {
                    "sku": product.sku,
                    "product_name": product.name,
                    "quantity": return_line.quantity,
                    "disposition": return_line.disposition,
                    "notes": return_line.notes,
                }
            )
        returns.append(
            {
                "id": item.id,
                "reason": item.reason,
                "returned_at": item.returned_at,
                "delivery_id": item.delivery_id,
                "lines": return_lines,
            }
        )
    credits = sum(
        (item.value for item in adjustments if item.document_type == "credit_note"),
        start=0,
    )
    debits = sum(
        (item.value for item in adjustments if item.document_type == "debit_note"),
        start=0,
    )
    return {
        "invoice": {
            "id": invoice.id,
            "number": invoice.invoice_number,
            "date": invoice.invoice_date,
            "customer": invoice.customer_name,
            "chain": invoice.chain_name,
            "source_type": invoice.source_type,
            "authorization_number": invoice.authorization_number,
            "remittance_guide": invoice.remittance_guide,
            "notes": invoice.notes,
            "total_value": invoice.total_value,
            "net_value": (invoice.total_value or 0) - credits + debits,
            "statuses": {
                "administrative": invoice.administrative_status,
                "dispatch": invoice.dispatch_status,
                "delivery": invoice.delivery_status,
                "incident": invoice.incident_status,
                "return": invoice.return_status,
            },
        },
        "purchase_order": {
            "id": po.id,
            "number": po.order_number,
            "chain": po.chain_name,
        }
        if po
        else None,
        "lines": lines,
        "deliveries": db.scalars(
            select(Delivery)
            .where(Delivery.invoice_id == invoice.id)
            .order_by(Delivery.delivered_at)
        ).all(),
        "incidents": db.scalars(
            select(Incident)
            .where(Incident.invoice_id == invoice.id)
            .order_by(Incident.created_at)
        ).all(),
        "alerts": db.scalars(
            select(InvoiceAlert).where(InvoiceAlert.invoice_id == invoice.id)
        ).all(),
        "returns": returns,
        "adjustments": adjustments,
    }
