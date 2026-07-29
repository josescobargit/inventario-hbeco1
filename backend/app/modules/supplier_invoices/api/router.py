import re
import unicodedata
from collections import defaultdict
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Annotated
from uuid import UUID

import fitz
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
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
from app.modules.documents.domain.extraction_runner import run_document_extraction
from app.modules.documents.domain.upload_stream import stream_upload
from app.modules.supplier_invoices.domain.extraction import (
    supplier_result_from_extracted,
)
from app.modules.supplier_invoices.infrastructure.models import (
    SupplierInvoice,
    SupplierInvoiceLine,
    SupplierProductAlias,
)


router = APIRouter(prefix="/supplier-invoices", tags=["Facturas de proveedores"])
MAX_FILE_SIZE = 15 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}


class SupplierInvoiceLineInput(BaseModel):
    line_number: int = Field(gt=0)
    sku: str = Field(min_length=1, max_length=50)
    supplier_code: str | None = Field(default=None, max_length=100)
    barcode: str | None = Field(default=None, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    quantity: int = Field(gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    discount: Decimal | None = Field(default=None, ge=0)
    line_total: Decimal | None = Field(default=None, ge=0)
    reviewed: bool


class SupplierInvoiceInput(BaseModel):
    supplier_ruc: str = Field(pattern=r"^\d{13}$")
    supplier_name: str = Field(min_length=2, max_length=200)
    invoice_number: str = Field(pattern=r"^\d{3}-\d{3}-\d{9}$")
    issued_at: date
    authorization_number: str | None = Field(default=None, max_length=60)
    buyer_name: str | None = Field(default=None, max_length=200)
    buyer_ruc: str | None = Field(default=None, max_length=13)
    subtotal: Decimal | None = Field(default=None, ge=0)
    tax: Decimal | None = Field(default=None, ge=0)
    total: Decimal | None = Field(default=None, ge=0)
    extraction_method: str | None = Field(default=None, max_length=80)
    original_filename: str | None = Field(default=None, max_length=255)
    file_sha256: str | None = Field(default=None, max_length=64)
    lines: list[SupplierInvoiceLineInput] = Field(min_length=1)


def _normalized(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFD", value or "")
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]+", " ", plain.upper()).strip()


def _product_matcher(db: Session, supplier_ruc: str | None):
    products = list(
        db.scalars(
            select(Product)
            .where(Product.is_active.is_(True))
            .order_by(Product.name, Product.sku)
        ).all()
    )
    aliases = (
        list(
            db.scalars(
                select(SupplierProductAlias).where(
                    SupplierProductAlias.supplier_ruc == supplier_ruc
                )
            ).all()
        )
        if supplier_ruc
        else []
    )
    by_id = {product.id: product for product in products}
    by_barcode = {product.barcode: product for product in products if product.barcode}
    by_aux = {
        product.contifico_aux_code.upper(): product
        for product in products
        if product.contifico_aux_code
    }
    by_sku = {product.sku.upper(): product for product in products}
    by_name: dict[str, list[Product]] = defaultdict(list)
    for product in products:
        by_name[_normalized(product.name)].append(product)
    alias_by_code = {
        alias.supplier_code.upper(): by_id.get(alias.product_id)
        for alias in aliases
        if alias.supplier_code
    }
    alias_by_barcode = {
        alias.barcode: by_id.get(alias.product_id) for alias in aliases if alias.barcode
    }

    def result(product: Product | None, method: str, confidence: float) -> dict:
        return {
            "sku": product.sku if product else None,
            "product_name": product.name if product else None,
            "match_method": method,
            "confidence": round(confidence, 3),
            "status": (
                "recognized"
                if product and method != "similar_name"
                else "requires_confirmation"
                if product
                else "not_found"
            ),
        }

    def match(line: dict) -> dict:
        barcode = str(line.get("barcode") or "").strip()
        code = str(line.get("supplier_code") or "").strip().upper()
        description = _normalized(str(line.get("description") or ""))
        if barcode and barcode in by_barcode:
            return result(by_barcode[barcode], "barcode", 1)
        if code and code in by_aux:
            return result(by_aux[code], "supplier_code", 1)
        if barcode and alias_by_barcode.get(barcode):
            return result(alias_by_barcode[barcode], "supplier_alias", 1)
        if code and alias_by_code.get(code):
            return result(alias_by_code[code], "supplier_alias", 1)
        if code and code in by_sku:
            return result(by_sku[code], "sku", 1)
        exact = by_name.get(description, [])
        if len(exact) == 1:
            return result(exact[0], "normalized_name", 1)
        ranked = sorted(
            (
                (SequenceMatcher(None, description, normalized_name).ratio(), product)
                for normalized_name, candidates in by_name.items()
                for product in candidates
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if (
            ranked
            and ranked[0][0] >= 0.86
            and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.08)
        ):
            return result(ranked[0][1], "similar_name", ranked[0][0])
        return result(None, "none", 0)

    return match


def _position_snapshot(position: InventoryPositionModel) -> dict[str, int]:
    return {
        "physical_confirmed": position.physical_confirmed,
        "reserved": position.reserved,
        "invoiced_not_dispatched": position.invoiced_not_dispatched,
        "blocked_by_incident": position.blocked_by_incident,
        "version": position.version,
    }


def _warehouse_and_products(
    db: Session, skus: set[str]
) -> tuple[Warehouse, dict[str, tuple[Product, InventoryPositionModel]]]:
    warehouse = db.scalar(
        select(Warehouse).where(Warehouse.code == "principal").with_for_update()
    )
    if not warehouse:
        raise HTTPException(status_code=409, detail="No existe la bodega principal.")
    products = list(
        db.scalars(
            select(Product).where(Product.sku.in_(skus), Product.is_active.is_(True))
        ).all()
    )
    by_sku = {product.sku: product for product in products}
    missing = skus - set(by_sku)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Productos desconocidos: {', '.join(sorted(missing))}.",
        )
    positions = {
        position.product_id: position
        for position in db.scalars(
            select(InventoryPositionModel)
            .where(
                InventoryPositionModel.warehouse_id == warehouse.id,
                InventoryPositionModel.product_id.in_(
                    [product.id for product in products]
                ),
            )
            .with_for_update()
        ).all()
    }
    for product in products:
        if product.id not in positions:
            position = InventoryPositionModel(
                warehouse_id=warehouse.id, product_id=product.id
            )
            db.add(position)
            db.flush()
            positions[product.id] = position
    return warehouse, {
        sku: (product, positions[product.id]) for sku, product in by_sku.items()
    }


def _serialize(db: Session, invoice: SupplierInvoice) -> dict:
    rows = db.execute(
        select(SupplierInvoiceLine, Product)
        .join(Product, Product.id == SupplierInvoiceLine.product_id)
        .where(SupplierInvoiceLine.supplier_invoice_id == invoice.id)
        .order_by(SupplierInvoiceLine.line_number)
    ).all()
    return {
        "id": invoice.id,
        "supplier_ruc": invoice.supplier_ruc,
        "supplier_name": invoice.supplier_name,
        "invoice_number": invoice.invoice_number,
        "issued_at": invoice.issued_at,
        "authorization_number": invoice.authorization_number,
        "buyer_name": invoice.buyer_name,
        "buyer_ruc": invoice.buyer_ruc,
        "subtotal": invoice.subtotal,
        "tax": invoice.tax,
        "total": invoice.total,
        "status": invoice.status,
        "inventory_applied_at": invoice.inventory_applied_at,
        "inventory_reversed_at": invoice.inventory_reversed_at,
        "created_at": invoice.created_at,
        "lines": [
            {
                "line_number": line.line_number,
                "sku": product.sku,
                "product_name": product.name,
                "supplier_code": line.supplier_code,
                "barcode": line.barcode,
                "description": line.description,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "discount": line.discount,
                "line_total": line.line_total,
            }
            for line, product in rows
        ],
    }


@router.post("/imports/preview")
async def preview_supplier_invoices(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    files: Annotated[list[UploadFile], File()],
) -> list[dict]:
    del user
    previews = []
    for uploaded in files:
        document = await stream_upload(
            uploaded,
            allowed_types=ALLOWED_CONTENT_TYPES,
            max_bytes=MAX_FILE_SIZE,
        )
        try:
            raw = run_document_extraction(document)
            pdf = (
                fitz.open(document.path)
                if document.content_type == "application/pdf"
                else None
            )
            try:
                extracted = supplier_result_from_extracted(raw, pdf)
            finally:
                if pdf is not None:
                    pdf.close()
        except Exception as error:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{uploaded.filename}: no se pudo leer el documento. "
                    f"Detalle: {error}"
                ),
            ) from error
        finally:
            document.cleanup()
        match = _product_matcher(db, extracted.get("supplier_ruc"))
        lines = [{**line, **match(line)} for line in extracted["lines"]]
        warnings = list(extracted["warnings"])
        if not lines:
            warnings.append("No se encontraron líneas de producto para revisar.")
        previews.append(
            {
                **extracted,
                "original_filename": uploaded.filename,
                "file_sha256": document.sha256,
                "lines": lines,
                "summary": {
                    "detected": len(lines),
                    "recognized": sum(line["status"] == "recognized" for line in lines),
                    "pending": sum(line["status"] != "recognized" for line in lines),
                },
                "warnings": warnings,
            }
        )
    return previews


def _validated_lines(payload: SupplierInvoiceInput) -> list[SupplierInvoiceLineInput]:
    if any(not line.reviewed for line in payload.lines):
        raise HTTPException(
            status_code=422,
            detail="Confirma o corrige todas las líneas antes de registrar la factura.",
        )
    numbers = [line.line_number for line in payload.lines]
    if len(numbers) != len(set(numbers)):
        raise HTTPException(status_code=422, detail="No repitas el número de línea.")
    return payload.lines


def _save_aliases(
    db: Session,
    payload: SupplierInvoiceInput,
    products: dict[str, tuple[Product, InventoryPositionModel]],
    user_id: UUID,
) -> None:
    for line in payload.lines:
        if not line.supplier_code and not line.barcode:
            continue
        existing = db.scalar(
            select(SupplierProductAlias).where(
                SupplierProductAlias.supplier_ruc == payload.supplier_ruc,
                or_(
                    SupplierProductAlias.supplier_code == line.supplier_code
                    if line.supplier_code
                    else False,
                    SupplierProductAlias.barcode == line.barcode
                    if line.barcode
                    else False,
                ),
            )
        )
        if existing:
            existing.product_id = products[line.sku.strip().upper()][0].id
            existing.normalized_description = _normalized(line.description)[:300]
            existing.confirmed_by_user_id = user_id
        else:
            db.add(
                SupplierProductAlias(
                    supplier_ruc=payload.supplier_ruc,
                    supplier_code=line.supplier_code,
                    barcode=line.barcode,
                    normalized_description=_normalized(line.description)[:300],
                    product_id=products[line.sku.strip().upper()][0].id,
                    confirmed_by_user_id=user_id,
                )
            )


@router.post("", status_code=201)
def register_supplier_invoice(
    payload: SupplierInvoiceInput,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    lines = _validated_lines(payload)
    existing = db.scalar(
        select(SupplierInvoice).where(
            or_(
                (
                    (SupplierInvoice.supplier_ruc == payload.supplier_ruc)
                    & (SupplierInvoice.invoice_number == payload.invoice_number)
                ),
                (SupplierInvoice.authorization_number == payload.authorization_number)
                if payload.authorization_number
                else False,
            )
        )
    )
    if existing:
        result = _serialize(db, existing)
        return {**result, "duplicate": True, "inventory_affected": []}
    skus = {line.sku.strip().upper() for line in lines}
    warehouse, products = _warehouse_and_products(db, skus)
    invoice = SupplierInvoice(
        supplier_ruc=payload.supplier_ruc,
        supplier_name=payload.supplier_name.strip(),
        invoice_number=payload.invoice_number,
        issued_at=payload.issued_at,
        authorization_number=payload.authorization_number,
        buyer_name=payload.buyer_name,
        buyer_ruc=payload.buyer_ruc,
        subtotal=payload.subtotal,
        tax=payload.tax,
        total=payload.total,
        extraction_method=payload.extraction_method,
        original_filename=payload.original_filename,
        file_sha256=payload.file_sha256,
        registered_by_user_id=user.id,
    )
    db.add(invoice)
    db.flush()
    affected: dict[str, dict] = {}
    for line in lines:
        sku = line.sku.strip().upper()
        product, position = products[sku]
        before = _position_snapshot(position)
        position.physical_confirmed += line.quantity
        position.version += 1
        db.add(
            SupplierInvoiceLine(
                supplier_invoice_id=invoice.id,
                line_number=line.line_number,
                product_id=product.id,
                supplier_code=line.supplier_code,
                barcode=line.barcode,
                description=line.description.strip(),
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount=line.discount,
                line_total=line.line_total,
            )
        )
        db.add(
            InventoryMovement(
                warehouse_id=warehouse.id,
                product_id=product.id,
                actor_user_id=user.id,
                movement_type="supplier_invoice_registered",
                reference_type="supplier_invoice",
                reference_id=str(invoice.id),
                idempotency_key=f"supplier-invoice:{invoice.id}:{line.line_number}",
                quantity=line.quantity,
                reason="Entrada por factura de proveedor",
                before_value=before,
                after_value=_position_snapshot(position),
            )
        )
        affected[sku] = {
            "sku": sku,
            "product_name": product.name,
            "physical_confirmed": position.physical_confirmed,
        }
    _save_aliases(db, payload, products, user.id)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="supplier_invoice_registered",
            entity_type="supplier_invoice",
            entity_id=str(invoice.id),
            reason="Entrada por factura de proveedor",
            new_value={
                "invoice_number": invoice.invoice_number,
                "supplier_ruc": invoice.supplier_ruc,
                "lines": len(lines),
                "units": sum(line.quantity for line in lines),
            },
        )
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="La factura ya fue registrada; el inventario no se modificó nuevamente.",
        ) from error
    result = _serialize(db, invoice)
    return {**result, "duplicate": False, "inventory_affected": list(affected.values())}


@router.get("")
def list_supplier_invoices(
    _user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> list[dict]:
    return [
        _serialize(db, invoice)
        for invoice in db.scalars(
            select(SupplierInvoice).order_by(
                SupplierInvoice.issued_at.desc(), SupplierInvoice.created_at.desc()
            )
        ).all()
    ]


@router.get("/{invoice_id}")
def get_supplier_invoice(
    invoice_id: UUID, _user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> dict:
    invoice = db.get(SupplierInvoice, invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=404, detail="Factura de proveedor no encontrada."
        )
    return _serialize(db, invoice)


def _line_totals(db: Session, invoice_id: UUID) -> dict[UUID, int]:
    totals: dict[UUID, int] = defaultdict(int)
    for line in db.scalars(
        select(SupplierInvoiceLine).where(
            SupplierInvoiceLine.supplier_invoice_id == invoice_id
        )
    ).all():
        totals[line.product_id] += line.quantity
    return totals


@router.put("/{invoice_id}")
def update_supplier_invoice(
    invoice_id: UUID,
    payload: SupplierInvoiceInput,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    lines = _validated_lines(payload)
    invoice = db.scalar(
        select(SupplierInvoice)
        .where(SupplierInvoice.id == invoice_id)
        .with_for_update()
    )
    if not invoice:
        raise HTTPException(
            status_code=404, detail="Factura de proveedor no encontrada."
        )
    if invoice.status == "cancelled":
        raise HTTPException(
            status_code=409, detail="No puedes editar una factura anulada."
        )
    duplicate = db.scalar(
        select(SupplierInvoice).where(
            SupplierInvoice.id != invoice.id,
            or_(
                (
                    (SupplierInvoice.supplier_ruc == payload.supplier_ruc)
                    & (SupplierInvoice.invoice_number == payload.invoice_number)
                ),
                (SupplierInvoice.authorization_number == payload.authorization_number)
                if payload.authorization_number
                else False,
            ),
        )
    )
    if duplicate:
        raise HTTPException(
            status_code=409, detail="Ya existe esa factura del proveedor."
        )
    skus = {line.sku.strip().upper() for line in lines}
    old_lines = list(
        db.scalars(
            select(SupplierInvoiceLine).where(
                SupplierInvoiceLine.supplier_invoice_id == invoice.id
            )
        ).all()
    )
    old_product_ids = {line.product_id for line in old_lines}
    old_products = {
        product.id: product
        for product in db.scalars(
            select(Product).where(Product.id.in_(old_product_ids))
        ).all()
    }
    skus.update(product.sku for product in old_products.values())
    warehouse, products = _warehouse_and_products(db, skus)
    old_totals: dict[UUID, int] = defaultdict(int)
    new_totals: dict[UUID, int] = defaultdict(int)
    for line in old_lines:
        old_totals[line.product_id] += line.quantity
    for line in lines:
        new_totals[products[line.sku.strip().upper()][0].id] += line.quantity
    by_product_id = {product.id: (product, pos) for product, pos in products.values()}
    affected = []
    for product_id in old_product_ids | set(new_totals):
        product, position = by_product_id[product_id]
        delta = new_totals[product_id] - old_totals[product_id]
        if not delta:
            continue
        if delta < 0 and position.physical_confirmed < abs(delta):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"No puedes reducir {product.name}: solo existen "
                    f"{position.physical_confirmed} unidades físicas para compensar."
                ),
            )
        before = _position_snapshot(position)
        position.physical_confirmed += delta
        position.version += 1
        db.add(
            InventoryMovement(
                warehouse_id=warehouse.id,
                product_id=product.id,
                actor_user_id=user.id,
                movement_type="supplier_invoice_edited",
                reference_type="supplier_invoice",
                reference_id=str(invoice.id),
                quantity=abs(delta),
                reason=(
                    "Entrada adicional por edición de factura de proveedor"
                    if delta > 0
                    else "Salida compensatoria por edición de factura de proveedor"
                ),
                before_value=before,
                after_value=_position_snapshot(position),
            )
        )
        affected.append(
            {
                "sku": product.sku,
                "product_name": product.name,
                "physical_confirmed": position.physical_confirmed,
            }
        )
    for old_line in old_lines:
        db.delete(old_line)
    db.flush()
    for line in lines:
        product = products[line.sku.strip().upper()][0]
        db.add(
            SupplierInvoiceLine(
                supplier_invoice_id=invoice.id,
                line_number=line.line_number,
                product_id=product.id,
                supplier_code=line.supplier_code,
                barcode=line.barcode,
                description=line.description.strip(),
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount=line.discount,
                line_total=line.line_total,
            )
        )
    for field in (
        "supplier_ruc",
        "supplier_name",
        "invoice_number",
        "issued_at",
        "authorization_number",
        "buyer_name",
        "buyer_ruc",
        "subtotal",
        "tax",
        "total",
        "extraction_method",
        "original_filename",
        "file_sha256",
    ):
        setattr(invoice, field, getattr(payload, field))
    _save_aliases(db, payload, products, user.id)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="supplier_invoice_edited",
            entity_type="supplier_invoice",
            entity_id=str(invoice.id),
            reason="Corrección de factura de proveedor",
            new_value={"lines": len(lines), "units": sum(x.quantity for x in lines)},
        )
    )
    db.commit()
    return {
        **_serialize(db, invoice),
        "inventory_updated": True,
        "inventory_affected": affected,
    }


@router.post("/{invoice_id}/cancel")
def cancel_supplier_invoice(
    invoice_id: UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    invoice = db.scalar(
        select(SupplierInvoice)
        .where(SupplierInvoice.id == invoice_id)
        .with_for_update()
    )
    if not invoice:
        raise HTTPException(
            status_code=404, detail="Factura de proveedor no encontrada."
        )
    if invoice.inventory_reversed_at is not None or invoice.status == "cancelled":
        return {**_serialize(db, invoice), "duplicate": True}
    totals = _line_totals(db, invoice.id)
    products = list(db.scalars(select(Product).where(Product.id.in_(totals))).all())
    warehouse = db.scalar(select(Warehouse).where(Warehouse.code == "principal"))
    positions = {
        position.product_id: position
        for position in db.scalars(
            select(InventoryPositionModel)
            .where(
                InventoryPositionModel.warehouse_id == warehouse.id,
                InventoryPositionModel.product_id.in_(totals),
            )
            .with_for_update()
        ).all()
    }
    for product in products:
        position = positions[product.id]
        quantity = totals[product.id]
        if position.physical_confirmed < quantity:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"No se puede anular {product.name}: se requieren {quantity} "
                    f"unidades y el inventario físico es {position.physical_confirmed}."
                ),
            )
    for product in products:
        position = positions[product.id]
        quantity = totals[product.id]
        before = _position_snapshot(position)
        position.physical_confirmed -= quantity
        position.version += 1
        db.add(
            InventoryMovement(
                warehouse_id=warehouse.id,
                product_id=product.id,
                actor_user_id=user.id,
                movement_type="supplier_invoice_cancelled",
                reference_type="supplier_invoice",
                reference_id=str(invoice.id),
                idempotency_key=f"supplier-invoice-cancel:{invoice.id}:{product.id}",
                quantity=quantity,
                reason="Salida compensatoria por anulación de factura de proveedor",
                before_value=before,
                after_value=_position_snapshot(position),
            )
        )
    invoice.status = "cancelled"
    invoice.inventory_reversed_at = utc_now()
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="supplier_invoice_cancelled",
            entity_type="supplier_invoice",
            entity_id=str(invoice.id),
            reason="Anulación de factura de proveedor",
            new_value={"status": "cancelled"},
        )
    )
    db.commit()
    return {
        **_serialize(db, invoice),
        "duplicate": False,
        "inventory_affected": [
            {
                "sku": product.sku,
                "product_name": product.name,
                "physical_confirmed": positions[product.id].physical_confirmed,
            }
            for product in products
        ],
    }
