import hashlib
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.resource_monitor import memory_snapshot
from app.modules.auth.api.dependencies import CurrentUser
from app.modules.documents.domain.job_service import (
    enqueue,
    service_metrics,
    start_workers,
)
from app.modules.documents.domain.extraction_runner import cancel_document_extraction
from app.modules.documents.domain.upload_stream import (
    TEMP_DIRECTORY,
    StreamedDocument,
    stream_upload,
)
from app.modules.documents.infrastructure.job_models import DocumentProcessingJob


router = APIRouter(prefix="/document-jobs", tags=["Procesamiento de documentos"])
MAX_BYTES = 15 * 1024 * 1024
ALLOWED_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}
JobKind = Literal["purchase_order", "supplier_invoice", "customer_invoice"]


def serialize(job: DocumentProcessingJob) -> dict:
    return {
        "id": job.id,
        "kind": job.kind,
        "filename": job.filename,
        "status": job.status,
        "progress": job.progress,
        "requires_ocr": job.requires_ocr,
        "page_count": job.page_count,
        "size_bytes": job.size_bytes,
        "extraction_method": job.extraction_method,
        "result": job.result if job.status == "review" else None,
        "error": job.error_detail,
        "attempt": job.attempt,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


def _create_job(
    db: Session,
    user_id: uuid.UUID,
    kind: str,
    document: StreamedDocument,
) -> tuple[DocumentProcessingJob, bool]:
    existing = db.scalar(
        select(DocumentProcessingJob)
        .where(
            DocumentProcessingJob.user_id == user_id,
            DocumentProcessingJob.kind == kind,
            DocumentProcessingJob.sha256 == document.sha256,
            DocumentProcessingJob.status.in_(["pending", "processing", "review"]),
        )
        .order_by(DocumentProcessingJob.created_at.desc())
    )
    if existing:
        document.cleanup()
        return existing, True
    job = DocumentProcessingJob(
        kind=kind,
        user_id=user_id,
        filename=document.filename,
        content_type=document.content_type,
        temporary_path=str(document.path),
        sha256=document.sha256,
        size_bytes=document.size_bytes,
        page_count=document.page_count,
        requires_ocr=document.requires_ocr,
    )
    db.add(job)
    db.commit()
    return job, False


def _purge_expired_jobs(db: Session) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    expired = list(
        db.scalars(
            select(DocumentProcessingJob).where(
                DocumentProcessingJob.created_at < cutoff,
                DocumentProcessingJob.status.notin_(["pending", "processing"]),
            )
        ).all()
    )
    for job in expired:
        if job.temporary_path:
            Path(job.temporary_path).unlink(missing_ok=True)
        db.delete(job)
    if expired:
        db.commit()


@router.post("", status_code=202)
async def create_document_jobs(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    kind: Annotated[JobKind, Form()],
    files: Annotated[list[UploadFile] | None, File()] = None,
    pasted_text: Annotated[str | None, Form(max_length=200_000)] = None,
) -> dict:
    if len(files or []) > 10:
        raise HTTPException(
            status_code=422,
            detail="Carga hasta 10 archivos por lote; se procesarán en cola.",
        )
    if not files and not (pasted_text and pasted_text.strip()):
        raise HTTPException(status_code=422, detail="Selecciona al menos un documento.")
    documents: list[StreamedDocument] = []
    jobs: list[dict] = []
    try:
        _purge_expired_jobs(db)
        for upload in files or []:
            documents.append(
                await stream_upload(
                    upload, allowed_types=ALLOWED_TYPES, max_bytes=MAX_BYTES
                )
            )
        if pasted_text and pasted_text.strip():
            if kind != "purchase_order":
                raise HTTPException(
                    status_code=422,
                    detail="El texto pegado solo está disponible para órdenes de compra.",
                )
            TEMP_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
            content = pasted_text.strip().encode("utf-8")
            descriptor, path_value = tempfile.mkstemp(
                prefix="pasted-", suffix=".txt", dir=TEMP_DIRECTORY
            )
            path = Path(path_value)
            with os.fdopen(descriptor, "wb") as target:
                target.write(content)
            documents.append(
                StreamedDocument(
                    path=path,
                    filename="pedido-pegado.txt",
                    content_type="text/plain",
                    size_bytes=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                    page_count=1,
                    requires_ocr=False,
                )
            )
        for document in documents:
            start_workers()
            job, duplicate = _create_job(db, user.id, kind, document)
            if not duplicate:
                try:
                    enqueue(job)
                except RuntimeError as error:
                    document.cleanup()
                    job.status = "error"
                    job.temporary_path = None
                    job.error_detail = str(error)
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
            jobs.append({**serialize(job), "duplicate": duplicate})
        memory_snapshot(
            "uploads_queued",
            files_received=len(documents),
            **service_metrics(),
        )
        return {"jobs": jobs, "queue": service_metrics()}
    except Exception:
        for document in documents:
            if not db.scalar(
                select(DocumentProcessingJob.id).where(
                    DocumentProcessingJob.temporary_path == str(document.path)
                )
            ):
                document.cleanup()
        raise


@router.get("")
def list_document_jobs(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    ids: Annotated[str | None, Query(max_length=2000)] = None,
) -> dict:
    statement = (
        select(DocumentProcessingJob)
        .where(DocumentProcessingJob.user_id == user.id)
        .order_by(DocumentProcessingJob.created_at.desc())
        .limit(50)
    )
    if ids:
        try:
            parsed = [uuid.UUID(value) for value in ids.split(",") if value]
        except ValueError as error:
            raise HTTPException(
                status_code=422, detail="Identificador inválido."
            ) from error
        statement = statement.where(DocumentProcessingJob.id.in_(parsed))
    jobs = list(db.scalars(statement).all())
    return {"jobs": [serialize(job) for job in jobs], "queue": service_metrics()}


@router.delete("/{job_id}", status_code=204)
def cancel_document_job(
    job_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    job = db.scalar(
        select(DocumentProcessingJob)
        .where(
            DocumentProcessingJob.id == job_id,
            DocumentProcessingJob.user_id == user.id,
        )
        .with_for_update()
    )
    if not job:
        return
    if job.status == "pending":
        job.cancel_requested = True
        job.status = "cancelled"
        job.completed_at = datetime.now(timezone.utc)
        if job.temporary_path:
            Path(job.temporary_path).unlink(missing_ok=True)
            job.temporary_path = None
    elif job.status == "processing":
        job.cancel_requested = True
        cancel_document_extraction(str(job.id))
    db.commit()


@router.get("/metrics/current")
def current_document_metrics(_user: CurrentUser) -> dict:
    return {
        **service_metrics(),
        "memory": memory_snapshot("metrics_requested", **service_metrics()),
    }
