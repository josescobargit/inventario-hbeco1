import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import utc_now
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.infrastructure.models import (
    InventoryMovement,
    InventoryPositionModel,
    Warehouse,
)
from app.modules.stock_adjustments.api.router import require_principal
from app.modules.stock_imports.api.schemas import (
    StockImportCreate,
    StockImportDecision,
    StockImportResponse,
)
from app.modules.stock_imports.infrastructure.models import StockImport, StockImportLine

router = APIRouter(prefix="/stock-imports", tags=["Conteos masivos"])


def apply_import(db: Session, item: StockImport, user, reason: str) -> int:
    lines = db.scalars(
        select(StockImportLine).where(StockImportLine.stock_import_id == item.id)
    ).all()
    positions = db.scalars(
        select(InventoryPositionModel)
        .where(
            InventoryPositionModel.product_id.in_([line.product_id for line in lines])
        )
        .with_for_update()
    ).all()
    by_product = {position.product_id: position for position in positions}
    if any(
        line.product_id not in by_product
        or by_product[line.product_id].version != line.position_version
        for line in lines
    ):
        item.status, item.decided_at = "obsolete", utc_now()
        item.decided_by_user_id, item.decision_reason = (
            user.id,
            "El inventario cambió después de la vista previa.",
        )
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="El inventario cambió. Revisa nuevamente el conteo completo.",
        )
    for line in lines:
        position = by_product[line.product_id]
        before = {
            "physical_confirmed": position.physical_confirmed,
            "version": position.version,
        }
        position.physical_confirmed, position.version = (
            line.counted_physical_confirmed,
            position.version + 1,
        )
        db.add(
            InventoryMovement(
                warehouse_id=position.warehouse_id,
                product_id=position.product_id,
                actor_user_id=user.id,
                movement_type="bulk_physical_count",
                reference_type="stock_import",
                reference_id=str(item.id),
                reason=reason,
                before_value=before,
                after_value={
                    "physical_confirmed": position.physical_confirmed,
                    "version": position.version,
                },
            )
        )
    item.status, item.decided_at = "approved", utc_now()
    item.decided_by_user_id, item.decision_reason = user.id, reason
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="stock_import_approved",
            entity_type="stock_import",
            entity_id=str(item.id),
            reason=reason,
            new_value={"products": len(lines)},
        )
    )
    return len(lines)


@router.post("", response_model=StockImportResponse, status_code=201)
def create_import(
    payload: StockImportCreate,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> StockImportResponse:
    records = db.execute(
        select(Product, InventoryPositionModel, Warehouse)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(Product.is_active.is_(True), Warehouse.code == "principal")
    ).all()
    catalog = {
        product.sku: (product, position, warehouse)
        for product, position, warehouse in records
    }
    supplied = [line.sku.strip().upper() for line in payload.lines]
    if len(supplied) != len(catalog) or set(supplied) != set(catalog):
        raise HTTPException(
            status_code=422,
            detail="Incluye exactamente todos los productos activos, sin duplicados.",
        )
    if db.scalar(
        select(func.count(StockImport.id)).where(StockImport.status == "pending")
    ):
        raise HTTPException(
            status_code=409, detail="Ya existe un conteo masivo pendiente."
        )
    item = StockImport(
        warehouse_id=records[0][2].id,
        requested_by_user_id=user.id,
        reason=payload.reason.strip(),
    )
    db.add(item)
    db.flush()
    for line in payload.lines:
        product, position, _ = catalog[line.sku.strip().upper()]
        if line.position_version != position.version:
            raise HTTPException(
                status_code=409,
                detail=f"El inventario de {product.sku} cambió después de la vista previa.",
            )
        db.add(
            StockImportLine(
                stock_import_id=item.id,
                product_id=product.id,
                previous_physical_confirmed=position.physical_confirmed,
                counted_physical_confirmed=line.counted_physical,
                position_version=line.position_version,
            )
        )
    db.flush()
    if user.role.code == "principal":
        apply_import(db, item, user, payload.reason.strip())
    else:
        db.add(
            AuditLog(
                actor_user_id=user.id,
                action="stock_import_requested",
                entity_type="stock_import",
                entity_id=str(item.id),
                reason=item.reason,
                new_value={"products": len(payload.lines)},
            )
        )
    db.commit()
    return StockImportResponse(
        id=item.id, status=item.status, total_products=len(payload.lines)
    )


@router.post("/{import_id}/approve", response_model=StockImportResponse)
def approve_import(
    import_id: uuid.UUID,
    payload: StockImportDecision,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> StockImportResponse:
    require_principal(user)
    item = db.scalar(
        select(StockImport).where(StockImport.id == import_id).with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="No encontramos el conteo masivo.")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail="Este conteo ya fue decidido.")
    total = apply_import(db, item, user, payload.reason.strip())
    db.commit()
    return StockImportResponse(id=item.id, status=item.status, total_products=total)


@router.post("/{import_id}/reject", response_model=StockImportResponse)
def reject_import(
    import_id: uuid.UUID,
    payload: StockImportDecision,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> StockImportResponse:
    require_principal(user)
    item = db.scalar(
        select(StockImport).where(StockImport.id == import_id).with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="No encontramos el conteo masivo.")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail="Este conteo ya fue decidido.")
    item.status, item.decided_at = "rejected", utc_now()
    item.decided_by_user_id, item.decision_reason = user.id, payload.reason.strip()
    total = db.scalar(
        select(func.count(StockImportLine.id)).where(
            StockImportLine.stock_import_id == item.id
        )
    )
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="stock_import_rejected",
            entity_type="stock_import",
            entity_id=str(item.id),
            reason=item.decision_reason,
        )
    )
    db.commit()
    return StockImportResponse(id=item.id, status=item.status, total_products=total)
