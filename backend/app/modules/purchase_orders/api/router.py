import base64
import json
import os
import shutil
import tempfile
import uuid
from hashlib import sha256
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.auth.infrastructure.models import User
from app.modules.catalog.infrastructure.models import Product
from app.modules.deliveries.infrastructure.models import Delivery, DeliveryLine
from app.modules.dispatches.infrastructure.models import Dispatch, DispatchLine
from app.modules.incidents.infrastructure.models import Incident
from app.modules.inventory.domain.availability import InventoryPosition
from app.modules.inventory.infrastructure.models import (
    InventoryPositionModel,
    Warehouse,
)
from app.modules.invoices.infrastructure.models import (
    Invoice,
    InvoiceAlert,
    InvoiceLine,
)
from app.modules.purchase_orders.infrastructure.models import (
    CustomerProductAlias,
    PurchaseOrder,
    PurchaseOrderDocumentLink,
    PurchaseOrderLine,
    PurchaseOrderSourceDocument,
)
from app.modules.purchase_orders.domain.document_extraction import (
    classify_document,
    expected_product_count,
    extraction_signals,
    normalize_identity,
    recognized_header,
    split_purchase_orders,
    suggest_chains_from_confirmed_aliases,
)
from app.modules.documents.domain.extraction_runner import run_document_extraction
from app.modules.documents.domain.upload_stream import (
    TEMP_DIRECTORY,
    StreamedDocument,
    stream_upload,
)
from app.modules.purchase_orders.domain.customer_profiles import (
    aliases_for_chain,
    chain_evidence_aliases,
)
from app.modules.reservations.infrastructure.models import Reservation, ReservationLine
from app.modules.returns.infrastructure.models import Return, ReturnLine


class LineInput(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    quantity: int = Field(gt=0)
    original_quantity: int | None = Field(default=None, gt=0)
    original_unit: str | None = Field(default=None, max_length=30)
    units_per_box: int | None = Field(default=None, gt=0, le=10000)
    conversion_method: str | None = Field(default=None, max_length=40)
    conversion_confirmed: bool = True
    source_page: int | None = Field(default=None, gt=0)
    source_text: str | None = Field(default=None, max_length=2000)
    source_code: str | None = Field(default=None, max_length=100)
    source_description: str | None = Field(default=None, max_length=300)


class ConfirmedAliasInput(BaseModel):
    source_text: str = Field(min_length=1, max_length=300)
    detected_code: str | None = Field(default=None, max_length=100)
    sku: str = Field(min_length=1, max_length=50)


class OrderInput(BaseModel):
    chain_name: str = Field(min_length=2, max_length=160)
    customer_name: str | None = Field(default=None, max_length=160)
    order_number: str = Field(min_length=1, max_length=100)
    order_date: date | None = None
    destination: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    secondary_reference: str | None = Field(default=None, max_length=100)
    local_name: str | None = Field(default=None, max_length=200)
    lines: list[LineInput] = Field(min_length=1)
    source_document_tokens: list[uuid.UUID] = []
    confirmed_aliases: list[ConfirmedAliasInput] = []


class OrderUpdateInput(BaseModel):
    chain_name: str = Field(min_length=2, max_length=160)
    customer_name: str | None = Field(default=None, max_length=160)
    order_number: str = Field(min_length=1, max_length=100)
    order_date: date | None = None
    destination: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[LineInput] = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=1000)


router = APIRouter(prefix="/purchase-orders", tags=["Órdenes de compra"])
PREVIEW_TTL = timedelta(hours=2)
PREVIEW_DIRECTORY = Path(tempfile.gettempdir()) / "inventario-purchase-order-previews"

CHAIN_ALIASES = {
    "TUTI": "TUTI",
    "TIENDAS TUTI": "TUTI",
    "TIA": "Tía",
    "TIENDAS TIA": "Tía",
    "EL ROSADO": "Rosado",
    "CORPORACION EL ROSADO": "Rosado",
}


def canonical_chain_name(value: str) -> str:
    """Return the user-facing identity used for new purchase orders."""
    clean = " ".join(value.strip().split())
    return CHAIN_ALIASES.get(normalize_identity(clean), clean)


def normalized_search_field(field):
    expression = func.lower(func.coalesce(field, ""))
    for accented, plain in zip("áéíóúüñ", "aeiouun", strict=True):
        expression = func.replace(expression, accented, plain)
    return expression


def validate_line_conversion(line: LineInput) -> None:
    if not line.conversion_confirmed:
        raise HTTPException(
            status_code=422,
            detail="Confirma todas las cantidades y conversiones antes de guardar la OC.",
        )
    if line.original_unit == "boxes":
        if not line.original_quantity or not line.units_per_box:
            raise HTTPException(
                status_code=422,
                detail="Una cantidad en cajas requiere cantidad original y UxC.",
            )
        if line.quantity != line.original_quantity * line.units_per_box:
            raise HTTPException(
                status_code=422,
                detail="Las unidades calculadas no coinciden con Cajas × UxC.",
            )


def validate_traceable_line_change(
    sku: str,
    quantity: int | None,
    *,
    invoiced: int,
    dispatched: int,
    delivered: int,
    reserved: int,
) -> None:
    operated = max(invoiced, dispatched, delivered, reserved)
    if quantity is None and operated:
        raise HTTPException(
            status_code=409,
            detail=(
                f"No puedes eliminar {sku} porque ya tiene operaciones relacionadas "
                f"({operated} unidades)."
            ),
        )
    if quantity is None:
        return
    limits = [
        ("facturaron", invoiced),
        ("despacharon", dispatched),
        ("entregaron", delivered),
        ("reservaron", reserved),
    ]
    limiting_action, minimum = max(limits, key=lambda item: item[1])
    if quantity < minimum:
        raise HTTPException(
            status_code=409,
            detail=(
                f"No puedes reducir {sku} a {quantity} unidades porque ya se "
                f"{limiting_action} {minimum}."
            ),
        )


def audit_value(value):
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: audit_value(item) for key, item in value.items()}
    return value


def fulfillment_status(
    ordered: int,
    invoiced: int,
    dispatched: int,
    delivered: int,
    returned: int,
    has_incident: bool,
) -> str:
    if has_incident:
        return "with_incident"
    if returned > 0:
        return "with_return"
    if delivered > ordered:
        return "delivered_excess"
    if delivered == ordered and ordered > 0:
        return "delivered_complete"
    if delivered > 0:
        return "delivery_partial"
    if dispatched > 0:
        return "dispatch_partial"
    if 0 < invoiced < ordered:
        return "invoicing_partial"
    if invoiced >= ordered and ordered > 0:
        return "pending"
    return "not_processed"


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
        .order_by(PurchaseOrderLine.sort_order, Product.sku)
    ).all()
    lines = []
    for line, product, stored in rows:
        invoiced = db.scalar(
            select(func.coalesce(func.sum(InvoiceLine.quantity), 0))
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(
                Invoice.purchase_order_id == order.id,
                Invoice.administrative_status == "confirmed",
                InvoiceLine.product_id == product.id,
            )
        )
        dispatched = db.scalar(
            select(func.coalesce(func.sum(DispatchLine.dispatched_quantity), 0))
            .select_from(DispatchLine)
            .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
            .join(InvoiceLine, InvoiceLine.id == DispatchLine.invoice_line_id)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(
                Invoice.purchase_order_id == order.id,
                Invoice.administrative_status == "confirmed",
                InvoiceLine.product_id == product.id,
            )
        )
        delivered = db.scalar(
            select(func.coalesce(func.sum(DeliveryLine.delivered_quantity), 0))
            .select_from(DeliveryLine)
            .join(Delivery, Delivery.id == DeliveryLine.delivery_id)
            .join(InvoiceLine, InvoiceLine.id == DeliveryLine.invoice_line_id)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(
                Invoice.purchase_order_id == order.id,
                Invoice.administrative_status == "confirmed",
                InvoiceLine.product_id == product.id,
            )
        )
        returned = db.scalar(
            select(func.coalesce(func.sum(ReturnLine.quantity), 0))
            .select_from(ReturnLine)
            .join(Return, Return.id == ReturnLine.return_id)
            .join(InvoiceLine, InvoiceLine.id == ReturnLine.invoice_line_id)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(
                Invoice.purchase_order_id == order.id,
                Invoice.administrative_status == "confirmed",
                InvoiceLine.product_id == product.id,
            )
        )
        has_incident = bool(
            db.scalar(
                select(Incident.id).where(
                    Incident.purchase_order_id == order.id,
                    Incident.product_id == product.id,
                    Incident.status.in_(["open", "in_review"]),
                )
            )
            or db.scalar(
                select(InvoiceAlert.id)
                .join(Invoice, Invoice.id == InvoiceAlert.invoice_id)
                .where(
                    Invoice.purchase_order_id == order.id,
                    InvoiceAlert.product_id == product.id,
                    InvoiceAlert.is_resolved.is_(False),
                )
            )
        )
        position = InventoryPosition(
            stored.physical_confirmed,
            stored.reserved,
            stored.invoiced_not_dispatched,
            stored.blocked_by_incident,
        )
        pending = max(0, line.ordered_quantity - invoiced)
        suggested = max(0, min(pending, position.available_to_invoice))
        shortage = max(0, pending - position.available_to_invoice)
        lines.append(
            {
                "sku": product.sku,
                "product_name": product.name,
                "sort_order": line.sort_order,
                "ordered_quantity": line.ordered_quantity,
                "invoiced_quantity": invoiced,
                "dispatched_quantity": dispatched,
                "delivered_quantity": delivered,
                "returned_quantity": returned,
                "net_delivered_quantity": delivered - returned,
                "pending_delivery": line.ordered_quantity - delivered,
                "difference": delivered - line.ordered_quantity,
                "fulfillment_status": fulfillment_status(
                    line.ordered_quantity,
                    invoiced,
                    dispatched,
                    delivered,
                    returned,
                    has_incident,
                ),
                "has_incident": has_incident,
                "remaining_quantity": pending,
                "available": position.available_to_invoice,
                "suggested_to_invoice": suggested,
                "shortage": shortage,
                "complete": pending == 0 or shortage == 0,
                "billing_result": (
                    "Completamente facturada"
                    if pending == 0
                    else "Lista para facturar completa"
                    if shortage == 0
                    else "Facturable parcialmente"
                    if suggested > 0
                    else "Sin inventario"
                ),
                "original_quantity": line.original_quantity,
                "original_unit": line.original_unit,
                "units_per_box": line.units_per_box,
                "conversion_method": line.conversion_method,
                "conversion_confirmed": line.conversion_confirmed,
                "source_page": line.source_page,
                "source_text": line.source_text,
                "source_code": line.source_code,
                "source_description": line.source_description,
            }
        )
    source_documents = [
        {
            "token": document.upload_token,
            "filename": document.original_filename,
            "content_type": document.content_type,
            "extraction_method": document.extraction_method,
            "page_count": document.page_count,
            "size_bytes": len(document.content) if document.content else 0,
            "available": document.content is not None,
            "uploaded_at": document.created_at,
            "uploaded_by_user_id": document.created_by_user_id,
            "sha256": document.sha256,
        }
        for document in db.scalars(
            select(PurchaseOrderSourceDocument)
            .join(
                PurchaseOrderDocumentLink,
                PurchaseOrderDocumentLink.document_id == PurchaseOrderSourceDocument.id,
            )
            .where(PurchaseOrderDocumentLink.purchase_order_id == order.id)
            .order_by(PurchaseOrderSourceDocument.created_at)
        )
    ]
    related_invoices = [
        {
            "id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "administrative_status": invoice.administrative_status,
            "dispatch_status": invoice.dispatch_status,
            "delivery_status": invoice.delivery_status,
            "dispatches": [
                {"id": item.id, "dispatched_at": item.dispatched_at}
                for item in db.scalars(
                    select(Dispatch)
                    .where(Dispatch.invoice_id == invoice.id)
                    .order_by(Dispatch.dispatched_at)
                )
            ],
            "deliveries": [
                {"id": item.id, "delivered_at": item.delivered_at}
                for item in db.scalars(
                    select(Delivery)
                    .where(Delivery.invoice_id == invoice.id)
                    .order_by(Delivery.delivered_at)
                )
            ],
        }
        for invoice in db.scalars(
            select(Invoice)
            .where(Invoice.purchase_order_id == order.id)
            .order_by(Invoice.invoice_date, Invoice.invoice_number)
        )
    ]
    related_reservations = [
        {
            "id": reservation.id,
            "status": reservation.status,
            "reason": reservation.reason,
        }
        for reservation in db.scalars(
            select(Reservation)
            .where(
                Reservation.purchase_order_reference == order.order_number,
                Reservation.status.in_(["active", "used"]),
            )
            .order_by(Reservation.created_at)
        )
    ]
    manually_modified = bool(
        db.scalar(
            select(AuditLog.id).where(
                AuditLog.entity_type == "purchase_order",
                AuditLog.entity_id == str(order.id),
                AuditLog.action == "purchase_order_updated",
            )
        )
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
        "secondary_reference": order.secondary_reference,
        "local_name": order.local_name,
        "lines": lines,
        "source_documents": source_documents,
        "related_invoices": related_invoices,
        "related_reservations": related_reservations,
        "has_related_operations": bool(related_invoices or related_reservations),
        "manually_modified": manually_modified,
    }


def encode_order_cursor(created_at: datetime, order_id: uuid.UUID) -> str:
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": str(order_id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_order_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(payload["created_at"]), uuid.UUID(payload["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=422, detail="El cursor de paginación no es válido."
        ) from error


@router.get("")
def list_orders(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[str | None, Query(max_length=120)] = None,
    chain: Annotated[str | None, Query(max_length=160)] = None,
    status: Annotated[str | None, Query(max_length=30)] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    cursor: Annotated[str | None, Query(max_length=300)] = None,
):
    line_counts = (
        select(
            PurchaseOrderLine.purchase_order_id.label("purchase_order_id"),
            func.count(PurchaseOrderLine.id).label("product_count"),
        )
        .group_by(PurchaseOrderLine.purchase_order_id)
        .subquery()
    )
    statement = (
        select(PurchaseOrder, func.coalesce(line_counts.c.product_count, 0))
        .outerjoin(line_counts, line_counts.c.purchase_order_id == PurchaseOrder.id)
        .order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc())
    )
    if search and search.strip():
        normalized_terms = (
            search.strip()
            .lower()
            .translate(str.maketrans("áéíóúüñ", "aeiouun"))
            .split()
        )
        searchable_fields = [
            normalized_search_field(field)
            for field in (
                PurchaseOrder.order_number,
                PurchaseOrder.chain_name,
                PurchaseOrder.status,
                PurchaseOrder.destination,
            )
        ]
        statement = statement.where(
            and_(
                *[
                    or_(*[field.like(f"%{term}%") for field in searchable_fields])
                    for term in normalized_terms
                ]
            )
        )
    if chain and chain.strip():
        statement = statement.where(
            func.lower(PurchaseOrder.chain_name) == canonical_chain_name(chain).lower()
        )
    if status and status.strip():
        statement = statement.where(PurchaseOrder.status == status.strip())
    if date_from:
        statement = statement.where(PurchaseOrder.order_date >= date_from)
    if date_to:
        statement = statement.where(PurchaseOrder.order_date <= date_to)
    if cursor:
        cursor_date, cursor_id = decode_order_cursor(cursor)
        statement = statement.where(
            or_(
                PurchaseOrder.created_at < cursor_date,
                and_(
                    PurchaseOrder.created_at == cursor_date,
                    PurchaseOrder.id < cursor_id,
                ),
            )
        )
    rows = db.execute(statement.limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        {
            "id": order.id,
            "order_number": order.order_number,
            "chain_name": canonical_chain_name(order.chain_name),
            "order_date": order.order_date,
            "status": order.status,
            "destination": order.destination,
            "product_count": int(product_count),
        }
        for order, product_count in rows
    ]
    next_cursor = (
        encode_order_cursor(rows[-1][0].created_at, rows[-1][0].id)
        if has_more and rows
        else None
    )
    return {"items": items, "next_cursor": next_cursor}


ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/plain",
}
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024


def preview_path(token: uuid.UUID) -> Path:
    return PREVIEW_DIRECTORY / str(token)


def write_preview(token: uuid.UUID, content: bytes) -> None:
    PREVIEW_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = preview_path(token)
    path.write_bytes(content)
    path.chmod(0o600)


def write_preview_path(token: uuid.UUID, source: Path) -> None:
    PREVIEW_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = preview_path(token)
    shutil.copyfile(source, path)
    path.chmod(0o600)


def delete_preview(token: uuid.UUID) -> None:
    preview_path(token).unlink(missing_ok=True)


def purge_expired_previews(db: Session) -> None:
    cutoff = datetime.now(timezone.utc) - PREVIEW_TTL
    expired = db.scalars(
        select(PurchaseOrderSourceDocument).where(
            PurchaseOrderSourceDocument.created_at < cutoff,
            ~PurchaseOrderSourceDocument.id.in_(
                select(PurchaseOrderDocumentLink.document_id)
            ),
        )
    ).all()
    for document in expired:
        delete_preview(document.upload_token)
        db.delete(document)
    if expired:
        db.commit()


@router.post("/imports/preview")
async def preview_purchase_order_documents(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    files: Annotated[list[UploadFile] | None, File()] = None,
    pasted_text: Annotated[str | None, Form(max_length=200_000)] = None,
):
    inputs: list[StreamedDocument] = []
    for upload in files or []:
        inputs.append(
            await stream_upload(
                upload,
                allowed_types=ALLOWED_DOCUMENT_TYPES - {"text/plain"},
                max_bytes=MAX_DOCUMENT_BYTES,
            )
        )
    if pasted_text and pasted_text.strip():
        TEMP_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
        content = pasted_text.strip().encode("utf-8")
        descriptor, path_value = tempfile.mkstemp(
            prefix="pasted-", suffix=".txt", dir=TEMP_DIRECTORY
        )
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
        inputs.append(
            StreamedDocument(
                path=Path(path_value),
                filename="pedido-pegado.txt",
                content_type="text/plain",
                size_bytes=len(content),
                sha256=sha256(content).hexdigest(),
                page_count=1,
                requires_ocr=False,
            )
        )
    if not inputs:
        raise HTTPException(
            status_code=422, detail="Carga un documento o pega el pedido."
        )
    purge_expired_previews(db)

    drafts = []
    temporary_tokens: list[uuid.UUID] = []
    for uploaded in inputs:
        filename = uploaded.filename
        content_type = uploaded.content_type
        digest = uploaded.sha256
        try:
            if content_type == "text/plain":
                extracted_text = (
                    f"[[PAGE:1]]\n{uploaded.path.read_text(encoding='utf-8')}"
                )
                method = "pasted_text"
                page_count = 1
                warnings = ()
                table_rows = ()
                expected_count = expected_product_count(extracted_text, table_rows)
            else:
                extracted = run_document_extraction(uploaded)
                extracted_text = extracted.text
                method = extracted.method
                page_count = extracted.page_count
                warnings = extracted.warnings
                table_rows = extracted.table_rows
                expected_count = extracted.expected_product_count
        except (RuntimeError, ValueError, OSError) as error:
            for item in inputs:
                item.cleanup()
            raise HTTPException(
                status_code=422, detail=f"{filename}: {error}"
            ) from error
        document = PurchaseOrderSourceDocument(
            original_filename=filename,
            content_type=content_type,
            content=None,
            sha256=digest,
            extraction_method=method,
            extracted_text=extracted_text,
            page_count=page_count,
            created_by_user_id=user.id,
        )
        db.add(document)
        db.flush()
        duplicate_document = db.scalar(
            select(PurchaseOrderSourceDocument.id).where(
                PurchaseOrderSourceDocument.sha256 == digest,
                PurchaseOrderSourceDocument.id != document.id,
            )
        )
        preview_warnings = list(warnings)
        if duplicate_document:
            preview_warnings.append(
                "Este mismo archivo ya fue cargado anteriormente; revisa si la OC está duplicada."
            )
        confirmed_profile_aliases = [
            (alias.chain_name, alias.source_text_normalized, alias.detected_code)
            for alias in db.scalars(select(CustomerProductAlias)).all()
        ] + chain_evidence_aliases()
        parts = split_purchase_orders(extracted_text)
        for part in parts or [extracted_text]:
            header = recognized_header(part, filename)
            classification = classify_document(part)
            learned_candidates = suggest_chains_from_confirmed_aliases(
                part,
                confirmed_profile_aliases,
            )
            candidates = list(
                dict.fromkeys(
                    [
                        *(header["chain_candidates"] or []),
                        *learned_candidates,
                    ]
                )
            )
            header["chain_candidates"] = candidates
            header["chain_name"] = candidates[0] if len(candidates) == 1 else None
            drafts.append(
                {
                    "document_token": document.upload_token,
                    "filename": filename,
                    "content_type": content_type,
                    "extraction_method": method,
                    "page_count": page_count,
                    "text": part,
                    "header": header,
                    "classification": classification,
                    "signals": extraction_signals(part),
                    "table_rows": list(table_rows) if len(parts) <= 1 else [],
                    "expected_product_count": (
                        expected_count
                        if len(parts) <= 1
                        else expected_product_count(part, [])
                    ),
                    "warnings": preview_warnings,
                    "separation_needs_review": len(parts) > 1,
                }
            )
        write_preview_path(document.upload_token, uploaded.path)
        temporary_tokens.append(document.upload_token)
        uploaded.cleanup()
    try:
        db.commit()
    except Exception:
        db.rollback()
        for token in temporary_tokens:
            delete_preview(token)
        raise
    finally:
        for uploaded in inputs:
            uploaded.cleanup()
    return {"drafts": drafts}


@router.get("/imports/{upload_token}/content")
def purchase_order_document_content(
    upload_token: uuid.UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    document = db.scalar(
        select(PurchaseOrderSourceDocument).where(
            PurchaseOrderSourceDocument.upload_token == upload_token
        )
    )
    linked = (
        db.scalar(
            select(PurchaseOrderDocumentLink.id).where(
                PurchaseOrderDocumentLink.document_id == document.id
            )
        )
        if document
        else None
    )
    if document is None or (document.created_by_user_id != user.id and not linked):
        raise HTTPException(status_code=404, detail="No encontramos el documento.")
    temporary_content = preview_path(document.upload_token)
    content = document.content
    if content is None and temporary_content.exists() and not linked:
        content = temporary_content.read_bytes()
    if content is None:
        raise HTTPException(
            status_code=410,
            detail="El archivo original no se conserva después de confirmar la OC.",
        )
    safe_name = document.original_filename.replace('"', "")
    return Response(
        content=content,
        media_type=document.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/imports/{upload_token}", status_code=204)
def discard_purchase_order_document(
    upload_token: uuid.UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    document = db.scalar(
        select(PurchaseOrderSourceDocument)
        .where(
            PurchaseOrderSourceDocument.upload_token == upload_token,
            PurchaseOrderSourceDocument.created_by_user_id == user.id,
        )
        .with_for_update()
    )
    if document is None:
        return Response(status_code=204)
    if db.scalar(
        select(PurchaseOrderDocumentLink.id).where(
            PurchaseOrderDocumentLink.document_id == document.id
        )
    ):
        return Response(status_code=204)
    delete_preview(document.upload_token)
    db.delete(document)
    db.commit()
    return Response(status_code=204)


@router.get("/customer-aliases")
def customer_aliases(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    chain_name: Annotated[str, Query(min_length=2, max_length=160)],
):
    normalized_chain = normalize_identity(chain_name)
    learned = [
        {
            "source_text": alias.source_text,
            "source_text_normalized": alias.source_text_normalized,
            "detected_code": alias.detected_code,
            "sku": product.sku,
        }
        for alias, product in db.execute(
            select(CustomerProductAlias, Product)
            .join(Product, Product.id == CustomerProductAlias.product_id)
            .where(CustomerProductAlias.chain_name_normalized == normalized_chain)
        )
    ]
    configured = aliases_for_chain(chain_name)
    return list(
        {
            (item["source_text_normalized"], item["sku"]): item
            for item in [*learned, *configured]
        }.values()
    )


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


def related_product_amounts(
    db: Session, order: PurchaseOrder, product_id: uuid.UUID
) -> dict[str, int]:
    invoiced = db.scalar(
        select(func.coalesce(func.sum(InvoiceLine.quantity), 0))
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(
            Invoice.purchase_order_id == order.id,
            Invoice.administrative_status == "confirmed",
            InvoiceLine.product_id == product_id,
        )
    )
    dispatched = db.scalar(
        select(func.coalesce(func.sum(DispatchLine.dispatched_quantity), 0))
        .select_from(DispatchLine)
        .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
        .join(InvoiceLine, InvoiceLine.id == DispatchLine.invoice_line_id)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(
            Invoice.purchase_order_id == order.id,
            Invoice.administrative_status == "confirmed",
            InvoiceLine.product_id == product_id,
        )
    )
    delivered = db.scalar(
        select(func.coalesce(func.sum(DeliveryLine.delivered_quantity), 0))
        .select_from(DeliveryLine)
        .join(Delivery, Delivery.id == DeliveryLine.delivery_id)
        .join(InvoiceLine, InvoiceLine.id == DeliveryLine.invoice_line_id)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(
            Invoice.purchase_order_id == order.id,
            Invoice.administrative_status == "confirmed",
            InvoiceLine.product_id == product_id,
        )
    )
    reserved = db.scalar(
        select(func.coalesce(func.sum(ReservationLine.quantity), 0))
        .select_from(ReservationLine)
        .join(Reservation, Reservation.id == ReservationLine.reservation_id)
        .where(
            Reservation.purchase_order_reference == order.order_number,
            Reservation.status.in_(["active", "used"]),
            ReservationLine.product_id == product_id,
        )
    )
    return {
        "invoiced": int(invoiced or 0),
        "dispatched": int(dispatched or 0),
        "delivered": int(delivered or 0),
        "reserved": int(reserved or 0),
    }


@router.get("/{order_id}/history")
def purchase_order_history(
    order_id: uuid.UUID,
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    if db.get(PurchaseOrder, order_id) is None:
        raise HTTPException(
            status_code=404, detail="No encontramos la orden de compra."
        )
    return [
        {
            "id": item.id,
            "occurred_at": item.occurred_at,
            "actor": actor.full_name if actor else "Sistema",
            "field": (item.new_value or {}).get("field"),
            "previous_value": (item.previous_value or {}).get("value"),
            "new_value": (item.new_value or {}).get("value"),
            "reason": item.reason,
        }
        for item, actor in db.execute(
            select(AuditLog, User)
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .where(
                AuditLog.entity_type == "purchase_order",
                AuditLog.entity_id == str(order_id),
                AuditLog.action == "purchase_order_updated",
            )
            .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        ).all()
    ]


@router.put("/{order_id}")
def update_order(
    order_id: uuid.UUID,
    payload: OrderUpdateInput,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    order = db.scalar(
        select(PurchaseOrder).where(PurchaseOrder.id == order_id).with_for_update()
    )
    if order is None:
        raise HTTPException(
            status_code=404, detail="No encontramos la orden de compra."
        )
    skus = [line.sku.strip().upper() for line in payload.lines]
    if len(set(skus)) != len(skus):
        raise HTTPException(status_code=422, detail="No repitas un SKU en la OC.")
    for line in payload.lines:
        validate_line_conversion(line)
    products = {
        product.sku: product
        for product in db.scalars(select(Product).where(Product.sku.in_(skus))).all()
    }
    if set(skus) != set(products):
        raise HTTPException(
            status_code=422,
            detail=f"SKU desconocidos: {', '.join(sorted(set(skus) - set(products)))}",
        )
    chain_name = canonical_chain_name(payload.chain_name)
    normalized_chain = normalize_identity(chain_name)
    duplicate = next(
        (
            existing
            for existing in db.scalars(
                select(PurchaseOrder).where(
                    PurchaseOrder.id != order.id,
                    func.lower(PurchaseOrder.order_number)
                    == payload.order_number.strip().lower(),
                )
            )
            if normalize_identity(existing.chain_name) == normalized_chain
        ),
        None,
    )
    if duplicate:
        raise HTTPException(
            status_code=409, detail="Esta cadena ya tiene una OC con ese número."
        )

    existing_rows = db.execute(
        select(PurchaseOrderLine, Product)
        .join(Product, Product.id == PurchaseOrderLine.product_id)
        .where(PurchaseOrderLine.purchase_order_id == order.id)
        .with_for_update(of=PurchaseOrderLine)
    ).all()
    existing_by_sku = {product.sku: line for line, product in existing_rows}
    related_by_sku = {
        sku: related_product_amounts(db, order, line.product_id)
        for sku, line in existing_by_sku.items()
    }
    has_related_operations = any(
        any(amounts.values()) for amounts in related_by_sku.values()
    )
    has_related_reservations = any(
        amounts["reserved"] > 0 for amounts in related_by_sku.values()
    )
    if has_related_reservations and (
        order.order_number != payload.order_number.strip()
        or normalize_identity(order.chain_name) != normalized_chain
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "No puedes cambiar la cadena o el número mientras existan reservas "
                "relacionadas. Libera o gestiona primero esas reservas."
            ),
        )

    changes: list[tuple[str, object, object]] = []
    header_values = [
        ("Cadena", order.chain_name, chain_name),
        ("Número de OC", order.order_number, payload.order_number.strip()),
        ("Fecha", order.order_date, payload.order_date),
        ("Destino", order.destination, payload.destination),
        ("Observaciones", order.notes, payload.notes),
    ]
    changes.extend(
        (field, previous, new)
        for field, previous, new in header_values
        if previous != new
    )
    incoming_by_sku = {
        line.sku.strip().upper(): (position, line)
        for position, line in enumerate(payload.lines)
    }
    for sku, existing_line in existing_by_sku.items():
        incoming = incoming_by_sku.get(sku)
        amounts = related_by_sku[sku]
        validate_traceable_line_change(
            sku,
            incoming[1].quantity if incoming else None,
            **amounts,
        )
        if incoming is None:
            changes.append(
                (f"Producto eliminado: {sku}", existing_line.ordered_quantity, None)
            )
            continue
        position, line = incoming
        if existing_line.ordered_quantity != line.quantity:
            changes.append(
                (
                    f"Cantidad: {sku}",
                    existing_line.ordered_quantity,
                    line.quantity,
                )
            )
        if (
            existing_line.original_quantity,
            existing_line.original_unit,
            existing_line.units_per_box,
        ) != (line.original_quantity, line.original_unit, line.units_per_box):
            changes.append(
                (
                    f"Conversión: {sku}",
                    {
                        "cantidad": existing_line.original_quantity,
                        "tipo": existing_line.original_unit,
                        "uxc": existing_line.units_per_box,
                    },
                    {
                        "cantidad": line.original_quantity,
                        "tipo": line.original_unit,
                        "uxc": line.units_per_box,
                    },
                )
            )
        if existing_line.sort_order != position:
            changes.append(
                (f"Posición: {sku}", existing_line.sort_order + 1, position + 1)
            )
    for sku, (_, line) in incoming_by_sku.items():
        if sku not in existing_by_sku:
            if not products[sku].is_active:
                raise HTTPException(
                    status_code=422, detail=f"{sku} no está activo en el catálogo."
                )
            changes.append((f"Producto agregado: {sku}", None, line.quantity))

    if has_related_operations and changes and not (payload.reason or "").strip():
        raise HTTPException(
            status_code=422,
            detail=(
                "Indica el motivo de la edición porque esta OC ya tiene operaciones "
                "relacionadas."
            ),
        )

    order.chain_name = chain_name
    order.customer_name = payload.customer_name or chain_name
    order.order_number = payload.order_number.strip()
    order.order_date = payload.order_date
    order.destination = payload.destination
    order.notes = payload.notes
    for sku, existing_line in existing_by_sku.items():
        incoming = incoming_by_sku.get(sku)
        if incoming is None:
            db.delete(existing_line)
            continue
        position, line = incoming
        existing_line.sort_order = position
        existing_line.ordered_quantity = line.quantity
        existing_line.original_quantity = line.original_quantity
        existing_line.original_unit = line.original_unit
        existing_line.units_per_box = line.units_per_box
        existing_line.conversion_method = line.conversion_method
        existing_line.conversion_confirmed = line.conversion_confirmed
    for sku, (position, line) in incoming_by_sku.items():
        if sku in existing_by_sku:
            continue
        db.add(
            PurchaseOrderLine(
                purchase_order_id=order.id,
                product_id=products[sku].id,
                sort_order=position,
                ordered_quantity=line.quantity,
                original_quantity=line.original_quantity,
                original_unit=line.original_unit,
                units_per_box=line.units_per_box,
                conversion_method=line.conversion_method,
                conversion_confirmed=line.conversion_confirmed,
            )
        )

    total_invoiced = sum(amounts["invoiced"] for amounts in related_by_sku.values())
    if order.status != "cancelled":
        if total_invoiced == 0:
            order.status = "open"
        elif all(
            related_by_sku.get(sku, {}).get("invoiced", 0) >= line.quantity
            for sku, (_, line) in incoming_by_sku.items()
        ):
            order.status = "completed"
        else:
            order.status = "partially_invoiced"
    for field, previous, new in changes:
        db.add(
            AuditLog(
                actor_user_id=user.id,
                action="purchase_order_updated",
                entity_type="purchase_order",
                entity_id=str(order.id),
                reason=(payload.reason or "").strip() or None,
                previous_value={"field": field, "value": audit_value(previous)},
                new_value={"field": field, "value": audit_value(new)},
            )
        )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Esta cadena ya tiene una OC con ese número."
        ) from error
    response = detail(db, order)
    response["change_summary"] = {
        "number_changed": any(field == "Número de OC" for field, _, _ in changes),
        "destination_changed": any(field == "Destino" for field, _, _ in changes),
        "products_added": sum(
            field.startswith("Producto agregado") for field, _, _ in changes
        ),
        "products_removed": sum(
            field.startswith("Producto eliminado") for field, _, _ in changes
        ),
        "quantities_changed": sum(
            field.startswith("Cantidad:") for field, _, _ in changes
        ),
    }
    return response


@router.post("/{order_id}/documents", status_code=201)
async def attach_corrected_document(
    order_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
):
    order = db.get(PurchaseOrder, order_id)
    if order is None:
        raise HTTPException(
            status_code=404, detail="No encontramos la orden de compra."
        )
    uploaded = await stream_upload(
        file,
        allowed_types=ALLOWED_DOCUMENT_TYPES - {"text/plain"},
        max_bytes=MAX_DOCUMENT_BYTES,
    )
    content_type = uploaded.content_type
    digest = uploaded.sha256
    duplicate = db.scalar(
        select(PurchaseOrderSourceDocument.id)
        .join(
            PurchaseOrderDocumentLink,
            PurchaseOrderDocumentLink.document_id == PurchaseOrderSourceDocument.id,
        )
        .where(
            PurchaseOrderDocumentLink.purchase_order_id == order.id,
            PurchaseOrderSourceDocument.sha256 == digest,
        )
    )
    if duplicate:
        uploaded.cleanup()
        raise HTTPException(
            status_code=409, detail="Este documento ya está adjunto a la OC."
        )
    try:
        extracted = run_document_extraction(uploaded)
    finally:
        uploaded.cleanup()
    document = PurchaseOrderSourceDocument(
        original_filename=file.filename or "documento-corregido",
        content_type=content_type,
        content=None,
        sha256=digest,
        extraction_method=extracted.method,
        extracted_text=extracted.text,
        page_count=extracted.page_count,
        created_by_user_id=user.id,
    )
    db.add(document)
    db.flush()
    db.add(
        PurchaseOrderDocumentLink(purchase_order_id=order.id, document_id=document.id)
    )
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="purchase_order_updated",
            entity_type="purchase_order",
            entity_id=str(order.id),
            previous_value={"field": "Documento corregido", "value": None},
            new_value={
                "field": "Documento corregido",
                "value": document.original_filename,
            },
        )
    )
    db.commit()
    return detail(db, order)


@router.post("", status_code=201)
def create_order(
    payload: OrderInput, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
):
    skus = [line.sku.strip().upper() for line in payload.lines]
    for line in payload.lines:
        validate_line_conversion(line)
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
    documents = []
    if payload.source_document_tokens:
        documents = db.scalars(
            select(PurchaseOrderSourceDocument)
            .where(
                PurchaseOrderSourceDocument.upload_token.in_(
                    payload.source_document_tokens
                ),
                PurchaseOrderSourceDocument.created_by_user_id == user.id,
            )
            .with_for_update()
        ).all()
        if len(documents) != len(set(payload.source_document_tokens)):
            raise HTTPException(
                status_code=422,
                detail="Algún documento de origen no existe o no pertenece a tu carga.",
            )
    alias_skus = {alias.sku.strip().upper() for alias in payload.confirmed_aliases}
    alias_products = (
        {
            product.sku: product
            for product in db.scalars(
                select(Product).where(
                    Product.sku.in_(alias_skus), Product.is_active.is_(True)
                )
            )
        }
        if alias_skus
        else {}
    )
    if set(alias_skus) != set(alias_products):
        raise HTTPException(
            status_code=422, detail="Un alias confirmado apunta a un producto inválido."
        )
    chain_name = canonical_chain_name(payload.chain_name)
    normalized_chain = normalize_identity(chain_name)
    duplicate = next(
        (
            existing
            for existing in db.scalars(
                select(PurchaseOrder).where(
                    func.lower(PurchaseOrder.order_number)
                    == payload.order_number.strip().lower()
                )
            )
            if normalize_identity(existing.chain_name) == normalized_chain
        ),
        None,
    )
    if duplicate:
        raise HTTPException(
            status_code=409, detail="Esta cadena ya tiene una OC con ese número."
        )
    order = PurchaseOrder(
        chain_name=chain_name,
        customer_name=chain_name,
        order_number=payload.order_number.strip(),
        order_date=payload.order_date,
        destination=payload.destination,
        notes=payload.notes,
        secondary_reference=payload.secondary_reference,
        local_name=payload.local_name,
        created_by_user_id=user.id,
    )
    db.add(order)
    db.flush()
    for sort_order, line in enumerate(payload.lines):
        db.add(
            PurchaseOrderLine(
                purchase_order_id=order.id,
                product_id=products[line.sku.strip().upper()].id,
                sort_order=sort_order,
                ordered_quantity=line.quantity,
                original_quantity=line.original_quantity,
                original_unit=line.original_unit,
                units_per_box=line.units_per_box,
                conversion_method=line.conversion_method,
                conversion_confirmed=line.conversion_confirmed,
                source_page=line.source_page,
                source_text=line.source_text,
                source_code=line.source_code,
                source_description=line.source_description,
            )
        )
    for document in documents:
        db.add(
            PurchaseOrderDocumentLink(
                purchase_order_id=order.id,
                document_id=document.id,
            )
        )
    for alias_input in payload.confirmed_aliases:
        normalized_source = normalize_identity(alias_input.source_text)
        existing_alias = db.scalar(
            select(CustomerProductAlias).where(
                CustomerProductAlias.chain_name_normalized == normalized_chain,
                CustomerProductAlias.source_text_normalized == normalized_source,
            )
        )
        if existing_alias:
            existing_alias.chain_name = order.chain_name
            existing_alias.source_text = alias_input.source_text.strip()
            existing_alias.detected_code = alias_input.detected_code
            existing_alias.product_id = alias_products[
                alias_input.sku.strip().upper()
            ].id
            existing_alias.confirmed_by_user_id = user.id
        else:
            db.add(
                CustomerProductAlias(
                    chain_name=order.chain_name,
                    chain_name_normalized=normalized_chain,
                    source_text=alias_input.source_text.strip(),
                    source_text_normalized=normalized_source,
                    detected_code=alias_input.detected_code,
                    product_id=alias_products[alias_input.sku.strip().upper()].id,
                    confirmed_by_user_id=user.id,
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
                "source_documents": len(documents),
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
    for document in documents:
        delete_preview(document.upload_token)
    return detail(db, order)
