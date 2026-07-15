from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.auth.infrastructure.models import User
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.api.schemas import AvailabilityResponse
from app.modules.inventory.domain.availability import InventoryPosition
from app.modules.inventory.infrastructure.models import (
    InventoryMovement,
    InventoryPositionModel,
    Warehouse,
)
from app.modules.settings.domain.operational import low_stock_limit_units


router = APIRouter(prefix="/inventory", tags=["Inventario"])


MOVEMENT_LABELS = {
    "bulk_physical_count": "Carga física",
    "physical_adjustment": "Ajuste físico",
    "reservation_created": "Reserva creada",
    "reservation_released": "Reserva liberada",
    "invoice_registered": "Factura registrada",
    "dispatch_confirmed": "Despacho confirmado",
    "incident_resolved": "Incidencia resuelta",
    "customer_return": "Devolución",
    "general_entry": "Entrada general",
    "general_exit": "Salida general",
}

TRACKED_FIELDS = (
    "physical_confirmed",
    "reserved",
    "invoiced_not_dispatched",
    "blocked_by_incident",
)


def movement_label(movement_type: str) -> str:
    return MOVEMENT_LABELS.get(movement_type, movement_type.replace("_", " ").title())


def movement_delta(
    before_value: dict[str, Any], after_value: dict[str, Any]
) -> tuple[str, int]:
    for field in TRACKED_FIELDS:
        before = int(before_value.get(field, 0) or 0)
        after = int(after_value.get(field, 0) or 0)
        if before != after:
            return field, after - before
    return "sin_cambio", 0


def serialize_movement(
    movement: InventoryMovement, product: Product, user: User | None
) -> dict[str, Any]:
    affected_field, delta = movement_delta(movement.before_value, movement.after_value)
    return {
        "id": movement.id,
        "occurred_at": movement.occurred_at,
        "movement_type": movement.movement_type,
        "movement_label": movement_label(movement.movement_type),
        "sku": product.sku,
        "product_name": product.name,
        "category": product.category,
        "affected_field": affected_field,
        "delta": delta,
        "reference_type": movement.reference_type,
        "reference_id": movement.reference_id,
        "reason": movement.reason,
        "actor": user.full_name if user else "Usuario no disponible",
        "before_value": movement.before_value,
        "after_value": movement.after_value,
    }


def visual_status(
    position: InventoryPosition, units_per_box: int, low_stock_units: int | None = None
) -> str:
    if position.blocked_by_incident > 0:
        return "blocked"
    if position.available_to_invoice <= 0:
        return "out_of_stock"
    if position.available_to_invoice <= (low_stock_units or units_per_box):
        return "low_stock"
    return "available"


@router.get("/availability", response_model=list[AvailabilityResponse])
def list_availability(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    category: Annotated[str | None, Query(max_length=100)] = None,
) -> list[AvailabilityResponse]:
    statement = (
        select(Product, InventoryPositionModel)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(Product.is_active.is_(True), Warehouse.code == "principal")
        .order_by(Product.sku)
    )
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(Product.sku.ilike(term), Product.name.ilike(term))
        )
    if category and category.strip():
        statement = statement.where(Product.category == category.strip())

    result: list[AvailabilityResponse] = []
    for product, stored in db.execute(statement).all():
        position = InventoryPosition(
            physical_confirmed=stored.physical_confirmed,
            reserved=stored.reserved,
            invoiced_not_dispatched=stored.invoiced_not_dispatched,
            blocked_by_incident=stored.blocked_by_incident,
        )
        result.append(
            AvailabilityResponse(
                sku=product.sku,
                product_name=product.name,
                category=product.category,
                physical_confirmed=position.physical_confirmed,
                reserved=position.reserved,
                invoiced_not_dispatched=position.invoiced_not_dispatched,
                blocked_by_incident=position.blocked_by_incident,
                available_to_invoice=position.available_to_invoice,
                units_per_box=product.units_per_box,
                physical_boxes=round(
                    position.physical_confirmed / product.units_per_box, 4
                ),
                available_boxes=round(
                    position.available_to_invoice / product.units_per_box, 4
                ),
                status=visual_status(
                    position,
                    product.units_per_box,
                    low_stock_limit_units(db, product.units_per_box),
                ),
            )
        )
    return result


@router.get("/movements")
def list_movements(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    movement_type: Annotated[str | None, Query(max_length=60)] = None,
    actor: Annotated[str | None, Query(max_length=120)] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=300)] = 100,
) -> list[dict[str, Any]]:
    statement = (
        select(InventoryMovement, Product, User)
        .join(Product, Product.id == InventoryMovement.product_id)
        .outerjoin(User, User.id == InventoryMovement.actor_user_id)
        .join(Warehouse, Warehouse.id == InventoryMovement.warehouse_id)
        .where(Warehouse.code == "principal")
        .order_by(InventoryMovement.occurred_at.desc(), InventoryMovement.id.desc())
        .limit(limit)
    )
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Product.sku.ilike(term),
                Product.name.ilike(term),
                InventoryMovement.reference_id.ilike(term),
                InventoryMovement.reason.ilike(term),
            )
        )
    if movement_type and movement_type.strip():
        statement = statement.where(
            InventoryMovement.movement_type == movement_type.strip()
        )
    if actor and actor.strip():
        statement = statement.where(User.full_name.ilike(f"%{actor.strip()}%"))
    if date_from:
        statement = statement.where(InventoryMovement.occurred_at >= date_from)
    if date_to:
        statement = statement.where(InventoryMovement.occurred_at <= date_to)

    return [
        serialize_movement(movement, product, user)
        for movement, product, user in db.execute(statement).all()
    ]
