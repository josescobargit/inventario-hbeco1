from app.modules.invoices.domain.quick_parser import (
    parse_invoice_blocks,
    parse_quantity_line,
)


def test_parses_multiple_invoice_blocks_and_separators() -> None:
    blocks = parse_invoice_blocks(
        """
        FAC 001-001-000000758
        480.00 TOALLITAS HÚMEDAS ANA X 100 - ACP001
        ----------------
        FAC 001-001-000000759
        120 SHAMPOO ANA REGENEXT 400 ML
        """
    )
    assert [block.invoice_number for block in blocks] == [
        "001-001-000000758",
        "001-001-000000759",
    ]
    assert blocks[0].lines[0].quantity == 480


def test_empty_and_explicit_void_invoice_are_proposed_as_void() -> None:
    blocks = parse_invoice_blocks(
        """
        FAC 001-001-000000760
        ANULADA
        FAC 001-001-000000761
        """
    )
    assert [block.is_void for block in blocks] == [True, True]
    assert all(not block.lines for block in blocks)


def test_invalid_and_fractional_quantities_do_not_break_other_lines() -> None:
    blocks = parse_invoice_blocks(
        """
        FAC 001-001-000000762
        producto sin cantidad
        1.5 PRODUCTO FRACCIONADO
        2 PRODUCTO CORRECTO
        """
    )
    assert blocks[0].lines[0].error
    assert blocks[0].lines[1].error
    assert blocks[0].lines[2].quantity == 2
    assert parse_quantity_line("0 PRODUCTO").error
