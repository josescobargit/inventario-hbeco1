import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.domain.availability import InventoryPosition
from app.modules.inventory.infrastructure.models import (
    InventoryMovement,
    InventoryPositionModel,
    Warehouse,
)
from app.modules.invoices.infrastructure.models import (
    Invoice,
    InvoiceAlert,
    InvoiceLine,
)
from app.modules.purchase_orders.infrastructure.models import (
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.modules.reservations.infrastructure.models import Reservation, ReservationLine
from app.modules.settings.domain.operational import exception_invoices_allowed


class LineInput(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    quantity: int = Field(gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)


class InvoiceInput(BaseModel):
    invoice_number: str
    invoice_date: date
    purchase_order_id: uuid.UUID | None = None
    source_type: Literal[
        "purchase_order",
        "sale_without_po",
        "internal_consumption",
        "sample",
        "replacement",
        "other",
    ]
    customer_name: str = Field(min_length=2, max_length=160)
    chain_name: str | None = Field(default=None, max_length=160)
    authorization_number: str | None = None
    remittance_guide: str | None = None
    total_value: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None
    reservation_ids: list[uuid.UUID] = []
    lines: list[LineInput] = Field(min_length=1)

    @field_validator("invoice_number")
    @classmethod
    def invoice_format(cls, value):
        value = value.strip()
        if not re.fullmatch(r"\d{3}-\d{3}-\d{9}", value):
            raise ValueError("Usa el formato 001-001-000000686.")
        return value

    @model_validator(mode="after")
    def source_matches(self):
        if self.source_type == "purchase_order" and not self.purchase_order_id:
            raise ValueError("Selecciona la OC relacionada.")
        if self.source_type != "purchase_order" and self.purchase_order_id:
            raise ValueError("La categoría elegida no corresponde a una OC.")
        return self


router = APIRouter(prefix="/invoices", tags=["Facturas emitidas"])


@router.get("")
def list_invoices(_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return (
        db.execute(select(Invoice).order_by(Invoice.created_at.desc())).scalars().all()
    )


@router.post("", status_code=201)
def register_invoice(
    payload: InvoiceInput, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
):
    if payload.source_type != "purchase_order" and not exception_invoices_allowed(db):
        raise HTTPException(
            status_code=422,
            detail="Las facturas de excepción están desactivadas en configuración.",
        )
    if db.scalar(
        select(Invoice.id).where(Invoice.invoice_number == payload.invoice_number)
    ):
        raise HTTPException(status_code=409, detail="Esta factura ya está registrada.")
    skus = [line.sku.strip().upper() for line in payload.lines]
    if len(set(skus)) != len(skus):
        raise HTTPException(status_code=422, detail="No repitas un SKU en la factura.")
    rows = db.execute(
        select(Product, InventoryPositionModel, Warehouse)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(Product.sku.in_(skus), Warehouse.code == "principal")
        .with_for_update(of=InventoryPositionModel)
    ).all()
    found = {p.sku: (p, pos, wh) for p, pos, wh in rows}
    if set(skus) != set(found):
        raise HTTPException(
            status_code=422,
            detail=f"SKU desconocidos: {', '.join(sorted(set(skus) - set(found)))}",
        )
    po = (
        db.get(PurchaseOrder, payload.purchase_order_id)
        if payload.purchase_order_id
        else None
    )
    po_quantities = {}
    if po:
        po_quantities = {
            p.sku: line.ordered_quantity
            for line, p in db.execute(
                select(PurchaseOrderLine, Product)
                .join(Product, Product.id == PurchaseOrderLine.product_id)
                .where(PurchaseOrderLine.purchase_order_id == po.id)
            )
        }
    reservations = []
    if payload.reservation_ids:
        reservations = db.scalars(
            select(Reservation)
            .where(
                Reservation.id.in_(payload.reservation_ids),
                Reservation.status == "active",
            )
            .with_for_update()
        ).all()
        if len(reservations) != len(set(payload.reservation_ids)):
            raise HTTPException(
                status_code=422, detail="Alguna reserva no existe o ya no está activa."
            )
        if po and any(
            r.purchase_order_reference != po.order_number for r in reservations
        ):
            raise HTTPException(
                status_code=422,
                detail="Las reservas seleccionadas deben estar vinculadas a esta OC.",
            )
    reservation_lines = (
        db.scalars(
            select(ReservationLine)
            .where(ReservationLine.reservation_id.in_([r.id for r in reservations]))
            .with_for_update()
        ).all()
        if reservations
        else []
    )
    reserved_by_product = {}
    for line in reservation_lines:
        reserved_by_product[line.product_id] = (
            reserved_by_product.get(line.product_id, 0) + line.remaining_quantity
        )
    requested = {line.sku.strip().upper(): line for line in payload.lines}
    quantity_excesses: dict[str, tuple[int, int]] = {}
    for sku, line in requested.items():
        product, pos, _ = found[sku]
        covered = min(line.quantity, reserved_by_product.get(product.id, 0))
        available = InventoryPosition(
            pos.physical_confirmed,
            pos.reserved,
            pos.invoiced_not_dispatched,
            pos.blocked_by_incident,
        ).available_to_invoice
        if line.quantity - covered > available:
            raise HTTPException(
                status_code=409,
                detail=f"{sku}: se requieren {line.quantity - covered} unidades libres y solo hay {available}.",
            )
        if po and sku in po_quantities:
            already = db.scalar(
                select(func.coalesce(func.sum(InvoiceLine.quantity), 0))
                .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
                .where(
                    Invoice.purchase_order_id == po.id,
                    InvoiceLine.product_id == product.id,
                )
            )
            if already + line.quantity > po_quantities[sku]:
                quantity_excesses[sku] = (
                    po_quantities[sku],
                    already + line.quantity,
                )
    invoice = Invoice(
        invoice_number=payload.invoice_number,
        invoice_date=payload.invoice_date,
        purchase_order_id=payload.purchase_order_id,
        source_type=payload.source_type,
        customer_name=payload.customer_name,
        chain_name=payload.chain_name or (po.chain_name if po else None),
        authorization_number=payload.authorization_number,
        remittance_guide=payload.remittance_guide,
        total_value=payload.total_value,
        notes=payload.notes,
        created_by_user_id=user.id,
    )
    db.add(invoice)
    db.flush()
    for sku, line_input in requested.items():
        product, pos, warehouse = found[sku]
        remaining = line_input.quantity
        for reservation_line in [
            x
            for x in reservation_lines
            if x.product_id == product.id and x.remaining_quantity > 0
        ]:
            used = min(remaining, reservation_line.remaining_quantity)
            reservation_line.remaining_quantity -= used
            pos.reserved -= used
            remaining -= used
            if remaining == 0:
                break
        outside = bool(po and sku not in po_quantities)
        db.add(
            InvoiceLine(
                invoice_id=invoice.id,
                product_id=product.id,
                quantity=line_input.quantity,
                unit_price=line_input.unit_price,
                outside_purchase_order=outside,
            )
        )
        if outside:
            db.add(
                InvoiceAlert(
                    invoice_id=invoice.id,
                    product_id=product.id,
                    alert_type="product_outside_purchase_order",
                    description=f"{sku} no consta en la OC original.",
                )
            )
            invoice.incident_status = "open"
        if sku in quantity_excesses:
            ordered_quantity, cumulative_invoiced = quantity_excesses[sku]
            db.add(
                InvoiceAlert(
                    invoice_id=invoice.id,
                    product_id=product.id,
                    alert_type="quantity_exceeds_purchase_order",
                    description=(
                        f"{sku}: la OC registra {ordered_quantity} unidades y las "
                        f"facturas vinculadas acumulan {cumulative_invoiced}."
                    ),
                )
            )
            invoice.incident_status = "open"
        before = {
            "reserved": pos.reserved + line_input.quantity - remaining,
            "invoiced_not_dispatched": pos.invoiced_not_dispatched,
            "version": pos.version,
        }
        pos.invoiced_not_dispatched += line_input.quantity
        pos.version += 1
        db.add(
            InventoryMovement(
                warehouse_id=warehouse.id,
                product_id=product.id,
                actor_user_id=user.id,
                movement_type="invoice_registered",
                reference_type="invoice",
                reference_id=str(invoice.id),
                reason="Factura emitida en Contífico registrada",
                before_value=before,
                after_value={
                    "reserved": pos.reserved,
                    "invoiced_not_dispatched": pos.invoiced_not_dispatched,
                    "version": pos.version,
                },
            )
        )
    for reservation in reservations:
        if not any(
            line.remaining_quantity
            for line in reservation_lines
            if line.reservation_id == reservation.id
        ):
            reservation.status = "used"
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="invoice_registered",
            entity_type="invoice",
            entity_id=str(invoice.id),
            new_value={"number": invoice.invoice_number, "products": len(requested)},
        )
    )
    db.commit()
    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "incident_status": invoice.incident_status,
        "dispatch_status": invoice.dispatch_status,
    }
