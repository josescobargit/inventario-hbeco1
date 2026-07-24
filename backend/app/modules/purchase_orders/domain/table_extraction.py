import re
import unicodedata
from collections import defaultdict
from typing import Any

import fitz


HEADER_KIND_PATTERNS = (
    ("item", re.compile(r"^(?:ITEM|ITEN|NRO|NO|#)$")),
    ("article_code", re.compile(r"^(?:ARTICULO|ARTICLE|CODIGO|SKU)$")),
    ("description", re.compile(r"^(?:DESCRIPCION|DESCRIPTION|PRODUCTO|DETALLE)$")),
    ("supplier_reference", re.compile(r"^(?:REFERENCIA|REFERENCE|REF|EAN|BARRAS)$")),
    ("size", re.compile(r"^(?:TAMANO|PRESENTACION|SIZE)$")),
    ("units_per_box", re.compile(r"^(?:UXC|UC|U/C|UNIXCAJA)$")),
    ("quantity", re.compile(r"^(?:CANTIDAD|CANT|QTY|SOLICITADO|PEDIDO)$")),
    ("cost", re.compile(r"^(?:COSTO|PRECIO|VALOR|COST)$")),
)
STOP_PATTERN = re.compile(
    r"^(?:TOTAL(?:\s+DE)?\s+(?:ITEMS?|PRODUCTOS?)|SUBTOTAL|IVA|TOTAL|"
    r"OBSERVACIONES?|CONDICIONES?\s+COMERCIALES?|FIRMAS?)\b"
)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"[^A-Z0-9/#]+", "", without_marks.upper())


def _header_kind(value: str) -> str | None:
    normalized = _normalize(value)
    for kind, pattern in HEADER_KIND_PATTERNS:
        if pattern.match(normalized):
            return kind
    return None


def _group_visual_rows(words: list[dict[str, Any]], tolerance: float = 4.5):
    rows: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (item["y0"], item["x0"])):
        center_y = (word["y0"] + word["y1"]) / 2
        matching = next(
            (
                row
                for row in reversed(rows[-4:])
                if abs(
                    center_y
                    - sum((item["y0"] + item["y1"]) / 2 for item in row) / len(row)
                )
                <= tolerance
            ),
            None,
        )
        if matching is None:
            rows.append([word])
        else:
            matching.append(word)
    return [sorted(row, key=lambda item: item["x0"]) for row in rows]


def _header_columns(row: list[dict[str, Any]]) -> list[dict[str, Any]]:
    columns = []
    seen: set[str] = set()
    for word in row:
        kind = _header_kind(word["text"])
        if kind and kind not in seen:
            columns.append(
                {
                    "kind": kind,
                    "center": (word["x0"] + word["x1"]) / 2,
                    "x0": word["x0"],
                    "x1": word["x1"],
                }
            )
            seen.add(kind)
    kinds = {column["kind"] for column in columns}
    if "description" not in kinds or "quantity" not in kinds or len(kinds) < 3:
        return []
    return sorted(columns, key=lambda column: column["center"])


def _column_boundaries(columns: list[dict[str, Any]], page_width: float):
    boundaries = [0.0]
    for left, right in zip(columns, columns[1:]):
        boundaries.append((left["center"] + right["center"]) / 2)
    boundaries.append(page_width)
    return boundaries


def _integer(value: str) -> int | None:
    cleaned = value.strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.00)?", cleaned):
        return None
    parsed = int(float(cleaned))
    return parsed if parsed > 0 else None


def _row_cells(
    row: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    boundaries: list[float],
) -> dict[str, str]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for word in row:
        center = (word["x0"] + word["x1"]) / 2
        for index, column in enumerate(columns):
            if boundaries[index] <= center < boundaries[index + 1]:
                grouped[column["kind"]].append(word["text"])
                break
    return {kind: " ".join(values).strip() for kind, values in grouped.items()}


def _bounds(row: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "x": min(word["x0"] for word in row),
        "y": min(word["y0"] for word in row),
        "width": max(word["x1"] for word in row) - min(word["x0"] for word in row),
        "height": max(word["y1"] for word in row) - min(word["y0"] for word in row),
    }


def extract_pdf_table_rows(pdf: fitz.Document) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    for page_index, page in enumerate(pdf):
        words = [
            {
                "x0": float(word[0]),
                "y0": float(word[1]),
                "x1": float(word[2]),
                "y1": float(word[3]),
                "text": str(word[4]),
            }
            for word in page.get_text("words", sort=True)
            if str(word[4]).strip()
        ]
        visual_rows = _group_visual_rows(words)
        header_index = -1
        columns: list[dict[str, Any]] = []
        for index, row in enumerate(visual_rows):
            candidate = _header_columns(row)
            if candidate:
                header_index = index
                columns = candidate
                break
        if header_index < 0:
            continue
        boundaries = _column_boundaries(columns, page.rect.width)
        last_product: dict[str, Any] | None = None
        for row in visual_rows[header_index + 1 :]:
            raw = " ".join(word["text"] for word in row).strip()
            normalized_raw = " ".join(_normalize(word["text"]) for word in row)
            if STOP_PATTERN.match(normalized_raw):
                break
            if _header_columns(row):
                continue
            cells = _row_cells(row, columns, boundaries)
            quantity = _integer(cells.get("quantity", ""))
            description = cells.get("description", "").strip()
            if quantity is None:
                continuation = description or cells.get("size", "")
                has_new_identity = bool(
                    cells.get("item")
                    or cells.get("article_code")
                    or cells.get("supplier_reference")
                )
                if last_product and continuation and not has_new_identity:
                    last_product["description"] = (
                        f"{last_product['description']} {continuation}".strip()
                    )
                    last_product["raw"] = f"{last_product['raw']} {raw}".strip()
                    bounds = _bounds(row)
                    last_product["bounds"]["height"] = (
                        bounds["y"] + bounds["height"] - last_product["bounds"]["y"]
                    )
                continue
            if not description or not re.search(
                r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", description
            ):
                continue
            product = {
                "page": page_index + 1,
                "raw": raw,
                "item_number": cells.get("item") or None,
                "chain_code": cells.get("article_code") or None,
                "description": description,
                "supplier_reference": cells.get("supplier_reference") or None,
                "size": cells.get("size") or None,
                "units_per_box": _integer(cells.get("units_per_box", "")),
                "quantity": quantity,
                "original_unit_type": (
                    "boxes" if cells.get("units_per_box") else "ambiguous"
                ),
                "bounds": _bounds(row),
                "source": "pdf_positions",
            }
            extracted.append(product)
            last_product = product
    return extracted
