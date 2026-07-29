import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.catalog.infrastructure.models import Product
from app.core.time import utc_now
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
from app.modules.invoices.domain.inventory_audit import audit_invoices
from app.modules.purchase_orders.infrastructure.models import (
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.modules.documents.domain.extraction_runner import run_document_extraction
from app.modules.documents.domain.upload_stream import stream_upload
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


class QuickInvoiceInput(BaseModel):
    invoice_number: str
    invoice_date: date
    purchase_order_id: uuid.UUID
    is_void: bool = False
    authorization_number: str | None = None
    remittance_guide: str | None = None
    total_value: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None
    lines: list[LineInput] = []

    @field_validator("invoice_number")
    @classmethod
    def invoice_format(cls, value):
        return InvoiceInput.invoice_format(value)

    @model_validator(mode="after")
    def valid_detail(self):
        if self.is_void and self.lines:
            raise ValueError("Una factura anulada no puede contener productos.")
        if not self.is_void and not self.lines:
            raise ValueError("Una factura activa debe contener al menos un producto.")
        return self


class BulkInvoiceInput(BaseModel):
    invoices: list[QuickInvoiceInput] = Field(min_length=1, max_length=100)
    batch_id: uuid.UUID = Field(default_factory=uuid.uuid4)


router = APIRouter(prefix="/invoices", tags=["Facturas emitidas"])

ALLOWED_IMPORT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}
MAX_IMPORT_BYTES = 15 * 1024 * 1024


@router.post("/imports/preview")
async def preview_invoice_documents(
    _user: CurrentUser,
    files: Annotated[list[UploadFile], File()],
):
    if not files:
        raise HTTPException(status_code=422, detail="Selecciona al menos un documento.")
    if len(files) > 50:
        raise HTTPException(
            status_code=422, detail="Procesa hasta 50 documentos por lote."
        )
    documents = []
    for upload in files:
        document = await stream_upload(
            upload,
            allowed_types=ALLOWED_IMPORT_TYPES,
            max_bytes=MAX_IMPORT_BYTES,
        )
        try:
            extracted = run_document_extraction(document)
        except Exception as error:
            documents.append(
                {
                    "filename": upload.filename or "documento",
                    "status": "error",
                    "detail": str(error),
                    "text": "",
                    "table_rows": [],
                }
            )
            continue
        finally:
            document.cleanup()
        documents.append(
            {
                "filename": upload.filename or "documento",
                "status": "recognized",
                "text": extracted.text,
                "table_rows": extracted.table_rows,
                "extraction_method": extracted.method,
                "page_count": extracted.page_count,
                "warnings": extracted.warnings,
            }
        )
    return {"documents": documents}


@router.get("")
def list_invoices(_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return (
        db.execute(select(Invoice).order_by(Invoice.created_at.desc())).scalars().all()
    )


def _register_invoice(
    payload: InvoiceInput,
    user,
    db: Session,
    *,
    commit: bool,
    idempotency_key: str | None = None,
    batch_id: uuid.UUID | None = None,
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
        idempotency_key=idempotency_key,
        batch_id=batch_id,
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
        inventory_applied_at=utc_now(),
    )
    db.add(invoice)
    db.flush()
    inventory_affected = []
    inventory_movements = []
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
            "physical_confirmed": pos.physical_confirmed,
            "reserved": pos.reserved + line_input.quantity - remaining,
            "version": pos.version,
        }
        if line_input.quantity > pos.physical_confirmed:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{sku}: se intentan facturar {line_input.quantity} unidades "
                    f"y el inventario físico es {pos.physical_confirmed}."
                ),
            )
        pos.physical_confirmed -= line_input.quantity
        pos.invoiced_not_dispatched += line_input.quantity
        pos.version += 1
        movement = InventoryMovement(
            warehouse_id=warehouse.id,
            product_id=product.id,
            purchase_order_id=invoice.purchase_order_id,
            actor_user_id=user.id,
            movement_type="invoice_registered",
            reference_type="invoice",
            reference_id=str(invoice.id),
            idempotency_key=f"invoice:{invoice.id}:{product.id}:confirmed",
            batch_id=batch_id,
            quantity=line_input.quantity,
            reason="Salida por factura",
            before_value=before,
            after_value={
                "physical_confirmed": pos.physical_confirmed,
                "reserved": pos.reserved,
                "invoiced_not_dispatched": pos.invoiced_not_dispatched,
                "version": pos.version,
            },
        )
        db.add(movement)
        db.flush()
        inventory_movements.append(movement)
        inventory_affected.append(
            {
                "sku": sku,
                "quantity": line_input.quantity,
                "physical_confirmed": pos.physical_confirmed,
                "available_to_invoice": InventoryPosition(
                    pos.physical_confirmed,
                    pos.reserved,
                    pos.invoiced_not_dispatched,
                    pos.blocked_by_incident,
                ).available_to_invoice,
            }
        )
    for reservation in reservations:
        if not any(
            line.remaining_quantity
            for line in reservation_lines
            if line.reservation_id == reservation.id
        ):
            reservation.status = "used"
    invoice.inventory_status = "discounted"
    invoice.inventory_discounted_quantity = sum(line.quantity for line in payload.lines)
    invoice.inventory_movement_id = (
        inventory_movements[0].id if inventory_movements else None
    )
    invoice.inventory_attempts = 1
    invoice.inventory_last_error = None
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="invoice_registered",
            entity_type="invoice",
            entity_id=str(invoice.id),
            new_value={"number": invoice.invoice_number, "products": len(requested)},
        )
    )
    if commit:
        db.commit()
    else:
        db.flush()
    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "incident_status": invoice.incident_status,
        "dispatch_status": invoice.dispatch_status,
        "delivery_status": invoice.delivery_status,
        "inventory_affected": inventory_affected,
    }


@router.post("", status_code=201)
def register_invoice(
    payload: InvoiceInput,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    # The invoice number remains the durable business key; the request key is
    # also persisted so a retry can be audited and resolved to the same result.
    existing = db.scalar(
        select(Invoice).where(Invoice.invoice_number == payload.invoice_number)
    )
    if existing is None and idempotency_key:
        existing = db.scalar(
            select(Invoice).where(Invoice.idempotency_key == idempotency_key)
        )
    if existing is not None:
        return {
            "id": existing.id,
            "invoice_number": existing.invoice_number,
            "incident_status": existing.incident_status,
            "dispatch_status": existing.dispatch_status,
            "delivery_status": existing.delivery_status,
            "inventory_affected": [],
            "duplicate": True,
            "idempotency_key": idempotency_key,
        }
    try:
        result = _register_invoice(
            payload, user, db, commit=True, idempotency_key=idempotency_key
        )
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(Invoice).where(
                (Invoice.invoice_number == payload.invoice_number)
                | (
                    (Invoice.idempotency_key == idempotency_key)
                    if idempotency_key
                    else False
                )
            )
        )
        if existing is None:
            raise
        return {
            "id": existing.id,
            "invoice_number": existing.invoice_number,
            "incident_status": existing.incident_status,
            "dispatch_status": existing.dispatch_status,
            "delivery_status": existing.delivery_status,
            "inventory_affected": [],
            "duplicate": True,
            "idempotency_key": idempotency_key,
        }
    return {**result, "duplicate": False, "idempotency_key": idempotency_key}


@router.post("/bulk", status_code=201)
def register_bulk_invoices(
    payload: BulkInvoiceInput,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    results = []
    for item in payload.invoices:
        existing = db.scalar(
            select(Invoice).where(Invoice.invoice_number == item.invoice_number)
        )
        if existing is not None:
            results.append(
                {
                    "id": existing.id,
                    "invoice_number": existing.invoice_number,
                    "status": "duplicate",
                    "detail": "Esta factura ya está registrada.",
                }
            )
            continue
        try:
            po = db.get(PurchaseOrder, item.purchase_order_id)
            if po is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"{item.invoice_number}: selecciona una OC válida.",
                )
            customer = po.customer_name or po.chain_name
            if item.is_void:
                invoice = Invoice(
                    invoice_number=item.invoice_number,
                    idempotency_key=f"{payload.batch_id}:{item.invoice_number}",
                    batch_id=payload.batch_id,
                    invoice_date=item.invoice_date,
                    purchase_order_id=po.id,
                    source_type="purchase_order",
                    customer_name=customer,
                    chain_name=po.chain_name,
                    authorization_number=item.authorization_number,
                    remittance_guide=item.remittance_guide,
                    total_value=item.total_value,
                    notes=item.notes,
                    administrative_status="cancelled",
                    dispatch_status="not_applicable",
                    delivery_status="not_applicable",
                    inventory_status="not_applicable",
                    created_by_user_id=user.id,
                )
                db.add(invoice)
                db.flush()
                db.add(
                    AuditLog(
                        actor_user_id=user.id,
                        action="void_invoice_registered",
                        entity_type="invoice",
                        entity_id=str(invoice.id),
                        new_value={"number": invoice.invoice_number},
                    )
                )
                results.append(
                    {
                        "id": invoice.id,
                        "invoice_number": invoice.invoice_number,
                        "administrative_status": "cancelled",
                        "status": "saved",
                    }
                )
            else:
                result = _register_invoice(
                    InvoiceInput(
                        invoice_number=item.invoice_number,
                        invoice_date=item.invoice_date,
                        purchase_order_id=po.id,
                        source_type="purchase_order",
                        customer_name=customer,
                        chain_name=po.chain_name,
                        authorization_number=item.authorization_number,
                        remittance_guide=item.remittance_guide,
                        total_value=item.total_value,
                        notes=item.notes,
                        lines=item.lines,
                    ),
                    user,
                    db,
                    commit=False,
                    idempotency_key=f"{payload.batch_id}:{item.invoice_number}",
                    batch_id=payload.batch_id,
                )
                results.append({**result, "status": "saved"})
            # Each document is its own atomic unit. Its invoice, lines,
            # movements, reservations and audit record commit together.
            db.commit()
        except HTTPException as caught:
            db.rollback()
            results.append(
                {
                    "invoice_number": item.invoice_number,
                    "status": "error",
                    "detail": str(caught.detail),
                }
            )
        except Exception:
            db.rollback()
            results.append(
                {
                    "invoice_number": item.invoice_number,
                    "status": "error",
                    "detail": "No se pudo guardar esta factura.",
                }
            )
    return {
        "invoices": results,
        "summary": {
            "saved": sum(item["status"] == "saved" for item in results),
            "duplicates": sum(item["status"] == "duplicate" for item in results),
            "errors": sum(item["status"] == "error" for item in results),
        },
    }


@router.post("/{invoice_id}/cancel")
def cancel_invoice(
    invoice_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    invoice = db.scalar(
        select(Invoice).where(Invoice.id == invoice_id).with_for_update()
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="No encontramos la factura.")
    if invoice.administrative_status == "cancelled":
        return {
            "id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "administrative_status": "cancelled",
            "duplicate": True,
            "inventory_affected": [],
        }
    if invoice.dispatch_status != "pending":
        raise HTTPException(
            status_code=409,
            detail="No puede anularse una factura después de iniciar su despacho.",
        )
    audit = audit_invoices(db, [invoice.id])[0]
    if audit["status"] in {"duplicate", "over", "error", "product_incorrect"}:
        raise HTTPException(
            status_code=409,
            detail="La factura tiene movimientos inconsistentes y requiere revisión antes de anularse.",
        )
    discounted_by_product = {
        item["product_id"]: max(0, item["discounted"])
        for item in audit["product_differences"]
    }
    rows = db.execute(
        select(InvoiceLine, Product, InventoryPositionModel, Warehouse)
        .join(Product, Product.id == InvoiceLine.product_id)
        .join(
            InventoryPositionModel,
            InventoryPositionModel.product_id == Product.id,
        )
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(InvoiceLine.invoice_id == invoice.id, Warehouse.code == "principal")
        .with_for_update(of=InventoryPositionModel)
    ).all()
    inventory_affected = []
    for line, product, position, warehouse in rows:
        before = {
            "physical_confirmed": position.physical_confirmed,
            "invoiced_not_dispatched": position.invoiced_not_dispatched,
            "version": position.version,
        }
        reversed_quantity = min(line.quantity, discounted_by_product.get(product.id, 0))
        position.physical_confirmed += reversed_quantity
        position.invoiced_not_dispatched = max(
            0, position.invoiced_not_dispatched - line.quantity
        )
        position.version += 1
        if reversed_quantity:
            db.add(
                InventoryMovement(
                    warehouse_id=warehouse.id,
                    product_id=product.id,
                    purchase_order_id=invoice.purchase_order_id,
                    actor_user_id=user.id,
                    movement_type="invoice_cancelled",
                    reference_type="invoice",
                    reference_id=str(invoice.id),
                    idempotency_key=f"invoice-cancel:{invoice.id}:{product.id}",
                    batch_id=invoice.batch_id,
                    quantity=reversed_quantity,
                    reason="Reversión por anulación de factura",
                    before_value=before,
                    after_value={
                        "physical_confirmed": position.physical_confirmed,
                        "invoiced_not_dispatched": position.invoiced_not_dispatched,
                        "version": position.version,
                    },
                )
            )
        inventory_affected.append(
            {
                "sku": product.sku,
                "quantity": reversed_quantity,
                "physical_confirmed": position.physical_confirmed,
                "available_to_invoice": InventoryPosition(
                    position.physical_confirmed,
                    position.reserved,
                    position.invoiced_not_dispatched,
                    position.blocked_by_incident,
                ).available_to_invoice,
            }
        )
    invoice.administrative_status = "cancelled"
    invoice.inventory_reversed_at = utc_now()
    invoice.inventory_status = "reverted"
    invoice.inventory_last_error = None
    invoice.inventory_attempts += 1
    invoice.dispatch_status = "not_applicable"
    invoice.delivery_status = "not_applicable"
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="invoice_cancelled",
            entity_type="invoice",
            entity_id=str(invoice.id),
            new_value={
                "number": invoice.invoice_number,
                "reversed_products": len(inventory_affected),
            },
        )
    )
    db.commit()
    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "administrative_status": invoice.administrative_status,
        "duplicate": False,
        "inventory_affected": inventory_affected,
    }


@router.put("/{invoice_id}")
def update_invoice(
    invoice_id: uuid.UUID,
    payload: InvoiceInput,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    invoice = db.scalar(
        select(Invoice).where(Invoice.id == invoice_id).with_for_update()
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="No encontramos la factura.")
    if invoice.administrative_status != "confirmed":
        raise HTTPException(
            status_code=409, detail="La factura anulada no puede editarse."
        )
    if invoice.dispatch_status != "pending":
        raise HTTPException(
            status_code=409,
            detail="No se puede editar el detalle porque el despacho ya inició.",
        )
    audit = audit_invoices(db, [invoice.id])[0]
    if audit["status"] != "correct":
        raise HTTPException(
            status_code=409,
            detail="Audita y corrige el inventario de esta factura antes de editarla.",
        )
    duplicate = db.scalar(
        select(Invoice.id).where(
            Invoice.invoice_number == payload.invoice_number,
            Invoice.id != invoice.id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Esta factura ya está registrada.")
    po = (
        db.get(PurchaseOrder, payload.purchase_order_id)
        if payload.purchase_order_id
        else None
    )
    if payload.source_type == "purchase_order" and po is None:
        raise HTTPException(status_code=422, detail="Selecciona una OC válida.")
    old_rows = db.execute(
        select(InvoiceLine, Product)
        .join(Product, Product.id == InvoiceLine.product_id)
        .where(InvoiceLine.invoice_id == invoice.id)
    ).all()
    old_by_sku = {product.sku: line for line, product in old_rows}
    requested = {line.sku.strip().upper(): line for line in payload.lines}
    if len(requested) != len(payload.lines):
        raise HTTPException(status_code=422, detail="No repitas un SKU en la factura.")
    all_skus = set(old_by_sku) | set(requested)
    rows = db.execute(
        select(Product, InventoryPositionModel, Warehouse)
        .join(InventoryPositionModel, InventoryPositionModel.product_id == Product.id)
        .join(Warehouse, Warehouse.id == InventoryPositionModel.warehouse_id)
        .where(Product.sku.in_(all_skus), Warehouse.code == "principal")
        .with_for_update(of=InventoryPositionModel)
    ).all()
    found = {
        product.sku: (product, position, warehouse)
        for product, position, warehouse in rows
    }
    if set(requested) - set(found):
        raise HTTPException(
            status_code=422,
            detail=f"SKU desconocidos: {', '.join(sorted(set(requested) - set(found)))}",
        )
    before_snapshot = {
        "number": invoice.invoice_number,
        "purchase_order_id": str(invoice.purchase_order_id)
        if invoice.purchase_order_id
        else None,
        "lines": {sku: line.quantity for sku, line in old_by_sku.items()},
    }
    inventory_affected = []
    for sku in all_skus:
        product, position, warehouse = found[sku]
        previous = old_by_sku[sku].quantity if sku in old_by_sku else 0
        new = requested[sku].quantity if sku in requested else 0
        delta = new - previous
        if delta > 0:
            available = InventoryPosition(
                position.physical_confirmed,
                position.reserved,
                position.invoiced_not_dispatched,
                position.blocked_by_incident,
            ).available_to_invoice
            if delta > available:
                raise HTTPException(
                    status_code=409,
                    detail=f"{sku}: el cambio requiere {delta} unidades y solo hay {available}.",
                )
        if delta:
            before = {"version": position.version}
            before["physical_confirmed"] = position.physical_confirmed
            before["invoiced_not_dispatched"] = position.invoiced_not_dispatched
            position.physical_confirmed -= delta
            position.invoiced_not_dispatched += delta
            position.version += 1
            after = {"version": position.version}
            after["physical_confirmed"] = position.physical_confirmed
            after["invoiced_not_dispatched"] = position.invoiced_not_dispatched
            db.add(
                InventoryMovement(
                    warehouse_id=warehouse.id,
                    product_id=product.id,
                    purchase_order_id=payload.purchase_order_id,
                    actor_user_id=user.id,
                    movement_type="invoice_edited",
                    reference_type="invoice",
                    reference_id=str(invoice.id),
                    quantity=abs(delta),
                    reason=(
                        "Salida adicional por edición de factura"
                        if delta > 0
                        else "Entrada compensatoria por edición de factura"
                    ),
                    before_value=before,
                    after_value=after,
                )
            )
            inventory_affected.append(
                {
                    "sku": sku,
                    "quantity_delta": -delta,
                    "physical_confirmed": position.physical_confirmed,
                    "available_to_invoice": InventoryPosition(
                        position.physical_confirmed,
                        position.reserved,
                        position.invoiced_not_dispatched,
                        position.blocked_by_incident,
                    ).available_to_invoice,
                }
            )
    db.execute(delete(InvoiceAlert).where(InvoiceAlert.invoice_id == invoice.id))
    db.execute(delete(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id))
    po_quantities = (
        {
            product.sku: line.ordered_quantity
            for line, product in db.execute(
                select(PurchaseOrderLine, Product)
                .join(Product, Product.id == PurchaseOrderLine.product_id)
                .where(PurchaseOrderLine.purchase_order_id == po.id)
            )
        }
        if po
        else {}
    )
    invoice.incident_status = "none"
    for sku, line_input in requested.items():
        product = found[sku][0]
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
        other_invoiced = (
            db.scalar(
                select(func.coalesce(func.sum(InvoiceLine.quantity), 0))
                .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
                .where(
                    Invoice.purchase_order_id == po.id,
                    Invoice.id != invoice.id,
                    Invoice.administrative_status == "confirmed",
                    InvoiceLine.product_id == product.id,
                )
            )
            if po
            else 0
        )
        if outside or (
            po and other_invoiced + line_input.quantity > po_quantities.get(sku, 0)
        ):
            alert_type = (
                "product_outside_purchase_order"
                if outside
                else "quantity_exceeds_purchase_order"
            )
            description = (
                f"{sku} no consta en la OC original."
                if outside
                else f"{sku}: la cantidad acumulada supera las {po_quantities[sku]} unidades de la OC."
            )
            db.add(
                InvoiceAlert(
                    invoice_id=invoice.id,
                    product_id=product.id,
                    alert_type=alert_type,
                    description=description,
                )
            )
            invoice.incident_status = "open"
    invoice.invoice_number = payload.invoice_number
    invoice.invoice_date = payload.invoice_date
    invoice.purchase_order_id = payload.purchase_order_id
    invoice.source_type = payload.source_type
    invoice.customer_name = (
        (po.customer_name or po.chain_name) if po else payload.customer_name
    )
    invoice.chain_name = po.chain_name if po else payload.chain_name
    invoice.authorization_number = payload.authorization_number
    invoice.remittance_guide = payload.remittance_guide
    invoice.total_value = payload.total_value
    invoice.notes = payload.notes
    invoice.inventory_status = "discounted"
    invoice.inventory_discounted_quantity = sum(line.quantity for line in payload.lines)
    invoice.inventory_last_error = None
    invoice.inventory_attempts += 1
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="invoice_edited",
            entity_type="invoice",
            entity_id=str(invoice.id),
            previous_value=before_snapshot,
            new_value={
                "number": invoice.invoice_number,
                "purchase_order_id": str(invoice.purchase_order_id)
                if invoice.purchase_order_id
                else None,
                "lines": {sku: line.quantity for sku, line in requested.items()},
            },
        )
    )
    db.commit()
    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "inventory_affected": inventory_affected,
    }
