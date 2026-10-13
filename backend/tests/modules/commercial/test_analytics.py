from app.modules.commercial.analytics import build_commercial_summary
from app.modules.commercial.workflow import build_workflow


def evidence(
    doc,
    kind="order",
    number="OC1",
    code="P1",
    quantity=10,
    amount=100,
    when="2026-09-07",
    reference="",
    chain="TIA",
    currency="USD",
):
    return dict(
        id=f"{doc}:{code}",
        document_id=doc,
        filename=doc + ".pdf",
        origin="import",
        kind=kind,
        chain=chain,
        date=when,
        product_id=None,
        product_name="Producto " + code,
        sku=code,
        units=quantity,
        unit_price=None,
        amount=amount,
        line="Cabello",
        order_number=number if kind == "order" else reference,
        invoice_number=number if kind == "invoice" else "",
        excluded=False,
        administrative_status="activo",
        issues=[],
        monetary_issues=[],
        source={
            "code": code,
            "quantity": quantity,
            "unit": "units",
            "amount": amount,
            "currency": currency,
        },
    )


def summary(rows, **filters):
    return build_commercial_summary(build_workflow(rows, **filters), **filters)


def test_dashboard_weekly_report_use_same_comparison_and_cap_excess_per_product():
    data = summary(
        [
            evidence("o", quantity=10, amount=100),
            evidence("o", code="P2", quantity=10, amount=200),
            evidence("i1", "invoice", "F1", quantity=15, amount=150, reference="OC1"),
            evidence(
                "i2", "invoice", "F2", code="P2", quantity=4, amount=80, reference="OC1"
            ),
        ]
    )
    assert data["summary"]["ordered"] == 20
    assert data["summary"]["invoiced"] == 19
    assert data["summary"]["difference"] == 1
    assert data["summary"]["missing"] == 6
    assert data["summary"]["fulfillment"] == 70
    assert data["summary"]["unbilled_amount"] == 120
    assert data["rows"][0]["fulfillment"] == 150
    assert data["weekly_report"]["summary"] == data["summary"]
    assert data["weekly_report"]["chains"] == data["chains"]
    assert (
        data["weekly_report"]["critical_products"]["missing"][0]["product_name"]
        == "Producto P2"
    )
    assert (
        data["weekly_report"]["critical_products"]["economic"][0]["unbilled_amount"]
        == 120
    )


def test_missing_price_keeps_quantities_but_monetary_summary_is_unknown():
    data = summary([evidence("o", amount=None)])
    assert data["summary"]["ordered"] == 10
    assert data["summary"]["invoiced"] == 0
    assert data["summary"]["missing"] == 10
    assert data["summary"]["unbilled_amount"] is None
    assert data["summary"]["missing_valuation_rows"] == 1
    assert data["rows"][0]["status"] == "NO FACTURADO"


def test_missing_currency_never_becomes_usd_and_mixed_currency_not_summed():
    data = summary([evidence("o", currency=None)])
    assert data["summary"]["currency"] is None
    assert data["summary"]["ordered_amount"] is None
    assert data["rows"][0]["ordered_amount"] == 100
    assert data["rows"][0]["currency"] is None
    data = summary(
        [evidence("o1"), evidence("o2", number="OC2", chain="TUTI", currency="EUR")]
    )
    assert data["summary"]["ordered"] == 20
    assert data["summary"]["currency"] is None
    assert data["summary"]["ordered_amount"] is None
    assert {c["currency"] for c in data["chains"]} == {"USD", "EUR"}


def test_invoice_value_is_preserved_when_only_order_currency_is_unknown():
    data = summary(
        [
            evidence("o", currency=None),
            evidence("i", "invoice", "F1", quantity=5, amount=50, reference="OC1"),
        ]
    )
    assert data["summary"]["ordered_amount"] is None
    assert data["summary"]["unbilled_amount"] is None
    assert data["summary"]["invoiced_amount"] == 50
    assert data["summary"]["invoiced_currency"] == "USD"
    assert data["summary"]["missing"] == 5


def test_document_metadata_problem_is_one_alert_for_many_lines():
    rows = [
        evidence("i", "invoice", "F1", code=code, reference="missing")
        for code in ("P1", "P2", "P3")
    ]
    for record in rows:
        record["issues"] = ["Fecha ausente o inválida"]
        record["date"] = None
    data = summary(rows)
    assert data["summary"]["review_documents"] == 1
    assert len(data["alerts"]) == 1
    assert len(data["alerts"][0]["record_ids"]) == 3
    assert data["alerts"][0]["message"].count("Fecha ausente o inválida") == 1


def test_unresolved_invoice_never_shows_confirmed_zero_facturado():
    data = summary(
        [
            evidence("o1"),
            evidence("o2", number="OC2"),
            evidence("i", "invoice", "F1"),
        ]
    )
    assert data["summary"]["ordered"] == 20
    assert data["summary"]["invoiced"] is None
    assert data["summary"]["missing"] is None
    assert data["summary"]["fulfillment"] is None
    assert data["summary"]["review_documents"] == 1
    assert len(data["weekly_report"]["critical_products"]["missing"]) == 0


def test_cancelled_invoice_alert_is_once_and_excluded_from_dashboard_and_report():
    order = evidence("o")
    cancelled = evidence("i", "invoice", "F1", reference="OC1")
    cancelled["source"]["status"] = "anulada"
    data = summary([order, cancelled])
    assert data["summary"]["invoiced"] == 0
    assert data["summary"]["excluded_documents"] == 1
    assert len([a for a in data["alerts"] if a["code"] == "excluded"]) == 1
    assert data["weekly_report"]["counts"]["excluded_invoices"] == 1
    assert all(e["kind"] != "invoice" for e in data["evolution"])


def test_filter_period_reports_order_cohort_and_all_linked_invoices_until_end():
    data = summary(
        [
            evidence("o", when="2026-09-07"),
            evidence(
                "i1",
                "invoice",
                "F1",
                quantity=4,
                amount=40,
                reference="OC1",
                when="2026-09-08",
            ),
            evidence(
                "i2",
                "invoice",
                "F2",
                quantity=3,
                amount=30,
                reference="OC1",
                when="2026-09-14",
            ),
            evidence(
                "i3",
                "invoice",
                "F3",
                quantity=3,
                amount=30,
                reference="OC1",
                when="2026-09-21",
            ),
            evidence("old", number="OC2", when="2026-08-01"),
        ],
        start="2026-09-07",
        end="2026-09-14",
    )
    assert data["summary"]["invoiced"] == 7
    assert data["summary"]["missing"] == 3
    assert data["weekly_report"]["period"]["date_from"] == "2026-09-07"
    assert data["weekly_report"]["counts"]["invoices"] == 2
    assert (
        sum(
            e["units"]
            for e in data["evolution"]
            if e["kind"] == "invoice" and e["grain"] == "week"
        )
        == 7
    )


def test_document_net_price_discount_is_used_to_value_missing_not_tax_total():
    order = evidence("o", quantity=10, amount=80)
    order["source"].update(
        unit_price=10, discount=20, document_total=92, document_tax=12
    )
    invoice = evidence("i", "invoice", "F1", quantity=6, amount=48, reference="OC1")
    data = summary([order, invoice])
    assert data["rows"][0]["ordered_amount"] == 80
    assert data["rows"][0]["unbilled_amount"] == 32


def test_consolidated_product_preserves_evidence_for_each_order():
    data = summary([evidence("o1"), evidence("o2", number="OC2")])
    assert len(data["by_chain_product"]) == 1
    consolidated = data["by_chain_product"][0]
    assert consolidated["ordered"] == 20
    assert consolidated["order_number"] == "Varias OC"
    assert len(consolidated["order_records"]) == 2


def test_extra_product_does_not_make_unbilled_total_unknown():
    data = summary(
        [
            evidence("o"),
            evidence("i", "invoice", "F1", reference="OC1"),
            evidence(
                "i",
                "invoice",
                "F1",
                code="EXTRA",
                quantity=3,
                amount=30,
                reference="OC1",
            ),
        ]
    )
    assert data["summary"]["missing"] == 0
    assert data["summary"]["fulfillment"] == 100
    assert data["summary"]["unbilled_amount"] == 0
    assert data["rows"][1]["status"] == "EXCESO"
