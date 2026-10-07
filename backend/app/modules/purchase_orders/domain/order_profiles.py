"""Recognition profiles learned from verified customer purchase-order formats."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime


def _identity(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", plain).strip().upper()


def _date(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    for pattern in (
        "%Y-%m-%d",
        "%Y.%m.%d",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d.%m.%Y",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(cleaned, pattern).date().isoformat()
        except ValueError:
            continue
    months = {
        "ENE": 1,
        "FEB": 2,
        "MAR": 3,
        "ABR": 4,
        "MAY": 5,
        "JUN": 6,
        "JUL": 7,
        "AGO": 8,
        "SEP": 9,
        "OCT": 10,
        "NOV": 11,
        "DIC": 12,
    }
    match = re.fullmatch(r"(\d{1,2})/([A-Z]{3})/(\d{4})", cleaned.upper())
    if match and match.group(2) in months:
        return (
            datetime(int(match.group(3)), months[match.group(2)], int(match.group(1)))
            .date()
            .isoformat()
        )
    return None


PROFILES = (
    {
        "canonical": "CORPORACIÓN FAVORITA",
        "legal": "CORPORACION FAVORITA C.A.",
        "ruc": "1790016919001",
        "aliases": ("CORPORACION FAVORITA",),
        "type": "ORDEN COMPRA INIC. INDIVIDUAL",
        "order": r"ORDEN\s+COMPRA\s+INIC\.\s+INDIVIDUAL\s+\d+\s*:\s*([\d ]{8,})",
        "date": r"FECHA\s+ELABORA\s*:\s*(\d{1,2}/[A-Z]{3}/\d{4})",
    },
    {
        "canonical": "CORPORACIÓN EL ROSADO",
        "legal": "CORPORACION EL ROSADO S.A.",
        "ruc": None,
        "aliases": ("CORPORACION EL ROSADO",),
        "type": "NUMERO DE ORDEN",
        "order": r"NUMERO\s+DE\s+ORDEN\s+(\d{6,})",
        "date": r"FECHA\s+DEL\s+(\d{4}\.\d{2}\.\d{2})\s+FECHA\s+DE",
    },
    {
        "canonical": "FARCOMED",
        "legal": "FARMACIAS Y COMISARIATOS DE MEDICINAS S.A.",
        "ruc": "1790710319001",
        "aliases": (
            "FARCOMED VIRTUAL",
            "FARMACIAS Y COMISARIATOS DE MEDICINAS",
            "CORPORACION GPF",
        ),
        "type": "PEDIDO A PROVEEDOR",
        "order": r"ORDEN\s+PEDIDO\s+NO\.?\s*:\s*(\d{5,})",
        "date": r"EMISI[OÓ]N\s*:\s*(\d{1,2}/\d{1,2}/\d{4})",
    },
    {
        "canonical": "INDUSTRIAL DANEC",
        "legal": "INDUSTRIAL DANEC S A",
        "ruc": "1790040968001",
        "aliases": ("INDUSTRIAL DANEC",),
        "type": "ORDEN DE COMPRA",
        "order": r"ORDEN\s+DE\s+COMPRA\s*(?:N(?:[º°]|O\.?|UMERO)?\s*[:#.-]?\s*)?(\d{6,})",
        "date": r"FECHA\s+DE\s+ORDEN\s*:\s*(\d{1,2}/\d{1,2}/\d{2,4})",
    },
    {
        "canonical": "GERARDO ORTIZ",
        "legal": "GERARDO ORTIZ E HIJOS CIA",
        "ruc": None,
        "aliases": ("GERARDO ORTIZ E HIJOS",),
        "type": "PED. COMPRA",
        "order": r"PED\.\s*COMPRA\s*:\s*(\d{6,})",
        "date": r"FECHA\s+DE\s+ENV[IÍ]O\s*:\s*(\d{4}-\d{2}-\d{2})",
    },
    {
        "canonical": "TIA",
        "legal": "TIENDAS INDUSTRIALES ASOCIADAS (TIA) S.A.",
        "ruc": "0990017514001",
        "aliases": ("TIENDAS INDUSTRIALES ASOCIADAS", "TIA S.A."),
        "type": "ORDEN DE COMPRA",
        "order": r"ORDEN\s+DE\s+COMPRA\s+N?[º°]?\s*(\d{6,})",
        "date": r"FECHA\s+DE\s+LA\s+ORDEN\s*:\s*(\d{4}-\d{2}-\d{2})",
    },
    {
        "canonical": "TUTI",
        "legal": "TIENDAS TUTI TTDE S.A.",
        "ruc": "0993152161001",
        "aliases": ("TIENDAS TUTI",),
        "type": "ORDEN DE COMPRA",
        "order": r"ORDEN\s+DE\s+COMPRA\s+(\d{6,})",
        "date": r"FECHA\s+DEL\s+DOCUMENTO\s+(\d{1,2}\.\d{1,2}\.\d{4})",
    },
    {
        "canonical": "LIRIS DEL PORTAL",
        "legal": "LIRIS S.A.",
        "ruc": "0990865477001",
        "aliases": ("LIRIS S.A", "DELPORTAL"),
        "type": "ORDEN DE COMPRA",
        "order": r"ORDEN\s+DE\s+COMPRA\s+(OC[_-]\d+)",
        "date": r"FECHA\s+DE\s+PEDIDO\.*\s*:\s*(\d{1,2}/\d{1,2}/\d{2,4})",
    },
)


def recognize_known_order(text: str) -> dict[str, object] | None:
    """Return a canonical header only when the document itself supplies evidence."""
    normalized = _identity(text)
    compact = re.sub(r"[^A-Z0-9]", "", normalized)
    profile = next(
        (item for item in PROFILES if item["ruc"] and str(item["ruc"]) in text),
        None,
    )
    if not profile:
        profile = next(
            (
                item
                for item in PROFILES
                if any(
                    alias in normalized or re.sub(r"[^A-Z0-9]", "", alias) in compact
                    for alias in item["aliases"]
                )
            ),
            None,
        )
    if not profile:
        return None
    order_match = re.search(str(profile["order"]), normalized, re.IGNORECASE)
    date_match = re.search(str(profile["date"]), normalized, re.IGNORECASE)
    order_number = None
    if order_match:
        order_number = re.sub(r"\s+", "", order_match.group(1))
    order_date = _date(date_match.group(1) if date_match else None)
    if profile["canonical"] == "TUTI" and not order_number:
        fallback = re.search(r"CITA\s+PARA\s+ENTREGA\s*:?\s*(\d{6,})", normalized)
        order_number = fallback.group(1) if fallback else None
    if profile["canonical"] == "CORPORACIÓN EL ROSADO":
        if not order_number:
            fallback = re.search(r"NUMERODEORDEN\s*(\d{6,})", compact)
            order_number = fallback.group(1) if fallback else None
        if not order_date:
            fallback = re.search(r"FECHADEL\s*(\d{4}\.\d{2}\.\d{2})", normalized)
            order_date = _date(fallback.group(1) if fallback else None)
    missing = []
    if not order_number:
        missing.append("Número de OC pendiente")
    if not order_date:
        missing.append("Fecha de OC pendiente")
    return {
        "order_number": order_number,
        "order_number_source": "document_profile" if order_number else None,
        "secondary_reference": None,
        "chain_name": profile["canonical"],
        "chain_candidates": [profile["canonical"]],
        "order_date": order_date,
        "document_type": profile["type"],
        "buyer_legal_name": profile["legal"],
        "buyer_ruc": (
            profile["ruc"] if profile["ruc"] and str(profile["ruc"]) in text else None
        ),
        "confidence": "ALTA" if order_number and order_date else "MEDIA",
        "status": "OK" if not missing else "REVISAR",
        "pending_fields": missing,
    }


def split_known_orders(text: str) -> list[str] | None:
    """Split true multi-order files and collapse repeated page headers for one OC."""
    normalized = _identity(text)
    if "CORPORACION EL ROSADO" in normalized:
        starts = [
            match.start() for match in re.finditer(r"(?im)^CORPORACION EL ROSADO", text)
        ]
        if len(starts) > 1:
            return [
                text[start : starts[index + 1]].strip()
                if index + 1 < len(starts)
                else text[start:].strip()
                for index, start in enumerate(starts)
            ]
    known = recognize_known_order(text)
    if known and known["chain_name"] == "LIRIS DEL PORTAL":
        return [text.strip()] if text.strip() else []
    return None
