from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import utc_now
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.auth.infrastructure.models import User
from app.modules.catalog.infrastructure.models import Product
from app.modules.incidents.infrastructure.models import Incident
from app.modules.inventory.domain.availability import InventoryPosition
from app.modules.inventory.infrastructure.models import (
    InventoryPositionModel,
    Warehouse,
)
from app.modules.invoices.infrastructure.models import Invoice, InvoiceLine
from app.modules.settings.domain.operational import low_stock_limit_units
from app.modules.stock_adjustments.infrastructure.models import StockAdjustmentRequest
from app.modules.supplier_invoices.infrastructure.models import (
    SupplierInvoice,
    SupplierInvoiceLine,
)


router = APIRouter(prefix="/dashboard", tags=["Resumen operativo"])


def period_start(period: str, today: date) -> date:
    if period == "today":
        return today
    if period == "week":
        return today - timedelta(days=today.weekday())
    return today.replace(day=1)


@router.get("/summary")
def summary(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    period: Annotated[Literal["today", "week", "month"], Query()] = "month",
):
    now = datetime.now(ZoneInfo("America/Guayaquil"))
    start = period_start(period, now.date())
    inventory_rows = db.execute(
        select(Product, InventoryPositionModel)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(Product.is_active.is_(True), Warehouse.code == "principal")
        .order_by(Product.sku)
    ).all()
    available_units = 0
    products_with_stock = 0
    low_stock = []
    for product, stored in inventory_rows:
        position = InventoryPosition(
            stored.physical_confirmed,
            stored.reserved,
            stored.invoiced_not_dispatched,
            stored.blocked_by_incident,
        )
        available_units += position.available_to_invoice
        if position.available_to_invoice > 0:
            products_with_stock += 1
        limit = low_stock_limit_units(db, product.units_per_box)
        if position.available_to_invoice <= limit:
            low_stock.append(
                {
                    "sku": product.sku,
                    "product_name": product.name,
                    "available": position.available_to_invoice,
                    "threshold": limit,
                    "status": (
                        "out_of_stock"
                        if position.available_to_invoice <= 0
                        else "low_stock"
                    ),
                }
            )

    supplier_filters = (
        SupplierInvoice.status == "confirmed",
        SupplierInvoice.issued_at >= start,
        SupplierInvoice.issued_at <= now.date(),
    )
    entries_units = int(
        db.scalar(
            select(func.coalesce(func.sum(SupplierInvoiceLine.quantity), 0))
            .join(
                SupplierInvoice,
                SupplierInvoice.id == SupplierInvoiceLine.supplier_invoice_id,
            )
            .where(*supplier_filters)
        )
        or 0
    )
    supplier_invoice_count = int(
        db.scalar(select(func.count(SupplierInvoice.id)).where(*supplier_filters)) or 0
    )

    sales_filters = (
        Invoice.administrative_status == "confirmed",
        Invoice.invoice_date >= start,
        Invoice.invoice_date <= now.date(),
    )
    sales_units = int(
        db.scalar(
            select(func.coalesce(func.sum(InvoiceLine.quantity), 0))
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(*sales_filters)
        )
        or 0
    )
    sales_invoice_count = int(
        db.scalar(select(func.count(Invoice.id)).where(*sales_filters)) or 0
    )
    invoiced_value = db.scalar(
        select(func.coalesce(func.sum(Invoice.total_value), 0)).where(*sales_filters)
    )

    invoice_issues = list(
        db.scalars(
            select(Invoice)
            .where(
                Invoice.administrative_status == "confirmed",
                Invoice.inventory_status.in_(["pending", "partial", "error"]),
            )
            .order_by(Invoice.invoice_date, Invoice.created_at)
            .limit(5)
        ).all()
    )
    invoice_issue_count = int(
        db.scalar(
            select(func.count(Invoice.id)).where(
                Invoice.administrative_status == "confirmed",
                Invoice.inventory_status.in_(["pending", "partial", "error"]),
            )
        )
        or 0
    )
    open_incidents = list(
        db.scalars(
            select(Incident)
            .where(Incident.status.in_(["open", "in_review"]))
            .order_by(Incident.created_at)
            .limit(5)
        ).all()
    )
    open_incident_count = int(
        db.scalar(
            select(func.count(Incident.id)).where(
                Incident.status.in_(["open", "in_review"])
            )
        )
        or 0
    )
    pending_adjustments = int(
        db.scalar(
            select(func.count(StockAdjustmentRequest.id)).where(
                StockAdjustmentRequest.status == "pending"
            )
        )
        or 0
    )
    pending_adjustment_rows = db.execute(
        select(StockAdjustmentRequest, Product)
        .join(Product, Product.id == StockAdjustmentRequest.product_id)
        .where(StockAdjustmentRequest.status == "pending")
        .order_by(StockAdjustmentRequest.requested_at)
        .limit(5)
    ).all()

    attention = [
        {
            "type": "invoice_inventory",
            "title": f"Factura {invoice.invoice_number}",
            "description": invoice.inventory_last_error
            or "El descuento de inventario requiere revisión.",
            "date": invoice.created_at,
            "target": "invoices",
            "target_id": str(invoice.id),
            "severity": "error",
        }
        for invoice in invoice_issues
    ]
    attention.extend(
        {
            "type": "incident",
            "title": "Incidencia abierta",
            "description": incident.description,
            "date": incident.created_at,
            "target": "deliveries",
            "target_id": str(incident.invoice_id) if incident.invoice_id else None,
            "severity": "warning",
        }
        for incident in open_incidents
    )
    attention.extend(
        {
            "type": "adjustment",
            "title": f"Ajuste pendiente · {product.name}",
            "description": request.request_reason,
            "date": request.requested_at,
            "target": "adjustments",
            "target_id": str(request.id),
            "severity": "warning",
        }
        for request, product in pending_adjustment_rows
    )
    attention.extend(
        {
            "type": "stock",
            "title": item["product_name"],
            "description": (
                "Producto agotado."
                if item["status"] == "out_of_stock"
                else f"Disponible por debajo del mínimo: {item['available']} unidades."
            ),
            "date": now,
            "target": "inventory",
            "target_id": item["sku"],
            "severity": "error" if item["status"] == "out_of_stock" else "warning",
        }
        for item in low_stock[:5]
    )
    attention.sort(key=lambda item: (item["severity"] != "error", str(item["date"])))

    sales_activity = list(
        db.scalars(
            select(Invoice)
            .where(*sales_filters)
            .order_by(Invoice.created_at.desc())
            .limit(5)
        ).all()
    )
    supplier_activity = list(
        db.scalars(
            select(SupplierInvoice)
            .where(*supplier_filters)
            .order_by(SupplierInvoice.created_at.desc())
            .limit(5)
        ).all()
    )
    activity = []
    for invoice in sales_activity:
        units = int(
            db.scalar(
                select(func.coalesce(func.sum(InvoiceLine.quantity), 0)).where(
                    InvoiceLine.invoice_id == invoice.id
                )
            )
            or 0
        )
        user = db.get(User, invoice.created_by_user_id)
        activity.append(
            {
                "date": invoice.created_at,
                "type": "Factura de venta",
                "document": f"Factura {invoice.invoice_number}",
                "description": invoice.chain_name or invoice.customer_name,
                "quantity": -units,
                "user": user.full_name if user else "Usuario no disponible",
                "result": "Inventario descontado",
                "target": "invoices",
                "target_id": str(invoice.id),
            }
        )
    for supplier_invoice in supplier_activity:
        units = int(
            db.scalar(
                select(func.coalesce(func.sum(SupplierInvoiceLine.quantity), 0)).where(
                    SupplierInvoiceLine.supplier_invoice_id == supplier_invoice.id
                )
            )
            or 0
        )
        user = db.get(User, supplier_invoice.registered_by_user_id)
        activity.append(
            {
                "date": supplier_invoice.created_at,
                "type": "Entrada de proveedor",
                "document": f"Factura {supplier_invoice.invoice_number}",
                "description": supplier_invoice.supplier_name,
                "quantity": units,
                "user": user.full_name if user else "Usuario no disponible",
                "result": "Inventario ingresado",
                "target": "entries",
                "target_id": str(supplier_invoice.id),
            }
        )
    activity.sort(key=lambda item: item["date"], reverse=True)

    return {
        "period": {
            "key": period,
            "start": start,
            "end": now.date(),
            "last_updated": utc_now(),
        },
        "metrics": {
            "available_units": available_units,
            "products_with_stock": products_with_stock,
            "entries_units": entries_units,
            "supplier_invoices": supplier_invoice_count,
            "sales_units": sales_units,
            "sales_invoices": sales_invoice_count,
            "invoiced_value": invoiced_value,
            "out_of_stock": sum(item["status"] == "out_of_stock" for item in low_stock),
            "low_stock": sum(item["status"] == "low_stock" for item in low_stock),
            "attention": (
                invoice_issue_count
                + open_incident_count
                + pending_adjustments
                + len(low_stock)
            ),
        },
        "attention": attention[:10],
        "recent_activity": activity[:8],
    }
