"""Read invoice identity and detail before catalog matching or OC linking.

The buyer block and labeled evidence determine identity. Neither the filename,
the issuer nor an authorization timestamp substitutes invoice metadata.
"""

import re
from decimal import Decimal

from app.modules.commercial.normalization import identity, number, parse_date
from app.modules.purchase_orders.domain.order_profiles import PROFILES


INVOICE_NUMBER = r"\d{3}\s*-\s*\d{3}\s*-\s*\d{6,9}"
NUMERIC = r"-?\d[\d.,]*"
DATE = r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
PAGE_MARKER = re.compile(r"^\[\[PAGE:(\d+)]]$")
FOOTER = re.compile(
    r"(?i)^\s*(?:informaci[oó]n\s+adicional|formas?\s+de\s+pago|"
    r"subtotal|sub\s+total|valor\s+total|total\s+(?:factura|a\s+pagar)|"
    r"descuentos?\s*:|iva\s*\d|observaciones?\s*:|condiciones?\s+de\s+pago)"
)

# These RUCs are present in verified invoice buyer blocks. Recognition does not
# fill a RUC into a document when it is absent from the original evidence.
BUYER_RUCS = {
    **{str(p["ruc"]): p["canonical"] for p in PROFILES if p["ruc"]},
    "0990004196001": "CORPORACIÓN EL ROSADO",
    "0190072002001": "GERARDO ORTIZ",
}


def _compact(value):
    return re.sub(r"[^a-z0-9]", "", identity(value))


def _buyer(text):
    """Never recognize a buyer from issuer identities elsewhere in the file."""
    start = re.search(
        r"(?i)(?:raz[oó]n\s+social\s*/\s*nombres(?:\s+y\s+apellidos)?|"
        r"cliente|adquirente|comprador)\s*:",
        text,
    )
    if not start:
        start = re.search(r"(?i)raz[oó]n\s+social\s*:", text)
    if not start:
        return {}, []
    tail = text[start.end() :]
    end = re.search(
        r"(?i)\b(?:direcci[oó]n|tel[eé]fono|fecha\s*(?:de\s*)?emisi[oó]n|"
        r"correo|c[oó]digo\s+principal|descripci[oó]n|cantidad)\b",
        tail,
    )
    identity_block = tail[: end.start()] if end else tail[:500]
    ruc = re.search(
        r"(?i)\b(?:R\.?\s*U\.?\s*C\.?\s*(?:/\s*C\.?\s*I\.?)?|"
        r"identificaci[oó]n)\s*[:#]?\s*(\d{13})\b",
        identity_block,
    )
    name = identity_block[: ruc.start()] if ruc else identity_block
    name = re.sub(r"\s+", " ", name).strip(" :")
    compact = _compact(name)
    name_candidates = {
        profile["canonical"]
        for profile in PROFILES
        if any(_compact(alias) in compact for alias in profile["aliases"])
        or _compact(profile["legal"]) in compact
    }
    ruc_value = ruc.group(1) if ruc else None
    ruc_chain = BUYER_RUCS.get(ruc_value)
    issues = []
    if ruc_chain:
        chain = ruc_chain
        if name_candidates and name_candidates != {chain}:
            issues.append(
                "RUC y razón social del comprador identifican cadenas diferentes"
            )
    elif len(name_candidates) == 1:
        chain = next(iter(name_candidates))
        if ruc_value:
            issues.append("RUC del comprador no coincide con la cadena identificada")
    else:
        chain = None
        if len(name_candidates) > 1:
            issues.append("Razón social del comprador identifica más de una cadena")
    return {
        "chain": chain,
        "buyer_legal_name": name or None,
        "buyer_ruc": ruc_value,
        "buyer_evidence": identity_block.strip(),
    }, issues


def _money(text, label):
    matches = list(re.finditer(rf"(?im)\b(?:{label})\s*:?\s*\$?\s*({NUMERIC})", text))
    values = []
    for match in matches:
        try:
            parsed = number(match.group(1))
        except ValueError:
            continue
        if parsed is not None:
            values.append((parsed, match.group(0).strip()))
    unique = {value for value, _ in values}
    if len(unique) == 1:
        value = next(iter(unique))
        return str(value), [evidence for _, evidence in values], False
    return None, [evidence for _, evidence in values], len(unique) > 1


def _order_references(text):
    label = (
        r"(?:orden\s*(?:de\s*)?compra|referencia\s*(?:de\s*)?pedido|"
        r"(?:n[uú]mero\s+de\s+)?pedido|\bO\.?\s*C\.?)"
    )
    marker = r"(?:N\s*(?:[º°]|o\s*\.?|[uú]mero)|#)?"
    references = []
    evidence = []
    for match in re.finditer(
        rf"(?i){label}\s*{marker}\s*[:#.-]?\s*(?:\d{{1,3}}\s*:\s*)?"
        r"(OC[_-]\d{5,}|[A-Z]{1,5}\d{4,}|\d{2,}(?:[ \t]+\d{3,})*)",
        text,
    ):
        candidate = re.sub(r"\s+", "", match.group(1)).rstrip(".-")
        if len(candidate) < 5:
            continue
        references.append(candidate)
        evidence.append(match.group(0).strip())
    return list(dict.fromkeys(references)), evidence


def _administrative_state(text):
    """Explicit administrative labels only; terms in conditions are not proof."""
    states = set()
    evidence = []
    for match in re.finditer(
        r"(?im)^\s*(?:(?:estado\s*(?:de\s*(?:la\s*)?)?(?:factura|documento)?\s*[:.-]\s*)|"
        r"(?:factura\s+))?(activa?|anulad[ao]|cancelad[ao]|reemplazad[ao])\s*(?:$|por\b)",
        text,
    ):
        value = identity(match.group(1))
        state = (
            "activo"
            if value.startswith("activ")
            else "reemplazada"
            if value.startswith("reemplaz")
            else "anulada"
        )
        states.add(state)
        evidence.append(match.group(0).strip())
    replaces = re.search(
        rf"(?i)\b(?:reemplaza\s*(?:a\s*)?(?:la\s*)?(?:factura\s*)?|"
        rf"factura\s+reemplazada\s*[:#]\s*)({INVOICE_NUMBER})",
        text,
    )
    replaced_by = re.search(
        rf"(?i)\b(?:factura\s*)?reemplazad[ao]\s+por\s*(?:la\s*)?(?:factura\s*)?"
        rf"(?:N(?:o\.?|[º°])?\s*)?[:#]?\s*({INVOICE_NUMBER})",
        text,
    )
    if replaced_by:
        states.add("reemplazada")
        evidence.append(replaced_by.group(0).strip())
    if replaces:
        evidence.append(replaces.group(0).strip())
    return {
        "status": next(iter(states))
        if len(states) == 1
        else "revisar"
        if states
        else "activo",
        "status_evidence": evidence,
        "replaces": re.sub(r"\s+", "", replaces.group(1)) if replaces else None,
        "replaced_by": re.sub(r"\s+", "", replaced_by.group(1))
        if replaced_by
        else None,
    }, ["Estados administrativos contradictorios en la factura"] if len(
        states
    ) > 1 else []


def invoice_header(text):
    labels = list(
        re.finditer(
            rf"(?im)^\s*(?:[^\n]{{1,50}}[ \t]+)?F\s*A\s*C\s*T\s*U\s*R\s*A\s*(?:ELECTR[OÓ]NICA\s*)?"
            rf"(?:(?:N[º°o.]*(?:umero)?|No\.?|N[uú]mero)\s*[:#.]?)?"
            rf"\s*[:#]?\s*(?:\n\s*)?({INVOICE_NUMBER})",
            text,
        )
    )
    if not labels and not (
        re.search(
            r"(?im)^\s*(?:[^\n]{1,50}[ \t]+)?FACTURA\s*(?:ELECTR[OÓ]NICA)?(?:\s|$)",
            text,
        )
        and re.search(r"(?i)\b(?:raz[oó]n\s+social|cliente|adquirente)\s*:", text)
        and re.search(r"(?i)\b(?:fecha\s*(?:de\s*)?emisi[oó0]n|emisor|RUC)\s*:", text)
    ):
        return None
    invoice_numbers = {re.sub(r"\s+", "", label.group(1)) for label in labels}
    buyer, issues = _buyer(text)
    if len(invoice_numbers) > 1:
        issues.append(
            "Más de un número de factura en el documento; separar las facturas"
        )
    dates = [
        parse_date(match.group(1))
        for match in re.finditer(
            rf"(?i)\bfecha\s*(?:de\s*)?(?:emisi[oó0]n|factura)\s*[:.]?\s*({DATE})",
            text,
        )
    ]
    valid_dates = {value for value in dates if value}
    if len(valid_dates) > 1:
        issues.append("Fechas de emisión contradictorias en la factura")
    references, reference_evidence = _order_references(text)
    if len(references) > 1:
        issues.append("Más de una referencia de OC en la factura")
    state, state_issues = _administrative_state(text)
    issues.extend(state_issues)
    financial = {}
    monetary_evidence = {}
    for field, label in (
        ("document_subtotal", r"subtotal\s+(?:sin\s+impuestos|sin\s+iva|neto)"),
        ("document_discount", r"descuentos?(?:\s+total)?"),
        ("document_total", r"valor\s*total|total\s+(?:factura|a\s+pagar)"),
    ):
        value, evidence, conflicting = _money(text, label)
        financial[field] = value
        monetary_evidence[field] = evidence
        if conflicting:
            issues.append(f"Valores contradictorios para {field}")
    taxes = []
    tax_evidence = []
    for match in re.finditer(
        rf"(?im)\bIVA\s*(\d+(?:[.,]\d+)?\s*%)?\s*:\s*\$?\s*({NUMERIC})",
        text,
    ):
        line_prefix = text[text.rfind("\n", 0, match.start()) + 1 : match.start()]
        if re.search(r"(?i)subtotal\s+no\s+objeto\s*$", line_prefix):
            continue
        try:
            amount = number(match.group(2))
        except ValueError:
            continue
        taxes.append((identity(match.group(1) or "total"), amount))
        tax_evidence.append(match.group(0).strip())
    tax_rates = {}
    for rate, value in taxes:
        tax_rates.setdefault(rate, set()).add(value)
    if any(len(values) > 1 for values in tax_rates.values()):
        issues.append("Valores de IVA contradictorios en la factura")
        financial["document_tax"] = None
    elif tax_rates:
        rate_total = sum(
            (
                next(iter(values))
                for rate, values in tax_rates.items()
                if rate != "total"
            ),
            Decimal(0),
        )
        explicit_total = (
            next(iter(tax_rates["total"])) if "total" in tax_rates else None
        )
        if (
            explicit_total is not None
            and len(tax_rates) > 1
            and abs(explicit_total - rate_total) > Decimal("0.02")
        ):
            issues.append("Total de IVA no coincide con los impuestos por tarifa")
            financial["document_tax"] = None
        else:
            financial["document_tax"] = str(
                explicit_total if explicit_total is not None else rate_total
            )
    else:
        financial["document_tax"] = None
    monetary_evidence["document_tax"] = tax_evidence
    authorization = re.search(
        r"(?i)n[uú]mero\s+de\s+autorizaci[oó]n\s*:\s*(\d{49})\b", text
    )
    return {
        "kind": "invoice",
        "document_type": "FACTURA",
        "invoice_number": next(iter(invoice_numbers))
        if len(invoice_numbers) == 1
        else None,
        **buyer,
        "date": next(iter(valid_dates)) if len(valid_dates) == 1 else None,
        "order_number": references[0] if len(references) == 1 else None,
        "order_reference_evidence": reference_evidence,
        "authorization_number": authorization.group(1) if authorization else None,
        **financial,
        **state,
        "monetary_evidence": monetary_evidence,
        "document_issues": issues,
    }


def invoice_text_rows(text):
    """Read all electronic invoice detail lines, preserving wraps and precision.

    Grid detection can collapse the detail into one cell and truncate the
    four-decimal price. Text rows preserve each SKU and the original precision.
    """
    rows = []
    current = None
    in_detail = False
    page = 1
    lines = text.splitlines()
    detail_header = re.compile(
        r"(?i)\b(?:c[oó]digo|cod\.?\s*principal|descripci[oó]n)\b"
    )
    row_pattern = re.compile(
        rf"^\s*([A-Z0-9][A-Z0-9_.-]{{1,30}})\s+({NUMERIC})\s+"
        rf"(.+?)\s+\$?\s*({NUMERIC})\s+\$?\s*({NUMERIC})\s+\$?\s*({NUMERIC})\s*$",
        re.IGNORECASE,
    )

    def finish():
        if current is None:
            return
        current["product_name"] = re.sub(
            r"\s+", " ", current.pop("description")
        ).strip()
        barcode = re.match(r"^(\d{13,14})\s*[-–]\s*(.+)$", current["product_name"])
        if barcode:
            current["ean"] = barcode.group(1)
            current["product_name"] = barcode.group(2).strip()
        current["source_text"] = "\n".join(current.pop("original_lines"))
        rows.append(current)

    for index, line in enumerate(lines):
        marker = PAGE_MARKER.match(line.strip())
        if marker:
            page = int(marker.group(1))
            continue
        if detail_header.search(line) and re.search(
            r"(?i)\bcantidad\b", " ".join(lines[index : index + 8])
        ):
            if re.search(
                r"(?i)\b(?:precio|unitario)\b", " ".join(lines[index : index + 8])
            ):
                in_detail = True
                continue
        if not in_detail:
            continue
        if FOOTER.search(line):
            finish()
            current = None
            in_detail = False
            continue
        if not line.strip():
            continue
        match = row_pattern.match(line)
        if match and (
            re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", match.group(3))
            or re.fullmatch(r"\d{13,14}\s*[-–]?", match.group(3).strip())
        ):
            finish()
            current = {
                "code": match.group(1),
                "quantity": match.group(2),
                # Verified format: Cantidad counts the principal SKU. Explicit
                # carton columns in other layouts use table_records instead.
                "unit": "units",
                "quantity_basis": "Cantidad del SKU en la tabla de factura electrónica",
                "description": match.group(3),
                "unit_price": match.group(4),
                "discount": match.group(5),
                "amount": match.group(6),
                "source_location": f"Página {page}, línea {index + 1}",
                "original_lines": [line.strip()],
            }
        elif current:
            if not re.search(
                r"(?i)^(?:principal|adicionales|unitario|factura\b|c[oó]digo\b)",
                line.strip(),
            ):
                current["description"] += " " + line.strip()
                current["original_lines"].append(line.strip())
    finish()
    return rows


def validate_invoice_amounts(header, rows):
    """One document warning for reconciliation; keep every valid product row."""
    issues = []
    amounts = []
    discounts = []
    for row in rows:
        try:
            amounts.append(number(row.get("amount")))
            discounts.append(number(row.get("discount")))
        except ValueError:
            return issues
    if (
        amounts
        and all(value is not None for value in amounts)
        and header.get("document_subtotal") is not None
    ):
        subtotal = number(header["document_subtotal"])
        if abs(sum(amounts, Decimal(0)) - subtotal) > Decimal("0.02"):
            issues.append(
                "Subtotal de factura no coincide con la suma de los productos"
            )
    if (
        discounts
        and all(value is not None for value in discounts)
        and header.get("document_discount") is not None
    ):
        total_discount = number(header["document_discount"])
        if abs(sum(discounts, Decimal(0)) - total_discount) > Decimal("0.02"):
            issues.append("Descuento total de factura no coincide con sus líneas")
    return issues


def document_currency(text):
    matches = re.findall(r"\b(?:USD|EUR|D[OÓ]LARES?)\b|US\$", text or "", re.IGNORECASE)
    currencies = {"EUR" if value.upper() == "EUR" else "USD" for value in matches}
    if len(currencies) == 1:
        return next(iter(currencies))
    if currencies:
        return None
    # Verified Ecuador electronic invoice: issuer and recipient RUC blocks,
    # SRI authorization/access-key label and dollar-marked totals. A bare dollar
    # sign in an arbitrary document is insufficient currency evidence.
    if (
        re.search(r"(?i)\bRUC\s*:\s*\d{13}\b", text or "")
        and re.search(r"(?i)\bRUC\s*/\s*CI\s*:\s*\d{13}\b", text or "")
        and re.search(
            r"(?i)(?:clave\s+de\s+acceso|n[uú]mero\s+de\s+autorizaci[oó]n)\s*:",
            text or "",
        )
        and re.search(r"(?i)\bvalor\s*total\s*:\s*\$", text or "")
    ):
        return "USD"
    return None
