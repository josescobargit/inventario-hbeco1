"""Invoice headers are read before details, independently of OC templates."""

import re
from app.modules.commercial.normalization import parse_date
from app.modules.purchase_orders.domain.order_profiles import recognize_known_order


def invoice_header(text):
    label = re.search(
        r"(?im)^\s*F\s*A\s*C\s*T\s*U\s*R\s*A\s*(?:(?:N[º°o.]*(?:umero)?|No\.?|Número)\s*[:#.]?)?\s*[:#]?\s*(?:\n\s*)?(\d{3}\s*-\s*\d{3}\s*-\s*\d{6,9})",
        text,
    )
    if not label:
        return None
    # Prefer the recipient block over issuer identity when it is labeled.
    recipient = re.search(
        r"(?is)(?:raz[oó]n\s+social\s*/\s*nombres|cliente\s*:|adquirente\s*:)(.*?)(?:descripci[oó]n|c[oó]d\.?\s*principal|cantidad|detalle)",
        text,
    )
    buyer_text = recipient.group(1) if recipient else text
    buyer = recognize_known_order(buyer_text) or {}
    dated = re.search(
        r"(?i)fecha\s*(?:de\s*)?(?:emisi[oó]n|factura)\s*[:.]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})",
        text,
    )
    when = dated.group(1) if dated else None
    if when and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2}", when):
        from datetime import datetime

        when = datetime.strptime(when, "%d/%m/%y").date().isoformat()
    order = re.search(
        r"(?i)(?:orden\s*(?:de\s*)?compra|referencia\s*(?:de\s*)?pedido|pedido|\bO\.?\s*C\.?)\s*(?:N(?:[º°o.]|[uú]mero)*\s*)?[:#.-]?\s*(OC[_-]?\d+|\d{5,})",
        text,
    )
    total = re.findall(
        r"(?im)^\s*(?:VALOR\s+TOTAL|TOTAL\s+(?:FACTURA|A\s+PAGAR))\s*[:$]?\s*([\d.,]+)\s*$",
        text,
    )
    return dict(
        kind="invoice",
        document_type="FACTURA",
        invoice_number=re.sub(r"\s+", "", label.group(1)),
        chain=buyer.get("chain_name"),
        buyer_legal_name=buyer.get("buyer_legal_name"),
        buyer_ruc=buyer.get("buyer_ruc"),
        date=parse_date(when),
        order_number=order.group(1) if order else None,
        document_total=total[-1] if total else None,
    )


def document_currency(text):
    matches = re.findall(r"\b(?:USD|EUR|D[OÓ]LARES?)\b|US\$", text or "", re.IGNORECASE)
    currencies = {"EUR" if value.upper() == "EUR" else "USD" for value in matches}
    return next(iter(currencies)) if len(currencies) == 1 else None
