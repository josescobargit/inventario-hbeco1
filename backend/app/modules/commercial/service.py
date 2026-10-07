"""One audited data projection feeds dashboard, assistant and exports."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.modules.catalog.infrastructure.models import Product
from app.modules.commercial.models import (
    CommercialDocument,
    CommercialProductProfile,
    CommercialRecord,
)
from app.modules.commercial.normalization import identity, normalize
from app.modules.invoices.infrastructure.models import Invoice, InvoiceLine
from app.modules.purchase_orders.infrastructure.models import (
    CustomerProductAlias,
    PurchaseOrder,
    PurchaseOrderLine,
)


def catalog_context(db):
    products = list(db.scalars(select(Product).order_by(Product.name)))
    profiles = {
        str(p.product_id): {
            "ean14": p.ean14,
            "presentation": p.presentation,
            "content": p.content,
            "line": p.line,
            "aliases": p.aliases,
        }
        for p in db.scalars(select(CommercialProductProfile))
    }
    aliases = list(db.scalars(select(CustomerProductAlias)))
    return products, profiles, aliases


def records(db):
    products, profiles, aliases = catalog_context(db)
    result = []
    for row, doc in db.execute(
        select(CommercialRecord, CommercialDocument)
        .join(CommercialDocument, CommercialDocument.id == CommercialRecord.document_id)
        .where(CommercialRecord.superseded.is_(False))
        .order_by(CommercialDocument.created_at, CommercialRecord.row_number)
    ):
        raw = {**row.source, **row.corrections}
        item = normalize(raw, products, profiles, aliases)
        if raw.get("extraction_issue") and not row.corrections.get(
            "extraction_confirmed"
        ):
            header_note = (
                raw["extraction_issue"]
                == "Verificar los campos pendientes de la cabecera del documento"
            )
            pending_header = any(
                issue in item["issues"]
                for issue in (
                    "Cadena no identificada",
                    "Fecha ausente o inválida",
                    "Tipo de documento no identificado",
                    "Número de documento ausente",
                )
            )
            # Specific unresolved fields are sufficient; correcting them resolves the
            # generic notice automatically for documents with readable PDF text.
            if not header_note or (not pending_header and doc.method != "pdf_text"):
                item["issues"].append(raw["extraction_issue"])
        item.update(
            id=str(row.id),
            document_id=str(doc.id),
            filename=doc.filename,
            source_location=raw.get("source_location", f"Fila {row.row_number}"),
            source=raw,
            original_source=row.source,
            revision=row.revision,
            origin="import",
            source_url=f"/commercial/documents/{doc.id}/content",
        )
        result.append(item)
    product_map = {p.id: p for p in products}
    orders = {o.id: o for o in db.scalars(select(PurchaseOrder))}
    for line in db.scalars(select(PurchaseOrderLine)):
        order = orders[line.purchase_order_id]
        product = product_map[line.product_id]
        raw = {
            "kind": "order",
            "chain": order.chain_name,
            "date": order.order_date,
            "order_number": order.order_number,
            "product_id": str(product.id),
            "total_units": line.ordered_quantity,
            "status": order.status,
        }
        item = normalize(raw, products, profiles, aliases)
        if not line.conversion_confirmed:
            item["issues"].append("Conversión de la OC sin confirmar")
        item.update(
            id=f"order:{line.id}",
            document_id=f"order:{order.id}",
            filename=f"OC {order.order_number}",
            origin="operational",
            source_location=f"Página {line.source_page or '?'}",
            source_url=f"/purchase-orders/{order.id}",
            source={
                "source_text": line.source_text,
                "original_quantity": line.original_quantity,
                "original_unit": line.original_unit,
                "units_per_box": line.units_per_box,
            },
            revision=0,
        )
        item["conversion"] = (
            f"Original: {line.original_quantity} {line.original_unit}; factor {line.units_per_box}; {line.ordered_quantity} unidades. Método: {line.conversion_method}"
            if line.original_quantity is not None
            else "Unidades registradas en la OC"
        )
        result.append(item)
    for invoice, line in db.execute(
        select(Invoice, InvoiceLine).join(
            InvoiceLine, InvoiceLine.invoice_id == Invoice.id
        )
    ):
        order = orders.get(invoice.purchase_order_id)
        raw = {
            "kind": "invoice",
            "chain": invoice.chain_name or (order.chain_name if order else None),
            "date": invoice.invoice_date,
            "order_number": order.order_number if order else None,
            "invoice_number": invoice.invoice_number,
            "product_id": str(line.product_id),
            "total_units": line.quantity,
            "unit_price": line.unit_price,
            "currency": "USD",
            "status": invoice.administrative_status,
        }
        item = normalize(raw, products, profiles, aliases)
        if (
            order
            and identity(invoice.chain_name)
            and identity(invoice.chain_name) != identity(order.chain_name)
        ):
            item["issues"].append("La cadena de la factura difiere de la OC vinculada")
        item.update(
            id=f"invoice:{line.id}",
            document_id=f"invoice:{invoice.id}",
            filename=f"Factura {invoice.invoice_number}",
            origin="operational",
            source_location="Línea de factura",
            source_url=f"/invoices/{invoice.id}",
            source={
                "invoice_id": str(invoice.id),
                "currency": "USD",
                "purchase_order_id": str(invoice.purchase_order_id)
                if invoice.purchase_order_id
                else None,
            },
            revision=0,
        )
        result.append(item)
    return result


def amount_sum(items, field="amount"):
    values = list(items)
    if not values:
        return Decimal(0)
    if any(item.get(field) is None for item in values):
        return None
    return sum((Decimal(str(item[field])) for item in values), Decimal(0))


def as_number(value):
    return (
        float(value.quantize(Decimal("0.01"))) if isinstance(value, Decimal) else value
    )


def summarize_rows(rows):
    ordered = sum(r["ordered"] for r in rows)
    invoiced = sum(r["invoiced"] for r in rows)
    missing = sum(r["missing"] for r in rows)
    return {
        "ordered": ordered,
        "invoiced": invoiced,
        "missing": missing,
        "difference": ordered - invoiced,
        "fulfillment": round((ordered - missing) / ordered * 100, 2)
        if ordered
        else None,
        "ordered_amount": as_number(amount_sum(rows, "ordered_amount")),
        "invoiced_amount": as_number(amount_sum(rows, "invoiced_amount")),
        "unbilled_amount": as_number(amount_sum(rows, "unbilled_amount")),
        "missing_valuation_rows": sum(
            r["ordered_amount"] is None or r["invoiced_amount"] is None for r in rows
        ),
    }


def aggregate(rows, keys):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in keys)].append(row)
    return [
        {
            **dict(zip(keys, key)),
            **summarize_rows(group),
            "status": "REVISAR"
            if any(r["status"] == "REVISAR" for r in group)
            else "EXCESO"
            if any(r["status"] == "EXCESO" for r in group)
            else "COMPLETO"
            if not sum(r["missing"] for r in group)
            else "PARCIAL"
            if sum(r["invoiced"] for r in group)
            else "NO FACTURADO",
        }
        for key, group in groups.items()
    ]


def in_period(item, start, end):
    return bool(
        item["date"]
        and (not start or item["date"] >= start)
        and (not end or item["date"] <= end)
    )


def analyze(
    all_records,
    start=None,
    end=None,
    chain=None,
    product_id=None,
    line=None,
    target=95,
    economic_threshold=1000,
):
    all_records = [
        {
            **r,
            "issues": list(r["issues"]),
            "monetary_issues": list(r["monetary_issues"]),
        }
        for r in all_records
    ]
    alerts = []

    def alert(level, code, message, refs, **extra):
        alerts.append(
            {
                "level": level,
                "code": code,
                "message": message,
                "record_ids": [r["id"] for r in refs],
                "chain": refs[0]["chain"] if refs else "",
                **extra,
            }
        )

    # Identity duplicates are evaluated against all history, before any filtering.
    groups = defaultdict(list)
    for r in all_records:
        if r["excluded"]:
            continue
        if r["kind"] in ("order", "invoice"):
            key = (
                r["kind"],
                identity(r["chain"]) if r["kind"] == "order" else "",
                r["order_number"] if r["kind"] == "order" else r["invoice_number"],
            )
            if key[-1]:
                groups[key].append(r)
        elif r["kind"] in ("sell_in", "sell_out") and r["product_id"]:
            key = (
                r["kind"],
                identity(r["chain"]),
                r["date"],
                r["product_id"],
                r["units"],
                r["amount"],
            )
            groups[key].append(r)
    duplicate_refs = []
    for group in groups.values():
        if len({r["document_id"] for r in group}) <= 1:
            continue
        # Operational records are already authorized. Imported duplicates do not add units.
        duplicate_refs.append(group)
        for r in group:
            if r["origin"] == "import":
                r["issues"].append(
                    "Posible documento duplicado: excluido hasta revisar identidad y original"
                )
    replacement_refs = []
    for r in all_records:
        if r["replaces"] and not r["excluded"]:
            originals = [
                old
                for old in all_records
                if old["kind"] == "invoice" and old["invoice_number"] == r["replaces"]
            ]
            if not originals or any(not old["excluded"] for old in originals):
                for row in [r, *originals]:
                    row["issues"].append(
                        "Reemplazo requiere evidencia del estado de la factura original"
                    )
                replacement_refs.append([r, *originals])

    def dimensions(r):
        return (
            (not chain or identity(chain) == identity(r["chain"]))
            and (not product_id or r["product_id"] == product_id)
            and (not line or r["line"] == line)
        )

    scoped = [r for r in all_records if dimensions(r)]
    orders = [
        r
        for r in scoped
        if r["kind"] == "order" and (in_period(r, start, end) or not r["date"])
    ]
    cohort = {(identity(r["chain"]), r["order_number"]) for r in orders}
    visible = [
        r
        for r in scoped
        if in_period(r, start, end)
        or not r["date"]
        or (
            r["kind"] == "invoice"
            and (identity(r["chain"]), r["order_number"]) in cohort
            and (not end or r["date"] <= end)
        )
    ]
    visible_ids = {r["id"] for r in visible}
    for group in duplicate_refs:
        if any(r["id"] in visible_ids for r in group):
            alert(
                "ALTA",
                "duplicate",
                "Posible duplicado entre documentos; las copias importadas no se suman.",
                group,
            )
    for group in replacement_refs:
        if any(r["id"] in visible_ids for r in group):
            alert(
                "REVISIÓN",
                "replacement",
                "Factura reemplazada sin evidencia suficiente del estado original.",
                group,
            )
    for r in visible:
        if r["excluded"]:
            alert(
                "REVISIÓN",
                "excluded",
                f"{r['filename']}: estado {r['administrative_status']}; excluido del cálculo.",
                [r],
            )
        elif r["issues"]:
            alert("REVISIÓN", "invalid", "; ".join(r["issues"]), [r])
        if r["monetary_issues"]:
            alert("REVISIÓN", "valuation", "; ".join(r["monetary_issues"]), [r])
    valid = [r for r in scoped if not r["excluded"] and not r["issues"]]
    po_groups = defaultdict(list)
    for r in orders:
        if not r["excluded"] and not r["issues"]:
            po_groups[
                (identity(r["chain"]), r["order_number"], r["product_id"])
            ].append(r)
    invoice_groups = defaultdict(list)
    for r in valid:
        if r["kind"] == "invoice" and (not end or r["date"] <= end):
            invoice_groups[
                (identity(r["chain"]), r["order_number"], r["product_id"])
            ].append(r)
    pending_by_order = defaultdict(list)
    for r in visible:
        if r["kind"] == "invoice" and r["issues"] and not r["excluded"]:
            pending_by_order[
                (identity(r["chain"]), r["order_number"], r["product_id"])
            ].append(r)
    comparison = []
    for key, ordered_rows in po_groups.items():
        invoiced_rows = invoice_groups.get(key, [])
        requested = sum(r["units"] for r in ordered_rows)
        billed = sum(r["units"] for r in invoiced_rows)
        missing = max(requested - billed, 0)
        ordered_amount = amount_sum(ordered_rows)
        invoiced_amount = amount_sum(invoiced_rows)
        unbilled = (
            ordered_amount * Decimal(str(missing)) / Decimal(str(requested))
            if ordered_amount is not None and requested
            else None
        )
        pending = pending_by_order.get(key, []) + pending_by_order.get(
            (*key[:2], None), []
        )
        status = (
            "REVISAR"
            if pending
            else "EXCESO"
            if billed > requested
            else "COMPLETO"
            if billed == requested
            else "PARCIAL"
            if billed
            else "NO FACTURADO"
        )
        first = ordered_rows[0]
        row = {
            k: first[k]
            for k in (
                "chain",
                "product_id",
                "product_name",
                "sku",
                "line",
                "order_number",
                "date",
            )
        }
        row.update(
            ordered=requested,
            invoiced=billed,
            difference=requested - billed,
            missing=missing,
            fulfillment=round(billed / requested * 100, 2) if requested else None,
            ordered_amount=as_number(ordered_amount),
            invoiced_amount=as_number(invoiced_amount),
            unbilled_amount=as_number(unbilled),
            status=status,
            order_records=ordered_rows,
            invoices=invoiced_rows,
            pending_records=pending,
        )
        comparison.append(row)
        if not invoiced_rows:
            alert(
                "ALTA",
                "unbilled",
                f"OC {first['order_number']} · {first['product_name']}: {missing:g} unidades sin facturar.",
                ordered_rows,
            )
        if billed > requested:
            alert(
                "REVISIÓN",
                "excess",
                f"OC {first['order_number']}: {billed - requested:g} unidades facturadas en exceso.",
                [*ordered_rows, *invoiced_rows],
            )
        if ordered_amount is None or invoiced_amount is None:
            alert(
                "REVISIÓN",
                "missing_price",
                f"OC {first['order_number']} · {first['product_name']}: falta precio/subtotal verificable; importe sin calcular.",
                [*ordered_rows, *invoiced_rows],
            )
        if unbilled is not None and unbilled >= Decimal(str(economic_threshold)):
            alert(
                "ALTA",
                "economic_shortfall",
                f"{first['product_name']}: faltante valorado en USD {unbilled:.2f} al precio de la OC.",
                ordered_rows,
            )
        prices = {
            Decimal(r["unit_price"])
            for r in ordered_rows
            if r["unit_price"] is not None
        }
        if prices and any(
            r["unit_price"] is not None and Decimal(r["unit_price"]) not in prices
            for r in invoiced_rows
        ):
            alert(
                "MEDIA",
                "price",
                f"OC {first['order_number']}: precio unitario de factura diferente del pedido.",
                [*ordered_rows, *invoiced_rows],
            )
        if len({r["invoice_number"] for r in invoiced_rows}) > 1:
            alert(
                "REVISIÓN",
                "multiple_invoices",
                f"OC {first['order_number']}: varias facturas sumadas; consultar trazabilidad.",
                invoiced_rows,
            )
    all_order_keys = {
        (identity(r["chain"]), r["order_number"], r["product_id"])
        for r in valid
        if r["kind"] == "order"
    }
    unmatched = []
    for r in valid:
        if (
            r["kind"] == "invoice"
            and in_period(r, start, end)
            and (identity(r["chain"]), r["order_number"], r["product_id"])
            not in all_order_keys
        ):
            unmatched.append(r)
            alert(
                "REVISIÓN",
                "invoice_without_order",
                f"Factura {r['invoice_number']} · {r['product_name']}: no existe OC/producto relacionado con evidencia suficiente.",
                [r],
            )
    chains = aggregate(comparison, ["chain"])
    products = aggregate(comparison, ["product_id", "product_name", "sku", "line"])
    by_chain_product = aggregate(
        comparison, ["chain", "product_id", "product_name", "sku", "line"]
    )
    for c in chains:
        if c["fulfillment"] is not None and c["fulfillment"] < target:
            refs = [r for r in orders if r["chain"] == c["chain"]]
            alert(
                "ALTA",
                "fulfillment",
                f"{c['chain']}: cumplimiento {c['fulfillment']:.1f}% inferior al objetivo {target:g}%.",
                refs,
            )
    sales_records = [
        r
        for r in valid
        if r["kind"] in ("sell_in", "sell_out") and in_period(r, start, end)
    ]
    sales_groups = defaultdict(list)
    for r in sales_records:
        sales_groups[
            (r["kind"], r["chain"], r["product_id"], r["product_name"], r["line"])
        ].append(r)
    sales = [
        {
            **dict(zip(("kind", "chain", "product_id", "product_name", "line"), key)),
            "units": sum(r["units"] for r in group),
            "amount": as_number(amount_sum(group)),
            "record_ids": [r["id"] for r in group],
        }
        for key, group in sales_groups.items()
    ]
    for sale in sales:
        total = sum(s["units"] for s in sales if s["kind"] == sale["kind"])
        sale["share"] = round(sale["units"] / total * 100, 2) if total else None
    sell_comparison = []
    keys = {(s["chain"], s["product_id"], s["product_name"]) for s in sales}
    for c, p, name in sorted(keys):
        si = next(
            (
                s
                for s in sales
                if s["kind"] == "sell_in" and s["chain"] == c and s["product_id"] == p
            ),
            None,
        )
        so = next(
            (
                s
                for s in sales
                if s["kind"] == "sell_out" and s["chain"] == c and s["product_id"] == p
            ),
            None,
        )
        # Equal coverage is required, but still cannot prove actual stock.
        si_dates = {
            r["date"]
            for r in sales_records
            if r["kind"] == "sell_in" and r["chain"] == c and r["product_id"] == p
        }
        so_dates = {
            r["date"]
            for r in sales_records
            if r["kind"] == "sell_out" and r["chain"] == c and r["product_id"] == p
        }
        hypothesis = (
            "Cobertura incompleta: no se puede concluir sobre inventario o reposición."
        )
        if si and so and si_dates == so_dates:
            if si["units"] > so["units"]:
                hypothesis = "Posible acumulación; confirmar inventario inicial, devoluciones y cobertura."
            elif so["units"] > si["units"]:
                hypothesis = "Posible oportunidad de reposición; confirmar existencias y abastecimiento."
            else:
                hypothesis = "Flujos iguales en las fechas disponibles; no demuestra equilibrio de inventario."
        sell_comparison.append(
            {
                "chain": c,
                "product_name": name,
                "sell_in": si["units"] if si else None,
                "sell_out": so["units"] if so else None,
                "difference": si["units"] - so["units"]
                if si and so and si_dates == so_dates
                else None,
                "hypothesis": hypothesis,
            }
        )
    evolution = []
    for grain in ("week", "month"):
        buckets = defaultdict(list)
        for r in sales_records + [
            r
            for r in valid
            if r["kind"] in ("invoice", "order") and in_period(r, start, end)
        ]:
            day = date.fromisoformat(r["date"])
            period = (
                (day - timedelta(days=day.weekday())).isoformat()
                if grain == "week"
                else day.strftime("%Y-%m")
            )
            buckets[(grain, period, r["kind"])].append(r)
        evolution.extend(
            {
                "grain": g,
                "period": p,
                "kind": k,
                "units": sum(r["units"] for r in group),
                "amount": as_number(amount_sum(group)),
            }
            for (g, p, k), group in sorted(buckets.items())
        )
    monthly_sales = defaultdict(lambda: defaultdict(list))
    for r in sales_records:
        monthly_sales[(r["kind"], r["chain"], r["product_id"], r["product_name"])][
            r["date"][:7]
        ].append(r)
    sales_movements = []
    for (kind, chain_name, product, name), periods in monthly_sales.items():
        months = sorted(periods)
        if len(months) < 2:
            continue
        before, after = months[-2:]
        before_date = date.fromisoformat(before + "-01")
        after_date = date.fromisoformat(after + "-01")
        if (
            after_date.year - before_date.year
        ) * 12 + after_date.month - before_date.month != 1:
            continue
        old = sum(r["units"] for r in periods[before])
        new = sum(r["units"] for r in periods[after])
        variation = round((new - old) / old * 100, 2) if old else None
        sales_movements.append(
            {
                "kind": kind,
                "chain": chain_name,
                "product_name": name,
                "product_id": product,
                "previous_period": before,
                "period": after,
                "previous": old,
                "current": new,
                "variation": variation,
            }
        )
        if kind == "sell_out" and variation is not None and variation <= -20:
            alert(
                "MEDIA",
                "sell_out_decline",
                f"{chain_name} · {name}: Sell Out registrado cae {abs(variation):.1f}% entre {before} y {after}. Verificar cobertura de ambos meses antes de concluir caída real.",
                [*periods[before], *periods[after]],
            )
    sales_by_line = []
    for kind, product_line in sorted({(r["kind"], r["line"]) for r in sales_records}):
        group = [
            r for r in sales_records if r["kind"] == kind and r["line"] == product_line
        ]
        sales_by_line.append(
            {
                "kind": kind,
                "line": product_line,
                "units": sum(r["units"] for r in group),
                "amount": as_number(amount_sum(group)),
            }
        )
    summary = summarize_rows(comparison)
    summary.update(
        review_records=sum(
            bool(r["issues"] or r["monetary_issues"])
            for r in visible
            if not r["excluded"]
        ),
        excluded_records=sum(r["excluded"] for r in visible),
        sell_in_units=sum(s["units"] for s in sales if s["kind"] == "sell_in")
        if any(s["kind"] == "sell_in" for s in sales)
        else None,
        sell_out_units=sum(s["units"] for s in sales if s["kind"] == "sell_out")
        if any(s["kind"] == "sell_out" for s in sales)
        else None,
    )
    alerts.sort(key=lambda a: {"ALTA": 0, "MEDIA": 1, "REVISIÓN": 2}[a["level"]])

    def ranking(items, field, reverse=True):
        return sorted(
            [r for r in items if r.get(field) is not None],
            key=lambda r: r[field],
            reverse=reverse,
        )[:10]

    return {
        "filters": {
            "date_from": start,
            "date_to": end,
            "chain": chain,
            "product_id": product_id,
            "line": line,
            "target": target,
            "economic_threshold": economic_threshold,
        },
        "summary": summary,
        "rows": comparison,
        "chains": chains,
        "products": products,
        "by_chain_product": by_chain_product,
        "sales": sales,
        "sales_movements": sales_movements,
        "sales_by_line": sales_by_line,
        "sell_comparison": sell_comparison,
        "evolution": evolution,
        "alerts": alerts,
        "records": visible,
        "unmatched_invoices": unmatched,
        "rankings": {
            "chains_billed": ranking(chains, "invoiced_amount"),
            "chains_low_fulfillment": ranking(chains, "fulfillment", False),
            "chains_missing": ranking(chains, "missing"),
            "products_ordered": ranking(products, "ordered"),
            "products_billed": ranking(products, "invoiced"),
            "products_missing": ranking(products, "missing"),
            "products_impact": ranking(products, "unbilled_amount"),
        },
        "basis": "OC fechadas en el período y sus facturas hasta la fecha final (o todo el histórico si no hay fecha final). Sell In/Out por fecha del reporte. Importes netos USD; faltante valorado al precio de la OC. Cumplimiento general limita excesos por producto para no compensar faltantes. Datos dudosos excluidos; importes incompletos se muestran sin dato.",
    }


def executive_report(data):
    s = data["summary"]

    def money(value):
        return (
            f"USD {value:,.2f}" if value is not None else "sin dato completo (REVISAR)"
        )

    pct = (
        f"{s['fulfillment']:.1f}%"
        if s["fulfillment"] is not None
        else "sin pedidos comparables"
    )
    lines = [
        f"Se pidieron {s['ordered']:g} unidades y se facturaron {s['invoiced']:g} unidades vinculadas a esas OC. Cumplimiento: {pct}.",
        f"Pedido: {money(s['ordered_amount'])}. Facturado: {money(s['invoiced_amount'])}.",
        f"Quedaron {s['missing']:g} unidades pendientes, valoradas en {money(s['unbilled_amount'])} al precio del pedido.",
    ]
    for c in data["rankings"]["chains_low_fulfillment"][:3]:
        lines.append(
            f"{c['chain']}: {c['fulfillment']:.1f}% de cumplimiento; {c['missing']:g} unidades faltantes."
        )
    for p in data["rankings"]["products_missing"][:3]:
        if p["missing"]:
            lines.append(
                f"{p['product_name']}: {p['missing']:g} unidades pendientes; impacto {money(p['unbilled_amount'])}."
            )
    for kind, label in (("sell_in", "Sell In"), ("sell_out", "Sell Out")):
        sales = [r for r in data["sales"] if r["kind"] == kind]
        lines.append(
            f"{label}: {sum(r['units'] for r in sales):g} unidades; {money(amount_sum(sales))}."
            if sales
            else f"{label}: no hay datos válidos en este período."
        )
    for movement in data["sales_movements"][:5]:
        if movement["variation"] is not None:
            lines.append(
                f"{movement['kind'].replace('_', ' ').title()} · {movement['chain']} · {movement['product_name']}: variación registrada {movement['variation']:+.1f}% ({movement['previous_period']} vs {movement['period']}); verificar cobertura."
            )
    lines.append(
        f"{len(data['alerts'])} alertas; {s['review_records']} registros requieren revisión. Los datos dudosos no forman parte de los totales confirmados."
    )
    lines.extend(a["message"] for a in data["alerts"][:5])
    return lines
