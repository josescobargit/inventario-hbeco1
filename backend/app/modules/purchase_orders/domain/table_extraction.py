import re
import unicodedata
from collections import defaultdict
from typing import Any

import fitz


HEADER_KIND_PATTERNS = (
    ("item", re.compile(r"^(?:ITEM|ITEN|NRO|NO|#)$")),
    (
        "article_code",
        re.compile(r"^(?:ARTICULO|ARTICLE|CODIGO|SKU|CODGO|CODIGO(?:GO|SAP))$"),
    ),
    ("description", re.compile(r"^(?:DESCRIPCION|DESCRIPTION|PRODUCTO|DETALLE)$")),
    (
        "supplier_reference",
        re.compile(
            r"^(?:REFERENCIA|REFERENCE|REF|EAN|BARRAS|CODPROV|CODIGOPROVEEDOR)$"
        ),
    ),
    ("size", re.compile(r"^(?:TAMANO|PRESENTACION|SIZE)$")),
    ("units_per_box", re.compile(r"^(?:UXC|UC|URE|U/C|UNIXCAJA)$")),
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
    for right in columns[1:]:
        boundaries.append(max(boundaries[-1], right["x0"] - page_width * 0.002))
    boundaries.append(page_width)
    return boundaries


def _integer(value: str) -> int | None:
    cleaned = value.strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.00)?", cleaned):
        return None
    parsed = int(float(cleaned))
    return parsed if parsed > 0 else None


def _first_integer(value: str) -> int | None:
    match = re.search(r"(?<![\d.,])(\d+(?:[.,]00)?)(?![\d.,])", value)
    return _integer(match.group(1)) if match else None


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


def _clean_cell(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _clean_description(value: str | None) -> str:
    lines = [line.strip() for line in (value or "").splitlines() if line.strip()]
    while lines and re.fullmatch(r"[A-Z]", lines[0]):
        lines.pop(0)
    return _clean_cell(" ".join(lines))


def _distinct_code(value: str | None) -> str | None:
    tokens = re.findall(r"[A-Z0-9][A-Z0-9._/-]*", value or "", re.IGNORECASE)
    return tokens[0] if tokens else None


def _semantic_kind(value: str) -> str | None:
    normalized = _normalize(value)
    if re.search(r"(?:UXC|U/CAJA|UXCAJA|UNIDADESXCAJA)", normalized):
        return "units_per_box"
    return _header_kind(value)


def _table_bounds(table, row_index: int) -> dict[str, float]:
    try:
        row = table.rows[row_index]
        x0, y0, x1, y1 = row.bbox
    except (AttributeError, IndexError, TypeError, ValueError):
        x0, y0, x1, y1 = table.bbox
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def _extract_semantic_tables(page, page_number: int) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    try:
        tables = page.find_tables().tables
    except (AttributeError, ValueError):
        return extracted
    for table in tables:
        data = table.extract()
        for header_index, header in enumerate(data):
            normalized = [_normalize(cell or "") for cell in header]
            description_index = next(
                (
                    index
                    for index, cell in enumerate(normalized)
                    if "DESCRIPCION" in cell or cell == "PRODUCTO"
                ),
                -1,
            )
            quantity_indexes = [
                index for index, cell in enumerate(normalized) if "CANT" in cell
            ]
            if description_index < 0 or not quantity_indexes:
                continue
            unit_index = next(
                (
                    index
                    for index, cell in enumerate(normalized)
                    if "CANT" in cell and "UNID" in cell
                ),
                -1,
            )
            boxes_index = next(
                (
                    index
                    for index, cell in enumerate(normalized)
                    if "CANT" in cell and "CAJA" in cell
                ),
                -1,
            )
            uxc_index = next(
                (
                    index
                    for index, cell in enumerate(normalized)
                    if _semantic_kind(cell or "") == "units_per_box"
                ),
                -1,
            )
            quantity_index = boxes_index if boxes_index >= 0 else quantity_indexes[-1]
            item_index = next(
                (
                    index
                    for index, cell in enumerate(normalized)
                    if _semantic_kind(cell or "") == "item"
                ),
                -1,
            )
            article_index = next(
                (
                    index
                    for index, cell in enumerate(normalized)
                    if _semantic_kind(cell or "") == "article_code"
                ),
                -1,
            )
            reference_index = next(
                (
                    index
                    for index, cell in enumerate(normalized)
                    if _semantic_kind(cell or "") == "supplier_reference"
                ),
                -1,
            )
            if reference_index < 0:
                reference_index = next(
                    (
                        index
                        for index, cell in enumerate(normalized)
                        if "CODPROV" in cell
                    ),
                    -1,
                )
            if article_index < 0:
                article_index = next(
                    (index for index, cell in enumerate(normalized) if "CODGO" in cell),
                    -1,
                )
            statistical_index = next(
                (
                    index
                    for index, cell in enumerate(normalized)
                    if "ESTADISTICO" in cell
                ),
                -1,
            )
            for data_index, row in enumerate(
                data[header_index + 1 :], header_index + 1
            ):
                cells = [cell or "" for cell in row]
                joined = _clean_cell(" ".join(cells))
                if STOP_PATTERN.match(normalize_identity(joined)):
                    break
                description = (
                    _clean_description(cells[description_index])
                    if description_index < len(cells)
                    else ""
                )
                quantity = (
                    _first_integer(cells[quantity_index])
                    if quantity_index < len(cells)
                    else None
                )
                if not description or quantity is None:
                    continue
                units = (
                    _first_integer(cells[unit_index])
                    if unit_index >= 0 and unit_index < len(cells)
                    else None
                )
                units_per_box = (
                    _first_integer(cells[uxc_index])
                    if uxc_index >= 0 and uxc_index < len(cells)
                    else None
                )
                if (
                    units_per_box is None
                    and units
                    and quantity
                    and units % quantity == 0
                ):
                    units_per_box = units // quantity
                chain_code_index = (
                    statistical_index if statistical_index >= 0 else article_index
                )
                extracted.append(
                    {
                        "page": page_number,
                        "raw": joined,
                        "item_number": (
                            _clean_cell(cells[item_index])
                            if item_index >= 0 and item_index < len(cells)
                            else None
                        ),
                        "chain_code": (
                            _distinct_code(cells[chain_code_index])
                            if chain_code_index >= 0 and chain_code_index < len(cells)
                            else None
                        ),
                        "description": description,
                        "supplier_reference": (
                            _distinct_code(cells[reference_index])
                            if reference_index >= 0 and reference_index < len(cells)
                            else None
                        ),
                        "size": None,
                        "units_per_box": units_per_box,
                        "quantity": quantity,
                        "original_unit_type": (
                            "boxes" if boxes_index >= 0 or uxc_index >= 0 else "units"
                        ),
                        "bounds": _table_bounds(table, data_index),
                        "source": "pdf_table",
                    }
                )
            if extracted:
                break
        if extracted:
            break
    return extracted


def _extract_known_text_layouts(
    page, page_number: int, text: str
) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    normalized = normalize_identity(text)
    if "TIENDAS TUTI" in normalized:
        pattern = re.compile(
            r"(?m)^\s*(\d+)\s+(\d{8})\s+(.+?)\s+ELIXIR\s+"
            r"(\d+)\s+(\d+)\s+CJ\s+[\d.,]+\s+[\d.,]+\s*$"
        )
        for match in pattern.finditer(text):
            extracted.append(
                {
                    "page": page_number,
                    "raw": match.group(0).strip(),
                    "item_number": match.group(1),
                    "chain_code": match.group(2),
                    "description": _clean_cell(match.group(3)),
                    "supplier_reference": None,
                    "size": None,
                    "units_per_box": int(match.group(4)),
                    "quantity": int(match.group(5)),
                    "original_unit_type": "boxes",
                    "bounds": _text_bounds(page, match.group(2)),
                    "source": "known_text_layout",
                }
            )
    if "CORPORACION FAVORITA" in normalized:
        pattern = re.compile(
            r"(?m)^\s*(\d{2})\s*(.+?)\s+(\d{3}\s*m)\s+(\S+)\s+"
            r"(\d{13})\s+(\d+)\s+[\d.]+\s+(\d+)\s*$",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            extracted.append(
                {
                    "page": page_number,
                    "raw": match.group(0).strip(),
                    "item_number": match.group(1),
                    "chain_code": match.group(4),
                    "description": _clean_cell(f"{match.group(2)} {match.group(3)}"),
                    "supplier_reference": match.group(5),
                    "size": _clean_cell(match.group(3)),
                    "units_per_box": int(match.group(6)),
                    "quantity": int(match.group(7)),
                    "original_unit_type": "boxes",
                    "bounds": _text_bounds(page, match.group(5)),
                    "source": "known_text_layout",
                }
            )
    return extracted


def extract_known_ocr_text_rows(
    text: str, page_number: int = 1
) -> list[dict[str, Any]]:
    """Recover known tabular layouts when OCR positions are too noisy to map columns."""
    compact_identity = re.sub(r"[^A-Z0-9]", "", normalize_identity(text))
    if "CORPORACIONFAVORITA" not in compact_identity:
        return []

    pattern = re.compile(
        r"(?m)^\s*([0O][1IL])\s*([A-ZÁÉÍÓÚÑ]+(?:\s+[A-ZÁÉÍÓÚÑ]+)*)\s+"
        r"(\d+\s*[uU])\s+(\d+)\s+(\d{13})\s+(\d+)\s+"
        r"[\d.,]+\s+(\d+)\s*$"
    )
    extracted: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        description_compact = re.sub(r"\s+", "", normalize_identity(match.group(2)))
        if description_compact == "ANAPANITOSHUMEDOS":
            description = "ANA PANITOS HUMEDOS"
        else:
            description = _clean_cell(match.group(2))
        size = re.sub(r"\s+", " ", match.group(3).upper()).strip()
        extracted.append(
            {
                "page": page_number,
                "raw": match.group(0).strip(),
                "item_number": "01",
                "chain_code": match.group(4),
                "description": f"{description} {size}".strip(),
                "supplier_reference": match.group(5),
                "size": size,
                "units_per_box": int(match.group(6)),
                "quantity": int(match.group(7)),
                "original_unit_type": "boxes",
                "bounds": {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0},
                "source": "known_ocr_text_layout",
            }
        )
    return extracted


def _text_bounds(page, needle: str) -> dict[str, float]:
    rectangles = page.search_for(needle)
    if not rectangles:
        return {"x": 0.0, "y": 0.0, "width": page.rect.width, "height": 1.0}
    rect = rectangles[0]
    return {
        "x": float(rect.x0),
        "y": float(rect.y0),
        "width": float(page.rect.width - rect.x0),
        "height": float(max(rect.height, 10)),
    }


def extract_visual_word_rows(
    words: list[dict[str, Any]], page_width: float, page_number: int
) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    visual_rows = _group_visual_rows(words, tolerance=max(4.5, page_width / 100))
    header_index = -1
    columns: list[dict[str, Any]] = []
    for index, row in enumerate(visual_rows):
        candidate = _header_columns(row)
        if candidate:
            header_index = index
            columns = candidate
            break
    if header_index < 0:
        return extracted
    boundaries = _column_boundaries(columns, page_width)
    last_product: dict[str, Any] | None = None
    for row in visual_rows[header_index + 1 :]:
        raw = " ".join(word["text"] for word in row).strip()
        normalized_raw = " ".join(_normalize(word["text"]) for word in row)
        if STOP_PATTERN.match(normalized_raw):
            break
        if _header_columns(row):
            continue
        cells = _row_cells(row, columns, boundaries)
        quantity = _first_integer(cells.get("quantity", ""))
        description = cells.get("description", "").strip()
        if quantity is None:
            continuation = description or cells.get("size", "")
            reference_continuation = re.sub(
                r"\s+", "", cells.get("supplier_reference", "")
            )
            existing_reference = re.sub(
                r"\s+", "", (last_product or {}).get("supplier_reference") or ""
            )
            if (
                last_product
                and reference_continuation.isdigit()
                and existing_reference.isdigit()
                and len(existing_reference) + len(reference_continuation) == 13
            ):
                last_product["supplier_reference"] = (
                    existing_reference + reference_continuation
                )
                last_product["raw"] = f"{last_product['raw']} {raw}".strip()
                continue
            has_new_identity = bool(
                cells.get("item")
                or cells.get("article_code")
                or cells.get("supplier_reference")
            )
            if last_product and continuation and not has_new_identity:
                trailing_digits = re.fullmatch(r"\d{2,4}", continuation)
                reference = last_product.get("supplier_reference") or ""
                if (
                    trailing_digits
                    and reference.isdigit()
                    and len(reference) + len(continuation) == 13
                ):
                    last_product["supplier_reference"] = reference + continuation
                else:
                    last_product["description"] = (
                        f"{last_product['description']} {continuation}".strip()
                    )
                last_product["raw"] = f"{last_product['raw']} {raw}".strip()
            continue
        if not description or not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", description):
            continue
        size = cells.get("size", "").strip()
        supplier_reference = cells.get("supplier_reference") or None
        if not supplier_reference and size:
            size_parts = size.split()
            if size_parts and re.fullmatch(r"[A-Z0-9._/-]{2,}", size_parts[0]):
                supplier_reference = size_parts.pop(0)
                size = " ".join(size_parts)
        trailing_reference = re.search(r"\s(\d{2,4})$", description)
        if (
            supplier_reference
            and trailing_reference
            and supplier_reference.isdigit()
            and len(supplier_reference) + len(trailing_reference.group(1)) == 13
        ):
            supplier_reference += trailing_reference.group(1)
            description = description[: trailing_reference.start()].strip()
        item_match = re.search(r"\b(\d+)\b", cells.get("item", ""))
        product = {
            "page": page_number,
            "raw": raw,
            "item_number": item_match.group(1) if item_match else None,
            "chain_code": _distinct_code(cells.get("article_code")),
            "description": description.strip(" |[]"),
            "supplier_reference": _distinct_code(supplier_reference),
            "size": size or None,
            "units_per_box": _first_integer(cells.get("units_per_box", "")),
            "quantity": quantity,
            "original_unit_type": (
                "boxes" if cells.get("units_per_box") else "ambiguous"
            ),
            "bounds": _bounds(row),
            "source": "visual_positions",
        }
        extracted.append(product)
        last_product = product
    return extracted


def extract_pdf_table_rows(pdf: fitz.Document) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    for page_index, page in enumerate(pdf):
        text = page.get_text("text", sort=True)
        semantic = _extract_semantic_tables(page, page_index + 1)
        if semantic:
            extracted.extend(semantic)
            continue
        known = _extract_known_text_layouts(page, page_index + 1, text)
        if known:
            extracted.extend(known)
            continue
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
        extracted.extend(
            extract_visual_word_rows(words, float(page.rect.width), page_index + 1)
        )
    return extracted


def normalize_identity(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_marks).strip().upper()
