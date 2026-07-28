import uuid
from datetime import datetime
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.catalog.infrastructure.models import Product
from app.modules.deliveries.infrastructure.models import Delivery, DeliveryLine
from app.modules.dispatches.infrastructure.models import Dispatch, DispatchLine
from app.modules.incidents.infrastructure.models import Incident
from app.modules.invoices.infrastructure.models import Invoice, InvoiceLine


class DeliveryLineInput(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    delivered_quantity: int = Field(ge=0)
    rejected_quantity: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def reported(self):
        if self.delivered_quantity + self.rejected_quantity <= 0:
            raise ValueError("Reporta una cantidad recibida o rechazada.")
        if self.rejected_quantity and not self.notes:
            raise ValueError("Explica por qué el cliente rechazó unidades.")
        return self


class DeliveryInput(BaseModel):
    invoice_id: uuid.UUID
    delivered_at: datetime | None = None
    delivery_type: Literal["without_issue", "confirmed", "with_issue"]
    recipient: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[DeliveryLineInput] = Field(min_length=1)


router = APIRouter(prefix="/deliveries", tags=["Entregas"])


@router.post("", status_code=201)
def register_delivery(
    payload: DeliveryInput, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
):
    invoice = db.scalar(
        select(Invoice).where(Invoice.id == payload.invoice_id).with_for_update()
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="No encontramos la factura.")
    if invoice.administrative_status != "confirmed":
        raise HTTPException(status_code=409, detail="La factura no está activa.")
    dispatched = db.scalar(
        select(func.coalesce(func.sum(DispatchLine.dispatched_quantity), 0))
        .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
        .where(Dispatch.invoice_id == invoice.id)
    )
    if dispatched <= 0:
        raise HTTPException(
            status_code=409,
            detail="No puede registrarse una entrega sin unidades despachadas.",
        )
    skus = [line.sku.strip().upper() for line in payload.lines]
    if len(set(skus)) != len(skus):
        raise HTTPException(status_code=422, detail="No repitas un SKU en la entrega.")
    invoice_rows = db.execute(
        select(InvoiceLine, Product)
        .join(Product, Product.id == InvoiceLine.product_id)
        .where(InvoiceLine.invoice_id == invoice.id, Product.sku.in_(skus))
    ).all()
    found = {product.sku: (line, product) for line, product in invoice_rows}
    if set(skus) != set(found):
        raise HTTPException(
            status_code=422,
            detail="La entrega contiene productos que no están en la factura.",
        )
    item = Delivery(
        invoice_id=invoice.id,
        delivery_type=payload.delivery_type,
        recipient=payload.recipient,
        notes=payload.notes,
        registered_by_user_id=user.id,
    )
    if payload.delivered_at is not None:
        item.delivered_at = payload.delivered_at
    db.add(item)
    db.flush()
    rejected_total = 0
    delivered_total = 0
    for report in payload.lines:
        invoice_line, product = found[report.sku.strip().upper()]
        dispatched_for_line = db.scalar(
            select(func.coalesce(func.sum(DispatchLine.dispatched_quantity), 0))
            .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
            .where(
                Dispatch.invoice_id == invoice.id,
                DispatchLine.invoice_line_id == invoice_line.id,
            )
        )
        already_reported = db.scalar(
            select(
                func.coalesce(
                    func.sum(
                        DeliveryLine.delivered_quantity + DeliveryLine.rejected_quantity
                    ),
                    0,
                )
            )
            .join(Delivery, Delivery.id == DeliveryLine.delivery_id)
            .where(
                Delivery.invoice_id == invoice.id,
                DeliveryLine.invoice_line_id == invoice_line.id,
            )
        )
        pending_delivery = dispatched_for_line - already_reported
        reported = report.delivered_quantity + report.rejected_quantity
        if reported > pending_delivery:
            raise HTTPException(
                status_code=409,
                detail=f"{product.sku}: quedan {pending_delivery} unidades pendientes de entrega y se intentan reportar {reported}.",
            )
        delivered_total += report.delivered_quantity
        rejected_total += report.rejected_quantity
        db.add(
            DeliveryLine(
                delivery_id=item.id,
                invoice_line_id=invoice_line.id,
                delivered_quantity=report.delivered_quantity,
                rejected_quantity=report.rejected_quantity,
                notes=report.notes,
            )
        )
    db.flush()
    total_delivered_or_rejected = db.scalar(
        select(
            func.coalesce(
                func.sum(
                    DeliveryLine.delivered_quantity + DeliveryLine.rejected_quantity
                ),
                0,
            )
        )
        .join(Delivery, Delivery.id == DeliveryLine.delivery_id)
        .where(Delivery.invoice_id == invoice.id)
    )
    if total_delivered_or_rejected < dispatched:
        invoice.delivery_status = "partial_delivery"
    else:
        invoice.delivery_status = {
            "without_issue": "delivered_without_issue",
            "confirmed": "delivered_confirmed",
            "with_issue": "delivered_with_issue",
        }[payload.delivery_type]
    if payload.delivery_type == "with_issue" or rejected_total:
        if not payload.notes:
            raise HTTPException(
                status_code=422, detail="Describe la novedad de entrega."
            )
        db.add(
            Incident(
                incident_type="delivery_issue",
                invoice_id=invoice.id,
                purchase_order_id=invoice.purchase_order_id,
                affected_quantity=rejected_total or None,
                description=payload.notes,
                created_by_user_id=user.id,
            )
        )
        invoice.incident_status = "open"
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="delivery_registered",
            entity_type="delivery",
            entity_id=str(item.id),
            new_value={
                "invoice": invoice.invoice_number,
                "type": payload.delivery_type,
                "delivered_units": delivered_total,
                "rejected_units": rejected_total,
            },
        )
    )
    db.commit()
    return {
        "id": item.id,
        "invoice_number": invoice.invoice_number,
        "delivery_status": invoice.delivery_status,
    }
