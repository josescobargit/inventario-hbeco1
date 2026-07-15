import uuid
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
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
from app.modules.returns.infrastructure.models import Return, ReturnLine


class LineInput(BaseModel):
    sku: str
    quantity: int = Field(gt=0)
    disposition: Literal[
        "available_warehouse",
        "available_floor",
        "blocked",
        "damaged",
        "in_review",
        "unusable",
    ]
    notes: str | None = None


class ReturnInput(BaseModel):
    invoice_id: uuid.UUID
    reason: str = Field(min_length=5, max_length=1000)
    lines: list[LineInput] = Field(min_length=1)


router = APIRouter(prefix="/returns", tags=["Devoluciones"])


@router.post("", status_code=201)
def register_return(
    payload: ReturnInput, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
):
    invoice = db.scalar(
        select(Invoice).where(Invoice.id == payload.invoice_id).with_for_update()
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="No encontramos la factura.")
    skus = [x.sku.strip().upper() for x in payload.lines]
    if len(set(skus)) != len(skus):
        raise HTTPException(
            status_code=422, detail="No repitas un SKU en la devolución."
        )
    rows = db.execute(
        select(InvoiceLine, Product, InventoryPositionModel)
        .join(Product, Product.id == InvoiceLine.product_id)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .where(InvoiceLine.invoice_id == invoice.id, Product.sku.in_(skus))
        .with_for_update(of=InventoryPositionModel)
    ).all()
    found = {p.sku: (line, p, pos) for line, p, pos in rows}
    if set(skus) != set(found):
        raise HTTPException(
            status_code=422,
            detail="La devolución contiene productos ajenos a la factura.",
        )
    item = Return(
        invoice_id=invoice.id,
        reason=payload.reason.strip(),
        registered_by_user_id=user.id,
    )
    db.add(item)
    db.flush()
    for report in payload.lines:
        line, product, pos = found[report.sku.strip().upper()]
        dispatched = db.scalar(
            select(func.coalesce(func.sum(DispatchLine.dispatched_quantity), 0))
            .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
            .where(
                Dispatch.invoice_id == invoice.id,
                DispatchLine.invoice_line_id == line.id,
            )
        )
        returned = db.scalar(
            select(func.coalesce(func.sum(ReturnLine.quantity), 0))
            .join(Return, Return.id == ReturnLine.return_id)
            .where(
                Return.invoice_id == invoice.id, ReturnLine.invoice_line_id == line.id
            )
        )
        if returned + report.quantity > dispatched:
            raise HTTPException(
                status_code=409,
                detail=f"{product.sku}: solo pueden devolverse {dispatched - returned} unidades.",
            )
        before = {
            "physical_confirmed": pos.physical_confirmed,
            "blocked_by_incident": pos.blocked_by_incident,
            "version": pos.version,
        }
        pos.physical_confirmed += report.quantity
        if report.disposition not in {"available_warehouse", "available_floor"}:
            pos.blocked_by_incident += report.quantity
            db.add(
                Incident(
                    incident_type="returned_product_review",
                    invoice_id=invoice.id,
                    purchase_order_id=invoice.purchase_order_id,
                    product_id=product.id,
                    affected_quantity=report.quantity,
                    description=report.notes or f"Devolución: {report.disposition}",
                    created_by_user_id=user.id,
                )
            )
            invoice.incident_status = "open"
        pos.version += 1
        db.add(
            ReturnLine(
                return_id=item.id,
                invoice_line_id=line.id,
                quantity=report.quantity,
                disposition=report.disposition,
                notes=report.notes,
            )
        )
        db.add(
            InventoryMovement(
                warehouse_id=pos.warehouse_id,
                product_id=pos.product_id,
                actor_user_id=user.id,
                movement_type="customer_return",
                reference_type="return",
                reference_id=str(item.id),
                reason=item.reason,
                before_value=before,
                after_value={
                    "physical_confirmed": pos.physical_confirmed,
                    "blocked_by_incident": pos.blocked_by_incident,
                    "version": pos.version,
                },
            )
        )
    db.flush()
    total_dispatched = db.scalar(
        select(func.coalesce(func.sum(DispatchLine.dispatched_quantity), 0))
        .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
        .where(Dispatch.invoice_id == invoice.id)
    )
    total_returned = db.scalar(
        select(func.coalesce(func.sum(ReturnLine.quantity), 0))
        .join(Return, Return.id == ReturnLine.return_id)
        .where(Return.invoice_id == invoice.id)
    )
    invoice.return_status = "total" if total_returned >= total_dispatched else "partial"
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="return_registered",
            entity_type="return",
            entity_id=str(item.id),
            reason=item.reason,
            new_value={"units": sum(x.quantity for x in payload.lines)},
        )
    )
    db.commit()
    return {
        "id": item.id,
        "invoice_number": invoice.invoice_number,
        "return_status": invoice.return_status,
        "incident_status": invoice.incident_status,
    }
