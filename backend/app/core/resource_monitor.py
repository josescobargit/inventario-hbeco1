import json
import logging
import os
import resource
import tracemalloc
from typing import Any


logger = logging.getLogger("inventario.document_memory")
if os.getenv("DOCUMENT_MEMORY_TRACING", "false").lower() in {"1", "true", "yes"}:
    tracemalloc.start(1)


def _rss_bytes() -> int:
    try:
        import psutil

        process = psutil.Process()
        return process.memory_info().rss + sum(
            child.memory_info().rss
            for child in process.children(recursive=True)
            if child.is_running()
        )
    except Exception:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if os.uname().sysname == "Darwin" else peak * 1024)


def memory_snapshot(stage: str, job_id: str | None = None, **extra: Any) -> dict:
    heap_current = heap_peak = 0
    if tracemalloc.is_tracing():
        heap_current, heap_peak = tracemalloc.get_traced_memory()
    snapshot = {
        "event": "document_memory",
        "stage": stage,
        "job_id": job_id,
        "rss_bytes": _rss_bytes(),
        "python_heap_bytes": heap_current,
        "python_heap_peak_bytes": heap_peak,
        **extra,
    }
    logger.info(json.dumps(snapshot, sort_keys=True, default=str))
    return snapshot
