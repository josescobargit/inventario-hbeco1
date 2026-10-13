"""Dashboard and weekly reports use the exact saved-document comparison."""

from collections import defaultdict
from datetime import timedelta

from app.modules.commercial.workflow import day, sum_known


BASIS = (
    "OC fechadas en el período y sus facturas hasta la fecha final; sin fecha final, "
    "todo el histórico. El cumplimiento limita excesos por producto para no "
    "compensar faltantes. Las facturas anuladas/reemplazadas con evidencia no se "
    "suman. Los totales incompletos y las monedas pendientes permanecen sin dato."
)


def comparison_totals(rows):
    """Never turn an unresolved comparison or mixed units into a confirmed zero."""
    rows = list(rows)
    units = {r.get("unit") for r in rows}
    comparable_units = len(units) <= 1 and (not units or bool(next(iter(units))))
    confirmed = [r for r in rows if r["status"] != "REVISAR"]
    uncertain = len(confirmed) != len(rows) or not comparable_units
    ordered = sum_known(r["ordered"] for r in rows) if comparable_units else None
    invoiced = sum_known(r["invoiced"] for r in rows) if not uncertain else None
    missing = sum_known(r["missing"] for r in rows) if not uncertain else None
    currencies = {r.get("currency") for r in rows}
    currency = (
        next(iter(currencies))
        if len(currencies) == 1 and None not in currencies
        else None
    )
    money_confirmed = currency is not None
    invoice_currencies = {r.get("invoiced_currency") for r in rows if r.get("invoiced")}
    invoice_currency = (
        next(iter(invoice_currencies))
        if len(invoice_currencies) == 1 and None not in invoice_currencies
        else None
    )
    invoice_money_confirmed = invoice_currency is not None or not invoice_currencies
    ordered_amount = (
        sum_known(r["ordered_amount"] for r in rows)
        if money_confirmed
        else (0 if not rows else None)
    )
    invoiced_amount = (
        sum_known(r["invoiced_amount"] for r in rows)
        if invoice_money_confirmed and not uncertain
        else (0 if not rows else None)
    )
    unbilled_amount = (
        sum_known(r["unbilled_amount"] for r in rows)
        if money_confirmed and not uncertain
        else (0 if not rows else None)
    )
    status = (
        "REVISAR"
        if uncertain
        else "EXCESO"
        if any(r["status"] == "EXCESO" for r in rows)
        else "COMPLETO"
        if rows and missing == 0
        else "PARCIAL"
        if invoiced
        else "NO FACTURADO"
    )
    return {
        "ordered": ordered,
        "invoiced": invoiced,
        "difference": round(ordered - invoiced, 2)
        if ordered is not None and invoiced is not None
        else None,
        "missing": missing,
        # Per-product excess never contributes to coverage of a different SKU.
        "fulfillment": round((ordered - missing) / ordered * 100, 2)
        if ordered and missing is not None
        else None,
        "ordered_amount": ordered_amount,
        "invoiced_amount": invoiced_amount,
        "unbilled_amount": unbilled_amount,
        "currency": currency,
        "invoiced_currency": invoice_currency
        or (currency if not invoice_currencies else None),
        "quantity_unit": next(iter(units)) if len(units) == 1 else None,
        "known_ordered": sum(r["ordered"] for r in rows if r["ordered"] is not None)
        if comparable_units
        else None,
        "known_invoiced": sum(
            r["invoiced"] for r in confirmed if r["invoiced"] is not None
        )
        if comparable_units
        else None,
        "known_missing": sum(
            r["missing"] for r in confirmed if r["missing"] is not None
        )
        if comparable_units
        else None,
        "known_unbilled_amount": sum_known(r["unbilled_amount"] for r in confirmed)
        if money_confirmed
        else None,
        "confirmed_rows": len(confirmed),
        "review_rows": len(rows) - len(confirmed),
        "missing_valuation_rows": sum(
            r["ordered_amount"] is None
            or r["invoiced_amount"] is None
            or not r.get("currency")
            for r in rows
        ),
        "status": status,
    }


def grouped(rows, keys):
    buckets = defaultdict(list)
    for row in rows:
        buckets[tuple(row.get(key) for key in keys)].append(row)
    results = []
    for key, values in buckets.items():
        result = {**dict(zip(keys, key)), **comparison_totals(values)}
        order_numbers = {r["order_number"] for r in values}
        result["order_number"] = (
            next(iter(order_numbers)) if len(order_numbers) == 1 else "Varias OC"
        )
        for field in ("order_records", "invoices", "pending_records"):
            result[field] = [record for row in values for record in row.get(field, [])]
        results.append(result)
    return results


def rank(rows, field, reverse=True):
    return sorted(
        [r for r in rows if r.get(field) is not None],
        key=lambda r: r[field],
        reverse=reverse,
    )[:10]


def build_commercial_summary(
    workflow,
    start=None,
    end=None,
    chain=None,
    product_id=None,
    line=None,
    target=95,
    economic_threshold=1000,
    **_,
):
    rows = []
    for result in workflow["comparisons"]:
        row = {
            **result,
            "product_name": result["product"],
            "sku": result["code"],
            "pending_records": result.get("pending_records", []),
        }
        # Preserve documented numbers in detail; do not claim a currency when it
        # was not found in the original, and do not consolidate mixed currencies.
        rows.append(row)
    orders, invoices = workflow["orders"], workflow["invoices"]
    documents = orders + invoices
    records = [
        r
        for document in documents
        for r in document.get("evidence_records", document["records"])
    ]
    chains = grouped(rows, ["chain"])
    products = grouped(rows, ["key", "product_name", "sku", "product_id"])
    by_chain_product = grouped(
        rows, ["chain", "key", "product_name", "sku", "product_id"]
    )
    summary = comparison_totals(rows)
    review_docs = [
        d
        for d in documents
        if not d["excluded"] and (d["issues"] or d.get("monetary_issues"))
    ]
    excluded = [d for d in invoices if d["excluded"]]
    summary.update(
        review_documents=len(review_docs),
        review_records=sum(
            bool(r.get("issues") or r.get("monetary_issues"))
            for d in documents
            if not d["excluded"]
            for r in d["records"]
        ),
        excluded_documents=len(excluded),
        excluded_records=sum(len(d["records"]) for d in excluded),
        sell_in_units=None,
        sell_out_units=None,
    )
    alerts = []

    def alert(document, code, message, level="REVISIÓN"):
        alerts.append(
            {
                "level": level,
                "code": code,
                "message": message,
                "record_ids": [r["id"] for r in document["records"]],
                "document_id": document["document_id"],
                "chain": document["chain"],
            }
        )

    for document in documents:
        label = document["filename"] or document["number"] or "Documento"
        if document["excluded"]:
            state = {
                "cancelled": "anulada",
                "replaced": "reemplazada",
                "excluded": "excluida",
            }.get(document["administrative_status"], document["administrative_status"])
            alert(
                document,
                "excluded",
                f"{label}: factura {state}; excluida del comparativo.",
                "MEDIA",
            )
            continue
        problems = list(
            dict.fromkeys(document["issues"] + document.get("monetary_issues", []))
        )
        if problems:
            code = (
                "invoice_without_order"
                if document["kind"] == "invoice" and not document["linked_order_id"]
                else "document_review"
            )
            alert(document, code, f"{label}: " + "; ".join(problems))
        elif document["kind"] == "order" and not document["invoices"]:
            alert(
                document,
                "order_without_invoice",
                f"{label}: OC sin factura vinculada.",
                "MEDIA",
            )
    for row in rows:
        if row["status"] == "REVISAR":
            continue
        refs = [r["id"] for r in row["order_records"] + row["invoices"]]
        if row["status"] == "EXCESO":
            alerts.append(
                {
                    "level": "MEDIA",
                    "code": "excess",
                    "message": f"{row['chain']} · OC {row['order_number']} · {row['product_name']}: {row['invoiced'] - row['ordered']:g} {row['unit']} facturadas por encima de lo pedido.",
                    "record_ids": refs,
                    "chain": row["chain"],
                }
            )
        if (
            row["ordered"]
            and row["invoiced"]
            and row["ordered_amount"] is not None
            and row["invoiced_amount"] is not None
            and row.get("currency")
            and row.get("currency") == row.get("invoiced_currency")
        ):
            ordered_price = row["ordered_amount"] / row["ordered"]
            billed_price = row["invoiced_amount"] / row["invoiced"]
            if abs(ordered_price - billed_price) > 0.02:
                alerts.append(
                    {
                        "level": "MEDIA",
                        "code": "price_difference",
                        "message": f"{row['chain']} · OC {row['order_number']} · {row['product_name']}: precio neto OC {row['currency']} {ordered_price:.4f}; facturado {billed_price:.4f}.",
                        "record_ids": refs,
                        "chain": row["chain"],
                    }
                )
        if row["fulfillment"] is not None and row["fulfillment"] < target:
            alerts.append(
                {
                    "level": "MEDIA",
                    "code": "low_fulfillment",
                    "message": f"{row['chain']} · OC {row['order_number']} · {row['product_name']}: {row['missing']:g} {row['unit']} faltantes; {row['fulfillment']:g}% de entrega.",
                    "record_ids": [
                        r["id"] for r in row["order_records"] + row["invoices"]
                    ],
                    "chain": row["chain"],
                }
            )
        if (
            row["currency"]
            and row["unbilled_amount"] is not None
            and row["unbilled_amount"] >= economic_threshold
            and row["unbilled_amount"] > 0
        ):
            alerts.append(
                {
                    "level": "ALTA",
                    "code": "economic_impact",
                    "message": f"{row['chain']} · {row['product_name']}: {row['currency']} {row['unbilled_amount']:,.2f} pendientes al precio neto de la OC.",
                    "record_ids": [r["id"] for r in row["order_records"]],
                    "chain": row["chain"],
                }
            )
    alerts.sort(key=lambda a: {"ALTA": 0, "MEDIA": 1, "REVISIÓN": 2}[a["level"]])
    evolution_buckets = defaultdict(list)
    for document in documents:
        when = day(document["date"])
        if (
            not when
            or document["excluded"]
            or document["link_blocked"]
            or document["kind"] == "invoice"
            and not document["linked_order_id"]
        ):
            continue
        for item in document["lines"]:
            if item["issues"] or item["quantity"] is None:
                continue
            if (
                product_id
                and item["product_id"] != product_id
                or line
                and item["line"] != line
            ):
                continue
            for grain in ("week", "month"):
                period = (
                    (when - timedelta(days=when.weekday())).isoformat()
                    if grain == "week"
                    else when.strftime("%Y-%m")
                )
                evolution_buckets[(grain, period, document["kind"])].append(item)
    evolution = []
    for (grain, period, kind), items in sorted(evolution_buckets.items()):
        same_unit = len({item["unit"] for item in items}) == 1
        currencies = {item["currency"] for item in items}
        currency = (
            next(iter(currencies))
            if len(currencies) == 1 and None not in currencies
            else None
        )
        evolution.append(
            {
                "grain": grain,
                "period": period,
                "kind": kind,
                "units": sum_known(item["quantity"] for item in items)
                if same_unit
                else None,
                "amount": sum_known(item["amount"] for item in items)
                if currency
                else None,
                "currency": currency,
            }
        )
    rankings = {
        "chains_billed": rank(chains, "invoiced_amount"),
        "chains_low_fulfillment": rank(chains, "fulfillment", False),
        "chains_missing": rank(chains, "missing"),
        "products_ordered": rank(products, "ordered"),
        "products_billed": rank(products, "invoiced"),
        "products_missing": rank(products, "missing"),
        "products_impact": rank(products, "unbilled_amount"),
    }
    filters = {
        "date_from": start,
        "date_to": end,
        "chain": chain,
        "product_id": product_id,
        "line": line,
        "target": target,
        "economic_threshold": economic_threshold,
    }
    critical = {
        "missing": rank(
            [r for r in rows if r["status"] != "REVISAR" and r["missing"] > 0],
            "missing",
        ),
        "not_invoiced": rank(
            [r for r in rows if r["status"] == "NO FACTURADO"], "missing"
        ),
        "economic": rank(
            [
                r
                for r in rows
                if r["status"] != "REVISAR"
                and r["currency"]
                and r["unbilled_amount"] is not None
                and r["unbilled_amount"] > 0
            ],
            "unbilled_amount",
        ),
    }
    return {
        "filters": filters,
        "summary": summary,
        "rows": rows,
        "chains": chains,
        "products": products,
        "by_chain_product": by_chain_product,
        "records": records,
        "alerts": alerts,
        "rankings": rankings,
        "evolution": evolution,
        "basis": BASIS,
        "unmatched_invoices": [
            r
            for d in invoices
            if not d["excluded"] and not d["linked_order_id"]
            for r in d["records"]
        ],
        "weekly_report": {
            "period": {"date_from": start, "date_to": end, "basis": BASIS},
            "summary": summary,
            "chains": chains,
            "critical_products": critical,
            "alerts": alerts,
            "counts": {
                "orders": len(orders),
                **workflow["summary"],
                "review_documents": len(review_docs),
                "excluded_invoices": len(excluded),
            },
        },
    }
