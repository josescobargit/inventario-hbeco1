import uuid
from datetime import date
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.domain.availability import InventoryPosition
from app.modules.inventory.infrastructure.models import (
    InventoryPositionModel,
    Warehouse,
)
from app.modules.purchase_orders.infrastructure.models import (
    PurchaseOrder,
    PurchaseOrderLine,
)


class LineInput(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    quantity: int = Field(gt=0)


class OrderInput(BaseModel):
    chain_name: str = Field(min_length=2, max_length=160)
    customer_name: str | None = Field(default=None, max_length=160)
    order_number: str = Field(min_length=1, max_length=100)
    order_date: date | None = None
    destination: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[LineInput] = Field(min_length=1)


router = APIRouter(prefix="/purchase-orders", tags=["Órdenes de compra"])


def detail(db: Session, order: PurchaseOrder) -> dict:
    rows = db.execute(
        select(PurchaseOrderLine, Product, InventoryPositionModel)
        .join(Product, Product.id == PurchaseOrderLine.product_id)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(
            PurchaseOrderLine.purchase_order_id == order.id,
            Warehouse.code == "principal",
        )
        .order_by(Product.sku)
    ).all()
    lines = []
    for line, product, stored in rows:
        position = InventoryPosition(
            stored.physical_confirmed,
            stored.reserved,
            stored.invoiced_not_dispatched,
            stored.blocked_by_incident,
        )
        suggested = max(0, min(line.ordered_quantity, position.available_to_invoice))
        lines.append(
            {
                "sku": product.sku,
                "product_name": product.name,
                "ordered_quantity": line.ordered_quantity,
                "available": position.available_to_invoice,
                "suggested_to_invoice": suggested,
                "shortage": line.ordered_quantity - suggested,
                "complete": suggested == line.ordered_quantity,
            }
        )
    return {
        "id": order.id,
        "chain_name": order.chain_name,
        "customer_name": order.customer_name,
        "order_number": order.order_number,
        "order_date": order.order_date,
        "destination": order.destination,
        "status": order.status,
        "notes": order.notes,
        "lines": lines,
    }


@router.get("")
def list_orders(_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return [
        detail(db, order)
        for order in db.scalars(
            select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())
        ).all()
    ]


@router.get("/{order_id}")
def get_order(
    order_id: uuid.UUID, _user: CurrentUser, db: Annotated[Session, Depends(get_db)]
):
    order = db.get(PurchaseOrder, order_id)
    if order is None:
        raise HTTPException(
            status_code=404, detail="No encontramos la orden de compra."
        )
    return detail(db, order)


@router.post("", status_code=201)
def create_order(
    payload: OrderInput, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
):
    skus = [line.sku.strip().upper() for line in payload.lines]
    if len(set(skus)) != len(skus):
        raise HTTPException(status_code=422, detail="No repitas un SKU en la OC.")
    products = {
        p.sku: p
        for p in db.scalars(
            select(Product).where(Product.sku.in_(skus), Product.is_active.is_(True))
        ).all()
    }
    if set(skus) != set(products):
        raise HTTPException(
            status_code=422,
            detail=f"SKU desconocidos: {', '.join(sorted(set(skus) - set(products)))}",
        )
    order = PurchaseOrder(
        chain_name=payload.chain_name.strip(),
        customer_name=payload.customer_name,
        order_number=payload.order_number.strip(),
        order_date=payload.order_date,
        destination=payload.destination,
        notes=payload.notes,
        created_by_user_id=user.id,
    )
    db.add(order)
    db.flush()
    for line in payload.lines:
        db.add(
            PurchaseOrderLine(
                purchase_order_id=order.id,
                product_id=products[line.sku.strip().upper()].id,
                ordered_quantity=line.quantity,
            )
        )
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="purchase_order_created",
            entity_type="purchase_order",
            entity_id=str(order.id),
            new_value={
                "chain": order.chain_name,
                "number": order.order_number,
                "products": len(payload.lines),
            },
        )
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Esta cadena ya tiene una OC con ese número."
        ) from error
    return detail(db, order)
