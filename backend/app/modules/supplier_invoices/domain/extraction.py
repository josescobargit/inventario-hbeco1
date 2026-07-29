import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import fitz

from app.modules.purchase_orders.domain.document_extraction import (
    ExtractedDocument,
    extract_document,
    extract_document_path,
)


INVOICE_NUMBER = re.compile(r"\b\d{3}-\d{3}-\d{9}\b")
ACCESS_KEY = re.compile(r"\b\d{40,60}\b")
SUPPLIER_CODE = re.compile(r"^[A-Z][A-Z0-9._/-]{5,}$")
NUMBER = re.compile(r"^-?\d[\d,.]*$")
IGNORED_DESCRIPTION_LINES = {
    "CODIGO PRINCIPAL",
    "PRECIO UNITARIO",
    "PRECIO TOTAL",
    "DESCRIPCION",
    "CODIGO DE BARRAS",
    "DESCUENTO",
    "CANTIDAD",
}


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", plain).strip().upper()


def decimal_value(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = value.strip().replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _table_lines(text: str) -> list[dict]:
    raw_lines = text.splitlines()
    layout_pattern = re.compile(
        r"^\s*([A-Z][A-Z0-9._/-]{5,})\s+([\d.,]+)\s+(.*?)\s+"
        r"(\d{12,14})\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*$"
    )
    layout_rows = []
    for index, raw in enumerate(raw_lines):
        match = layout_pattern.match(raw)
        if not match:
            continue
        description = re.sub(r"\s+", " ", match.group(3)).strip()
        if not description:
            fragments = []
            for adjacent in (index - 1, index + 1):
                if 0 <= adjacent < len(raw_lines):
                    fragment = re.sub(r"\s+", " ", raw_lines[adjacent]).strip()
                    if fragment and not re.search(r"\d{12,14}", fragment):
                        fragments.append(fragment)
            description = " ".join(fragments)
        layout_rows.append(
            {
                "line_number": len(layout_rows) + 1,
                "supplier_code": match.group(1),
                "barcode": match.group(4),
                "description": description,
                "quantity": int(decimal_value(match.group(2)) or 0),
                "unit_price": decimal_value(match.group(5)),
                "discount": decimal_value(match.group(6)),
                "line_total": decimal_value(match.group(7)),
            }
        )
    if layout_rows:
        return layout_rows

    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_lines]
    lines = [line for line in lines if line and not line.startswith("[[PAGE:")]
    extracted: list[dict] = []
    for index, candidate in enumerate(lines):
        code = candidate.upper()
        if not SUPPLIER_CODE.fullmatch(code) or code in {
            "PRODUCCION",
            "INFORMACION",
            "ADICIONAL",
        }:
            continue
        if index < 3 or index + 3 >= len(lines):
            continue
        quantity = decimal_value(lines[index - 1])
        unit_price = decimal_value(lines[index - 2])
        discount = decimal_value(lines[index + 1])
        line_total = decimal_value(lines[index + 2])
        barcode = re.sub(r"\D", "", lines[index + 3])
        if (
            quantity is None
            or unit_price is None
            or discount is None
            or line_total is None
            or len(barcode) not in {12, 13, 14}
        ):
            continue
        description_parts = []
        cursor = index - 3
        while cursor >= 0 and len(description_parts) < 3:
            value = lines[cursor]
            normalized = normalize(value)
            if NUMBER.fullmatch(value) or normalized in IGNORED_DESCRIPTION_LINES:
                break
            if re.search(r"[A-ZÁÉÍÓÚÑ]", value, re.IGNORECASE):
                description_parts.append(value)
                cursor -= 1
                continue
            break
        description = " ".join(reversed(description_parts)).strip()
        if not description:
            continue
        extracted.append(
            {
                "line_number": len(extracted) + 1,
                "supplier_code": code,
                "barcode": barcode,
                "description": description,
                "quantity": int(quantity),
                "unit_price": unit_price,
                "discount": discount,
                "line_total": line_total,
            }
        )
    return extracted


def _row_amount(pdf: fitz.Document, label: str) -> Decimal | None:
    expected = normalize(label)
    for page in pdf:
        words = page.get_text("words", sort=True)
        rows: dict[int, list[tuple]] = {}
        for word in words:
            rows.setdefault(round(float(word[1]) / 3), []).append(word)
        for row in rows.values():
            row = sorted(row, key=lambda word: word[0])
            text = normalize(" ".join(str(word[4]) for word in row))
            if expected not in text:
                continue
            numbers = [
                decimal_value(str(word[4]))
                for word in row
                if decimal_value(str(word[4])) is not None
            ]
            if numbers:
                return numbers[-1]
    return None


def _company_candidates(lines: list[str]) -> list[str]:
    result = []
    for line in lines:
        cleaned = re.sub(r"\s+", " ", line).strip()
        if not cleaned or len(cleaned) > 200:
            continue
        normalized = normalize(cleaned)
        if re.search(r"\b(?:S\.?A\.?S?\.?|CIA\.?\s*LTDA\.?)\b", normalized):
            cleaned = re.sub(
                r"\s+\d{2}/\d{2}/\d{4}.*$|^RAZ[ÓO]N SOCIAL / NOMBRES Y APELLIDOS:\s*",
                "",
                cleaned,
                flags=re.IGNORECASE,
            ).strip()
            if normalize(cleaned) not in {"FACTURA"} and cleaned not in result:
                result.append(cleaned)
    return result


def supplier_result_from_extracted(
    extracted: ExtractedDocument, pdf: fitz.Document | None
) -> dict:
    text = extracted.text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    invoice_match = INVOICE_NUMBER.search(text)
    access_keys = ACCESS_KEY.findall(text)
    authorization = max(access_keys, key=len, default=None)
    supplier_ruc = (
        authorization[10:23] if authorization and len(authorization) >= 23 else None
    )
    standalone_rucs = re.findall(r"(?<!\d)(\d{13})(?!\d)", text)
    if not supplier_ruc and standalone_rucs:
        supplier_ruc = standalone_rucs[0]
    buyer_ruc = next(
        (value for value in standalone_rucs if value != supplier_ruc), None
    )
    companies = _company_candidates(lines)
    supplier_name = companies[0] if companies else "Proveedor por confirmar"
    buyer_name = next(
        (
            company
            for company in companies[1:]
            if normalize(company) != normalize(supplier_name)
        ),
        None,
    )
    dates = re.findall(r"\b(\d{2}/\d{2}/\d{4})\b", text)
    issued_at = (
        datetime.strptime(dates[0], "%d/%m/%Y").date().isoformat() if dates else None
    )
    return {
        "supplier_ruc": supplier_ruc,
        "supplier_name": supplier_name,
        "invoice_number": invoice_match.group(0) if invoice_match else None,
        "issued_at": issued_at,
        "authorization_number": authorization,
        "buyer_name": buyer_name,
        "buyer_ruc": buyer_ruc,
        "subtotal": _row_amount(pdf, "SUBTOTAL SIN IMPUESTOS") if pdf else None,
        "tax": _row_amount(pdf, "IVA 15%") if pdf else None,
        "total": _row_amount(pdf, "VALOR TOTAL") if pdf else None,
        "extraction_method": extracted.method,
        "page_count": extracted.page_count,
        "lines": _table_lines(text),
        "warnings": list(extracted.warnings),
    }


def extract_supplier_invoice(content: bytes, content_type: str, filename: str) -> dict:
    extracted = extract_document(content, content_type, filename)
    pdf = (
        fitz.open(stream=content, filetype="pdf")
        if content_type == "application/pdf"
        else None
    )
    try:
        return supplier_result_from_extracted(extracted, pdf)
    finally:
        if pdf is not None:
            pdf.close()


def extract_supplier_invoice_path(path: Path, content_type: str, filename: str) -> dict:
    extracted = extract_document_path(path, content_type, filename)
    pdf = fitz.open(path) if content_type == "application/pdf" else None
    try:
        return supplier_result_from_extracted(extracted, pdf)
    finally:
        if pdf is not None:
            pdf.close()
