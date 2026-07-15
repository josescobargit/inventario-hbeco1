import uuid
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.catalog.infrastructure.models import Product
from app.modules.incidents.infrastructure.models import Incident
from app.modules.inventory.infrastructure.models import (
    InventoryMovement,
    InventoryPositionModel,
)
from app.modules.invoices.infrastructure.models import Invoice


class Resolution(BaseModel):
    decision: Literal["found_available", "retry_dispatch", "confirm_physical_shortage"]
    reason: str = Field(min_length=5, max_length=1000)


router = APIRouter(prefix="/incidents", tags=["Incidencias"])


@router.get("")
def list_incidents(_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    rows = db.execute(
        select(Incident, Invoice, Product)
        .outerjoin(Invoice, Invoice.id == Incident.invoice_id)
        .outerjoin(Product, Product.id == Incident.product_id)
        .order_by(Incident.created_at.desc())
    ).all()
    return [
        {
            "id": incident.id,
            "incident_type": incident.incident_type,
            "invoice_id": incident.invoice_id,
            "invoice_number": invoice.invoice_number if invoice else None,
            "sku": product.sku if product else None,
            "product_name": product.name if product else None,
            "affected_quantity": incident.affected_quantity,
            "description": incident.description,
            "status": incident.status,
            "responsible_name": incident.responsible_name,
            "decision": incident.decision,
            "created_at": incident.created_at,
            "can_resolve_inventory": bool(
                incident.incident_type == "missing_stock"
                and incident.product_id
                and incident.affected_quantity
            ),
        }
        for incident, invoice, product in rows
    ]


@router.post("/{incident_id}/resolve")
def resolve_incident(
    incident_id: uuid.UUID,
    payload: Resolution,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    incident = db.scalar(
        select(Incident).where(Incident.id == incident_id).with_for_update()
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="No encontramos la incidencia.")
    if incident.status not in {"open", "in_review"}:
        raise HTTPException(status_code=409, detail="Esta incidencia ya está resuelta.")
    if (
        incident.incident_type != "missing_stock"
        or not incident.product_id
        or not incident.affected_quantity
    ):
        raise HTTPException(
            status_code=422,
            detail="Esta incidencia requiere una resolución administrativa específica.",
        )
    position = db.scalar(
        select(InventoryPositionModel)
        .where(InventoryPositionModel.product_id == incident.product_id)
        .with_for_update()
    )
    quantity = incident.affected_quantity
    if position is None or position.blocked_by_incident < quantity:
        raise HTTPException(
            status_code=409,
            detail="El saldo bloqueado ya no coincide con la incidencia.",
        )
    before = {
        "physical_confirmed": position.physical_confirmed,
        "invoiced_not_dispatched": position.invoiced_not_dispatched,
        "blocked_by_incident": position.blocked_by_incident,
        "version": position.version,
    }
    position.blocked_by_incident -= quantity
    if payload.decision == "retry_dispatch":
        position.invoiced_not_dispatched += quantity
    elif payload.decision == "confirm_physical_shortage":
        if position.physical_confirmed < quantity:
            raise HTTPException(
                status_code=409, detail="La corrección dejaría stock físico negativo."
            )
        position.physical_confirmed -= quantity
    position.version += 1
    incident.status = "resolved"
    incident.decision = f"{payload.decision}: {payload.reason.strip()}"
    db.add(
        InventoryMovement(
            warehouse_id=position.warehouse_id,
            product_id=position.product_id,
            actor_user_id=user.id,
            movement_type="incident_resolved",
            reference_type="incident",
            reference_id=str(incident.id),
            reason=payload.reason.strip(),
            before_value=before,
            after_value={
                "physical_confirmed": position.physical_confirmed,
                "invoiced_not_dispatched": position.invoiced_not_dispatched,
                "blocked_by_incident": position.blocked_by_incident,
                "version": position.version,
            },
        )
    )
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="incident_resolved",
            entity_type="incident",
            entity_id=str(incident.id),
            reason=incident.decision,
        )
    )
    db.commit()
    return {"id": incident.id, "status": incident.status, "decision": incident.decision}
