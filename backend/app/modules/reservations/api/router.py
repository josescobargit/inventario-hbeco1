import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.time import utc_now
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.domain.availability import (
    InventoryPosition,
    InsufficientAvailabilityError,
)
from app.modules.inventory.infrastructure.models import (
    InventoryMovement,
    InventoryPositionModel,
    Warehouse,
)
from app.modules.reservations.api.schemas import (
    ReservationCreate,
    ReservationLineResponse,
    ReservationRelease,
    ReservationResponse,
)
from app.modules.reservations.infrastructure.models import Reservation, ReservationLine

router = APIRouter(prefix="/reservations", tags=["Reservas"])


def serialize(db: Session, item: Reservation) -> ReservationResponse:
    rows = db.execute(
        select(ReservationLine, Product)
        .join(Product, Product.id == ReservationLine.product_id)
        .where(ReservationLine.reservation_id == item.id)
        .order_by(Product.sku)
    ).all()
    return ReservationResponse(
        id=item.id,
        purpose=item.purpose,
        customer_name=item.customer_name,
        purchase_order_reference=item.purchase_order_reference,
        responsible_name=item.responsible_name,
        reason=item.reason,
        status=item.status,
        release_reason=item.release_reason,
        created_at=item.created_at,
        lines=[
            ReservationLineResponse(
                sku=p.sku,
                product_name=p.name,
                quantity=line.quantity,
                remaining_quantity=line.remaining_quantity,
            )
            for line, p in rows
        ],
    )


@router.get("", response_model=list[ReservationResponse])
def list_reservations(_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return [
        serialize(db, item)
        for item in db.scalars(
            select(Reservation).order_by(Reservation.created_at.desc())
        ).all()
    ]


@router.post("", response_model=ReservationResponse, status_code=201)
def create_reservation(
    payload: ReservationCreate,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    skus = [line.sku.strip().upper() for line in payload.lines]
    if len(set(skus)) != len(skus):
        raise HTTPException(
            status_code=422, detail="No repitas un SKU dentro de la reserva."
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
    found = {p.sku: (p, pos, wh) for p, pos, wh in rows}
    if set(skus) != set(found):
        raise HTTPException(
            status_code=422,
            detail=f"SKU desconocidos: {', '.join(sorted(set(skus) - set(found)))}",
        )
    requested = {line.sku.strip().upper(): line.quantity for line in payload.lines}
    for sku, quantity in requested.items():
        _, pos, _ = found[sku]
        try:
            InventoryPosition(
                pos.physical_confirmed,
                pos.reserved,
                pos.invoiced_not_dispatched,
                pos.blocked_by_incident,
            ).require_available(quantity)
        except InsufficientAvailabilityError as error:
            raise HTTPException(status_code=409, detail=f"{sku}: {error}") from error
    warehouse = rows[0][2]
    item = Reservation(
        warehouse_id=warehouse.id,
        created_by_user_id=user.id,
        purpose=payload.purpose,
        customer_name=payload.customer_name,
        purchase_order_reference=payload.purchase_order_reference,
        responsible_name=payload.responsible_name,
        reason=payload.reason.strip(),
    )
    db.add(item)
    db.flush()
    for sku, quantity in requested.items():
        product, pos, _ = found[sku]
        before = {"reserved": pos.reserved, "version": pos.version}
        pos.reserved += quantity
        pos.version += 1
        db.add(
            ReservationLine(
                reservation_id=item.id,
                product_id=product.id,
                quantity=quantity,
                remaining_quantity=quantity,
            )
        )
        db.add(
            InventoryMovement(
                warehouse_id=warehouse.id,
                product_id=product.id,
                actor_user_id=user.id,
                movement_type="reservation_created",
                reference_type="reservation",
                reference_id=str(item.id),
                reason=item.reason,
                before_value=before,
                after_value={"reserved": pos.reserved, "version": pos.version},
            )
        )
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="reservation_created",
            entity_type="reservation",
            entity_id=str(item.id),
            reason=item.reason,
            new_value={"products": len(requested)},
        )
    )
    db.commit()
    return serialize(db, item)


@router.post("/{reservation_id}/release", response_model=ReservationResponse)
def release_reservation(
    reservation_id: uuid.UUID,
    payload: ReservationRelease,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    item = db.scalar(
        select(Reservation).where(Reservation.id == reservation_id).with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="No encontramos la reserva.")
    if item.status != "active":
        raise HTTPException(status_code=409, detail="Esta reserva ya no está activa.")
    lines = db.scalars(
        select(ReservationLine)
        .where(ReservationLine.reservation_id == item.id)
        .with_for_update()
    ).all()
    positions = {
        p.product_id: p
        for p in db.scalars(
            select(InventoryPositionModel)
            .where(
                InventoryPositionModel.product_id.in_(
                    [line.product_id for line in lines]
                )
            )
            .with_for_update()
        ).all()
    }
    for line in lines:
        pos = positions[line.product_id]
        before = {"reserved": pos.reserved, "version": pos.version}
        pos.reserved -= line.remaining_quantity
        pos.version += 1
        line.remaining_quantity = 0
        db.add(
            InventoryMovement(
                warehouse_id=pos.warehouse_id,
                product_id=pos.product_id,
                actor_user_id=user.id,
                movement_type="reservation_released",
                reference_type="reservation",
                reference_id=str(item.id),
                reason=payload.reason.strip(),
                before_value=before,
                after_value={"reserved": pos.reserved, "version": pos.version},
            )
        )
    item.status, item.closed_at, item.closed_by_user_id, item.release_reason = (
        "released",
        utc_now(),
        user.id,
        payload.reason.strip(),
    )
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="reservation_released",
            entity_type="reservation",
            entity_id=str(item.id),
            reason=item.release_reason,
        )
    )
    db.commit()
    return serialize(db, item)
