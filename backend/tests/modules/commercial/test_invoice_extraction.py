"""Invoice extraction, contradictory evidence and optional real-file regressions.

REAL_INVOICE_DIR=/absolute/path/Downloads PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/modules/commercial/test_invoice_extraction.py -q
Original customer files remain outside the repository.
"""

import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.commercial.ingestion import parse_file
from app.modules.commercial.invoice_extraction import (
    document_currency,
    invoice_header,
    invoice_text_rows,
    validate_invoice_amounts,
)
from app.modules.commercial.normalization import normalize, number
from app.modules.commercial.processing import recognition_evidence


def invoice_text(extra="", reference="Orden de Compra no. 26003023"):
    return f"""[[PAGE:1]]
FACTURA No.001-001-000001016
Emisor: CORPORACION FAVORITA C.A.
RUC: 1790016919001
Número de Autorización:
1609202601179323070000120010010000010162291993513
Fecha y hora de Autorización: 17/09/2026 08:39:48
Razón Social: INDUSTRIAL DANEC S.A. RUC/CI: 1790040968001
Dirección: Quito
Fecha Emisión: 16/09/2026
Código Cantidad Descripción Detalles Precio Descuento Total
Principal Adicionales Unitario
AR001 10.00 SHAMPOO ANA 3.0000 $2.00 $28.00
REGENEXT 400 ML.
AE003 2.00 PACK SH + AC ANA 6.5000 $0.00 $13.00
ELIXIR ROMERO 370 ML.
Información Adicional Subtotal Sin Impuestos: $41.00
Descripción {reference}
Descuentos: $2.00
Subtotal No Objeto IVA: $99.00
IVA 15%: $6.15
IVA 5%: $0.00
Valor Total: $47.15
{extra}
"""


def catalog_product(sku="AR001", name="SHAMPOO ANA REGENEXT 400 ML."):
    return SimpleNamespace(
        id=uuid.uuid4(),
        sku=sku,
        name=name,
        units_per_box=12,
        category="Capilar",
        barcode=None,
        contifico_aux_code=None,
    )


def test_buyer_is_not_issuer_and_emission_is_not_authorization_date():
    header = invoice_header(invoice_text())
    assert header["chain"] == "INDUSTRIAL DANEC"
    assert header["buyer_ruc"] == "1790040968001"
    assert header["buyer_legal_name"] == "INDUSTRIAL DANEC S.A."
    assert header["date"] == "2026-09-16"
    assert header["invoice_number"] == "001-001-000001016"
    assert header["order_number"] == "26003023"
    assert header["document_subtotal"] == "41.00"
    assert header["document_discount"] == "2.00"
    # A "Subtotal No Objeto IVA" is a tax base, never another tax amount.
    assert header["document_tax"] == "6.15"
    assert header["document_total"] == "47.15"
    assert header["document_issues"] == []
    assert header["monetary_evidence"]["document_total"]


def test_recipient_specific_label_takes_priority_over_issuer_legal_label():
    text = invoice_text().replace(
        "Emisor: CORPORACION FAVORITA C.A.", "Razón Social: CORPORACION FAVORITA C.A."
    )
    text = text.replace(
        "Razón Social: INDUSTRIAL DANEC",
        "Razón Social / Nombres y apellidos: INDUSTRIAL DANEC",
    )
    assert invoice_header(text)["chain"] == "INDUSTRIAL DANEC"


def test_unknown_buyer_preserves_legal_name_and_never_uses_known_issuer():
    text = invoice_text().replace(
        "INDUSTRIAL DANEC S.A. RUC/CI: 1790040968001",
        "OTRO CLIENTE S.A. RUC/CI: 0991234567001",
    )
    header = invoice_header(text)
    assert header["chain"] is None
    assert header["buyer_legal_name"] == "OTRO CLIENTE S.A."
    assert header["buyer_ruc"] == "0991234567001"
    assert len(invoice_text_rows(text)) == 2


def test_ruc_priority_keeps_conflicting_legal_name_reviewable():
    text = invoice_text().replace(
        "INDUSTRIAL DANEC S.A. RUC/CI", "CORPORACION FAVORITA C.A. RUC/CI"
    )
    header = invoice_header(text)
    assert header["chain"] == "INDUSTRIAL DANEC"
    assert header["document_issues"] == [
        "RUC y razón social del comprador identifican cadenas diferentes"
    ]


@pytest.mark.parametrize(
    "reference,expected",
    [
        ("Orden de Compra no. CP143221 1417 - TIENDA CORAL", "CP143221"),
        ("Orden de Compra no. MA001426 GERARDO ORTIZ", "MA001426"),
        ("Orden de Compra no . 6974083 FARCOMED", "6974083"),
        ("Orden de compra no. 50 : 100 6253 88996 FAVORITA", "100625388996"),
        ("Orden de Compra no. OC_005889797 LIRIS", "OC_005889797"),
        ("Orden de Compra no. 005884445 LIRIS", "005884445"),
        ("Orden de Compra no. ?4617943860? ROSADO", None),
    ],
)
def test_explicit_order_reference_preserves_alphanumeric_and_grouped_digits(
    reference, expected
):
    assert invoice_header(invoice_text(reference=reference))["order_number"] == expected


def test_contradictory_order_numbers_are_not_chosen_by_first_occurrence():
    header = invoice_header(invoice_text("Orden de Compra no. 26003024"))
    assert header["order_number"] is None
    assert header["document_issues"] == ["Más de una referencia de OC en la factura"]
    assert len(invoice_text_rows(invoice_text())) == 2


def test_missing_invoice_number_stays_invoice_and_keeps_other_valid_fields():
    header = invoice_header(
        invoice_text().replace(
            "FACTURA No.001-001-000001016", "FACTURA\nNúmero pendiente"
        )
    )
    assert header["kind"] == "invoice"
    assert header["invoice_number"] is None
    assert header["chain"] == "INDUSTRIAL DANEC"
    assert header["date"] == "2026-09-16"


@pytest.mark.parametrize(
    "extra,state",
    [
        ("ESTADO FACTURA: ANULADA", "anulada"),
        ("FACTURA ANULADA", "anulada"),
        ("Estado: ACTIVA", "activo"),
        ("Factura reemplazada por 001-001-000001017", "reemplazada"),
        ("Condiciones: una factura anulada debe ser reemplazada", "activo"),
    ],
)
def test_only_explicit_administrative_evidence_changes_participation(extra, state):
    assert invoice_header(invoice_text(extra))["status"] == state


def test_replacement_and_conflicting_status_preserve_evidence():
    header = invoice_header(invoice_text("Reemplaza a factura 001-001-000001015"))
    assert header["replaces"] == "001-001-000001015"
    assert header["status"] == "activo"
    assert header["status_evidence"]
    header = invoice_header(invoice_text("Estado: ACTIVA\nEstado: ANULADA"))
    assert header["status"] == "revisar"
    assert "Estados administrativos contradictorios" in header["document_issues"][0]


def test_wrapped_products_keep_all_lines_and_four_decimal_prices():
    rows = invoice_text_rows(invoice_text())
    assert len(rows) == 2
    assert rows[0]["product_name"] == "SHAMPOO ANA REGENEXT 400 ML."
    assert rows[0]["unit_price"] == "3.0000"
    assert rows[0]["discount"] == "2.00"
    assert rows[0]["amount"] == "28.00"
    assert "Página 1" in rows[0]["source_location"]
    assert "REGENEXT 400 ML." in rows[0]["source_text"]
    assert all("Subtotal" not in row["product_name"] for row in rows)


def test_ean_first_description_line_is_not_discarded_as_non_product():
    text = invoice_text().replace("SHAMPOO ANA 3.0000", "7862133169541 - 3.0000")
    text = text.replace("REGENEXT 400 ML.", "SHAMPOO ANA REGENEXT 400 ML.")
    rows = invoice_text_rows(text)
    assert len(rows) == 2
    assert rows[0]["ean"] == "7862133169541"
    assert rows[0]["product_name"] == "SHAMPOO ANA REGENEXT 400 ML."


def test_same_invoice_across_pages_keeps_detail_and_footer_together():
    text = invoice_text().replace("AE003 2.00", "[[PAGE:2]]\nAE003 2.00")
    header = invoice_header(text)
    rows = invoice_text_rows(text)
    assert len(rows) == 2
    assert rows[1]["source_location"].startswith("Página 2")
    assert validate_invoice_amounts(header, rows) == []
    text += "\nFACTURA No.001-001-000001017"
    assert invoice_header(text)["invoice_number"] is None


def test_document_reconciliation_has_one_issue_and_keeps_all_details():
    text = invoice_text().replace(
        "Subtotal Sin Impuestos: $41.00", "Subtotal Sin Impuestos: $42.00"
    )
    rows = invoice_text_rows(text)
    issues = validate_invoice_amounts(invoice_header(text), rows)
    assert len(rows) == 2
    assert issues == ["Subtotal de factura no coincide con la suma de los productos"]


def test_empty_trailing_pdf_page_does_not_require_ocr(monkeypatch):
    import fitz
    from app.modules.purchase_orders.domain import document_extraction

    document = fitz.open()
    page = document.new_page()
    page.insert_text((30, 40), invoice_text(), fontsize=8)
    document.new_page()
    payload = document.tobytes()
    document.close()
    monkeypatch.setattr(
        document_extraction,
        "_ocr_image",
        lambda _: pytest.fail("A blank page must not trigger OCR"),
    )
    _, method, _, rows, _ = parse_file("documento.pdf", payload)
    assert method == "pdf_text"
    assert len(rows) == 2


@pytest.mark.parametrize(
    "discount_fields",
    [
        {"discount": "2.00"},
        {"discount_percent": "10"},
        {"discount": "2.00", "discount_percent": "10"},
    ],
)
def test_line_discount_is_used_in_net_price_without_losing_original_price(
    discount_fields,
):
    product = catalog_product()
    raw = dict(
        kind="order",
        chain="INDUSTRIAL DANEC",
        date="2026-09-14",
        order_number="26003023",
        product_id=str(product.id),
        quantity=10,
        unit="units",
        unit_price="2.00",
        amount="18.00",
        currency="USD",
        **discount_fields,
    )
    normalized = normalize(raw, [product], {}, [])
    assert normalized["unit_price"] == "1.80"
    assert normalized["amount"] == "18.00"
    assert normalized["monetary_issues"] == []
    assert raw["unit_price"] == "2.00"


def test_discount_contradiction_requires_review_instead_of_replacing_amount():
    product = catalog_product()
    normalized = normalize(
        dict(
            kind="invoice",
            chain="TIA",
            date="2026-09-14",
            invoice_number="001-001-000001016",
            product_id=str(product.id),
            quantity=10,
            unit="units",
            unit_price=2,
            amount=18,
            discount=3,
            discount_percent=10,
            currency="USD",
        ),
        [product],
        {},
        [],
    )
    assert normalized["monetary_issues"]
    assert normalized["amount"] is None


def test_known_chain_code_alias_is_exact_and_does_not_leak_to_other_chains():
    product = catalog_product()
    raw = dict(
        kind="order",
        chain="INDUSTRIAL DANEC",
        date="2026-09-14",
        order_number="26003023",
        code="1283410280001",
        product_name="ANA REGEN SHAM BOT400ML 12U",
        quantity=360,
        unit="units",
        unit_price=2.81,
        currency="USD",
    )
    assert normalize(raw, [product], {}, [])["product_id"] == str(product.id)
    assert normalize({**raw, "chain": "TIA"}, [product], {}, [])["product_id"] is None
    second = catalog_product("AR002", "ACONDICIONADOR ANA REGENEXT 400 ML.")
    inconsistent = normalize(
        {**raw, "product_name": second.name}, [product, second], {}, []
    )
    assert inconsistent["product_id"] is None


def test_currency_requires_explicit_or_verified_invoice_layout_evidence():
    assert document_currency("Valor Total: $47.15") is None
    assert document_currency(invoice_text()) == "USD"
    assert document_currency(invoice_text() + "\nEUR") == "EUR"
    assert document_currency(invoice_text() + "\nUSD EUR") is None


REAL_DIR = (
    Path(os.environ["REAL_INVOICE_DIR"]) if os.environ.get("REAL_INVOICE_DIR") else None
)
REAL_FILES = sorted(REAL_DIR.glob("FAC*.pdf")) if REAL_DIR else []


@pytest.mark.skipif(
    not REAL_FILES, reason="Requires the customer's real invoice directory"
)
@pytest.mark.parametrize(
    "path",
    REAL_FILES or [None],
    ids=[path.name for path in REAL_FILES] or ["real-files-not-provided"],
)
def test_every_real_invoice_independently_preserves_header_all_details_and_net_totals(
    path,
):
    _, method, text, sources, _ = parse_file("documento.pdf", path.read_bytes())
    assert sources
    # The input is anonymous: its filename cannot supply invoice or OC identity.
    label = re.search(r"(?i)FACTURA\s+No\.\s*(\d{3}-\d{3}-\d{9})", text)
    assert label is not None
    assert all(
        row["kind"] == "invoice" and row["invoice_number"] == label.group(1)
        for row in sources
    )
    expected = len(re.findall(r"(?m)^\s*([A-Z]{1,6}\d{2,})\s+([\d.,]+)\s", text))
    assert len(sources) == expected
    assert all(
        row["date"] and row["buyer_legal_name"] and row["buyer_ruc"] for row in sources
    )
    assert all(
        row["unit"] == "units" and row["currency"] == "USD" and row["source_text"]
        for row in sources
    )
    assert all(row["document_issues"] == [] for row in sources)
    assert sum(number(row["amount"]) for row in sources) == number(
        sources[0]["document_subtotal"]
    )
    assert number(sources[0]["document_subtotal"]) + number(
        sources[0]["document_tax"]
    ) == number(sources[0]["document_total"])
    # Unknown recipients remain unknown; a familiar issuer cannot substitute them.
    unknown_rucs = {"1793230700001", "1791414667001", "0990858322001"}
    if sources[0]["buyer_ruc"] in unknown_rucs:
        assert all(row["chain"] is None for row in sources)
    document = SimpleNamespace(
        id="test", filename="documento.pdf", method=method, extracted_text=text
    )
    for index, source in enumerate(sources, 1):
        evidence = recognition_evidence(
            SimpleNamespace(
                id=str(index),
                row_number=index,
                source=source,
                corrections={},
                revision=1,
            ),
            document,
        )
        assert (
            not evidence["issues"]
            if source["chain"]
            else evidence["issues"] == ["Cadena no identificada"]
        )


@pytest.mark.skipif(not REAL_DIR, reason="Requires the customer's actual invoice")
def test_real_invoice_image_uses_local_ocr_and_retains_same_evidence():
    import fitz

    source = REAL_DIR / "FAC 001-001-000001016.pdf"
    with fitz.open(source) as pdf:
        image = pdf[0].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
    _, method, _, rows, _ = parse_file("documento.png", image)
    assert "ocr" in method
    assert len(rows) == 4
    assert [number(row["quantity"]) for row in rows] == [360, 480, 168, 240]
    assert all(
        row["chain"] == "INDUSTRIAL DANEC"
        and row["kind"] == "invoice"
        and row["invoice_number"] == "001-001-000001016"
        and row["order_number"] == "26003023"
        and row["date"] == "2026-09-16"
        for row in rows
    )
    assert rows[0]["document_subtotal"] == "5218.08"
    assert rows[0]["document_tax"] == "782.71"
    assert rows[0]["document_total"] == "6000.79"
