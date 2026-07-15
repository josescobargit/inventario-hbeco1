import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import utc_now
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.auth.infrastructure.models import User
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.infrastructure.models import (
    InventoryMovement,
    InventoryPositionModel,
    Warehouse,
)
from app.modules.stock_adjustments.api.schemas import (
    AdjustmentCreate,
    AdjustmentDecision,
    AdjustmentResponse,
)
from app.modules.stock_adjustments.infrastructure.models import StockAdjustmentRequest


router = APIRouter(prefix="/stock-adjustments", tags=["Ajustes de stock"])


def require_principal(user: User) -> None:
    if user.role.code != "principal":
        raise HTTPException(
            status_code=403, detail="Solo el usuario principal puede decidir ajustes."
        )


def applies_immediately(user: User) -> bool:
    return user.role.code == "principal"


def response_for(
    adjustment: StockAdjustmentRequest, product: Product
) -> AdjustmentResponse:
    return AdjustmentResponse(
        id=adjustment.id,
        sku=product.sku,
        product_name=product.name,
        status=adjustment.status,
        previous_physical_confirmed=adjustment.previous_physical_confirmed,
        requested_physical_confirmed=adjustment.requested_physical_confirmed,
        request_reason=adjustment.request_reason,
        decision_reason=adjustment.decision_reason,
        requested_at=adjustment.requested_at,
        decided_at=adjustment.decided_at,
    )


@router.get("", response_model=list[AdjustmentResponse])
def list_adjustments(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    adjustment_status: Annotated[str | None, Query(alias="status")] = None,
) -> list[AdjustmentResponse]:
    statement = (
        select(StockAdjustmentRequest, Product)
        .join(Product, Product.id == StockAdjustmentRequest.product_id)
        .order_by(StockAdjustmentRequest.requested_at.desc())
    )
    if adjustment_status:
        statement = statement.where(StockAdjustmentRequest.status == adjustment_status)
    return [response_for(item, product) for item, product in db.execute(statement)]


@router.post("", response_model=AdjustmentResponse, status_code=status.HTTP_201_CREATED)
def request_adjustment(
    payload: AdjustmentCreate,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentResponse:
    row = db.execute(
        select(Product, InventoryPositionModel, Warehouse)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(
            Product.sku == payload.sku.strip().upper(), Warehouse.code == "principal"
        )
        .with_for_update(of=InventoryPositionModel)
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404, detail="No encontramos ese SKU en el catálogo activo."
        )
    product, position, warehouse = row
    adjustment = StockAdjustmentRequest(
        warehouse_id=warehouse.id,
        product_id=product.id,
        requested_by_user_id=user.id,
        previous_physical_confirmed=position.physical_confirmed,
        requested_physical_confirmed=payload.requested_physical_confirmed,
        position_version=position.version,
        request_reason=payload.reason.strip(),
    )
    db.add(adjustment)
    db.flush()
    is_principal = applies_immediately(user)
    if is_principal:
        before = {
            "physical_confirmed": position.physical_confirmed,
            "version": position.version,
        }
        position.physical_confirmed = payload.requested_physical_confirmed
        position.version += 1
        adjustment.status = "approved"
        adjustment.decided_by_user_id = user.id
        adjustment.decision_reason = payload.reason.strip()
        adjustment.decided_at = utc_now()
        db.add(
            InventoryMovement(
                warehouse_id=warehouse.id,
                product_id=product.id,
                actor_user_id=user.id,
                movement_type="physical_adjustment",
                reference_type="stock_adjustment",
                reference_id=str(adjustment.id),
                reason=payload.reason.strip(),
                before_value=before,
                after_value={
                    "physical_confirmed": position.physical_confirmed,
                    "version": position.version,
                },
            )
        )
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action=(
                "stock_adjustment_approved"
                if is_principal
                else "stock_adjustment_requested"
            ),
            entity_type="stock_adjustment",
            entity_id=str(adjustment.id),
            reason=adjustment.request_reason,
            previous_value={"physical": adjustment.previous_physical_confirmed}
            if is_principal
            else None,
            new_value={
                "sku": product.sku,
                "physical": payload.requested_physical_confirmed,
            },
        )
    )
    db.commit()
    return response_for(adjustment, product)


def decide(
    adjustment_id: uuid.UUID,
    payload: AdjustmentDecision,
    user: User,
    db: Session,
    approve: bool,
) -> AdjustmentResponse:
    require_principal(user)
    adjustment = db.scalar(
        select(StockAdjustmentRequest)
        .where(StockAdjustmentRequest.id == adjustment_id)
        .with_for_update()
    )
    if adjustment is None:
        raise HTTPException(
            status_code=404, detail="No encontramos la solicitud de ajuste."
        )
    product = db.get(Product, adjustment.product_id)
    if adjustment.status != "pending":
        raise HTTPException(
            status_code=409, detail="Esta solicitud ya fue decidida o quedó obsoleta."
        )
    now = utc_now()
    if not approve:
        adjustment.status = "rejected"
    else:
        position = db.scalar(
            select(InventoryPositionModel)
            .where(
                InventoryPositionModel.warehouse_id == adjustment.warehouse_id,
                InventoryPositionModel.product_id == adjustment.product_id,
            )
            .with_for_update()
        )
        if position is None or position.version != adjustment.position_version:
            adjustment.status = "obsolete"
            adjustment.decided_by_user_id = user.id
            adjustment.decision_reason = (
                "El inventario cambió después de crear la solicitud."
            )
            adjustment.decided_at = now
            db.commit()
            raise HTTPException(
                status_code=409,
                detail="El inventario cambió. Crea una solicitud con el conteo actualizado.",
            )
        before = {
            "physical_confirmed": position.physical_confirmed,
            "version": position.version,
        }
        position.physical_confirmed = adjustment.requested_physical_confirmed
        position.version += 1
        after = {
            "physical_confirmed": position.physical_confirmed,
            "version": position.version,
        }
        adjustment.status = "approved"
        db.add(
            InventoryMovement(
                warehouse_id=position.warehouse_id,
                product_id=position.product_id,
                actor_user_id=user.id,
                movement_type="physical_adjustment",
                reference_type="stock_adjustment",
                reference_id=str(adjustment.id),
                reason=payload.reason.strip(),
                before_value=before,
                after_value=after,
            )
        )
    adjustment.decided_by_user_id = user.id
    adjustment.decision_reason = payload.reason.strip()
    adjustment.decided_at = now
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action=f"stock_adjustment_{adjustment.status}",
            entity_type="stock_adjustment",
            entity_id=str(adjustment.id),
            reason=adjustment.decision_reason,
            previous_value={"physical": adjustment.previous_physical_confirmed},
            new_value={"physical": adjustment.requested_physical_confirmed}
            if approve
            else None,
        )
    )
    db.commit()
    return response_for(adjustment, product)


@router.post("/{adjustment_id}/approve", response_model=AdjustmentResponse)
def approve_adjustment(
    adjustment_id: uuid.UUID,
    payload: AdjustmentDecision,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentResponse:
    return decide(adjustment_id, payload, user, db, True)


@router.post("/{adjustment_id}/reject", response_model=AdjustmentResponse)
def reject_adjustment(
    adjustment_id: uuid.UUID,
    payload: AdjustmentDecision,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> AdjustmentResponse:
    return decide(adjustment_id, payload, user, db, False)
