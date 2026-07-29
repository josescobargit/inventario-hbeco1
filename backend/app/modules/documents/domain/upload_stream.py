import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import fitz
from fastapi import HTTPException, UploadFile
from PIL import Image

from app.modules.purchase_orders.domain.document_extraction import (
    has_usable_digital_text,
)


TEMP_DIRECTORY = Path(tempfile.gettempdir()) / "inventario-document-jobs"
CHUNK_SIZE = 1024 * 1024
MAX_PAGES = int(os.getenv("DOCUMENT_MAX_PAGES", "50"))
MAX_IMAGE_PIXELS = int(os.getenv("DOCUMENT_MAX_IMAGE_PIXELS", "30000000"))


@dataclass(frozen=True)
class StreamedDocument:
    path: Path
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    page_count: int
    requires_ocr: bool

    def cleanup(self) -> None:
        self.path.unlink(missing_ok=True)


def _inspect(path: Path, content_type: str) -> tuple[int, bool]:
    if content_type == "application/pdf":
        try:
            with fitz.open(path) as pdf:
                if len(pdf) < 1 or len(pdf) > MAX_PAGES:
                    raise HTTPException(
                        status_code=422,
                        detail=f"El PDF debe contener entre 1 y {MAX_PAGES} páginas.",
                    )
                requires_ocr = any(
                    not has_usable_digital_text(pdf[index].get_text("text", sort=True))
                    for index in range(len(pdf))
                )
                return len(pdf), requires_ocr
        except HTTPException:
            raise
        except (RuntimeError, ValueError) as error:
            raise HTTPException(
                status_code=422, detail="El PDF está dañado o no puede abrirse."
            ) from error
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            pixels = image.width * image.height
            if pixels > MAX_IMAGE_PIXELS:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "La imagen supera el límite de resolución "
                        f"({MAX_IMAGE_PIXELS:,} píxeles)."
                    ),
                )
        return 1, True
    except HTTPException:
        raise
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=422, detail="La imagen está dañada o no puede abrirse."
        ) from error


async def stream_upload(
    upload: UploadFile,
    *,
    allowed_types: set[str],
    max_bytes: int,
) -> StreamedDocument:
    content_type = (upload.content_type or "").lower()
    if content_type not in allowed_types:
        raise HTTPException(
            status_code=422,
            detail=f"{upload.filename}: usa PDF, JPG, JPEG, PNG o WEBP.",
        )
    TEMP_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix="upload-", dir=TEMP_DIRECTORY)
    path = Path(raw_path)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as target:
            while chunk := await upload.read(CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"{upload.filename}: supera el límite de {max_bytes // 1024 // 1024} MB.",
                    )
                digest.update(chunk)
                target.write(chunk)
        if not size:
            raise HTTPException(
                status_code=422, detail=f"{upload.filename}: el archivo está vacío."
            )
        page_count, requires_ocr = _inspect(path, content_type)
        path.chmod(0o600)
        return StreamedDocument(
            path=path,
            filename=upload.filename or "documento",
            content_type=content_type,
            size_bytes=size,
            sha256=digest.hexdigest(),
            page_count=page_count,
            requires_ocr=requires_ocr,
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
