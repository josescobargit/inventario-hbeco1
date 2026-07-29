import queue
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import fitz
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.resource_monitor import memory_snapshot
from app.modules.documents.domain.extraction_runner import (
    queue_metrics as extraction_queue_metrics,
)
from app.modules.documents.domain.extraction_runner import run_document_extraction
from app.modules.documents.domain.upload_stream import StreamedDocument
from app.modules.documents.infrastructure.job_models import DocumentProcessingJob


OCR_JOBS: queue.Queue[uuid.UUID] = queue.Queue(maxsize=100)
DIGITAL_JOBS: queue.Queue[uuid.UUID] = queue.Queue(maxsize=100)
_started = False
_start_lock = threading.Lock()
_active_lock = threading.Lock()
_active_ocr_jobs = 0
_active_digital_jobs = 0


def service_metrics() -> dict[str, int]:
    with _active_lock:
        return {
            "pending_ocr_jobs": OCR_JOBS.qsize(),
            "pending_digital_jobs": DIGITAL_JOBS.qsize(),
            "active_ocr_jobs": _active_ocr_jobs,
            "active_digital_jobs": _active_digital_jobs,
            **extraction_queue_metrics(),
        }


def enqueue(job: DocumentProcessingJob) -> None:
    target = OCR_JOBS if job.requires_ocr else DIGITAL_JOBS
    try:
        target.put_nowait(job.id)
    except queue.Full as error:
        raise RuntimeError(
            "La cola de documentos está llena. Intenta nuevamente más tarde."
        ) from error


def _purchase_order_result(db, job, extracted, source_path: Path) -> dict:
    from app.modules.purchase_orders.api.router import (
        preview_path,
        purge_expired_previews,
    )
    from app.modules.purchase_orders.domain.customer_profiles import (
        chain_evidence_aliases,
    )
    from app.modules.purchase_orders.domain.document_extraction import (
        classify_document,
        expected_product_count,
        extraction_signals,
        recognized_header,
        split_purchase_orders,
        suggest_chains_from_confirmed_aliases,
    )
    from app.modules.purchase_orders.infrastructure.models import (
        CustomerProductAlias,
        PurchaseOrderSourceDocument,
    )

    purge_expired_previews(db)
    document = PurchaseOrderSourceDocument(
        original_filename=job.filename,
        content_type=job.content_type,
        content=None,
        sha256=job.sha256,
        extraction_method=extracted.method,
        extracted_text=extracted.text,
        page_count=extracted.page_count,
        created_by_user_id=job.user_id,
    )
    db.add(document)
    db.flush()
    duplicate = db.scalar(
        select(PurchaseOrderSourceDocument.id).where(
            PurchaseOrderSourceDocument.sha256 == job.sha256,
            PurchaseOrderSourceDocument.id != document.id,
        )
    )
    warnings = list(extracted.warnings)
    if duplicate:
        warnings.append(
            "Este mismo archivo ya fue cargado anteriormente; revisa si la OC está duplicada."
        )
    aliases = [
        (alias.chain_name, alias.source_text_normalized, alias.detected_code)
        for alias in db.scalars(select(CustomerProductAlias)).all()
    ] + chain_evidence_aliases()
    parts = split_purchase_orders(extracted.text)
    drafts = []
    for part in parts or [extracted.text]:
        header = recognized_header(part, job.filename)
        learned = suggest_chains_from_confirmed_aliases(part, aliases)
        candidates = list(
            dict.fromkeys([*(header["chain_candidates"] or []), *learned])
        )
        header["chain_candidates"] = candidates
        header["chain_name"] = candidates[0] if len(candidates) == 1 else None
        drafts.append(
            {
                "document_token": document.upload_token,
                "filename": job.filename,
                "content_type": job.content_type,
                "extraction_method": extracted.method,
                "page_count": extracted.page_count,
                "text": part,
                "header": header,
                "classification": classify_document(part),
                "signals": extraction_signals(part),
                "table_rows": (list(extracted.table_rows) if len(parts) <= 1 else []),
                "expected_product_count": (
                    extracted.expected_product_count
                    if len(parts) <= 1
                    else expected_product_count(part, [])
                ),
                "warnings": warnings,
                "separation_needs_review": len(parts) > 1,
            }
        )
    destination = preview_path(document.upload_token)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copyfile(source_path, destination)
    destination.chmod(0o600)
    return {"drafts": drafts}


def _supplier_invoice_result(db, job, extracted, source_path: Path) -> dict:
    from app.modules.supplier_invoices.api.router import _product_matcher
    from app.modules.supplier_invoices.domain.extraction import (
        supplier_result_from_extracted,
    )

    pdf = fitz.open(source_path) if job.content_type == "application/pdf" else None
    try:
        result = supplier_result_from_extracted(extracted, pdf)
    finally:
        if pdf is not None:
            pdf.close()
    match = _product_matcher(db, result.get("supplier_ruc"))
    lines = [{**line, **match(line)} for line in result["lines"]]
    warnings = list(result["warnings"])
    if not lines:
        warnings.append("No se encontraron líneas de producto para revisar.")
    return {
        **result,
        "original_filename": job.filename,
        "file_sha256": job.sha256,
        "lines": lines,
        "summary": {
            "detected": len(lines),
            "recognized": sum(line["status"] == "recognized" for line in lines),
            "pending": sum(line["status"] != "recognized" for line in lines),
        },
        "warnings": warnings,
    }


def _customer_invoice_result(_db, job, extracted, _source_path: Path) -> dict:
    return {
        "filename": job.filename,
        "status": "recognized",
        "text": extracted.text,
        "table_rows": list(extracted.table_rows),
        "extraction_method": extracted.method,
        "page_count": extracted.page_count,
        "warnings": list(extracted.warnings),
    }


def _process(job_id: uuid.UUID, *, is_ocr: bool) -> None:
    global _active_digital_jobs, _active_ocr_jobs
    db = SessionLocal()
    job = db.get(DocumentProcessingJob, job_id)
    if not job:
        db.close()
        return
    if job.status != "pending" or job.cancel_requested:
        if job.temporary_path:
            Path(job.temporary_path).unlink(missing_ok=True)
        db.close()
        return
    with _active_lock:
        if is_ocr:
            _active_ocr_jobs += 1
        else:
            _active_digital_jobs += 1
    job.status = "processing"
    job.progress = 20
    job.started_at = datetime.now(timezone.utc)
    db.commit()
    initial = memory_snapshot(
        "job_processing_start",
        str(job.id),
        kind=job.kind,
        **service_metrics(),
    )
    path = Path(job.temporary_path or "")
    try:
        document = StreamedDocument(
            path=path,
            filename=job.filename,
            content_type=job.content_type,
            size_bytes=job.size_bytes,
            sha256=job.sha256,
            page_count=job.page_count,
            requires_ocr=job.requires_ocr,
        )
        extracted = run_document_extraction(document, str(job.id))
        db.refresh(job)
        if job.cancel_requested:
            job.status = "cancelled"
            job.error_detail = "Procesamiento cancelado por el usuario."
            job.progress = 0
        else:
            processors = {
                "purchase_order": _purchase_order_result,
                "supplier_invoice": _supplier_invoice_result,
                "customer_invoice": _customer_invoice_result,
            }
            result = processors[job.kind](db, job, extracted, path)
            job.result = jsonable_encoder(result)
            job.extraction_method = extracted.method
            job.status = "review"
            job.progress = 100
        job.completed_at = datetime.now(timezone.utc)
        final = memory_snapshot(
            "job_processing_complete",
            str(job.id),
            extraction_method=extracted.method,
            **service_metrics(),
        )
        job.memory_metrics = {"initial": initial, "final": final}
        job.temporary_path = None
        db.commit()
    except Exception as error:
        db.rollback()
        job = db.get(DocumentProcessingJob, job_id)
        if job:
            cancelled = job.cancel_requested
            job.status = "cancelled" if cancelled else "error"
            job.progress = 0
            job.error_detail = (
                "Procesamiento cancelado por el usuario."
                if cancelled
                else str(error)[:2000]
            )
            job.completed_at = datetime.now(timezone.utc)
            job.temporary_path = None
            job.memory_metrics = {
                "initial": initial,
                "final": memory_snapshot(
                    "job_processing_error",
                    str(job.id),
                    error_type=type(error).__name__,
                    **service_metrics(),
                ),
            }
            db.commit()
    finally:
        path.unlink(missing_ok=True)
        with _active_lock:
            if is_ocr:
                _active_ocr_jobs -= 1
            else:
                _active_digital_jobs -= 1
        db.close()


def _worker(target: queue.Queue[uuid.UUID], *, is_ocr: bool) -> None:
    while True:
        job_id = target.get()
        try:
            _process(job_id, is_ocr=is_ocr)
        finally:
            target.task_done()


def start_workers() -> None:
    global _started
    with _start_lock:
        if _started:
            return
        db = SessionLocal()
        try:
            interrupted = list(
                db.scalars(
                    select(DocumentProcessingJob).where(
                        DocumentProcessingJob.status == "processing"
                    )
                ).all()
            )
            for job in interrupted:
                if job.temporary_path:
                    Path(job.temporary_path).unlink(missing_ok=True)
                job.temporary_path = None
                job.status = "error"
                job.progress = 0
                job.error_detail = (
                    "El servicio se reinició durante el procesamiento. "
                    "Vuelve a cargar el archivo; no se creó ningún duplicado."
                )
                job.completed_at = datetime.now(timezone.utc)
            pending = list(
                db.scalars(
                    select(DocumentProcessingJob).where(
                        DocumentProcessingJob.status == "pending"
                    )
                ).all()
            )
            for job in pending:
                if not job.temporary_path or not Path(job.temporary_path).exists():
                    job.status = "error"
                    job.error_detail = (
                        "El archivo temporal no sobrevivió al reinicio. "
                        "Vuelve a cargarlo."
                    )
                    job.temporary_path = None
                    job.completed_at = datetime.now(timezone.utc)
            db.commit()
            pending = [
                job
                for job in pending
                if job.status == "pending"
                and job.temporary_path
                and Path(job.temporary_path).exists()
            ]
        finally:
            db.close()
        _started = True
        threading.Thread(
            target=_worker,
            args=(OCR_JOBS,),
            kwargs={"is_ocr": True},
            name="document-ocr-worker",
            daemon=True,
        ).start()
        for index in range(2):
            threading.Thread(
                target=_worker,
                args=(DIGITAL_JOBS,),
                kwargs={"is_ocr": False},
                name=f"document-digital-worker-{index + 1}",
                daemon=True,
            ).start()
        for job in pending:
            enqueue(job)
