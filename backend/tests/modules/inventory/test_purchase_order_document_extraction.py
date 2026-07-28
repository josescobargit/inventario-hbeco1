import io
import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.core.database import get_db
from app.modules.auth.api.dependencies import get_current_user
from app.modules.purchase_orders.domain import document_extraction
from app.modules.purchase_orders.domain.table_extraction import (
    extract_known_ocr_text_rows,
)
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
        lambda _image: (
            "ORDEN DE COMPRA OC-200\n2 PRODUCTO",
            "ocr_test_local",
            [],
            _image.size,
        ),
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
            [],
            _image.size,
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
            [],
            _image.size,
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


SUPPLIED_OC_DIRECTORY = Path(
    os.environ.get("PURCHASE_ORDER_SAMPLE_DIR", Path.home() / "Downloads")
)
SUPPLIED_OC_CASES = [
    ("OC 23 JUL ROSADO UIO .pdf", 4),
    ("OC TIA 3000927171.pdf", 4),
    ("OC 919979 - 21 JUL.pdf", 6),
    ("OC 4500346780 - 23 JUL.PDF", 4),
    ("pedidos_125167-2.pdf", 9),
    ("AL193257.pdf", 16),
]


@pytest.mark.parametrize(("filename", "expected_lines"), SUPPLIED_OC_CASES)
def test_each_supplied_purchase_order_has_exact_product_count(
    filename: str, expected_lines: int
) -> None:
    path = SUPPLIED_OC_DIRECTORY / filename
    if not path.exists():
        pytest.skip(
            "Set PURCHASE_ORDER_SAMPLE_DIR to run the supplied-document regression."
        )

    result = document_extraction.extract_document(
        path.read_bytes(), "application/pdf", filename
    )

    assert result.expected_product_count == expected_lines
    assert len(result.table_rows) == expected_lines
    assert all(row["description"] for row in result.table_rows)
    assert all(row["quantity"] > 0 for row in result.table_rows)
    forbidden = (
        "PROVEEDOR",
        "DIRECCION",
        "OBSERVACION",
        "SUBTOTAL",
        "TOTAL DE ITEMS",
        "PRECIO UNITARIO",
    )
    assert not any(
        term in row["description"].upper()
        for row in result.table_rows
        for term in forbidden
    )


def test_supplied_purchase_orders_total_exactly_43_product_lines() -> None:
    paths = [SUPPLIED_OC_DIRECTORY / filename for filename, _ in SUPPLIED_OC_CASES]
    if not all(path.exists() for path in paths):
        pytest.skip(
            "Set PURCHASE_ORDER_SAMPLE_DIR to run the supplied-document regression."
        )

    extracted_counts = [
        len(
            document_extraction.extract_document(
                path.read_bytes(), "application/pdf", path.name
            ).table_rows
        )
        for path in paths
    ]

    assert extracted_counts == [4, 4, 6, 4, 9, 16]
    assert sum(extracted_counts) == 43


@pytest.mark.parametrize(
    ("filename", "expected_lines", "expected_units"),
    [
        ("WhatsApp Image 2026-07-27 at 09.58.52.jpeg", 1, 120),
        ("WhatsApp Image 2026-07-27 at 15.49.30.jpeg", 5, 1446),
    ],
)
def test_supplied_phone_images_preserve_boxes_uxc_and_units(
    filename: str, expected_lines: int, expected_units: int
) -> None:
    path = SUPPLIED_OC_DIRECTORY / filename
    if not path.exists():
        pytest.skip("La imagen real está disponible en la validación local.")

    try:
        content = path.read_bytes()
    except PermissionError:
        pytest.skip("El entorno de pruebas no tiene permiso para leer Downloads.")
    result = document_extraction.extract_document(content, "image/jpeg", filename)

    assert len(result.table_rows) == expected_lines
    assert (
        sum(row["quantity"] * row["units_per_box"] for row in result.table_rows)
        == expected_units
    )


def test_favorita_ocr_text_recovers_the_single_product_row() -> None:
    rows = extract_known_ocr_text_rows(
        "\n".join(
            [
                "CORPORACIONFAVORITAC.A.",
                "ITDescripcion Tamano AcabadoS CodigoBarras UC.Prec.Costo",
                "01ANAPANITOSHUMEDOS 100u 786213 7862133169244 12 1.3802 10",
            ]
        )
    )

    assert rows == [
        {
            "page": 1,
            "raw": "01ANAPANITOSHUMEDOS 100u 786213 7862133169244 12 1.3802 10",
            "item_number": "01",
            "chain_code": "786213",
            "description": "ANA PANITOS HUMEDOS 100U",
            "supplier_reference": "7862133169244",
            "size": "100U",
            "units_per_box": 12,
            "quantity": 10,
            "original_unit_type": "boxes",
            "bounds": {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0},
            "source": "known_ocr_text_layout",
        }
    ]


def test_frontend_purchase_order_import_route_matches_backend_contract() -> None:
    frontend_source = (
        Path(__file__).parents[4]
        / "frontend/src/features/purchase-orders/PurchaseOrderDocumentImport.tsx"
    ).read_text(encoding="utf-8")
    route = re.search(r'purchaseOrderPreviewPath\s*=\s*"([^"]+)"', frontend_source)
    assert route is not None
    full_path = f"/api/v1{route.group(1)}"
    assert full_path in app.openapi()["paths"]
    assert "post" in app.openapi()["paths"][full_path]


def test_purchase_order_import_route_exists_for_unauthenticated_user() -> None:
    response = TestClient(app).post(
        "/api/v1/purchase-orders/imports/preview",
        files={"files": ("orden.pdf", b"%PDF-1.7", "application/pdf")},
    )
    assert response.status_code == 401
    assert response.status_code != 404


@pytest.mark.parametrize(
    ("filename", "content_type", "content", "expected_status"),
    [
        (
            "orden.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"invalid",
            422,
        ),
        ("grande.pdf", "application/pdf", b"x" * (15 * 1024 * 1024 + 1), 413),
    ],
)
def test_purchase_order_import_endpoint_validates_file_before_extraction(
    filename: str, content_type: str, content: bytes, expected_status: int
) -> None:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4()
    )
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    try:
        response = TestClient(app).post(
            "/api/v1/purchase-orders/imports/preview",
            files={"files": (filename, content, content_type)},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == expected_status
