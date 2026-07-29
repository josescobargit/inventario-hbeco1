import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from app.core.resource_monitor import memory_snapshot
from app.modules.documents.domain.upload_stream import StreamedDocument
from app.modules.purchase_orders.domain.document_extraction import (
    ExtractedDocument,
    expected_product_count,
    extract_document_path,
)


OCR_LIMIT = threading.BoundedSemaphore(
    value=max(1, int(os.getenv("DOCUMENT_OCR_CONCURRENCY", "1")))
)
DIGITAL_LIMIT = threading.BoundedSemaphore(
    value=max(1, int(os.getenv("DOCUMENT_DIGITAL_CONCURRENCY", "2")))
)
OCR_TIMEOUT_SECONDS = int(os.getenv("DOCUMENT_OCR_TIMEOUT_SECONDS", "120"))
_counter_lock = threading.Lock()
_waiting_ocr = 0
_active_ocr = 0
_process_lock = threading.Lock()
_active_processes: dict[str, subprocess.Popen[str]] = {}


def queue_metrics() -> dict[str, int]:
    with _counter_lock:
        return {
            "ocr_waiting": _waiting_ocr,
            "ocr_active": _active_ocr,
            "ocr_concurrency": 1,
        }


def cancel_document_extraction(job_id: str) -> None:
    with _process_lock:
        process = _active_processes.get(job_id)
    if process is not None and process.poll() is None:
        process.terminate()


def _from_payload(payload: dict) -> ExtractedDocument:
    return ExtractedDocument(
        text=payload["text"],
        method=payload["method"],
        page_count=payload["page_count"],
        warnings=tuple(payload.get("warnings", [])),
        table_rows=tuple(payload.get("table_rows", [])),
        expected_product_count=payload.get("expected_product_count"),
    )


def _ocr_in_subprocess(
    document: StreamedDocument, job_id: str | None
) -> ExtractedDocument:
    global _active_ocr, _waiting_ocr
    with _counter_lock:
        _waiting_ocr += 1
    with OCR_LIMIT:
        with _counter_lock:
            _waiting_ocr -= 1
            _active_ocr += 1
        descriptor, raw_result_path = tempfile.mkstemp(suffix=".json")
        os.close(descriptor)
        result_path = Path(raw_result_path)
        active_counted = True
        started = time.monotonic()
        process: subprocess.Popen[str] | None = None
        try:
            command = [
                sys.executable,
                "-m",
                "app.modules.documents.domain.extraction_worker",
                str(document.path),
                document.content_type,
                document.filename,
                str(result_path),
                job_id or "-",
            ]
            memory_snapshot(
                "ocr_start",
                job_id,
                page_count=document.page_count,
                **queue_metrics(),
            )
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            if job_id:
                with _process_lock:
                    _active_processes[job_id] = process
            try:
                process.communicate(timeout=OCR_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as error:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise RuntimeError(
                    f"El OCR superó el límite de {OCR_TIMEOUT_SECONDS} segundos."
                ) from error
            if process.returncode != 0:
                raise RuntimeError(
                    "El proceso OCR terminó con error y fue liberado correctamente."
                )
            return _from_payload(json.loads(result_path.read_text(encoding="utf-8")))
        finally:
            if job_id:
                with _process_lock:
                    _active_processes.pop(job_id, None)
            if active_counted:
                with _counter_lock:
                    _active_ocr -= 1
                active_counted = False
            memory_snapshot(
                "ocr_end",
                job_id,
                duration_ms=round((time.monotonic() - started) * 1000),
                return_code=process.returncode if process is not None else None,
                **queue_metrics(),
            )
            result_path.unlink(missing_ok=True)


def run_document_extraction(
    document: StreamedDocument, job_id: str | None = None
) -> ExtractedDocument:
    memory_snapshot(
        "extraction_received",
        job_id,
        size_bytes=document.size_bytes,
        page_count=document.page_count,
        requires_ocr=document.requires_ocr,
        **queue_metrics(),
    )
    if document.content_type == "text/plain":
        text = document.path.read_text(encoding="utf-8")
        marked = f"[[PAGE:1]]\n{text}"
        return ExtractedDocument(
            text=marked,
            method="pasted_text",
            page_count=1,
            expected_product_count=expected_product_count(marked, []),
        )
    if document.requires_ocr:
        return _ocr_in_subprocess(document, job_id)
    with DIGITAL_LIMIT:
        started = time.monotonic()
        memory_snapshot("digital_text_start", job_id, **queue_metrics())
        try:
            return extract_document_path(
                document.path, document.content_type, document.filename, job_id=job_id
            )
        finally:
            memory_snapshot(
                "digital_text_end",
                job_id,
                duration_ms=round((time.monotonic() - started) * 1000),
                **queue_metrics(),
            )
