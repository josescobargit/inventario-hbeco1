"""Saved-document commercial flow. Links are reproducible; no inventory mutations."""

from collections import defaultdict
from datetime import date
import re

from app.modules.commercial.normalization import identity, number
from app.modules.purchase_orders.domain.order_profiles import PROFILES


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
    unit = identity(raw.get("unit") or ("units" if quantity is not None else ""))
    if unit in {"units", "unit", "un", "unidad", "unidades", "ud", "uds"}:
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
    if amount is None and price is not None:
        original_qty = numeric(raw.get("quantity", row.get("units")))
        if original_qty is not None:
            amount = original_qty * price
    return dict(
        id=row["id"],
        key=product_key(row),
        name=row["product_name"],
        code=row.get("sku", ""),
        quantity=quantity,
        unit=unit,
        unit_price=price,
        currency=str(raw.get("currency") or "").upper() or None,
        amount=amount,
        issues=row.get("issues", []),
    )


def sum_known(values):
    values = list(values)
    return round(sum(values), 2) if all(v is not None for v in values) else None


def build_workflow(evidence):
    groups = defaultdict(list)
    for row in evidence:
        if row.get("kind") not in {"order", "invoice"} or row.get("excluded"):
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
            records=rows,
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
        signatures = {
            repr(
                (
                    d["date"],
                    d["reference"],
                    d["currency"],
                    d["amount"],
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
        removed.update(d["id"] for d in copies[1:])
        if len(signatures) > 1:
            representative["issues"].append(
                "Existen versiones distintas del mismo número de documento"
            )
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
    orders = [d for d in documents if d["kind"] == "order"]
    invoices = [d for d in documents if d["kind"] == "invoice"]
    for inv in invoices:
        candidates = [
            o
            for o in orders
            if o["chain"] == inv["chain"] and o["chain"] and not o["issues"]
        ]
        if inv["reference"]:
            candidates = [
                o
                for o in candidates
                if reference(o["number"]) == reference(inv["reference"])
            ]
            method = "Número de OC explícito"
        else:
            keys = {line["key"] for line in inv["lines"]}

            def compatible(order):
                if (
                    not order["date"]
                    or not inv["date"]
                    or not keys
                    or not keys <= {line["key"] for line in order["lines"]}
                ):
                    return False
                return (
                    0
                    <= (
                        date.fromisoformat(inv["date"])
                        - date.fromisoformat(order["date"])
                    ).days
                    <= 90
                )

            candidates = [o for o in candidates if compatible(o)]
            method = "Cadena, productos exactos y fecha compatible"
        if len(candidates) == 1 and not inv["issues"]:
            inv["linked_order_id"] = candidates[0]["id"]
            inv["link_method"] = method
        else:
            inv["issues"].append(
                "Varias OC compatibles"
                if len(candidates) > 1
                else "OC pendiente de vincular"
            )
    comparisons = []
    for order in orders:
        linked = [i for i in invoices if i["linked_order_id"] == order["id"]]
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
                i["chain"] == order["chain"]
                and not i["linked_order_id"]
                and (
                    not i["reference"]
                    or reference(i["reference"]) == reference(order["number"])
                )
                and key in {line["key"] for line in i["lines"]}
                for i in invoices
            )
            uncertain = (
                bool(order["issues"])
                or pending_invoice
                or not comparable
                or ordered is None
                or billed is None
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
                max(diff, 0) * ordered_amount / ordered
                if diff is not None and ordered_amount is not None and ordered
                else None
            )
            result_rows.append(
                dict(
                    chain=order["chain"],
                    order_id=order["id"],
                    order_number=order["number"],
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
                    currency=order["currency"],
                    invoiced_currency=next(iter({line["currency"] for line in il}))
                    if len({line["currency"] for line in il}) == 1
                    else order["currency"]
                    if not il
                    else None,
                    unbilled_amount=round(unbilled, 2)
                    if unbilled is not None
                    else None,
                    status=status,
                )
            )
        comparisons.extend(result_rows)
        order["fulfillment"] = (
            round(
                sum(min(r["ordered"], r["invoiced"]) for r in result_rows)
                / sum(r["ordered"] for r in result_rows)
                * 100,
                2,
            )
            if result_rows
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
        invoice["status"] = "OK" if invoice["linked_order_id"] else "REVISAR"
    chains = []
    for chain in sorted({d["chain"] for d in documents}):
        chain_orders = [d for d in orders if d["chain"] == chain]
        chain_invoices = [d for d in invoices if d["chain"] == chain]
        pending = sum(not i["linked_order_id"] for i in chain_invoices)
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
            invoices=len(invoices),
            linked=sum(bool(i["linked_order_id"]) for i in invoices),
            pending=sum(not i["linked_order_id"] for i in invoices),
        ),
    )


def saved_workflow(db):
    from app.modules.commercial.service import records
    from app.modules.commercial.processing import processing_records

    normalized = records(db)
    recognition = {r["id"]: r for r in processing_records(db)}
    evidence = []
    for row in normalized:
        if row["id"] in recognition:
            normalized_units = row["units"]
            normalized_name = row["product_name"]
            recognized = recognition[row["id"]]
            # Catalog uncertainty does not invalidate a readable source document.
            row = {
                **row,
                **recognized,
                "product_id": row["product_id"],
                "excluded": row["excluded"],
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
    return build_workflow(evidence)
