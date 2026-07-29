"""Measure parent + OCR child RSS for real document extraction."""

import gc
import hashlib
import json
import mimetypes
import threading
import time
import uuid
from pathlib import Path

import psutil

from app.core.resource_monitor import memory_snapshot
from app.modules.documents.domain.extraction_runner import run_document_extraction
from app.modules.documents.domain.upload_stream import StreamedDocument, _inspect


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def rss_with_children() -> int:
    process = psutil.Process()
    total = process.memory_info().rss
    try:
        children = process.children(recursive=True)
    except (PermissionError, psutil.AccessDenied):
        children = []
    for child in children:
        try:
            total += child.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return total


def measure(path: Path) -> dict:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() == ".pdf":
        content_type = "application/pdf"
    pages, requires_ocr = _inspect(path, content_type)
    document = StreamedDocument(
        path=path,
        filename=path.name,
        content_type=content_type,
        size_bytes=path.stat().st_size,
        sha256=digest(path),
        page_count=pages,
        requires_ocr=requires_ocr,
    )
    samples = []
    running = True

    def sample() -> None:
        while running:
            samples.append(rss_with_children())
            time.sleep(0.025)

    before = memory_snapshot("benchmark_before", str(uuid.uuid4()))
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    started = time.monotonic()
    try:
        extracted = run_document_extraction(document, str(uuid.uuid4()))
    finally:
        running = False
        sampler.join(timeout=1)
    gc.collect()
    time.sleep(0.2)
    after = memory_snapshot("benchmark_after", None)
    return {
        "file": path.name,
        "size_bytes": path.stat().st_size,
        "pages": pages,
        "requires_ocr": requires_ocr,
        "method": extracted.method,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "rss_before_bytes": before["rss_bytes"],
        "rss_peak_parent_and_children_bytes": max(samples, default=after["rss_bytes"]),
        "rss_after_bytes": after["rss_bytes"],
        "python_heap_before_bytes": before["python_heap_bytes"],
        "python_heap_after_bytes": after["python_heap_bytes"],
        "product_rows": len(extracted.table_rows),
    }


if __name__ == "__main__":
    import sys

    for argument in sys.argv[1:]:
        print(json.dumps(measure(Path(argument)), ensure_ascii=False))
