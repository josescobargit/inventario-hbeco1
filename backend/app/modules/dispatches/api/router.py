import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.catalog.infrastructure.models import Product
from app.modules.dispatches.infrastructure.models import Dispatch, DispatchLine
from app.modules.incidents.infrastructure.models import Incident
from app.modules.inventory.infrastructure.models import (
    InventoryMovement,
    InventoryPositionModel,
)
from app.modules.invoices.infrastructure.models import Invoice, InvoiceLine


class DispatchLineInput(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    dispatched_quantity: int = Field(ge=0)
    missing_quantity: int = Field(ge=0)
    missing_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def reported(self):
        if self.dispatched_quantity + self.missing_quantity <= 0:
            raise ValueError("Reporta una cantidad despachada o faltante.")
        if self.missing_quantity and not self.missing_reason:
            raise ValueError("Explica el motivo del faltante.")
        return self


class DispatchInput(BaseModel):
    invoice_id: uuid.UUID
    responsible_name: str = Field(min_length=2, max_length=160)
    recipient: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[DispatchLineInput] = Field(min_length=1)


router = APIRouter(prefix="/dispatches", tags=["Despachos"])


@router.get("/pending")
def pending(_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    invoices = db.scalars(
        select(Invoice)
        .where(Invoice.dispatch_status.in_(["pending", "partial"]))
        .order_by(Invoice.invoice_date)
    ).all()
    return [
        {
            "id": item.id,
            "invoice_number": item.invoice_number,
            "customer_name": item.customer_name,
            "dispatch_status": item.dispatch_status,
        }
        for item in invoices
    ]


@router.post("", status_code=201)
def confirm_dispatch(
    payload: DispatchInput, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
):
    invoice = db.scalar(
        select(Invoice).where(Invoice.id == payload.invoice_id).with_for_update()
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="No encontramos la factura.")
    if invoice.administrative_status != "confirmed":
        raise HTTPException(status_code=409, detail="La factura no está activa.")
    skus = [line.sku.strip().upper() for line in payload.lines]
    if len(set(skus)) != len(skus):
        raise HTTPException(status_code=422, detail="No repitas un SKU en el despacho.")
    invoice_rows = db.execute(
        select(InvoiceLine, Product, InventoryPositionModel)
        .join(Product, Product.id == InvoiceLine.product_id)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .where(InvoiceLine.invoice_id == invoice.id, Product.sku.in_(skus))
        .with_for_update(of=InventoryPositionModel)
    ).all()
    found = {
        product.sku: (line, product, position)
        for line, product, position in invoice_rows
    }
    if set(skus) != set(found):
        raise HTTPException(
            status_code=422,
            detail="El despacho contiene productos que no están en la factura.",
        )
    dispatch = Dispatch(
        invoice_id=invoice.id,
        responsible_name=payload.responsible_name,
        recipient=payload.recipient,
        notes=payload.notes,
        confirmed_by_user_id=user.id,
    )
    db.add(dispatch)
    db.flush()
    for report in payload.lines:
        invoice_line, product, position = found[report.sku.strip().upper()]
        prior = db.execute(
            select(
                func.coalesce(func.sum(DispatchLine.dispatched_quantity), 0),
                func.coalesce(func.sum(DispatchLine.missing_quantity), 0),
            )
            .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
            .where(
                Dispatch.invoice_id == invoice.id,
                DispatchLine.invoice_line_id == invoice_line.id,
            )
        ).one()
        remaining = invoice_line.quantity - prior[0] - prior[1]
        reported = report.dispatched_quantity + report.missing_quantity
        if reported > remaining:
            raise HTTPException(
                status_code=409,
                detail=f"{product.sku}: quedan {remaining} unidades pendientes y se intentan reportar {reported}.",
            )
        legacy_inventory = invoice.inventory_applied_at is None
        if legacy_inventory and report.dispatched_quantity > position.physical_confirmed:
            raise HTTPException(
                status_code=409,
                detail=f"{product.sku}: el despacho dejaría stock físico negativo.",
            )
        line = DispatchLine(
            dispatch_id=dispatch.id,
            invoice_line_id=invoice_line.id,
            dispatched_quantity=report.dispatched_quantity,
            missing_quantity=report.missing_quantity,
            missing_reason=report.missing_reason,
        )
        db.add(line)
        if report.missing_quantity:
            db.add(
                Incident(
                    incident_type=(
                        "missing_stock" if legacy_inventory else "delivery_issue"
                    ),
                    invoice_id=invoice.id,
                    purchase_order_id=invoice.purchase_order_id,
                    product_id=product.id,
                    affected_quantity=report.missing_quantity,
                    description=report.missing_reason,
                    created_by_user_id=user.id,
                )
            )
            invoice.incident_status = "open"
        if legacy_inventory:
            before = {
                "physical_confirmed": position.physical_confirmed,
                "invoiced_not_dispatched": position.invoiced_not_dispatched,
                "blocked_by_incident": position.blocked_by_incident,
                "version": position.version,
            }
            position.physical_confirmed -= report.dispatched_quantity
            position.invoiced_not_dispatched -= reported
            position.blocked_by_incident += report.missing_quantity
            position.version += 1
            db.add(
                InventoryMovement(
                    warehouse_id=position.warehouse_id,
                    product_id=product.id,
                    purchase_order_id=invoice.purchase_order_id,
                    actor_user_id=user.id,
                    movement_type="dispatch_confirmed",
                    reference_type="dispatch",
                    reference_id=str(dispatch.id),
                    quantity=reported,
                    reason=payload.notes or "Despacho confirmado",
                    before_value=before,
                    after_value={
                        "physical_confirmed": position.physical_confirmed,
                        "invoiced_not_dispatched": position.invoiced_not_dispatched,
                        "blocked_by_incident": position.blocked_by_incident,
                        "version": position.version,
                    },
                )
            )
    db.flush()
    invoice_total = db.scalar(
        select(func.coalesce(func.sum(InvoiceLine.quantity), 0)).where(
            InvoiceLine.invoice_id == invoice.id
        )
    )
    resolved = db.execute(
        select(
            func.coalesce(
                func.sum(
                    DispatchLine.dispatched_quantity + DispatchLine.missing_quantity
                ),
                0,
            )
        )
        .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
        .where(Dispatch.invoice_id == invoice.id)
    ).scalar_one()
    invoice.dispatch_status = "complete" if resolved >= invoice_total else "partial"
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="dispatch_confirmed",
            entity_type="dispatch",
            entity_id=str(dispatch.id),
            new_value={
                "invoice": invoice.invoice_number,
                "reported_units": sum(
                    x.dispatched_quantity + x.missing_quantity for x in payload.lines
                ),
            },
        )
    )
    db.commit()
    return {
        "id": dispatch.id,
        "invoice_number": invoice.invoice_number,
        "dispatch_status": invoice.dispatch_status,
        "incident_status": invoice.incident_status,
    }
