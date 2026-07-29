import csv
import io
import uuid
from datetime import date, datetime, time, timezone
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import BigInteger, and_, cast, func, or_, select
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
from app.modules.invoices.infrastructure.models import Invoice
from app.modules.settings.domain.operational import low_stock_limit_units


router = APIRouter(prefix="/inventory", tags=["Inventario"])


MOVEMENT_LABELS = {
    "bulk_physical_count": "Carga física",
    "physical_adjustment": "Ajuste físico",
    "reservation_created": "Reserva creada",
    "reservation_released": "Reserva liberada",
    "invoice_registered": "Factura registrada",
    "invoice_edited": "Factura corregida",
    "invoice_cancelled": "Factura anulada",
    "invoice_inventory_correction": "Corrección auditada de factura",
    "dispatch_confirmed": "Despacho confirmado",
    "incident_resolved": "Incidencia resuelta",
    "customer_return": "Devolución",
    "general_entry": "Entrada general",
    "general_exit": "Salida general",
    "supplier_invoice_registered": "Factura de proveedor registrada",
    "supplier_invoice_edited": "Factura de proveedor corregida",
    "supplier_invoice_cancelled": "Factura de proveedor anulada",
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
        "quantity": movement.quantity,
        "reference_type": movement.reference_type,
        "reference_id": movement.reference_id,
        "purchase_order_id": movement.purchase_order_id,
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
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[AvailabilityResponse]:
    statement = (
        select(Product, InventoryPositionModel)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(Product.is_active.is_(True), Warehouse.code == "principal")
        .order_by(Product.name, Product.sku)
        .limit(limit)
    )
    if search and search.strip():
        normalized_fields = []
        for field in (
            Product.sku,
            Product.name,
            Product.barcode,
            Product.contifico_aux_code,
            Product.description,
        ):
            expression = func.lower(func.coalesce(field, ""))
            for accented, plain in zip("áéíóúüñ", "aeiouun", strict=True):
                expression = func.replace(expression, accented, plain)
            normalized_fields.append(expression)
        terms = (
            search.strip()
            .lower()
            .translate(str.maketrans("áéíóúüñ", "aeiouun"))
            .split()
        )
        statement = statement.where(
            and_(
                *[
                    or_(*[field.like(f"%{term}%") for field in normalized_fields])
                    for term in terms
                ]
            )
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
                id=product.id,
                sku=product.sku,
                product_name=product.name,
                barcode=product.barcode,
                contifico_aux_code=product.contifico_aux_code,
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


def historical_cutoff(day: date) -> datetime:
    local = datetime.combine(
        day,
        time(23, 59, 59, 999999),
        tzinfo=ZoneInfo("America/Guayaquil"),
    )
    return local.astimezone(timezone.utc)


def _historical_inventory_rows(
    db: Session,
    *,
    cutoff: datetime,
    search: str | None,
    category: str | None,
    show_zero: bool,
    show_negative: bool,
) -> list[dict[str, Any]]:
    before_physical = cast(
        InventoryMovement.before_value["physical_confirmed"].as_integer(), BigInteger
    )
    after_physical = cast(
        InventoryMovement.after_value["physical_confirmed"].as_integer(), BigInteger
    )
    delta = func.coalesce(after_physical, 0) - func.coalesce(before_physical, 0)
    historical = (
        select(
            InventoryMovement.product_id.label("product_id"),
            func.coalesce(func.sum(delta), 0).label("historical_quantity"),
        )
        .join(Warehouse, Warehouse.id == InventoryMovement.warehouse_id)
        .where(
            Warehouse.code == "principal",
            InventoryMovement.status == "confirmed",
            InventoryMovement.occurred_at <= cutoff,
        )
        .group_by(InventoryMovement.product_id)
        .subquery()
    )
    latest_physical_count = (
        select(
            cast(
                InventoryMovement.after_value["physical_confirmed"].as_integer(),
                BigInteger,
            )
        )
        .where(
            InventoryMovement.product_id == Product.id,
            InventoryMovement.status == "confirmed",
            InventoryMovement.movement_type == "bulk_physical_count",
            InventoryMovement.occurred_at <= cutoff,
        )
        .order_by(
            InventoryMovement.occurred_at.desc(),
            InventoryMovement.id.desc(),
        )
        .limit(1)
        .correlate(Product)
        .scalar_subquery()
    )
    latest_physical_count_at = (
        select(InventoryMovement.occurred_at)
        .where(
            InventoryMovement.product_id == Product.id,
            InventoryMovement.status == "confirmed",
            InventoryMovement.movement_type == "bulk_physical_count",
            InventoryMovement.occurred_at <= cutoff,
        )
        .order_by(
            InventoryMovement.occurred_at.desc(),
            InventoryMovement.id.desc(),
        )
        .limit(1)
        .correlate(Product)
        .scalar_subquery()
    )
    statement = (
        select(
            Product,
            func.coalesce(historical.c.historical_quantity, 0),
            func.coalesce(InventoryPositionModel.physical_confirmed, 0),
            latest_physical_count,
            latest_physical_count_at,
        )
        .outerjoin(historical, historical.c.product_id == Product.id)
        .outerjoin(
            InventoryPositionModel,
            InventoryPositionModel.product_id == Product.id,
        )
        .outerjoin(
            Warehouse,
            Warehouse.id == InventoryPositionModel.warehouse_id,
        )
        .where(or_(Warehouse.code == "principal", Warehouse.id.is_(None)))
        .order_by(Product.name, Product.sku)
    )
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(Product.name.ilike(term), Product.sku.ilike(term))
        )
    if category and category.strip():
        statement = statement.where(Product.category == category.strip())
    result = []
    for (
        product,
        historical_quantity,
        current_quantity,
        physical_count,
        physical_count_at,
    ) in db.execute(statement):
        historical_value = int(historical_quantity)
        if not show_zero and historical_value == 0:
            continue
        if show_negative and historical_value >= 0:
            continue
        result.append(
            {
                "product_id": product.id,
                "product_name": product.name,
                "sku": product.sku,
                "category": product.category,
                "inventory_at_cutoff": historical_value,
                "current_inventory": int(current_quantity),
                "difference": int(current_quantity) - historical_value,
                "confirmed_physical_count": (
                    int(physical_count) if physical_count is not None else None
                ),
                "physical_count_at": physical_count_at,
                "difference_vs_physical_count": (
                    historical_value - int(physical_count)
                    if physical_count is not None
                    else None
                ),
            }
        )
    return result


@router.get("/history")
def inventory_at_date(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    cutoff_date: date,
    search: Annotated[str | None, Query(max_length=100)] = None,
    category: Annotated[str | None, Query(max_length=100)] = None,
    show_zero: bool = True,
    show_negative: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=10, le=100)] = 25,
) -> dict:
    cutoff = historical_cutoff(cutoff_date)
    rows = _historical_inventory_rows(
        db,
        cutoff=cutoff,
        search=search,
        category=category,
        show_zero=show_zero,
        show_negative=show_negative,
    )
    start = (page - 1) * page_size
    return {
        "label": f"Inventario según el sistema al {cutoff_date.strftime('%d/%m/%Y')}",
        "cutoff_local": datetime.combine(
            cutoff_date,
            time(23, 59, 59),
            tzinfo=ZoneInfo("America/Guayaquil"),
        ),
        "cutoff_utc": cutoff,
        "theoretical": True,
        "items": rows[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": len(rows),
        "pages": max(1, (len(rows) + page_size - 1) // page_size),
    }


@router.get("/history/export")
def export_inventory_at_date(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    cutoff_date: date,
    search: Annotated[str | None, Query(max_length=100)] = None,
    category: Annotated[str | None, Query(max_length=100)] = None,
    show_zero: bool = True,
    show_negative: bool = False,
) -> StreamingResponse:
    rows = _historical_inventory_rows(
        db,
        cutoff=historical_cutoff(cutoff_date),
        search=search,
        category=category,
        show_zero=show_zero,
        show_negative=show_negative,
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Producto",
            "SKU",
            "Categoría",
            "Inventario al corte",
            "Inventario actual",
            "Diferencia",
            "Conteo físico confirmado",
            "Fecha del conteo",
            "Diferencia vs. conteo físico",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["product_name"],
                row["sku"],
                row["category"],
                row["inventory_at_cutoff"],
                row["current_inventory"],
                row["difference"],
                row["confirmed_physical_count"],
                row["physical_count_at"],
                row["difference_vs_physical_count"],
            ]
        )
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="inventario-{cutoff_date.isoformat()}.csv"'
            )
        },
    )


@router.get("/history/{product_id}/movements")
def historical_product_movements(
    product_id: uuid.UUID,
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    cutoff_date: date,
) -> dict:
    product = db.get(Product, product_id)
    if product is None:
        return {"product": None, "items": []}
    cutoff = historical_cutoff(cutoff_date)
    movements = list(
        db.scalars(
            select(InventoryMovement)
            .join(Warehouse, Warehouse.id == InventoryMovement.warehouse_id)
            .where(
                InventoryMovement.product_id == product.id,
                InventoryMovement.status == "confirmed",
                InventoryMovement.occurred_at <= cutoff,
                Warehouse.code == "principal",
            )
            .order_by(InventoryMovement.occurred_at, InventoryMovement.id)
        ).all()
    )
    invoice_ids = []
    for movement in movements:
        if movement.reference_type == "invoice" and movement.reference_id:
            try:
                invoice_ids.append(uuid.UUID(movement.reference_id))
            except ValueError:
                pass
    invoice_numbers = {
        str(invoice.id): invoice.invoice_number
        for invoice in db.scalars(
            select(Invoice).where(Invoice.id.in_(invoice_ids))
        ).all()
    }
    balance = 0
    items = []
    for movement in movements:
        affected_field, delta = movement_delta(
            movement.before_value, movement.after_value
        )
        physical_delta = delta if affected_field == "physical_confirmed" else 0
        balance += physical_delta
        reference = invoice_numbers.get(
            movement.reference_id or "",
            (
                f"{movement.reference_type}: {movement.reference_id}"
                if movement.reference_type and movement.reference_id
                else "Sin documento"
            ),
        )
        items.append(
            {
                "id": movement.id,
                "occurred_at": movement.occurred_at,
                "movement_type": movement.movement_type,
                "movement_label": movement_label(movement.movement_type),
                "document": reference,
                "entry": max(physical_delta, 0),
                "exit": max(-physical_delta, 0),
                "balance": balance,
            }
        )
    return {
        "product": {
            "id": product.id,
            "name": product.name,
            "sku": product.sku,
        },
        "cutoff": cutoff,
        "items": items,
    }
