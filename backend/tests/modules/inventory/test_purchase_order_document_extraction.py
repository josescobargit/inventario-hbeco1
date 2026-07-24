import io
import uuid
from types import SimpleNamespace

import fitz
import pytest
from fastapi import HTTPException
from PIL import Image

from app.modules.purchase_orders.domain import document_extraction
from app.modules.purchase_orders.api.router import purchase_order_document_content


def pdf_bytes(pages: list[str]) -> bytes:
    document = fitz.open()
    for text in pages:
        page = document.new_page()
        page.insert_text((72, 72), text)
    return document.tobytes()


def rosado_table_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=900, height=500)
    page.insert_text((30, 40), "PROVEEDOR HOME BEAUTY S.A.", fontsize=8)
    page.insert_text((30, 60), "COMISARIATO DESTINO", fontsize=8)
    columns = [
        (20, "ITEN"),
        (70, "ARTICULO"),
        (220, "DESCRIPCION"),
        (500, "REFERENCIA"),
        (620, "TAMAÑO"),
        (700, "UXC"),
        (750, "CANTIDAD"),
        (820, "COSTO"),
    ]
    for x, value in columns:
        page.insert_text((x, 110), value, fontsize=7)
    values = [
        (20, "10"),
        (70, "000000000040622962"),
        (220, "CREMA DE PEINAR ANA"),
        (500, "7862133169220"),
        (620, "200ML"),
        (700, "12"),
        (750, "31"),
        (820, "1.25"),
    ]
    for x, value in values:
        page.insert_text((x, 135), value, fontsize=7)
    page.insert_text((220, 150), "REGENEXT 200ML", fontsize=7)
    page.insert_text((20, 180), "TOTAL DE ITEMS 1", fontsize=8)
    page.insert_text((20, 210), "OBSERVACIONES COMERCIALES", fontsize=8)
    return document.tobytes()


def test_extracts_text_pdf_and_every_page() -> None:
    result = document_extraction.extract_document(
        pdf_bytes(
            [
                "ORDEN DE COMPRA OC-100\nCLIENTE: CADENA UNO\n1 PRODUCTO UNO",
                "CODIGO DESCRIPCION CANTIDAD\nABC PRODUCTO DOS 2 UN",
            ]
        ),
        "application/pdf",
        "orden.pdf",
    )
    assert result.method == "pdf_text"
    assert result.page_count == 2
    assert "OC-100" in result.text
    assert "PRODUCTO DOS" in result.text


def test_reconstructs_table_columns_by_position_and_excludes_header_fragments() -> None:
    result = document_extraction.extract_document(
        rosado_table_pdf(), "application/pdf", "pedidos_125167-2.pdf"
    )
    assert len(result.table_rows) == 1
    row = result.table_rows[0]
    assert row["item_number"] == "10"
    assert row["chain_code"] == "000000000040622962"
    assert row["supplier_reference"] == "7862133169220"
    assert row["description"] == "CREMA DE PEINAR ANA REGENEXT 200ML"
    assert row["units_per_box"] == 12
    assert row["quantity"] == 31
    assert row["quantity"] * row["units_per_box"] == 372
    assert "PROVEEDOR" not in row["raw"]
    assert "COMISARIATO" not in row["raw"]


def test_scanned_pdf_uses_local_ocr(monkeypatch) -> None:
    image = Image.new("RGB", (600, 300), "white")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    document = fitz.open()
    page = document.new_page(width=600, height=300)
    page.insert_image(page.rect, stream=buffer.getvalue())
    monkeypatch.setattr(
        document_extraction,
        "_ocr_image",
        lambda _image: ("ORDEN DE COMPRA OC-200\n2 PRODUCTO", "ocr_test_local"),
    )
    result = document_extraction.extract_document(
        document.tobytes(), "application/pdf", "escaneada.pdf"
    )
    assert result.method == "ocr_test_local"
    assert "procesada con OCR" in result.warnings[0]


def test_image_preprocessing_enlarges_and_improves_low_quality_photo() -> None:
    source = Image.new("RGB", (240, 120), (145, 145, 145))
    prepared = document_extraction._prepare_image(source)
    assert max(prepared.size) >= 1800
    assert prepared.mode == "L"


def test_photographed_image_is_processed_as_a_single_ocr_page(monkeypatch) -> None:
    source = Image.new("RGB", (900, 600), (214, 210, 198))
    buffer = io.BytesIO()
    source.save(buffer, "JPEG", quality=55)
    monkeypatch.setattr(
        document_extraction,
        "_ocr_image",
        lambda _image: (
            "PEDIDO: FOTO-10\nCOMPRADOR: Cadena Foto\n"
            "DESCRIPCION QTY\nPRODUCTO FOTOGRAFIADO 4 UN",
            "ocr_test_photo",
        ),
    )
    result = document_extraction.extract_document(
        buffer.getvalue(), "image/jpeg", "foto-pedido.jpg"
    )
    assert result.method == "ocr_test_photo"
    assert result.page_count == 1
    assert result.text.startswith("[[PAGE:1]]")
    assert "PRODUCTO FOTOGRAFIADO" in result.text


def test_splits_multiple_orders_without_mixing_documents() -> None:
    text = "ORDEN DE COMPRA OC-301\n1 PRODUCTO A\nORDEN DE COMPRA OC-302\n2 PRODUCTO B"
    drafts = document_extraction.split_purchase_orders(text)
    assert len(drafts) == 2
    assert "PRODUCTO B" not in drafts[0]
    assert "PRODUCTO A" not in drafts[1]


def test_recognizes_existing_header_fields_only() -> None:
    header = document_extraction.recognized_header(
        "ORDEN DE COMPRA OC-400\nCLIENTE: Cadena Prueba\nFECHA: 23/07/2026"
    )
    assert header == {
        "order_number": "OC-400",
        "order_number_source": "document_label",
        "secondary_reference": None,
        "chain_name": "Cadena Prueba",
        "chain_candidates": ["Cadena Prueba"],
        "order_date": "2026-07-23",
    }


def test_digital_text_with_only_corporate_content_triggers_hybrid_ocr(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        document_extraction,
        "_ocr_image",
        lambda _image: (
            "PO: NEW-900\nBUYER: Cadena Nueva\nSKU DESCRIPTION QTY\nABC Producto universal 7 EA",
            "ocr_test_local",
        ),
    )
    result = document_extraction.extract_document(
        pdf_bytes(
            [
                "EMPRESA DEMOSTRACION S.A.\nRUC 0999999999001\nDIRECCION PRINCIPAL\n"
                "www.ejemplo.test redes sociales"
            ]
        ),
        "application/pdf",
        "corporativo.pdf",
    )
    assert result.method == "ocr_test_local+pdf_text"
    assert "Producto universal" in result.text
    assert "EMPRESA DEMOSTRACION" in result.text
    assert result.text.startswith("[[PAGE:1]]")


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("PURCHASE ORDER: PO-991\nBUYER: Example Retail LLC", "PO-991"),
        ("PEDIDO # PED-22\nCOMPRADOR: Comercial Uno S.A.", "PED-22"),
        ("NRO. DOCUMENTO: 7788-A\nCUSTOMER: Cadena Dos", "7788-A"),
    ],
)
def test_header_detection_accepts_equivalent_labels(text: str, number: str) -> None:
    assert document_extraction.recognized_header(text)["order_number"] == number


def test_local_filename_number_precedes_secondary_purchase_reference() -> None:
    header = document_extraction.recognized_header(
        "PED. COMPRA 4600430608\nLOCAL: Tienda Principal",
        "AL193257.pdf",
    )
    assert header["order_number"] == "AL193257"
    assert header["order_number_source"] == "filename_local_reference"
    assert header["secondary_reference"] == "4600430608"


def test_filename_is_secondary_and_never_uses_pedido_id_from_url() -> None:
    header = document_extraction.recognized_header(
        "Consulta: https://example.test/order?pedidoId=987654321\n"
        "CODIGO DESCRIPCION CANTIDAD",
        "OC 919979 - 21 JUL.pdf",
    )
    assert header["order_number"] == "919979"
    assert "987654321" not in str(header.values())


@pytest.mark.parametrize(
    ("text", "expected_type", "allowed"),
    [
        ("PREVALIDACIÓN FACTURA\nSD224955", "invoice_prevalidation", False),
        ("GUÍA DE REMISIÓN\nDESPACHO DE MERCADERÍA", "dispatch_document", False),
        ("ORDEN DE COMPRA: 10001\nSKU DESCRIPCION CANTIDAD", "purchase_order", True),
        ("PEDIDO: P-22\nPRODUCTO CANTIDAD", "order_request", True),
        ("INFORME GENERAL SIN TABLA", "unknown", False),
    ],
)
def test_classifies_documents_before_purchase_order_extraction(
    text: str, expected_type: str, allowed: bool
) -> None:
    classification = document_extraction.classify_document(text)
    assert classification["type"] == expected_type
    assert classification["allowed_for_purchase_order"] is allowed
    if not allowed:
        assert (
            classification["message"]
            == "Este documento no corresponde a una orden de compra."
        )


def test_structural_signals_do_not_accept_long_legal_footer_as_an_order() -> None:
    signals = document_extraction.extraction_signals(
        "EMPRESA LEGAL S.A. DIRECCION MATRIZ AVENIDA PRINCIPAL "
        "TELEFONO 2222222 RUC 0999999999001 TODOS LOS DERECHOS RESERVADOS"
    )
    assert signals["enough_text"] is True
    assert signals["candidate_rows"] == 0
    assert signals["product_structure"] is False


def test_confirmed_codes_propose_only_their_own_chain_profile() -> None:
    candidates = document_extraction.suggest_chains_from_confirmed_aliases(
        "SKU DESCRIPTION QTY\nCLI-77 PRODUCTO RECURRENTE 8 UN",
        [
            ("Cadena Norte", "OTRO PRODUCTO", "NORTE-11"),
            ("Cadena Sur", "PRODUCTO RECURRENTE", "CLI-77"),
        ],
    )
    assert candidates == ["Cadena Sur"]


def test_ambiguous_profile_evidence_requires_chain_confirmation() -> None:
    candidates = document_extraction.suggest_chains_from_confirmed_aliases(
        "A-10 PRODUCTO 2 UN\nB-20 OTRO PRODUCTO 3 UN",
        [
            ("Cadena A", "DESCRIPCION CONFIRMADA A", "A-10"),
            ("Cadena B", "DESCRIPCION CONFIRMADA B", "B-20"),
        ],
    )
    assert candidates == ["Cadena A", "Cadena B"]


class ScalarSequence:
    def __init__(self, *values):
        self.values = list(values)

    def scalar(self, _statement):
        return self.values.pop(0)


def test_document_route_requires_owner_or_linked_order() -> None:
    token = uuid.uuid4()
    document = SimpleNamespace(
        id=uuid.uuid4(),
        upload_token=token,
        created_by_user_id=uuid.uuid4(),
        original_filename="orden.pdf",
        content_type="application/pdf",
        content=b"%PDF-test",
    )
    user = SimpleNamespace(id=uuid.uuid4())
    with pytest.raises(HTTPException) as error:
        purchase_order_document_content(token, user, ScalarSequence(document, None))
    assert error.value.status_code == 404


def test_linked_document_response_preserves_pdf_headers_and_bytes() -> None:
    token = uuid.uuid4()
    document = SimpleNamespace(
        id=uuid.uuid4(),
        upload_token=token,
        created_by_user_id=uuid.uuid4(),
        original_filename="OC cliente.pdf",
        content_type="application/pdf",
        content=b"%PDF-persisted",
    )
    response = purchase_order_document_content(
        token,
        SimpleNamespace(id=uuid.uuid4()),
        ScalarSequence(document, uuid.uuid4()),
    )
    assert response.media_type == "application/pdf"
    assert response.body == b"%PDF-persisted"
    assert (
        response.headers["content-disposition"] == 'inline; filename="OC cliente.pdf"'
    )
    assert response.headers["cache-control"].startswith("private")
