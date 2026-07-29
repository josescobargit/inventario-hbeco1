import asyncio
import io
import queue
import threading
import time
import uuid
from pathlib import Path

from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import Headers, UploadFile

from app.api.router import api_router  # noqa: F401 - registers all models
from app.core.database import Base
from app.modules.documents.domain import job_service
from app.modules.documents.domain.upload_stream import stream_upload
from app.modules.documents.infrastructure.job_models import DocumentProcessingJob
from app.modules.purchase_orders.domain.document_extraction import ExtractedDocument


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (1200, 800), "white").save(output, format="PNG")
    return output.getvalue()


def test_upload_is_streamed_to_disk_and_removed(tmp_path, monkeypatch):
    content = png_bytes()
    upload = UploadFile(
        file=io.BytesIO(content),
        filename="orden.png",
        size=len(content),
        headers=Headers({"content-type": "image/png"}),
    )
    requested_sizes = []
    original_read = upload.read

    async def tracked_read(size: int = -1):
        requested_sizes.append(size)
        return await original_read(size)

    monkeypatch.setattr(upload, "read", tracked_read)
    document = asyncio.run(
        stream_upload(
            upload,
            allowed_types={"image/png"},
            max_bytes=15 * 1024 * 1024,
        )
    )

    assert document.path.exists()
    assert document.path.read_bytes() == content
    assert requested_sizes and set(requested_sizes) == {1024 * 1024}
    document.cleanup()
    assert not document.path.exists()


def test_ten_ocr_jobs_are_serial_and_cleanup_every_temporary(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(job_service, "SessionLocal", factory)
    active = 0
    peak_active = 0
    lock = threading.Lock()

    def fake_extract(_document, _job_id):
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.015)
        with lock:
            active -= 1
        return ExtractedDocument(
            text="[[PAGE:1]]\nFACTURA DIGITAL",
            method="ocr_test_subprocess",
            page_count=1,
        )

    monkeypatch.setattr(job_service, "run_document_extraction", fake_extract)
    monkeypatch.setattr(
        job_service,
        "_customer_invoice_result",
        lambda _db, job, _extracted, _path: {
            "filename": job.filename,
            "status": "recognized",
        },
    )
    user_id = uuid.uuid4()
    jobs = []
    with factory() as db:
        for index in range(10):
            path = tmp_path / f"job-{index}.png"
            path.write_bytes(b"temporary")
            job = DocumentProcessingJob(
                kind="customer_invoice",
                user_id=user_id,
                filename=path.name,
                content_type="image/png",
                temporary_path=str(path),
                sha256=f"{index:064d}",
                size_bytes=9,
                page_count=1,
                requires_ocr=True,
            )
            db.add(job)
            jobs.append(job)
        db.commit()
        job_ids = [job.id for job in jobs]

    local_queue: queue.Queue[uuid.UUID] = queue.Queue()
    worker = threading.Thread(
        target=job_service._worker,
        args=(local_queue,),
        kwargs={"is_ocr": True},
        daemon=True,
    )
    worker.start()
    for job_id in job_ids:
        local_queue.put(job_id)
    local_queue.join()

    with factory() as db:
        stored = list(
            db.scalars(
                select(DocumentProcessingJob).order_by(DocumentProcessingJob.created_at)
            ).all()
        )
    assert peak_active == 1
    assert [job.status for job in stored] == ["review"] * 10
    assert all(job.result["status"] == "recognized" for job in stored)
    assert not list(Path(tmp_path).glob("job-*.png"))
