from app.modules.commercial.workflow import build_workflow
from app.modules.commercial.invoice_extraction import invoice_header


def row(
    doc,
    kind="order",
    number="OC-12345",
    chain="TIA",
    code="P1",
    qty=10,
    when="2026-09-14",
    reference="",
    unit="units",
    amount=100,
    **kwargs,
):
    return dict(
        id=doc + code,
        document_id=doc,
        kind=kind,
        chain=chain,
        date=when,
        order_number=number if kind == "order" else reference,
        invoice_number=number if kind == "invoice" else "",
        product_name="Producto " + code,
        sku=code,
        units=qty,
        product_id=None,
        filename=doc + ".pdf",
        origin="import",
        excluded=False,
        source=dict(code=code, quantity=qty, unit=unit, amount=amount),
        issues=[],
        **kwargs,
    )


def test_explicit_link_and_comparison_with_partial_and_excess():
    result = build_workflow(
        [
            row("o"),
            row("o", code="P2", qty=5, amount=50),
            row(
                "i",
                "invoice",
                "001-001-000000001",
                reference="OC12345",
                qty=6,
                amount=60,
            ),
            row(
                "i",
                "invoice",
                "001-001-000000001",
                reference="OC12345",
                code="P2",
                qty=7,
                amount=70,
            ),
        ]
    )
    assert result["summary"] == dict(invoices=1, linked=1, pending=0)
    assert [r["status"] for r in result["comparisons"]] == ["PARCIAL", "EXCESO"]
    assert result["comparisons"][0]["unbilled_amount"] == 40
    assert result["comparisons"][1]["difference"] == -2
    assert result["chains"][0]["linked_orders"] == 1


def test_explicit_unknown_order_does_not_fallback_to_similar_products_or_totals():
    result = build_workflow(
        [row("o"), row("i", "invoice", "F1", reference="999999", amount=100)]
    )
    assert result["summary"]["linked"] == 0
    assert result["invoices"][0]["status"] == "REVISAR"


def test_chain_conflict_prevents_link():
    result = build_workflow(
        [row("o"), row("i", "invoice", "F1", chain="TUTI", reference="OC12345")]
    )
    assert result["summary"]["linked"] == 0


def test_unique_exact_products_and_compatible_date_links_without_reference():
    result = build_workflow([row("o"), row("i", "invoice", "F1", when="2026-09-16")])
    assert result["summary"]["linked"] == 1
    assert result["comparisons"][0]["status"] == "COMPLETO"


def test_two_candidates_remain_review_no_arbitrary_selection():
    result = build_workflow(
        [row("o"), row("o2", number="OC67890"), row("i", "invoice", "F1")]
    )
    assert result["summary"]["pending"] == 1
    assert "Varias OC compatibles" in result["invoices"][0]["issues"]
    assert all(r["status"] == "REVISAR" for r in result["comparisons"])


def test_similar_money_different_product_never_links():
    result = build_workflow([row("o"), row("i", "invoice", "F1", code="P2")])
    assert result["summary"]["linked"] == 0


def test_date_incompatible_never_links_without_reference():
    result = build_workflow([row("o"), row("i", "invoice", "F1", when="2026-09-13")])
    assert result["summary"]["linked"] == 0


def test_same_number_in_two_chains_remains_separate():
    result = build_workflow(
        [
            row("o"),
            row("o2", chain="TUTI"),
            row("i", "invoice", "F1", chain="TIA", reference="OC12345"),
        ]
    )
    assert len(result["orders"]) == 2
    assert result["invoices"][0]["linked_order_id"] == result["orders"][0]["id"]


def test_identical_reuploads_collapsed_but_conflicting_versions_reviewed():
    result = build_workflow(
        [row("o"), row("o2"), row("i", "invoice", "F1"), row("i2", "invoice", "F1")]
    )
    assert len(result["orders"]) == len(result["invoices"]) == 1
    assert result["summary"]["linked"] == 1
    result = build_workflow(
        [row("o"), row("o2", qty=12), row("i", "invoice", "F1", reference="OC12345")]
    )
    assert result["summary"]["linked"] == 0
    assert all(o["issues"] for o in result["orders"])


def test_unknown_box_factor_never_compared_as_units():
    result = build_workflow(
        [row("o", unit="boxes"), row("i", "invoice", "F1", reference="OC12345")]
    )
    comparison = result["comparisons"][0]
    assert comparison["status"] == "REVISAR"
    assert (
        comparison["invoiced"]
        is comparison["fulfillment"]
        is comparison["difference"]
        is None
    )


def test_box_factor_and_multiple_invoices_accumulate():
    order = row("o", qty=1, unit="boxes", amount=120)
    order["source"]["units_per_box"] = 12
    result = build_workflow(
        [
            order,
            row("i", "invoice", "F1", qty=5, reference="OC12345", amount=50),
            row("i2", "invoice", "F2", qty=7, reference="OC12345", amount=70),
        ]
    )
    assert result["comparisons"][0]["status"] == "COMPLETO"
    assert result["orders"][0]["fulfillment"] == 100
    assert result["chains"][0]["linked"] == 2
    assert result["chains"][0]["linked_orders"] == 1


def test_missing_prices_preserves_quantities_without_inventing_money():
    result = build_workflow([row("o", amount=None)])
    assert result["comparisons"][0]["status"] == "NO FACTURADO"
    assert result["comparisons"][0]["unbilled_amount"] is None
    assert result["comparisons"][0]["ordered"] == 10


def test_invoice_header_uses_recipient_and_own_date_not_order_date():
    text = """INDUSTRIAL DANEC S A RUC 1790040968001
FACTURA No. 001-002-000000123
Fecha Emisión: 16/09/2026
Razón Social / Nombres: TIENDAS TUTI TTDE S.A.
RUC: 0993152161001
Orden de Compra: 4500374870
Descripción Cantidad Precio Total
TOTAL FACTURA 120.00"""
    header = invoice_header(text)
    assert header["chain"] == "TUTI"
    assert header["date"] == "2026-09-16"
    assert header["invoice_number"] == "001-002-000000123"
    assert header["order_number"] == "4500374870"
    assert header["document_total"] == "120.00"


def test_invoice_header_missing_date_is_not_order_date():
    header = invoice_header(
        "FACTURA\n001-001-000000001\nINDUSTRIAL DANEC S.A.\nFecha de Orden: 14/09/26\nORDEN DE COMPRA Nº 26003023"
    )
    assert header["date"] is None
    assert header["order_number"] == "26003023"


def test_same_order_number_in_multiple_chains_in_one_file_is_not_merged():
    result = build_workflow([row("onefile"), row("onefile", chain="TUTI")])
    assert len(result["orders"]) == 2
    assert len({o["id"] for o in result["orders"]}) == 2


def test_repeated_product_with_missing_quantity_remains_reviewable():
    bad = row("o", qty=None)
    bad["id"] = "other-line"
    bad["issues"] = ["Cantidad ausente o inválida"]
    result = build_workflow([row("o"), bad])
    assert result["orders"][0]["status"] == "REVISAR"
    assert result["comparisons"][0]["ordered"] is None
