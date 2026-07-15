from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.auth.infrastructure.models import User
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.domain.availability import InventoryPosition
from app.modules.inventory.infrastructure.models import (
    InventoryMovement,
    InventoryPositionModel,
    Warehouse,
)
from app.modules.inventory_operations.infrastructure.models import (
    InventoryOperation,
    InventoryOperationLine,
)


class OperationLineInput(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    quantity: int = Field(gt=0)


class OperationInput(BaseModel):
    operation_type: Literal["entry", "exit"]
    responsible_name: str = Field(min_length=2, max_length=160)
    occurred_at: datetime
    document_reference: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=5, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[OperationLineInput] = Field(min_length=1)


router = APIRouter(prefix="/inventory-operations", tags=["Entradas y salidas"])


def serialize(db: Session, item: InventoryOperation) -> dict:
    user = db.get(User, item.registered_by_user_id)
    lines = db.execute(
        select(InventoryOperationLine, Product)
        .join(Product, Product.id == InventoryOperationLine.product_id)
        .where(InventoryOperationLine.operation_id == item.id)
        .order_by(Product.sku)
    ).all()
    return {
        "id": item.id,
        "operation_type": item.operation_type,
        "responsible_name": item.responsible_name,
        "occurred_at": item.occurred_at,
        "document_reference": item.document_reference,
        "reason": item.reason,
        "notes": item.notes,
        "registered_by": user.full_name if user else "Usuario no disponible",
        "lines": [
            {
                "sku": product.sku,
                "product_name": product.name,
                "quantity": line.quantity,
            }
            for line, product in lines
        ],
    }


@router.get("")
def list_operations(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    operation_type: Annotated[Literal["entry", "exit"] | None, Query()] = None,
):
    statement = select(InventoryOperation).order_by(
        InventoryOperation.occurred_at.desc(), InventoryOperation.created_at.desc()
    )
    if operation_type:
        statement = statement.where(InventoryOperation.operation_type == operation_type)
    return [serialize(db, item) for item in db.scalars(statement).all()]


@router.post("", status_code=201)
def register_operation(
    payload: OperationInput,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    skus = [line.sku.strip().upper() for line in payload.lines]
    if len(set(skus)) != len(skus):
        raise HTTPException(
            status_code=422, detail="No repitas un SKU en el movimiento."
        )
    rows = db.execute(
        select(Product, InventoryPositionModel, Warehouse)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(
            Product.sku.in_(skus),
            Product.is_active.is_(True),
            Warehouse.code == "principal",
        )
        .with_for_update(of=InventoryPositionModel)
    ).all()
    found = {
        product.sku: (product, position, warehouse)
        for product, position, warehouse in rows
    }
    if set(skus) != set(found):
        raise HTTPException(
            status_code=422,
            detail=f"SKU desconocidos: {', '.join(sorted(set(skus) - set(found)))}",
        )
    requested = {line.sku.strip().upper(): line.quantity for line in payload.lines}
    if payload.operation_type == "exit":
        for sku, quantity in requested.items():
            _, position, _ = found[sku]
            available = InventoryPosition(
                position.physical_confirmed,
                position.reserved,
                position.invoiced_not_dispatched,
                position.blocked_by_incident,
            ).available_to_invoice
            if quantity > available:
                raise HTTPException(
                    status_code=409,
                    detail=f"{sku}: la cantidad ingresada supera el stock disponible ({available}).",
                )
    warehouse = rows[0][2]
    item = InventoryOperation(
        warehouse_id=warehouse.id,
        registered_by_user_id=user.id,
        operation_type=payload.operation_type,
        responsible_name=payload.responsible_name.strip(),
        occurred_at=payload.occurred_at,
        document_reference=payload.document_reference.strip(),
        reason=payload.reason.strip(),
        notes=payload.notes.strip() if payload.notes else None,
    )
    db.add(item)
    db.flush()
    direction = 1 if payload.operation_type == "entry" else -1
    for sku, quantity in requested.items():
        product, position, _ = found[sku]
        before = {
            "physical_confirmed": position.physical_confirmed,
            "version": position.version,
        }
        position.physical_confirmed += direction * quantity
        position.version += 1
        db.add(
            InventoryOperationLine(
                operation_id=item.id, product_id=product.id, quantity=quantity
            )
        )
        db.add(
            InventoryMovement(
                warehouse_id=warehouse.id,
                product_id=product.id,
                actor_user_id=user.id,
                movement_type=f"general_{payload.operation_type}",
                reference_type="inventory_operation",
                reference_id=str(item.id),
                reason=payload.reason.strip(),
                before_value=before,
                after_value={
                    "physical_confirmed": position.physical_confirmed,
                    "version": position.version,
                },
                occurred_at=payload.occurred_at,
            )
        )
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action=f"inventory_{payload.operation_type}_registered",
            entity_type="inventory_operation",
            entity_id=str(item.id),
            reason=payload.reason.strip(),
            new_value={
                "document": item.document_reference,
                "responsible": item.responsible_name,
                "products": len(requested),
                "units": sum(requested.values()),
            },
        )
    )
    db.commit()
    return serialize(db, item)
