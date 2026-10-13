"""Saved-document commercial flow. Links are reproducible; no inventory mutations."""

from collections import defaultdict
from datetime import date
import re

from app.modules.commercial.normalization import identity, number
from app.modules.purchase_orders.domain.order_profiles import PROFILES


CANCELLED_STATES = {"anulada", "anulado", "cancelled", "canceled", "void"}
REPLACED_STATES = {"reemplazada", "reemplazado", "replaced"}
ACTIVE_STATES = {
    "activo",
    "active",
    "confirmed",
    "confirmada",
    "confirmado",
    "open",
    "completed",
    "partially_invoiced",
}


def administrative_state(row):
    raw = row.get("source", {})
    state = identity(raw.get("status") or row.get("administrative_status") or "activo")
    if state in CANCELLED_STATES:
        return "cancelled"
    if state in REPLACED_STATES:
        return "replaced"
    if row.get("excluded") or state == "excluido":
        return "excluded"
    return "active" if state in ACTIVE_STATES else "review"


def append_issue(document, message):
    if message not in document["issues"]:
        document["issues"].append(message)


def day(value):
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def period_matches(value, start=None, end=None):
    when = day(value)
    return bool(
        when and (not start or when >= day(start)) and (not end or when <= day(end))
    )


def document_financials(rows, currency):
    fields = {
        "subtotal": "document_subtotal",
        "discount": "document_discount",
        "tax": "document_tax",
        "total": "document_total",
    }
    result = {"currency": currency}
    for name, source_field in fields.items():
        values = {numeric(r.get("source", {}).get(source_field)) for r in rows} - {None}
        result[name] = next(iter(values)) if len(values) == 1 else None
    return result


def chain_name(value):
    key = identity(value)
    aliases = {
        "favorita": "CORPORACIÓN FAVORITA",
        "rosado": "CORPORACIÓN EL ROSADO",
        "el rosado": "CORPORACIÓN EL ROSADO",
        "danec": "INDUSTRIAL DANEC",
        "liris": "LIRIS DEL PORTAL",
        "tiendas tuti": "TUTI",
    }
    for profile in PROFILES:
        if key in {
            identity(profile["canonical"]),
            identity(profile["legal"]),
            *(identity(a) for a in profile["aliases"]),
        }:
            return profile["canonical"]
    return aliases.get(key, str(value or "").strip())


def reference(value):
    # Preserve meaningful leading zeros and letters; normalize only separators.
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def numeric(value):
    try:
        result = number(value)
        return float(result) if result is not None else None
    except ValueError:
        return None


def product_key(row):
    if row.get("product_id"):
        return "catalog:" + str(row["product_id"])
    raw = row.get("source", {})
    code = raw.get("ean") or raw.get("code") or row.get("sku")
    return (
        "code:" + reference(code)
        if code
        else "name:" + identity(row.get("product_name"))
    )


def line_view(row):
    raw = row.get("source", {})
    quantity = numeric(raw.get("quantity", row.get("units")))
    unit = identity(
        raw.get("unit")
        or (
            "units"
            if raw.get("total_units") is not None
            or row.get("origin") == "operational"
            and row.get("units") is not None
            else ""
        )
    )
    if unit in {"units", "unit", "un", "u", "und", "unidad", "unidades", "ud", "uds"}:
        unit = "unidades"
    elif unit in {"boxes", "cajas", "caja", "cj"}:
        unit = "cajas"
    factor = numeric(raw.get("units_per_box"))
    if raw.get("total_units") is not None:
        quantity, unit = numeric(raw["total_units"]), "unidades"
    elif unit == "cajas" and factor and factor > 0 and quantity is not None:
        quantity, unit = quantity * factor, "unidades"
    # Normalized catalog quantities incorporate confirmed catalog conversions.
    if (
        row.get("product_id")
        and row.get("units") is not None
        and not any("convers" in identity(i) for i in row.get("issues", []))
    ):
        quantity, unit = row["units"], "unidades"
    amount = numeric(raw.get("amount", row.get("amount")))
    price = numeric(raw.get("unit_price", row.get("unit_price")))
    discount = numeric(raw.get("discount"))
    if amount is None and price is not None:
        original_qty = numeric(raw.get("quantity", row.get("units")))
        if original_qty is not None:
            amount = original_qty * price - (discount or 0)
    # The subtotal is net of discounts and uses the original unit. Once quantity
    # has been converted to units, divide the net subtotal by that quantity.
    net_price = amount / quantity if amount is not None and quantity else None
    if row.get("monetary_issues"):
        amount = net_price = None
    return dict(
        id=row["id"],
        key=product_key(row),
        product_id=row.get("product_id"),
        line=row.get("line", ""),
        name=row["product_name"],
        code=row.get("sku", ""),
        quantity=quantity,
        unit=unit,
        unit_price=price,
        net_unit_price=net_price,
        discount=discount,
        currency=str(raw.get("currency") or "").upper() or None,
        amount=amount,
        issues=row.get("issues", []),
        comparison_issues=[
            issue
            for issue in row.get("issues", [])
            if issue
            not in {
                "Fecha ausente o inválida",
                "Fecha de OC pendiente",
                "Fecha de factura pendiente",
            }
        ],
        monetary_issues=row.get("monetary_issues", []),
        identity_unresolved=not row.get("product_id")
        and bool(row.get("catalog_issues")),
    )


def sum_known(values):
    values = list(values)
    return round(sum(values), 2) if all(v is not None for v in values) else None


def build_workflow(
    evidence, start=None, end=None, chain=None, product_id=None, line=None, **_
):
    filter_line = line
    groups = defaultdict(list)
    for row in evidence:
        if row.get("kind") not in {"order", "invoice"}:
            continue
        number_ = (
            row.get("invoice_number")
            if row["kind"] == "invoice"
            else row.get("order_number")
        )
        groups[
            (
                row["document_id"],
                row["kind"],
                chain_name(row.get("chain")),
                reference(number_),
            )
        ].append(row)
    documents = []
    for (document_id, kind, canonical_chain, _), rows in groups.items():
        first = rows[0]
        lines = [line_view(r) for r in rows]
        problems = list(dict.fromkeys(i for r in rows for i in r.get("issues", [])))
        if len({r.get("date") for r in rows}) > 1:
            problems.append("Fechas contradictorias dentro del documento")
        if (
            kind == "invoice"
            and len({reference(r.get("order_number")) for r in rows}) > 1
        ):
            problems.append("Referencias de OC contradictorias")
        states = {administrative_state(r) for r in rows}
        state = next(iter(states)) if len(states) == 1 else "review"
        if len(states) > 1 or state == "review":
            problems.append("Estado administrativo contradictorio o pendiente")
        replacements = {
            reference(r.get("source", {}).get("replaces") or r.get("replaces"))
            for r in rows
        } - {""}
        replaced_by = {
            reference(r.get("source", {}).get("replaced_by")) for r in rows
        } - {""}
        if len(replacements) > 1 or len(replaced_by) > 1:
            problems.append("Referencias de reemplazo contradictorias")
        doc = dict(
            id=f"{document_id}:{kind}:{reference(canonical_chain)}:{reference(first.get('invoice_number') if kind == 'invoice' else first.get('order_number'))}",
            document_id=document_id,
            kind=kind,
            number=first.get("invoice_number")
            if kind == "invoice"
            else first.get("order_number"),
            chain=canonical_chain,
            date=first.get("date"),
            filename=first.get("filename"),
            origin=first.get("origin"),
            reference=first.get("order_number", "") if kind == "invoice" else "",
            lines=lines,
            issues=problems,
            monetary_issues=list(
                dict.fromkeys(i for r in rows for i in r.get("monetary_issues", []))
            ),
            records=rows,
            evidence_records=rows,
            administrative_status=state,
            excluded=state in {"cancelled", "replaced", "excluded"},
            replaces=next(iter(replacements)) if len(replacements) == 1 else None,
            replaced_by=next(iter(replaced_by)) if len(replaced_by) == 1 else None,
            candidate_order_ids=[],
            link_blocked=state == "review"
            or len(replacements) > 1
            or len(replaced_by) > 1
            or any("contradictori" in identity(p) for p in problems),
            linked_order_id=None,
            link_method=None,
        )
        doc["quantity"] = (
            sum_known(line["quantity"] for line in lines)
            if len({line["unit"] for line in lines}) == 1
            else None
        )
        currencies = {line["currency"] for line in lines}
        doc["currency"] = next(iter(currencies)) if len(currencies) == 1 else None
        doc["financials"] = document_financials(rows, doc["currency"])
        doc["references"] = sorted(
            {
                reference(value)
                for r in rows
                for value in [
                    r.get("order_number"),
                    r.get("source", {}).get("secondary_reference"),
                    r.get("source", {}).get("order_reference"),
                    r.get("source", {}).get("pedido_reference"),
                    r.get("source", {}).get("purchase_order_reference"),
                ]
                if value
            }
        )
        # Liris prints "OC_" as the document label; its invoice prints the same
        # numeric reference without that label. Keep every leading zero.
        liris_number = re.fullmatch(r"OC[_-](\d+)", str(doc["number"] or "").upper())
        if kind == "order" and canonical_chain == "LIRIS DEL PORTAL" and liris_number:
            doc["references"] = sorted(set(doc["references"]) | {liris_number.group(1)})
        if kind == "invoice" and not doc["reference"]:
            if len(doc["references"]) == 1:
                doc["reference"] = doc["references"][0]
            elif len(doc["references"]) > 1:
                doc["link_blocked"] = True
                append_issue(doc, "Referencias de OC contradictorias")
        doc["quantity_unit"] = lines[0]["unit"] if lines else ""
        totals = {numeric(r.get("source", {}).get("document_total")) for r in rows} - {
            None
        }
        doc["amount"] = (
            next(iter(totals))
            if len(totals) == 1
            else sum_known(line["amount"] for line in lines)
        )
        documents.append(doc)
    # Group business identity separately from file identity, preserving conflicting versions.
    identities = defaultdict(list)
    for doc in documents:
        if doc["chain"] and doc["number"]:
            identities[(doc["kind"], doc["chain"], reference(doc["number"]))].append(
                doc
            )
    removed = set()
    for copies in identities.values():
        all_copies = list(copies)
        selected = [d for d in copies if d["administrative_status"] != "excluded"]
        if selected:
            removed.update(
                d["id"] for d in copies if d["administrative_status"] == "excluded"
            )
            copies = selected
        signatures = {
            repr(
                (
                    d["date"],
                    d["reference"],
                    d["currency"],
                    d["amount"],
                    d["administrative_status"],
                    d["replaces"],
                    d["replaced_by"],
                    sorted(
                        [
                            (
                                line["key"],
                                identity(line["name"]),
                                line["unit"],
                                line["quantity"],
                                line["amount"],
                            )
                            for line in d["lines"]
                        ],
                        key=repr,
                    ),
                )
            )
            for d in copies
        }
        # A business document occupies one position even when its versions conflict.
        copies.sort(key=lambda d: (d["origin"] != "operational", len(d["issues"])))
        representative = copies[0]
        representative["evidence_records"] = [
            r for d in all_copies for r in d["records"]
        ]
        representative["copies"] = [
            dict(
                id=d["id"],
                document_id=d["document_id"],
                filename=d["filename"],
                administrative_status=d["administrative_status"],
            )
            for d in all_copies
        ]
        removed.update(d["id"] for d in copies[1:])
        if len(signatures) > 1:
            representative["issues"].append(
                "Existen versiones distintas del mismo número de documento"
            )
            representative["link_blocked"] = True
            # Conflicting copies never decide whether an invoice is active.
            if len({d["administrative_status"] for d in copies}) > 1:
                representative["administrative_status"] = "review"
                representative["excluded"] = False
            representative["versions"] = [
                dict(
                    id=d["id"],
                    document_id=d["document_id"],
                    filename=d["filename"],
                    date=d["date"],
                    origin=d["origin"],
                    lines=d["lines"],
                    records=d["records"],
                )
                for d in copies
            ]
    documents = [d for d in documents if d["id"] not in removed]
    orders = [d for d in documents if d["kind"] == "order" and not d["excluded"]]
    invoices = [d for d in documents if d["kind"] == "invoice"]
    # A replacement number alone does not prove the original is invalid. Require
    # an explicit cancelled/replaced original before including the replacement.
    for inv in invoices:
        if inv["excluded"] or not inv["replaces"]:
            continue
        originals = [
            old
            for old in invoices
            if old["chain"] == inv["chain"]
            and reference(old["number"]) == inv["replaces"]
        ]
        if not originals or any(not old["excluded"] for old in originals):
            for document in [inv, *originals]:
                document["link_blocked"] = True
                append_issue(
                    document,
                    "Reemplazo requiere evidencia del estado de la factura original",
                )
    for old in invoices:
        if old["excluded"] and old["replaced_by"]:
            replacements = [
                inv
                for inv in invoices
                if inv["chain"] == old["chain"]
                and reference(inv["number"]) == old["replaced_by"]
            ]
            for inv in replacements:
                if inv["replaces"] and inv["replaces"] != reference(old["number"]):
                    inv["link_blocked"] = True
                    append_issue(inv, "Referencias de reemplazo contradictorias")
    for inv in invoices:
        if inv["excluded"]:
            continue
        candidates = [
            o
            for o in orders
            if o["chain"] == inv["chain"] and o["chain"] and not o["link_blocked"]
        ]
        if inv["reference"]:
            candidates = [
                o for o in candidates if reference(inv["reference"]) in o["references"]
            ]
            method = "Número de OC explícito"
        else:
            keys = {line["key"] for line in inv["lines"]}

            def compatible(order):
                if (
                    not day(order["date"])
                    or not day(inv["date"])
                    or not keys
                    or any(item["comparison_issues"] for item in inv["lines"])
                    or not keys <= {line["key"] for line in order["lines"]}
                ):
                    return False
                return 0 <= (day(inv["date"]) - day(order["date"])).days <= 90

            candidates = [o for o in candidates if compatible(o)]
            method = "Cadena, productos exactos y fecha compatible"
        inv["candidate_order_ids"] = [candidate["id"] for candidate in candidates]
        if len(candidates) == 1 and not inv["link_blocked"]:
            inv["linked_order_id"] = candidates[0]["id"]
            inv["link_method"] = method
        else:
            append_issue(
                inv,
                "Varias OC compatibles"
                if len(candidates) > 1
                else "OC pendiente de vincular",
            )
    # Filter after linking all history: a second OC outside the selected period
    # remains a real candidate and must not create a false unique match.
    selected_orders = [
        o
        for o in orders
        if (not chain or chain_name(chain) == o["chain"])
        and (period_matches(o["date"], start, end) or not day(o["date"]))
    ]
    selected_ids = {o["id"] for o in selected_orders}
    invoices = [
        inv
        for inv in invoices
        if (not chain or chain_name(chain) == inv["chain"])
        and (not end or not day(inv["date"]) or day(inv["date"]) <= day(end))
        and (
            inv["linked_order_id"] in selected_ids
            or not inv["linked_order_id"]
            and (period_matches(inv["date"], start, end) or not day(inv["date"]))
        )
    ]
    orders = selected_orders
    comparisons = []
    for order in orders:
        linked = [
            i
            for i in invoices
            if not i["excluded"] and i["linked_order_id"] == order["id"]
        ]
        order["invoices"] = [
            dict(
                id=i["id"], number=i["number"], date=i["date"], method=i["link_method"]
            )
            for i in linked
        ]
        buckets = defaultdict(lambda: {"orders": [], "invoices": []})
        for line in order["lines"]:
            buckets[line["key"]]["orders"].append(line)
        for invoice in linked:
            for line in invoice["lines"]:
                buckets[line["key"]]["invoices"].append(line)
        result_rows = []
        for key, group in buckets.items():
            ol, il = group["orders"], group["invoices"]
            sample = (ol or il)[0]
            comparable = len({line["unit"] for line in ol + il}) == 1 and bool(
                sample["unit"]
            )
            ordered = sum_known(line["quantity"] for line in ol)
            billed = sum_known(line["quantity"] for line in il)
            pending_invoice = any(
                not i["excluded"]
                and i["chain"] == order["chain"]
                and not i["linked_order_id"]
                and (
                    order["id"] in i["candidate_order_ids"]
                    or reference(i["reference"]) in order["references"]
                    or i["link_blocked"]
                    and not i["reference"]
                )
                and key in {line["key"] for line in i["lines"]}
                for i in invoices
            )
            uncertain = (
                order["link_blocked"]
                or pending_invoice
                or any(item["comparison_issues"] for item in ol + il)
                or not comparable
                or ordered is None
                or billed is None
                or bool(linked)
                and (
                    bool(ol)
                    and not il
                    and any(item["identity_unresolved"] for item in ol)
                    or bool(il)
                    and not ol
                    and any(item["identity_unresolved"] for item in order["lines"])
                )
            )
            if (
                uncertain
                and bool(linked)
                and (
                    any(item["identity_unresolved"] for item in ol)
                    or il
                    and not ol
                    and any(item["identity_unresolved"] for item in order["lines"])
                )
            ):
                append_issue(
                    order,
                    "Hay productos pendientes de equivalencia para el comparativo",
                )
            status = (
                "REVISAR"
                if uncertain
                else "EXCESO"
                if billed > ordered
                else "COMPLETO"
                if billed == ordered
                else "PARCIAL"
                if billed
                else "NO FACTURADO"
            )
            ordered_amount = sum_known(line["amount"] for line in ol)
            billed_amount = (
                sum_known(line["amount"] for line in il)
                if len({line["currency"] for line in il}) <= 1
                else None
            )
            diff = (
                ordered - billed
                if comparable and ordered is not None and billed is not None
                else None
            )
            # Missing quantity is valued at the OC price, never inferred from invoice totals.
            unbilled = (
                0
                if diff is not None and diff <= 0
                else max(diff, 0) * ordered_amount / ordered
                if diff is not None and ordered_amount is not None and ordered
                else None
            )
            order_currencies = {line["currency"] for line in ol}
            row_currency = (
                next(iter(order_currencies))
                if len(order_currencies) == 1
                else order["currency"]
                if not ol
                else None
            )
            result_rows.append(
                dict(
                    chain=order["chain"],
                    order_id=order["id"],
                    order_number=order["number"],
                    product_id=sample["product_id"],
                    line=sample["line"],
                    key=key,
                    product=sample["name"],
                    code=sample["code"],
                    unit=sample["unit"],
                    ordered=ordered,
                    invoiced=billed if comparable else None,
                    difference=diff,
                    missing=max(diff, 0) if diff is not None else None,
                    fulfillment=round(billed / ordered * 100, 2)
                    if comparable and ordered and billed is not None
                    else None,
                    ordered_amount=ordered_amount,
                    invoiced_amount=billed_amount,
                    currency=row_currency,
                    invoiced_currency=next(iter({line["currency"] for line in il}))
                    if len({line["currency"] for line in il}) == 1
                    else row_currency
                    if not il
                    else None,
                    unbilled_amount=round(unbilled, 2)
                    if unbilled is not None
                    else None,
                    status=status,
                    order_records=[
                        r for r in order["records"] if product_key(r) == key
                    ],
                    invoices=[
                        r for i in linked for r in i["records"] if product_key(r) == key
                    ],
                    pending_records=[
                        r
                        for i in invoices
                        if not i["excluded"]
                        and not i["linked_order_id"]
                        and order["id"] in i["candidate_order_ids"]
                        for r in i["records"]
                        if product_key(r) == key
                    ],
                )
            )
        if product_id or filter_line:
            result_rows = [
                r
                for r in result_rows
                if (not product_id or r["product_id"] == product_id)
                and (not filter_line or r["line"] == filter_line)
            ]
        comparisons.extend(result_rows)
        order["fulfillment"] = (
            round(
                sum(min(r["ordered"], r["invoiced"]) for r in result_rows)
                / sum(r["ordered"] for r in result_rows)
                * 100,
                2,
            )
            if result_rows
            and len({r["unit"] for r in result_rows}) == 1
            and all(r["status"] != "REVISAR" for r in result_rows)
            and sum(r["ordered"] for r in result_rows)
            else None
        )
        order["status"] = (
            "REVISAR"
            if any(r["status"] == "REVISAR" for r in result_rows)
            else "COMPLETO"
            if all(r["status"] == "COMPLETO" for r in result_rows)
            else "EXCESO"
            if any(r["status"] == "EXCESO" for r in result_rows)
            else "PARCIAL"
            if linked
            else "NO FACTURADO"
        )
    for invoice in invoices:
        invoice["status"] = (
            "OK"
            if invoice["excluded"]
            or invoice["linked_order_id"]
            and not invoice["issues"]
            and not invoice["monetary_issues"]
            else "REVISAR"
        )
    chains = []
    for chain in sorted({d["chain"] for d in orders + invoices}):
        chain_orders = [d for d in orders if d["chain"] == chain]
        chain_invoices = [
            d for d in invoices if d["chain"] == chain and not d["excluded"]
        ]
        pending = sum(i["status"] == "REVISAR" for i in chain_invoices)
        chains.append(
            dict(
                chain=chain or "Sin identificar",
                orders=len(chain_orders),
                invoices=len(chain_invoices),
                linked=sum(bool(i["linked_order_id"]) for i in chain_invoices),
                linked_orders=len(
                    {
                        i["linked_order_id"]
                        for i in chain_invoices
                        if i["linked_order_id"]
                    }
                ),
                pending=pending,
                status="REVISAR"
                if pending or any(d["issues"] for d in chain_orders)
                else "OK",
            )
        )
    return dict(
        orders=orders,
        invoices=invoices,
        comparisons=comparisons,
        chains=chains,
        summary=dict(
            invoices=sum(not i["excluded"] for i in invoices),
            linked=sum(
                bool(i["linked_order_id"]) for i in invoices if not i["excluded"]
            ),
            pending=sum(
                i["status"] == "REVISAR" for i in invoices if not i["excluded"]
            ),
            excluded_invoices=sum(i["excluded"] for i in invoices),
        ),
    )


def saved_evidence(db):
    from app.modules.commercial.service import records
    from app.modules.commercial.processing import processing_records

    normalized = records(db)
    recognition = {r["id"]: r for r in processing_records(db)}
    evidence = []
    for row in normalized:
        if row["id"] in recognition:
            normalized_units = row["units"]
            normalized_name = row["product_name"]
            monetary_issues = row.get("monetary_issues", [])
            recognized = recognition[row["id"]]
            catalog_issues = [
                issue
                for issue in row.get("issues", [])
                if issue not in recognized["issues"]
            ]
            blocking_catalog_issues = [
                issue
                for issue in catalog_issues
                if any(
                    word in identity(issue)
                    for word in (
                        "contrad",
                        "conflic",
                        "difier",
                        "conversion",
                        "inconsistente",
                        "ambiguo",
                    )
                )
            ]
            # Catalog uncertainty does not invalidate a readable source document.
            row = {
                **row,
                **recognized,
                "product_id": row["product_id"],
                "excluded": row["excluded"],
                "monetary_issues": monetary_issues,
                "catalog_issues": catalog_issues,
                "issues": list(
                    dict.fromkeys([*recognized["issues"], *blocking_catalog_issues])
                ),
            }
            if row["product_id"]:
                row["units"] = normalized_units
                if not row["product_name"]:
                    row["product_name"] = normalized_name
                    row["issues"] = [
                        i
                        for i in row["issues"]
                        if i != "Descripción del producto pendiente"
                    ]
        evidence.append(row)
    return evidence


def saved_workflow(db, **filters):
    return build_workflow(saved_evidence(db), **filters)
