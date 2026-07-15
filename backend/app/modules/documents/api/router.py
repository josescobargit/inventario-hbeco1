import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.audit.infrastructure.models import AuditLog
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.documents.infrastructure.models import InvoiceAdjustment
from app.modules.invoices.infrastructure.models import Invoice


class AdjustmentInput(BaseModel):
    document_type: Literal["credit_note", "debit_note"]
    document_number: str = Field(min_length=1, max_length=80)
    document_date: date
    value: Decimal = Field(ge=0)
    reason: str = Field(min_length=5, max_length=1000)


router = APIRouter(prefix="/invoices", tags=["Documentos relacionados"])


@router.post("/{invoice_id}/adjustments", status_code=201)
def add_adjustment(
    invoice_id: uuid.UUID,
    payload: AdjustmentInput,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="No encontramos la factura.")
    item = InvoiceAdjustment(
        invoice_id=invoice.id,
        document_type=payload.document_type,
        document_number=payload.document_number.strip(),
        document_date=payload.document_date,
        value=payload.value,
        reason=payload.reason.strip(),
        registered_by_user_id=user.id,
    )
    db.add(item)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            action="invoice_adjustment_registered",
            entity_type="invoice_adjustment",
            entity_id=str(item.id),
            reason=item.reason,
            new_value={
                "type": item.document_type,
                "number": item.document_number,
                "value": str(item.value),
            },
        )
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Este documento ya está registrado."
        ) from error
    credits = db.scalar(
        select(func.coalesce(func.sum(InvoiceAdjustment.value), 0)).where(
            InvoiceAdjustment.invoice_id == invoice.id,
            InvoiceAdjustment.document_type == "credit_note",
        )
    )
    debits = db.scalar(
        select(func.coalesce(func.sum(InvoiceAdjustment.value), 0)).where(
            InvoiceAdjustment.invoice_id == invoice.id,
            InvoiceAdjustment.document_type == "debit_note",
        )
    )
    return {"id": item.id, "net_value": (invoice.total_value or 0) - credits + debits}
