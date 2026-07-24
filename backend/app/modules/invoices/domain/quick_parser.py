import re
from dataclasses import dataclass


INVOICE_HEADER = re.compile(
    r"^\s*FAC(?:TURA)?\s*[:#-]?\s*(\d{3}-\d{3}-\d{9})\s*$", re.IGNORECASE
)
QUANTITY_LINE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s+(.+?)\s*$")
SEPARATOR = re.compile(r"^\s*[-–—]+\s*$")


@dataclass(frozen=True)
class ParsedLine:
    quantity: int | None
    description: str
    error: str | None = None


@dataclass(frozen=True)
class ParsedBlock:
    invoice_number: str
    is_void: bool
    lines: tuple[ParsedLine, ...]


def parse_quantity_line(value: str) -> ParsedLine:
    match = QUANTITY_LINE.fullmatch(value)
    if not match:
        return ParsedLine(
            None, value.strip(), "La línea debe iniciar con una cantidad."
        )
    raw_quantity = match.group(1).replace(",", ".")
    number = float(raw_quantity)
    if number <= 0 or not number.is_integer():
        return ParsedLine(
            None,
            match.group(2).strip(),
            "La cantidad debe ser un número entero positivo de unidades.",
        )
    return ParsedLine(int(number), match.group(2).strip())


def parse_invoice_blocks(value: str) -> list[ParsedBlock]:
    blocks: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for raw in value.splitlines():
        header = INVOICE_HEADER.fullmatch(raw)
        if header:
            if current:
                blocks.append(current)
            current = (header.group(1), [])
            continue
        if current and raw.strip() and not SEPARATOR.fullmatch(raw):
            current[1].append(raw.strip())
    if current:
        blocks.append(current)

    parsed: list[ParsedBlock] = []
    for number, raw_lines in blocks:
        explicit_void = any(line.upper() == "ANULADA" for line in raw_lines)
        product_lines = [line for line in raw_lines if line.upper() != "ANULADA"]
        parsed.append(
            ParsedBlock(
                invoice_number=number,
                is_void=explicit_void or not product_lines,
                lines=tuple(parse_quantity_line(line) for line in product_lines),
            )
        )
    return parsed
