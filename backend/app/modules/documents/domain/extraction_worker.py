import json
import sys
from dataclasses import asdict
from pathlib import Path

from app.core.resource_monitor import memory_snapshot
from app.modules.purchase_orders.domain.document_extraction import extract_document_path


def main() -> None:
    source, content_type, filename, result, job_id = sys.argv[1:6]
    memory_snapshot("ocr_child_start", None if job_id == "-" else job_id)
    extracted = extract_document_path(
        Path(source),
        content_type,
        filename,
        job_id=None if job_id == "-" else job_id,
    )
    Path(result).write_text(
        json.dumps(asdict(extracted), ensure_ascii=False), encoding="utf-8"
    )
    memory_snapshot(
        "ocr_child_complete",
        None if job_id == "-" else job_id,
        extraction_method=extracted.method,
        page_count=extracted.page_count,
    )


if __name__ == "__main__":
    main()
