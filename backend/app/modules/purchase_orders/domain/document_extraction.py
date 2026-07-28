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

from app.modules.purchase_orders.domain.table_extraction import (
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
    if max(prepared.size) < 1800:
        scale = 1800 / max(prepared.size)
        prepared = prepared.resize(
            (int(prepared.width * scale), int(prepared.height * scale)),
            Image.Resampling.LANCZOS,
        )
    prepared = ImageOps.autocontrast(prepared, cutoff=1)
    prepared = ImageEnhance.Contrast(prepared).enhance(1.45)
    return prepared.filter(ImageFilter.SHARPEN)


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
    result, _elapsed = RapidOCR()(np.asarray(image.convert("RGB")))
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


def _ocr_image(
    image: Image.Image,
) -> tuple[str, str, list[dict], tuple[int, int]]:
    prepared = _prepare_image(image)
    if shutil.which("tesseract"):
        try:
            osd = pytesseract.image_to_osd(
                prepared, output_type=pytesseract.Output.DICT
            )
            rotation = int(osd.get("rotate", 0))
            if rotation:
                prepared = prepared.rotate(rotation, expand=True)
        except (pytesseract.TesseractError, ValueError):
            pass
        return (
            pytesseract.image_to_string(prepared, lang="spa+eng"),
            "ocr_tesseract_local",
            [],
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


def extract_document(
    content: bytes, content_type: str, filename: str
) -> ExtractedDocument:
    if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
        pdf = fitz.open(stream=content, filetype="pdf")
        table_rows = extract_pdf_table_rows(pdf)
        pages: list[str] = []
        methods: set[str] = set()
        warnings: list[str] = []
        for page_number, page in enumerate(pdf):
            direct_text = page.get_text("text", sort=True).strip()
            if _is_usable_order_text(direct_text):
                pages.append(f"[[PAGE:{page_number + 1}]]\n{direct_text}")
                methods.add("pdf_text")
                continue
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            try:
                text, method, ocr_words, ocr_size = _ocr_image(image)
            except RuntimeError:
                if not direct_text:
                    raise
                pages.append(f"[[PAGE:{page_number + 1}]]\n{direct_text}")
                methods.add("pdf_text")
                warnings.append(
                    f"Página {page_number + 1}: requería OCR, pero no hay un motor "
                    "local disponible; se conservó el texto digital para revisión."
                )
                continue
            combined = _merge_page_text(direct_text, text.strip())
            if not table_rows and ocr_words:
                scale_x = float(page.rect.width) / ocr_size[0]
                scale_y = float(page.rect.height) / ocr_size[1]
                scaled_words = [
                    {
                        "x0": word["x0"] * scale_x,
                        "y0": word["y0"] * scale_y,
                        "x1": word["x1"] * scale_x,
                        "y1": word["y1"] * scale_y,
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
                f"Página {page_number + 1}: el texto digital no contenía una estructura "
                "de OC suficiente; fue procesada con OCR y se combinaron ambos resultados."
            )
        method = "+".join(sorted(methods)) if methods else "pdf_empty"
        return ExtractedDocument(
            text="\n\n".join(pages),
            method=method,
            page_count=len(pdf),
            warnings=tuple(warnings),
            table_rows=tuple(table_rows),
            expected_product_count=expected_product_count(
                "\n\n".join(pages), table_rows
            ),
        )
    image = Image.open(io.BytesIO(content))
    text, method, words, size = _ocr_image(image)
    rows = extract_visual_word_rows(words, float(size[0]), 1) if words else []
    return ExtractedDocument(
        text=f"[[PAGE:1]]\n{text.strip()}",
        method=method,
        page_count=1,
        table_rows=tuple(rows),
        expected_product_count=expected_product_count(text, rows),
    )


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
