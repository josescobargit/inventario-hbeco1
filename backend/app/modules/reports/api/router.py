from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.auth.infrastructure.models import User
from app.modules.catalog.infrastructure.models import Product
from app.modules.dispatches.infrastructure.models import Dispatch, DispatchLine
from app.modules.incidents.infrastructure.models import Incident
from app.modules.inventory.domain.availability import InventoryPosition
from app.modules.inventory.infrastructure.models import (
    InventoryMovement,
    InventoryPositionModel,
    Warehouse,
)
from app.modules.invoices.infrastructure.models import Invoice, InvoiceLine
from app.modules.settings.domain.operational import low_stock_limit_units


router = APIRouter(prefix="/reports", tags=["Reportes"])


def status_for(
    position: InventoryPosition, units_per_box: int, low_stock_units: int | None = None
) -> str:
    if position.blocked_by_incident > 0:
        return "blocked"
    if position.available_to_invoice <= 0:
        return "out_of_stock"
    if position.available_to_invoice <= (low_stock_units or units_per_box):
        return "low_stock"
    return "available"


@router.get("/operational")
def operational_report(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    chain: Annotated[str | None, Query(max_length=160)] = None,
) -> dict:
    inventory_rows = db.execute(
        select(Product, InventoryPositionModel)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(Product.is_active.is_(True), Warehouse.code == "principal")
        .order_by(Product.sku)
    ).all()
    inventory_summary = {
        "products": len(inventory_rows),
        "physical": sum(position.physical_confirmed for _, position in inventory_rows),
        "reserved": sum(position.reserved for _, position in inventory_rows),
        "invoiced_pending": sum(
            position.invoiced_not_dispatched for _, position in inventory_rows
        ),
        "blocked": sum(position.blocked_by_incident for _, position in inventory_rows),
        "available": 0,
        "low_stock_products": 0,
    }
    low_stock = []
    for product, stored in inventory_rows:
        position = InventoryPosition(
            stored.physical_confirmed,
            stored.reserved,
            stored.invoiced_not_dispatched,
            stored.blocked_by_incident,
        )
        inventory_summary["available"] += position.available_to_invoice
        visual_status = status_for(
            position,
            product.units_per_box,
            low_stock_limit_units(db, product.units_per_box),
        )
        if visual_status in ["low_stock", "out_of_stock"]:
            inventory_summary["low_stock_products"] += 1
            low_stock.append(
                {
                    "sku": product.sku,
                    "product_name": product.name,
                    "category": product.category,
                    "available": position.available_to_invoice,
                    "units_per_box": product.units_per_box,
                    "status": visual_status,
                }
            )

    invoice_filters = []
    if date_from:
        invoice_filters.append(Invoice.invoice_date >= date_from)
    if date_to:
        invoice_filters.append(Invoice.invoice_date <= date_to)
    if chain and chain.strip():
        invoice_filters.append(Invoice.chain_name.ilike(f"%{chain.strip()}%"))

    by_chain_rows = db.execute(
        select(
            Invoice.chain_name,
            func.count(func.distinct(Invoice.id)),
            func.coalesce(func.sum(InvoiceLine.quantity), 0),
        )
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .where(*invoice_filters)
        .group_by(Invoice.chain_name)
        .order_by(func.coalesce(func.sum(InvoiceLine.quantity), 0).desc())
        .limit(12)
    ).all()

    by_product_rows = db.execute(
        select(
            Product.sku,
            Product.name,
            Product.category,
            func.coalesce(func.sum(InvoiceLine.quantity), 0),
        )
        .join(InvoiceLine, InvoiceLine.product_id == Product.id)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(*invoice_filters)
        .group_by(Product.sku, Product.name, Product.category)
        .order_by(func.coalesce(func.sum(InvoiceLine.quantity), 0).desc())
        .limit(12)
    ).all()

    pending_rows = db.execute(
        select(
            Invoice.chain_name,
            func.count(Invoice.id),
            func.coalesce(func.sum(InvoiceLine.quantity), 0),
        )
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .where(
            *invoice_filters,
            Invoice.dispatch_status.in_(["pending", "partial"])
            | (Invoice.delivery_status.in_(["pending", "partial_delivery"])),
        )
        .group_by(Invoice.chain_name)
        .order_by(func.count(Invoice.id).desc())
        .limit(12)
    ).all()

    missing_rows = db.execute(
        select(
            Product.sku,
            Product.name,
            func.coalesce(func.sum(DispatchLine.missing_quantity), 0),
            func.count(DispatchLine.id),
        )
        .join(InvoiceLine, InvoiceLine.id == DispatchLine.invoice_line_id)
        .join(Product, Product.id == InvoiceLine.product_id)
        .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
        .join(Invoice, Invoice.id == Dispatch.invoice_id)
        .where(*invoice_filters, DispatchLine.missing_quantity > 0)
        .group_by(Product.sku, Product.name)
        .order_by(func.coalesce(func.sum(DispatchLine.missing_quantity), 0).desc())
        .limit(12)
    ).all()

    movement_rows = db.execute(
        select(
            func.coalesce(User.full_name, "Usuario no disponible"),
            func.count(InventoryMovement.id),
        )
        .outerjoin(User, User.id == InventoryMovement.actor_user_id)
        .group_by(User.full_name)
        .order_by(func.count(InventoryMovement.id).desc())
        .limit(10)
    ).all()

    open_incidents = db.scalar(
        select(func.count(Incident.id)).where(
            Incident.status.in_(["open", "in_review"])
        )
    )
    pending_dispatch = db.scalar(
        select(func.count(Invoice.id)).where(
            *invoice_filters, Invoice.dispatch_status.in_(["pending", "partial"])
        )
    )
    pending_delivery = db.scalar(
        select(func.count(Invoice.id)).where(
            *invoice_filters,
            Invoice.dispatch_status != "pending",
            Invoice.delivery_status.in_(["pending", "partial_delivery"]),
        )
    )

    return {
        "filters": {
            "date_from": date_from,
            "date_to": date_to,
            "chain": chain,
        },
        "inventory": inventory_summary,
        "workflow": {
            "pending_dispatch": pending_dispatch,
            "pending_delivery": pending_delivery,
            "open_incidents": open_incidents,
        },
        "by_chain": [
            {
                "chain_name": chain_name or "Sin cadena",
                "invoice_count": invoice_count,
                "units": units,
            }
            for chain_name, invoice_count, units in by_chain_rows
        ],
        "by_product": [
            {
                "sku": sku,
                "product_name": product_name,
                "category": category,
                "units": units,
            }
            for sku, product_name, category, units in by_product_rows
        ],
        "pending_by_chain": [
            {
                "chain_name": chain_name or "Sin cadena",
                "invoice_count": invoice_count,
                "units": units,
            }
            for chain_name, invoice_count, units in pending_rows
        ],
        "missing_products": [
            {
                "sku": sku,
                "product_name": product_name,
                "missing_units": missing_units,
                "events": events,
            }
            for sku, product_name, missing_units, events in missing_rows
        ],
        "low_stock": low_stock[:12],
        "movements_by_responsible": [
            {"responsible": responsible, "movements": movements}
            for responsible, movements in movement_rows
        ],
    }
