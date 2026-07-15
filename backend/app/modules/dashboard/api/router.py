from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.catalog.infrastructure.models import Product
from app.modules.incidents.infrastructure.models import Incident
from app.modules.inventory.domain.availability import InventoryPosition
from app.modules.inventory.infrastructure.models import (
    InventoryPositionModel,
    Warehouse,
)
from app.modules.invoices.infrastructure.models import Invoice
from app.modules.reservations.infrastructure.models import Reservation, ReservationLine
from app.modules.settings.domain.operational import low_stock_limit_units
from app.modules.stock_adjustments.infrastructure.models import StockAdjustmentRequest


router = APIRouter(prefix="/dashboard", tags=["Resumen operativo"])


@router.get("/summary")
def summary(_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    inventory_rows = db.execute(
        select(Product, InventoryPositionModel)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(Product.is_active.is_(True), Warehouse.code == "principal")
        .order_by(Product.sku)
    ).all()
    totals = {
        "products": len(inventory_rows),
        "physical": sum(position.physical_confirmed for _, position in inventory_rows),
        "reserved": sum(position.reserved for _, position in inventory_rows),
        "invoiced_pending": sum(
            position.invoiced_not_dispatched for _, position in inventory_rows
        ),
        "blocked": sum(position.blocked_by_incident for _, position in inventory_rows),
        "available": 0,
    }
    low_stock = []
    for product, stored in inventory_rows:
        position = InventoryPosition(
            stored.physical_confirmed,
            stored.reserved,
            stored.invoiced_not_dispatched,
            stored.blocked_by_incident,
        )
        totals["available"] += position.available_to_invoice
        if position.available_to_invoice <= low_stock_limit_units(
            db, product.units_per_box
        ):
            low_stock.append(
                {
                    "sku": product.sku,
                    "product_name": product.name,
                    "available": position.available_to_invoice,
                    "units_per_box": product.units_per_box,
                }
            )
    pending_dispatch = db.scalar(
        select(func.count(Invoice.id)).where(
            Invoice.dispatch_status.in_(["pending", "partial"])
        )
    )
    pending_delivery = db.scalar(
        select(func.count(Invoice.id)).where(
            Invoice.dispatch_status != "pending", Invoice.delivery_status == "pending"
        )
    )
    open_incidents = db.scalar(
        select(func.count(Incident.id)).where(
            Incident.status.in_(["open", "in_review"])
        )
    )
    active_reservations = db.scalar(
        select(func.count(Reservation.id)).where(Reservation.status == "active")
    )
    reserved_units = db.scalar(
        select(func.coalesce(func.sum(ReservationLine.remaining_quantity), 0))
        .join(Reservation, Reservation.id == ReservationLine.reservation_id)
        .where(Reservation.status == "active")
    )
    pending_approvals = db.scalar(
        select(func.count(StockAdjustmentRequest.id)).where(
            StockAdjustmentRequest.status == "pending"
        )
    )
    attention_invoices = db.scalars(
        select(Invoice)
        .where(
            (Invoice.dispatch_status.in_(["pending", "partial"]))
            | (
                (Invoice.delivery_status == "pending")
                & (Invoice.dispatch_status != "pending")
            )
            | (Invoice.incident_status == "open")
        )
        .order_by(Invoice.invoice_date, Invoice.created_at)
        .limit(10)
    ).all()
    return {
        "inventory": totals,
        "workflow": {
            "pending_dispatch": pending_dispatch,
            "pending_delivery": pending_delivery,
            "open_incidents": open_incidents,
            "active_reservations": active_reservations,
            "reserved_units": reserved_units,
            "pending_approvals": pending_approvals,
        },
        "attention_invoices": [
            {
                "id": item.id,
                "invoice_number": item.invoice_number,
                "customer_name": item.customer_name,
                "chain_name": item.chain_name,
                "invoice_date": item.invoice_date,
                "dispatch_status": item.dispatch_status,
                "delivery_status": item.delivery_status,
                "incident_status": item.incident_status,
            }
            for item in attention_invoices
        ],
        "low_stock": low_stock[:10],
    }
