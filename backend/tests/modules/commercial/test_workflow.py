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
    assert result["summary"] == dict(
        invoices=1, linked=1, pending=0, excluded_invoices=0
    )
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


def test_cancelled_invoice_is_visible_but_does_not_bill_or_require_linking():
    cancelled = row("i", "invoice", "F1", reference="OC12345")
    cancelled["source"]["status"] = "anulada"
    result = build_workflow([row("o"), cancelled])
    assert result["summary"] == dict(
        invoices=0, linked=0, pending=0, excluded_invoices=1
    )
    assert result["invoices"][0]["administrative_status"] == "cancelled"
    assert result["invoices"][0]["excluded"] is True
    assert result["invoices"][0]["status"] == "OK"
    assert result["comparisons"][0]["invoiced"] == 0
    assert result["comparisons"][0]["status"] == "NO FACTURADO"


def test_proven_replacement_uses_only_valid_invoice():
    old = row("old", "invoice", "F1", reference="OC12345", qty=10)
    old["source"].update(status="reemplazada", replaced_by="F2")
    replacement = row("new", "invoice", "F2", reference="OC12345", qty=7)
    replacement["source"]["replaces"] = "F1"
    result = build_workflow([row("o"), old, replacement])
    assert result["summary"] == dict(
        invoices=1, linked=1, pending=0, excluded_invoices=1
    )
    assert result["comparisons"][0]["invoiced"] == 7
    assert result["orders"][0]["invoices"][0]["number"] == "F2"


def test_replacement_without_original_state_evidence_blocks_both_invoices():
    old = row("old", "invoice", "F1", reference="OC12345")
    replacement = row("new", "invoice", "F2", reference="OC12345")
    replacement["source"]["replaces"] = "F1"
    result = build_workflow([row("o"), old, replacement])
    assert result["summary"] == dict(
        invoices=2, linked=0, pending=2, excluded_invoices=0
    )
    assert all(
        "Reemplazo requiere evidencia del estado de la factura original" in i["issues"]
        for i in result["invoices"]
    )
    assert result["comparisons"][0]["status"] == "REVISAR"


def test_conflicting_active_cancelled_versions_do_not_select_state():
    active = row("active", "invoice", "F1", reference="OC12345")
    cancelled = row("cancelled", "invoice", "F1", reference="OC12345")
    cancelled["source"]["status"] = "anulada"
    result = build_workflow([row("o"), active, cancelled])
    invoice = result["invoices"][0]
    assert invoice["administrative_status"] == "review"
    assert not invoice["excluded"]
    assert invoice["linked_order_id"] is None
    assert len(invoice["versions"]) == 2
    assert result["comparisons"][0]["status"] == "REVISAR"


def test_secondary_order_reference_is_exact_and_preserves_leading_zeros():
    order = row("o", number="OC_7742")
    order["source"]["secondary_reference"] = "005880189"
    invoice = row("i", "invoice", "F1", reference="005880189")
    result = build_workflow([order, invoice])
    assert result["summary"]["linked"] == 1
    invoice["order_number"] = "5880189"
    assert build_workflow([order, invoice])["summary"]["linked"] == 0


def test_explicit_document_link_preserves_valid_line_when_other_line_is_missing():
    bad = row("o", code="P2", qty=None)
    bad["issues"] = ["Cantidad ausente o inválida"]
    invoice = row("i", "invoice", "F1", reference="OC12345", qty=6)
    result = build_workflow([row("o"), bad, invoice])
    assert result["summary"]["linked"] == 1
    assert result["comparisons"][0]["status"] == "PARCIAL"
    assert result["comparisons"][0]["invoiced"] == 6
    assert result["comparisons"][1]["status"] == "REVISAR"


def test_date_cohort_retains_linked_invoices_until_cutoff_and_excludes_future():
    result = build_workflow(
        [
            row("o", when="2026-09-07"),
            row("i1", "invoice", "F1", reference="OC12345", when="2026-09-08", qty=3),
            row("i2", "invoice", "F2", reference="OC12345", when="2026-09-14", qty=4),
            row("i3", "invoice", "F3", reference="OC12345", when="2026-09-21", qty=3),
            row("outside", number="OC-999", when="2026-08-01"),
        ],
        start="2026-09-07",
        end="2026-09-14",
    )
    assert len(result["orders"]) == 1
    assert len(result["invoices"]) == 2
    assert result["comparisons"][0]["invoiced"] == 7


def test_period_filter_does_not_hide_real_ambiguous_candidate():
    result = build_workflow(
        [
            row("inside", number="OC1", when="2026-09-07"),
            row("outside", number="OC2", when="2026-09-01"),
            row("i", "invoice", "F1", when="2026-09-08"),
        ],
        start="2026-09-07",
        end="2026-09-14",
    )
    assert len(result["orders"]) == 1
    assert result["summary"]["linked"] == 0
    assert "Varias OC compatibles" in result["invoices"][0]["issues"]


def test_document_discounts_tax_and_total_are_not_product_net_amounts():
    invoice = row("i", "invoice", "F1", reference="OC12345", qty=2, amount=18)
    invoice["source"].update(
        unit_price=10,
        discount=2,
        document_subtotal=18,
        document_discount=2,
        document_tax=2.7,
        document_total=20.7,
        currency="USD",
    )
    result = build_workflow([row("o"), invoice])
    assert result["invoices"][0]["financials"] == dict(
        subtotal=18, discount=2, tax=2.7, total=20.7, currency="USD"
    )
    assert result["invoices"][0]["lines"][0]["unit_price"] == 10
    assert result["invoices"][0]["lines"][0]["net_unit_price"] == 9
    assert result["comparisons"][0]["invoiced_amount"] == 18


def test_missing_date_is_one_document_review_but_preserves_explicit_link_quantities():
    invoice = row("i", "invoice", "F1", reference="OC12345", when=None, qty=6)
    invoice["issues"] = ["Fecha ausente o inválida"]
    result = build_workflow([row("o"), invoice])
    assert result["summary"]["linked"] == 1
    assert result["summary"]["pending"] == 1
    assert result["invoices"][0]["status"] == "REVISAR"
    assert result["comparisons"][0]["status"] == "PARCIAL"
    assert result["comparisons"][0]["missing"] == 4


def test_unit_is_never_inferred_from_bare_quantity():
    order = row("o", unit="")
    order["issues"] = ["Unidad de cantidad no identificada"]
    result = build_workflow([order])
    assert result["orders"][0]["lines"][0]["unit"] == ""
    assert result["comparisons"][0]["status"] == "REVISAR"


def test_selected_version_keeps_discarded_copy_evidence_without_conflict():
    discarded = row("o", qty=10)
    discarded["source"]["status"] = "excluido"
    chosen = row("o2", qty=12)
    result = build_workflow([discarded, chosen])
    assert len(result["orders"]) == 1
    assert result["orders"][0]["quantity"] == 12
    assert not result["orders"][0]["issues"]
    assert len(result["orders"][0]["evidence_records"]) == 2


def test_liris_document_label_can_be_omitted_without_removing_leading_zeros():
    order = row("o", number="OC_005884445", chain="LIRIS S.A.")
    invoice = row("i", "invoice", "F1", reference="005884445", chain="LIRIS DEL PORTAL")
    assert build_workflow([order, invoice])["summary"]["linked"] == 1
    invoice["order_number"] = "5884445"
    assert build_workflow([order, invoice])["summary"]["linked"] == 0
    order["chain"] = invoice["chain"] = "TIA"
    invoice["order_number"] = "005884445"
    assert build_workflow([order, invoice])["summary"]["linked"] == 0


def test_no_explicit_reference_does_not_link_using_unidentified_product_name():
    order = row("o", code="")
    invoice = row("i", "invoice", "F1", code="")
    order["product_name"] = invoice["product_name"] = "Sin identificar"
    invoice["issues"] = ["Descripción del producto pendiente"]
    assert build_workflow([order, invoice])["summary"]["linked"] == 0
