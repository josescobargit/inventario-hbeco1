from io import BytesIO

from openpyxl import Workbook

from app.modules.stock_imports.domain.csv_parser import (
    parse_stock_csv,
    parse_stock_xlsx,
)


def test_valid_csv_is_parsed() -> None:
    rows, errors = parse_stock_csv(b"SKU,Producto,Stock_Fisico\nAE001,Shampoo,24\n")
    assert not errors
    assert rows[0].sku == "AE001"
    assert rows[0].physical_confirmed == 24


def test_duplicate_and_decimal_are_reported_by_row() -> None:
    rows, errors = parse_stock_csv(b"SKU,Stock_Fisico\nAE001,2.5\nAE002,4\nAE002,5\n")
    assert len(rows) == 1
    assert [(error.row, error.column) for error in errors] == [
        (2, "Stock_Fisico"),
        (4, "SKU"),
    ]


def test_xlsx_uses_the_same_validation_contract() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["SKU", "Producto", "Stock_Fisico"])
    sheet.append(["AE001", "Shampoo", 36])
    content = BytesIO()
    workbook.save(content)

    rows, errors = parse_stock_xlsx(content.getvalue())

    assert not errors
    assert rows[0].physical_confirmed == 36
