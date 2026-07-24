import uuid
from hashlib import sha256
from datetime import date
from typing import Annotated
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
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
    extraction_signals,
    extract_document,
    normalize_identity,
    recognized_header,
    split_purchase_orders,
    suggest_chains_from_confirmed_aliases,
)
from app.modules.purchase_orders.domain.customer_profiles import (
    aliases_for_chain,
    chain_evidence_aliases,
)
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


router = APIRouter(prefix="/purchase-orders", tags=["Órdenes de compra"])


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
        .order_by(Product.sku)
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
        suggested = max(0, min(line.ordered_quantity, position.available_to_invoice))
        lines.append(
            {
                "sku": product.sku,
                "product_name": product.name,
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
                "remaining_quantity": max(0, line.ordered_quantity - invoiced),
                "available": position.available_to_invoice,
                "suggested_to_invoice": max(
                    0, min(line.ordered_quantity - invoiced, suggested)
                ),
                "shortage": line.ordered_quantity - suggested,
                "complete": suggested == line.ordered_quantity,
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
        "source_documents": [
            {
                "token": document.upload_token,
                "filename": document.original_filename,
                "content_type": document.content_type,
                "extraction_method": document.extraction_method,
                "page_count": document.page_count,
                "size_bytes": len(document.content),
                "uploaded_at": document.created_at,
                "uploaded_by_user_id": document.created_by_user_id,
                "sha256": document.sha256,
            }
            for document in db.scalars(
                select(PurchaseOrderSourceDocument)
                .join(
                    PurchaseOrderDocumentLink,
                    PurchaseOrderDocumentLink.document_id
                    == PurchaseOrderSourceDocument.id,
                )
                .where(PurchaseOrderDocumentLink.purchase_order_id == order.id)
                .order_by(PurchaseOrderSourceDocument.created_at)
            )
        ],
        "related_invoices": [
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
        ],
    }


@router.get("")
def list_orders(_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return [
        detail(db, order)
        for order in db.scalars(
            select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())
        ).all()
    ]


ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/plain",
}
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024


@router.post("/imports/preview")
async def preview_purchase_order_documents(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    files: Annotated[list[UploadFile] | None, File()] = None,
    pasted_text: Annotated[str | None, Form(max_length=200_000)] = None,
):
    inputs: list[tuple[str, str, bytes]] = []
    for upload in files or []:
        content = await upload.read(MAX_DOCUMENT_BYTES + 1)
        content_type = (upload.content_type or "").lower()
        if content_type not in ALLOWED_DOCUMENT_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"{upload.filename}: usa PDF, JPG, JPEG, PNG o WEBP.",
            )
        if len(content) > MAX_DOCUMENT_BYTES:
            raise HTTPException(
                status_code=413, detail=f"{upload.filename}: supera el límite de 15 MB."
            )
        inputs.append((upload.filename or "documento", content_type, content))
    if pasted_text and pasted_text.strip():
        inputs.append(("pedido-pegado.txt", "text/plain", pasted_text.encode("utf-8")))
    if not inputs:
        raise HTTPException(
            status_code=422, detail="Carga un documento o pega el pedido."
        )

    drafts = []
    for filename, content_type, content in inputs:
        digest = sha256(content).hexdigest()
        try:
            if content_type == "text/plain":
                extracted_text = f"[[PAGE:1]]\n{content.decode('utf-8')}"
                method = "pasted_text"
                page_count = 1
                warnings = ()
                table_rows = ()
            else:
                extracted = extract_document(content, content_type, filename)
                extracted_text = extracted.text
                method = extracted.method
                page_count = extracted.page_count
                warnings = extracted.warnings
                table_rows = extracted.table_rows
        except (RuntimeError, ValueError, OSError) as error:
            raise HTTPException(
                status_code=422, detail=f"{filename}: {error}"
            ) from error
        document = PurchaseOrderSourceDocument(
            original_filename=filename,
            content_type=content_type,
            content=content,
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
                    "warnings": preview_warnings,
                    "separation_needs_review": len(parts) > 1,
                }
            )
    db.commit()
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
    safe_name = document.original_filename.replace('"', "")
    return Response(
        content=document.content,
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


@router.post("", status_code=201)
def create_order(
    payload: OrderInput, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
):
    skus = [line.sku.strip().upper() for line in payload.lines]
    for line in payload.lines:
        if not line.conversion_confirmed:
            raise HTTPException(
                status_code=422,
                detail="Confirma todas las cantidades y conversiones antes de crear la OC.",
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
    order = PurchaseOrder(
        chain_name=payload.chain_name.strip(),
        customer_name=payload.customer_name,
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
    for line in payload.lines:
        db.add(
            PurchaseOrderLine(
                purchase_order_id=order.id,
                product_id=products[line.sku.strip().upper()].id,
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
    normalized_chain = normalize_identity(order.chain_name)
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
    return detail(db, order)
