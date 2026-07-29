import io
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import fitz
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from app.core.resource_monitor import memory_snapshot
from app.modules.purchase_orders.domain.table_extraction import (
    extract_known_ocr_text_rows,
    extract_pdf_table_rows,
    extract_visual_word_rows,
)


ORDER_LABEL = (
    r"(?:ORDEN(?:\s+DE\s+COMPRA)?|O\.?\s*C\.?|PURCHASE\s+ORDER|P\.?\s*O\.?|"
    r"PEDIDO|N(?:Ú|U|RO|UMERO|°)\.?\s*(?:DE\s+)?(?:PEDIDO|DOCUMENTO|OC))"
)
ORDER_MARKER = re.compile(
    rf"(?im)^(?:{ORDER_LABEL})\s*(?:N(?:Ú|U|°|O|RO)\.?)?\s*[:#-]?\s*"
    r"([A-Z0-9][A-Z0-9._/-]{2,})\s*$"
)
DATE_PATTERN = re.compile(
    r"(?im)^(?:FECHA(?:\s+DE\s+(?:ORDEN|PEDIDO|EMISI[ÓO]N))?|EMISI[ÓO]N|DATE)"
    r"\s*[:#-]?\s*(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4})"
)
CHAIN_PATTERN = re.compile(
    r"(?im)^(?:CLIENTE|CADENA|COMPRADOR|BUYER|CUSTOMER|RAZ[ÓO]N\s+SOCIAL)"
    r"\s*[:#-]\s*(.{2,160})$"
)
PAGE_MARKER = re.compile(r"^\[\[PAGE:(\d+)]]$")
PRODUCT_TERMS = re.compile(
    r"\b(?:PRODUCTO|ART[IÍ]CULO|ITEM|[ÍI]TEM|DESCRIPCI[ÓO]N|DETALLE|MERCADER[IÍ]A|"
    r"C[ÓO]DIGO|SKU|EAN|BARRAS|PROVEEDOR)\b",
    re.IGNORECASE,
)
QUANTITY_TERMS = re.compile(
    r"\b(?:CANTIDAD|CANT\.?|QTY|UNIDADES?|UDS?\.?|SOLICITADO|PEDIDO)\b",
    re.IGNORECASE,
)
COMPANY_PATTERN = re.compile(
    r"(?im)^(.{2,120}\b(?:S\.?\s*A\.?\s*S?\.?|C[IÍ]A\.?\s*LTDA\.?|LTDA\.?|"
    r"CORPORACI[ÓO]N|SUPERMERCADOS?|COMERCIAL|INC\.?|LLC)\b.{0,40})$"
)
REFERENCE_PATTERN = re.compile(
    r"(?im)^(?:PED(?:IDO)?\.?\s*(?:DE\s+)?COMPRA|REFERENCIA(?:\s+DE\s+(?:ORDEN|PEDIDO))?|"
    r"REF\.?\s*(?:ORDEN|PEDIDO)?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,})\s*$"
)
PREVALIDATION_PATTERN = re.compile(
    r"\bPRE\s*VALIDACI[ÓO]N\s+(?:DE\s+)?FACTURA\b|\bPREVALIDACI[ÓO]N\s+FACTURA\b",
    re.IGNORECASE,
)
DISPATCH_PATTERN = re.compile(
    r"\b(?:GU[IÍ]A\s+DE\s+REMISI[ÓO]N|DOCUMENTO\s+DE\s+DESPACHO|NOTA\s+DE\s+ENTREGA|"
    r"DESPACHO\s+DE\s+MERCADER[IÍ]A)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    method: str
    page_count: int
    warnings: tuple[str, ...] = ()
    table_rows: tuple[dict, ...] = ()
    expected_product_count: int | None = None


def _candidate_product_rows(text: str) -> int:
    candidates = 0
    for line in text.splitlines():
        normalized = re.sub(r"\s+", " ", line).strip()
        if len(normalized) < 5:
            continue
        if re.search(
            r"\b(?:RUC|DIRECCI[ÓO]N|TEL[ÉE]FONO|EMAIL|CORREO|DERECHOS\s+RESERVADOS)\b",
            normalized,
            re.IGNORECASE,
        ) and not PRODUCT_TERMS.search(normalized):
            continue
        has_integer = bool(re.search(r"(?:^|\s)\d+(?:[.,]00)?(?:\s|$)", normalized))
        has_description = bool(re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", normalized))
        if has_integer and has_description:
            candidates += 1
    return candidates


def extraction_signals(text: str) -> dict[str, bool | int]:
    """Assess business structure, not merely whether a PDF contains characters."""
    compact = re.sub(r"\s+", "", text)
    return {
        "enough_text": len(compact) >= 30,
        "order": bool(ORDER_MARKER.search(text)),
        "chain": bool(CHAIN_PATTERN.search(text) or COMPANY_PATTERN.search(text)),
        "product_structure": bool(PRODUCT_TERMS.search(text)),
        "quantity_structure": bool(QUANTITY_TERMS.search(text)),
        "candidate_rows": _candidate_product_rows(text),
    }


def classify_document(text: str) -> dict[str, str | bool]:
    normalized = normalize_identity(text)
    if PREVALIDATION_PATTERN.search(normalized):
        return {
            "type": "invoice_prevalidation",
            "label": "Prevalidación de factura",
            "allowed_for_purchase_order": False,
            "message": "Este documento no corresponde a una orden de compra.",
        }
    if DISPATCH_PATTERN.search(normalized):
        return {
            "type": "dispatch_document",
            "label": "Documento de despacho",
            "allowed_for_purchase_order": False,
            "message": "Este documento no corresponde a una orden de compra.",
        }
    if re.search(r"(?im)^\s*PEDIDO\b", text) and not re.search(
        r"(?i)\bpedidoId\b", text
    ):
        return {
            "type": "order_request",
            "label": "Pedido",
            "allowed_for_purchase_order": True,
            "message": "",
        }
    signals = extraction_signals(text)
    if signals["order"] or (
        signals["product_structure"]
        and signals["quantity_structure"]
        and signals["candidate_rows"]
    ):
        return {
            "type": "purchase_order",
            "label": "Orden de compra",
            "allowed_for_purchase_order": True,
            "message": "",
        }
    return {
        "type": "unknown",
        "label": "Documento desconocido",
        "allowed_for_purchase_order": False,
        "message": "Este documento no corresponde a una orden de compra.",
    }


def _is_usable_order_text(text: str) -> bool:
    signals = extraction_signals(text)
    return bool(
        signals["enough_text"]
        and signals["candidate_rows"]
        and (
            (signals["product_structure"] and signals["quantity_structure"])
            or (signals["order"] and signals["chain"])
        )
    )


def _merge_page_text(direct_text: str, ocr_text: str) -> str:
    """Keep digital order/layout first and append only OCR lines that add evidence."""
    direct_lines = [line.strip() for line in direct_text.splitlines() if line.strip()]
    known = {normalize_identity(line) for line in direct_lines}
    added = [
        line.strip()
        for line in ocr_text.splitlines()
        if line.strip() and normalize_identity(line) not in known
    ]
    return "\n".join([*direct_lines, *added])


def _prepare_image(image: Image.Image) -> Image.Image:
    prepared = ImageOps.exif_transpose(image).convert("L")
    if max(prepared.size) > 1800:
        scale = 1800 / max(prepared.size)
        resized = prepared.resize(
            (int(prepared.width * scale), int(prepared.height * scale)),
            Image.Resampling.LANCZOS,
        )
        prepared.close()
        prepared = resized
    if max(prepared.size) < 1800:
        scale = 1800 / max(prepared.size)
        resized = prepared.resize(
            (int(prepared.width * scale), int(prepared.height * scale)),
            Image.Resampling.LANCZOS,
        )
        prepared.close()
        prepared = resized
    contrasted = ImageOps.autocontrast(prepared, cutoff=1)
    prepared.close()
    enhanced = ImageEnhance.Contrast(contrasted).enhance(1.45)
    contrasted.close()
    sharpened = enhanced.filter(ImageFilter.SHARPEN)
    enhanced.close()
    return sharpened


def _ocr_with_vision(image: Image.Image) -> str:
    swift = shutil.which("swift")
    script = Path(__file__).parents[4] / "scripts" / "ocr_vision.swift"
    if not swift or not script.exists():
        return ""
    with tempfile.NamedTemporaryFile(suffix=".png") as temporary:
        image.save(temporary.name, format="PNG")
        candidates = []
        for orientation in (1, 3, 6, 8):
            result = subprocess.run(
                [swift, str(script), temporary.name, str(orientation)],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if result.returncode == 0:
                candidates.append(result.stdout.strip())
        return max(
            candidates,
            key=lambda value: sum(char.isalnum() for char in value),
            default="",
        )


def _rapid_ocr(image: Image.Image) -> tuple[str, list[dict], tuple[int, int]]:
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return "", [], image.size
    rgb = image.convert("RGB")
    try:
        result, _elapsed = RapidOCR(
            use_cls=False,
            intra_op_num_threads=1,
            inter_op_num_threads=1,
            det_limit_side_len=960,
            rec_batch_num=1,
            max_side_len=1800,
        )(np.asarray(rgb))
    finally:
        rgb.close()
    if not result:
        return "", [], image.size
    words = []
    for box, text, _score in result:
        x_values = [float(point[0]) for point in box]
        y_values = [float(point[1]) for point in box]
        words.append(
            {
                "x0": min(x_values),
                "y0": min(y_values),
                "x1": max(x_values),
                "y1": max(y_values),
                "text": str(text),
            }
        )
    grouped: list[list[dict]] = []
    for word in sorted(words, key=lambda item: (item["y0"], item["x0"])):
        center_y = (word["y0"] + word["y1"]) / 2
        row = next(
            (
                candidate
                for candidate in reversed(grouped[-5:])
                if abs(
                    center_y
                    - sum((item["y0"] + item["y1"]) / 2 for item in candidate)
                    / len(candidate)
                )
                <= max(8, image.height / 120)
            ),
            None,
        )
        if row is None:
            grouped.append([word])
        else:
            row.append(word)
    text = "\n".join(
        " ".join(item["text"] for item in sorted(row, key=lambda item: item["x0"]))
        for row in grouped
    )
    return text, words, image.size


def _remove_table_rules(image: Image.Image) -> Image.Image:
    """Remove long dark rules without retaining another full RGB image."""
    grayscale = image if image.mode == "L" else image.convert("L")
    width, height = grayscale.size
    pixels = bytearray(grayscale.tobytes())
    dark_limit = 100
    row_limit = int(width * 0.35)
    column_limit = int(height * 0.25)
    rows = [
        y
        for y in range(height)
        if sum(value < dark_limit for value in pixels[y * width : (y + 1) * width])
        > row_limit
    ]
    columns = [
        x
        for x in range(width)
        if sum(pixels[y * width + x] < dark_limit for y in range(height))
        > column_limit
    ]
    for y in rows:
        start = y * width
        pixels[start : start + width] = b"\xff" * width
    for x in columns:
        for y in range(height):
            pixels[y * width + x] = 255
    cleaned = Image.frombytes("L", (width, height), bytes(pixels))
    if grayscale is not image:
        grayscale.close()
    return cleaned


def _recover_units_per_box_words(
    image: Image.Image, data: dict[str, list]
) -> list[dict]:
    header_index = next(
        (
            index
            for index, value in enumerate(data["text"])
            if re.sub(r"[^A-Z0-9]", "", str(value).upper())
            in {"UXC", "UC", "URE"}
        ),
        None,
    )
    if header_index is None:
        return []
    left = int(data["left"][header_index])
    top = int(data["top"][header_index])
    width = int(data["width"][header_index])
    height = int(data["height"][header_index])
    right = min(image.width, left + max(width + 20, round(width * 1.4)))
    bottom_of_header = top + height
    already_numeric = any(
        str(value).strip().isdigit()
        and bottom_of_header < int(data["top"][index])
        and left <= int(data["left"][index]) <= right
        for index, value in enumerate(data["text"])
    )
    if already_numeric or right <= left or bottom_of_header >= image.height:
        return []
    crop = image.crop((left, bottom_of_header, right, image.height))
    scale = 4
    enlarged = crop.resize(
        (crop.width * scale, crop.height * scale), Image.Resampling.LANCZOS
    )
    crop.close()
    try:
        numeric = pytesseract.image_to_data(
            enlarged,
            config="--psm 6 -c tessedit_char_whitelist=0123456789",
            output_type=pytesseract.Output.DICT,
            timeout=30,
        )
    finally:
        enlarged.close()
    recovered: list[dict] = []
    for index, value in enumerate(numeric["text"]):
        text = str(value).strip()
        if not re.fullmatch(r"\d{1,3}", text):
            continue
        word_left = left + int(numeric["left"][index]) / scale
        word_top = bottom_of_header + int(numeric["top"][index]) / scale
        word_width = int(numeric["width"][index]) / scale
        word_height = int(numeric["height"][index]) / scale
        recovered.append(
            {
                "x0": word_left,
                "y0": word_top,
                "x1": word_left + word_width,
                "y1": word_top + word_height,
                "text": text,
            }
        )
    return recovered


def _ocr_image(
    image: Image.Image,
) -> tuple[str, str, list[dict], tuple[int, int]]:
    prepared = _prepare_image(image)
    try:
        if shutil.which("tesseract"):
            ocr_image = _remove_table_rules(prepared)
            try:
                data = pytesseract.image_to_data(
                    ocr_image,
                    lang="spa+eng",
                    config="--psm 6",
                    output_type=pytesseract.Output.DICT,
                    timeout=90,
                )
            finally:
                ocr_image.close()
            words: list[dict] = []
            lines: dict[tuple[int, int, int, int], list[tuple[int, str]]] = {}
            for index, raw_text in enumerate(data["text"]):
                text = str(raw_text).strip()
                if not text:
                    continue
                left = int(data["left"][index])
                top = int(data["top"][index])
                width = int(data["width"][index])
                height = int(data["height"][index])
                words.append(
                    {
                        "x0": left,
                        "y0": top,
                        "x1": left + width,
                        "y1": top + height,
                        "text": text,
                    }
                )
                line_key = (
                    int(data["page_num"][index]),
                    int(data["block_num"][index]),
                    int(data["par_num"][index]),
                    int(data["line_num"][index]),
                )
                lines.setdefault(line_key, []).append((left, text))
            words.extend(_recover_units_per_box_words(prepared, data))
            recognized_text = "\n".join(
                " ".join(text for _, text in sorted(line))
                for line in lines.values()
            )
            return (
                recognized_text,
                "ocr_tesseract_local",
                words,
                prepared.size,
            )
        rapid_text, rapid_words, rapid_size = _rapid_ocr(prepared)
        if rapid_text:
            return rapid_text, "ocr_rapid_local", rapid_words, rapid_size
        vision_text = _ocr_with_vision(prepared)
        if vision_text:
            return vision_text, "ocr_apple_vision_local", [], prepared.size
        raise RuntimeError(
            "No hay un motor OCR local disponible. Instala Tesseract o ejecuta en macOS con Vision."
        )
    finally:
        prepared.close()


def _meaningful_digital_text(text: str) -> bool:
    if _is_usable_order_text(text):
        return True
    normalized = normalize_identity(text)
    return bool(
        "FACTURA" in normalized
        and _candidate_product_rows(text)
        and PRODUCT_TERMS.search(text)
        and QUANTITY_TERMS.search(text)
    )


def has_usable_digital_text(text: str) -> bool:
    return _meaningful_digital_text(text)


def _largest_embedded_page_image(
    pdf: fitz.Document, page: fitz.Page
) -> tuple[Image.Image, fitz.Rect] | None:
    candidates = sorted(
        page.get_images(full=True),
        key=lambda item: int(item[2]) * int(item[3]),
        reverse=True,
    )
    for candidate in candidates:
        xref, width, height = int(candidate[0]), int(candidate[2]), int(candidate[3])
        if width * height < 100_000:
            continue
        rectangles = page.get_image_rects(xref)
        if not rectangles:
            continue
        payload = pdf.extract_image(xref)
        image = Image.open(io.BytesIO(payload["image"]))
        image.load()
        return image, rectangles[0]
    return None


def _extract_pdf(
    pdf: fitz.Document, job_id: str | None = None
) -> ExtractedDocument:
    try:
        table_rows = extract_pdf_table_rows(pdf)
        pages: list[str] = []
        methods: set[str] = set()
        warnings: list[str] = []
        for page_number in range(len(pdf)):
            memory_snapshot(
                "pdf_page_start",
                job_id,
                page=page_number + 1,
                page_count=len(pdf),
            )
            page = pdf[page_number]
            direct_text = page.get_text("text", sort=True).strip()
            if _meaningful_digital_text(direct_text):
                pages.append(f"[[PAGE:{page_number + 1}]]\n{direct_text}")
                methods.add("pdf_text")
                del page
                memory_snapshot(
                    "pdf_page_digital_complete",
                    job_id,
                    page=page_number + 1,
                )
                continue
            pixmap = None
            image = None
            image_rect = page.rect
            try:
                memory_snapshot(
                    "pdf_page_render_start",
                    job_id,
                    page=page_number + 1,
                )
                embedded = _largest_embedded_page_image(pdf, page)
                if embedded:
                    image, image_rect = embedded
                    rendered_width, rendered_height = image.size
                else:
                    pixmap = page.get_pixmap(
                        matrix=fitz.Matrix(1.6, 1.6),
                        colorspace=fitz.csGRAY,
                        alpha=False,
                    )
                    rendered_width, rendered_height = pixmap.width, pixmap.height
                    image = Image.frombytes(
                        "L", (pixmap.width, pixmap.height), pixmap.samples
                    )
                text, method, ocr_words, ocr_size = _ocr_image(image)
                memory_snapshot(
                    "pdf_page_ocr_complete",
                    job_id,
                    page=page_number + 1,
                    rendered_width=rendered_width,
                    rendered_height=rendered_height,
                )
                combined = _merge_page_text(direct_text, text.strip())
                if not table_rows and ocr_words:
                    scale_x = float(image_rect.width) / ocr_size[0]
                    scale_y = float(image_rect.height) / ocr_size[1]
                    scaled_words = [
                        {
                            "x0": image_rect.x0 + word["x0"] * scale_x,
                            "y0": image_rect.y0 + word["y0"] * scale_y,
                            "x1": image_rect.x0 + word["x1"] * scale_x,
                            "y1": image_rect.y0 + word["y1"] * scale_y,
                            "text": word["text"],
                        }
                        for word in ocr_words
                    ]
                    table_rows.extend(
                        extract_visual_word_rows(
                            scaled_words, float(page.rect.width), page_number + 1
                        )
                    )
                pages.append(f"[[PAGE:{page_number + 1}]]\n{combined}")
                if direct_text:
                    methods.add("pdf_text")
                methods.add(method)
                warnings.append(
                    f"Página {page_number + 1}: no contenía texto digital suficiente; "
                    "solo esa página fue procesada con OCR."
                )
            except RuntimeError:
                if not direct_text:
                    raise
                pages.append(f"[[PAGE:{page_number + 1}]]\n{direct_text}")
                methods.add("pdf_text")
                warnings.append(
                    f"Página {page_number + 1}: requería OCR, pero no hay un motor "
                    "local disponible; se conservó el texto digital para revisión."
                )
            finally:
                if image is not None:
                    image.close()
                del pixmap
                del page
                memory_snapshot(
                    "pdf_page_resources_released",
                    job_id,
                    page=page_number + 1,
                )
        joined = "\n\n".join(pages)
        method = "+".join(sorted(methods)) if methods else "pdf_empty"
        return ExtractedDocument(
            text=joined,
            method=method,
            page_count=len(pdf),
            warnings=tuple(warnings),
            table_rows=tuple(table_rows),
            expected_product_count=expected_product_count(joined, table_rows),
        )
    finally:
        pdf.close()


def _extract_image(image: Image.Image) -> ExtractedDocument:
    try:
        text, method, words, size = _ocr_image(image)
        rows = extract_visual_word_rows(words, float(size[0]), 1) if words else []
        if not rows:
            rows = extract_known_ocr_text_rows(text)
        return ExtractedDocument(
            text=f"[[PAGE:1]]\n{text.strip()}",
            method=method,
            page_count=1,
            table_rows=tuple(rows),
            expected_product_count=expected_product_count(text, rows),
        )
    finally:
        image.close()


def extract_document_path(
    path: Path, content_type: str, filename: str, job_id: str | None = None
) -> ExtractedDocument:
    if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
        return _extract_pdf(fitz.open(path), job_id)
    return _extract_image(Image.open(path))


def extract_document(
    content: bytes, content_type: str, filename: str
) -> ExtractedDocument:
    if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
        return _extract_pdf(fitz.open(stream=content, filetype="pdf"))
    return _extract_image(Image.open(io.BytesIO(content)))


def expected_product_count(text: str, table_rows: list[dict] | tuple[dict, ...]) -> int:
    match = re.search(
        r"\bTOTAL\s+(?:DE\s+)?(?:ITEMS?|PRODUCTOS?)\s*[:#-]?\s*(\d+)\b",
        text,
        re.IGNORECASE,
    )
    return int(match.group(1)) if match else len(table_rows)


def split_purchase_orders(text: str) -> list[str]:
    matches = list(ORDER_MARKER.finditer(text))
    if len(matches) <= 1:
        return [text.strip()] if text.strip() else []
    return [
        text[match.start() : matches[index + 1].start()].strip()
        if index + 1 < len(matches)
        else text[match.start() :].strip()
        for index, match in enumerate(matches)
    ]


def recognized_header(
    text: str, filename: str | None = None
) -> dict[str, str | list[str] | None]:
    order = ORDER_MARKER.search(text)
    reference = REFERENCE_PATTERN.search(text)
    chain = CHAIN_PATTERN.search(text)
    date_match = DATE_PATTERN.search(text)
    parsed_date = None
    if date_match:
        raw = date_match.group(1)
        for pattern in (
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%Y/%m/%d",
            "%d.%m.%Y",
            "%Y.%m.%d",
        ):
            try:
                parsed_date = datetime.strptime(raw, pattern).date().isoformat()
                break
            except ValueError:
                continue
    candidates: list[str] = []
    if chain:
        candidates.append(chain.group(1).strip())
    for company in COMPANY_PATTERN.finditer(text):
        value = re.sub(r"\s+", " ", company.group(1)).strip(" :-")
        if normalize_identity(value) not in {
            normalize_identity(item) for item in candidates
        }:
            candidates.append(value)
    filename_number = None
    if filename:
        stem = re.sub(r"(?i)\.(?:PDF|PNG|JPE?G|WEBP|TXT)$", "", filename)
        tokens = re.findall(
            r"(?<![A-Z0-9])([A-Z]{1,6}[-_]?\d{4,}|\d{6,})(?![A-Z0-9])", stem.upper()
        )
        if tokens:
            filename_number = tokens[0].replace("_", "-")
    reference_number = reference.group(1).strip() if reference else None
    primary_number = order.group(1).strip() if order else None
    number_source = "document_label" if primary_number else None
    if not primary_number and filename_number and re.search(r"[A-Z]", filename_number):
        primary_number = filename_number
        number_source = "filename_local_reference"
    if not primary_number and reference_number:
        primary_number = reference_number
        number_source = "printed_reference"
    if not primary_number and filename_number:
        primary_number = filename_number
        number_source = "filename_suggestion"
    return {
        "order_number": primary_number,
        "order_number_source": number_source,
        "secondary_reference": (
            reference_number if reference_number != primary_number else None
        ),
        "chain_name": candidates[0] if len(candidates) == 1 else None,
        "chain_candidates": candidates[:5],
        "order_date": parsed_date,
    }


def suggest_chains_from_confirmed_aliases(
    text: str, aliases: list[tuple[str, str, str | None]]
) -> list[str]:
    """Use only chain-scoped, human-confirmed evidence; never globalize a client code."""
    normalized_text = f" {normalize_identity(text)} "
    scores: dict[str, int] = {}
    display_names: dict[str, str] = {}
    for chain_name, source_normalized, detected_code in aliases:
        normalized_chain = normalize_identity(chain_name)
        display_names[normalized_chain] = chain_name
        evidence = 0
        normalized_code = normalize_identity(detected_code or "")
        if normalized_code and re.search(
            rf"(?<![A-Z0-9]){re.escape(normalized_code)}(?![A-Z0-9])",
            normalized_text,
        ):
            evidence += 3
        if len(source_normalized) >= 12 and source_normalized in normalized_text:
            evidence += 2
        if evidence:
            scores[normalized_chain] = scores.get(normalized_chain, 0) + evidence
    if not scores:
        return []
    best = max(scores.values())
    return [
        display_names[chain]
        for chain, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        if score == best
    ][:5]


def normalize_identity(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip().upper()
    return normalized
