"""Conservative normalization: no fuzzy matches, guessed units or prices."""

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def identity(value) -> str:
    text = (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )
    return re.sub(r"\s+", " ", text).strip()


def product_identity(value) -> str:
    text = identity(value)
    for original, official in (
        ("crecimiento", "romero"),
        ("hidratacion", "coco"),
        ("fortalecimiento", "cebolla"),
    ):
        text = re.sub(rf"\b{original}\b", official, text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def pack_identity(value):
    text = product_identity(value)
    if not re.search(r"\bpack\b", text):
        return None
    volumes = [int(v) for v in re.findall(r"\b(\d+)\s*ml\b", text)]
    shampoo = bool(re.search(r"\b(?:sh|shampoo|champu)\b", text))
    conditioner = bool(re.search(r"\b(?:ac|acondicionador)\b", text))
    if not volumes or len(volumes) > 2:
        return None
    # Existing catalog uses 'PACK SH + AC ... 500 ML' for two 500 ml components.
    total = (
        sum(volumes)
        if len(volumes) == 2
        else volumes[0] * (2 if shampoo and conditioner else 1)
    )
    rest = re.sub(r"\b\d+\s*ml\b", "", text)
    rest = re.sub(r"\b(?:pack|sh|shampoo|champu|ac|acondicionador|y)\b", "", rest)
    remaining = tuple(sorted(rest.split()))
    # Preserve brand/line/scent; 'pack 1000 ml' alone is never enough.
    return (remaining, total) if remaining else None


def number(value) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().replace("$", "").replace("USD", "").strip()
    # Native Excel numbers have an unambiguous decimal representation.
    if isinstance(value, (float, int, Decimal)):
        text = str(value)
    elif "," in text and "." in text:
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
        grouping = "." if decimal_sep == "," else ","
        if not re.fullmatch(
            rf"-?\d{{1,3}}(?:\{grouping}\d{{3}})+\{decimal_sep}\d{{1,4}}", text
        ):
            raise ValueError("Número con separadores inválidos")
        text = text.replace(grouping, "").replace(decimal_sep, ".")
    elif re.fullmatch(r"-?\d{1,3}[.,]\d{3}", text):
        raise ValueError(
            "Separador ambiguo: usa número Excel o decimales sin miles (ej. 1000.00)"
        )
    else:
        text = text.replace(",", ".")
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Número inválido") from exc
    if not result.is_finite() or abs(result) > Decimal("999999999999"):
        raise ValueError("Número fuera de rango")
    return result


def parse_date(value) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(value or "").strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


HEADERS = {
    "kind": ["tipo", "tipo documento", "tipo de documento", "kind"],
    "chain": ["cadena", "cadena comercial", "cliente", "chain"],
    "order_number": [
        "oc",
        "numero oc",
        "numero de oc",
        "referencia pedido",
        "numero pedido",
        "pedido",
        "orden de compra",
        "order_number",
    ],
    "invoice_number": [
        "factura",
        "numero factura",
        "numero de factura",
        "invoice_number",
    ],
    "date": ["fecha", "fecha emision", "periodo", "date"],
    "product_name": [
        "producto",
        "descripcion",
        "descripción",
        "detalle",
        "nombre",
        "product_name",
    ],
    "code": [
        "codigo",
        "codigo producto",
        "cod. principal",
        "cod principal",
        "codigo principal",
        "sku",
        "code",
    ],
    "ean": ["ean", "ean13", "ean 13", "ean14", "ean 14", "gtin", "codigo de barras"],
    "quantity": ["cantidad", "cant.", "cant", "qty", "quantity"],
    "unit": ["unidad", "unidad medida", "unidad de medida", "unit"],
    "boxes": ["cajas", "cantidad cajas"],
    "total_units": ["unidades", "unidades totales", "cantidad unidades"],
    "units_per_box": ["unidades por caja", "uxc", "unid caja", "units_per_box"],
    "unit_price": [
        "precio",
        "precio unitario",
        "p unitario",
        "precio unit.",
        "precio unit",
        "p. unitario",
        "unit_price",
    ],
    "amount": [
        "subtotal",
        "valor neto",
        "venta neta",
        "dolares",
        "importe",
        "precio total",
        "total sin impuesto",
        "amount",
    ],
    "document_total": ["total documento", "total factura"],
    "currency": ["moneda", "currency"],
    "status": ["estado", "status"],
    "replaces": ["reemplaza", "factura reemplazada", "replaces"],
}
HEADER_MAP = {
    identity(label): key for key, labels in HEADERS.items() for label in [key, *labels]
}
KIND_MAP = {
    "oc": "order",
    "orden de compra": "order",
    "pedido": "order",
    "order": "order",
    "factura": "invoice",
    "invoice": "invoice",
    "sell in": "sell_in",
    "sellin": "sell_in",
    "sell out": "sell_out",
    "sellout": "sell_out",
    "sell_in": "sell_in",
    "sell_out": "sell_out",
}


def resolve_product(raw, products, profiles, aliases):
    explicit = raw.get("product_id")
    if explicit:
        return next(
            (p for p in products if str(p.id) == str(explicit)), None
        ), "selección revisada"
    candidates = set()
    evidence = []
    for field in ("ean", "code"):
        code = str(raw.get(field) or "").strip()
        if not code:
            continue
        matches = {
            str(p.id)
            for p in products
            if code
            in {
                p.sku,
                p.barcode,
                p.contifico_aux_code,
                profiles.get(str(p.id), {}).get("ean14"),
            }
        }
        if not matches:
            matches = {
                str(a.product_id)
                for a in aliases
                if identity(a.chain_name) == identity(raw.get("chain"))
                and a.detected_code == code
            }
        if field == "ean" and not matches:
            return None, "EAN no reconocido; requiere confirmación"
        if matches:
            evidence.append(matches)
    name = raw.get("product_name")
    if name:
        for p in products:
            names = [p.name, *profiles.get(str(p.id), {}).get("aliases", [])]
            if any(
                product_identity(name) == product_identity(n)
                or (
                    pack_identity(name) is not None
                    and pack_identity(name) == pack_identity(n)
                )
                for n in names
            ):
                candidates.add(str(p.id))
        candidates.update(
            str(a.product_id)
            for a in aliases
            if identity(a.chain_name) == identity(raw.get("chain"))
            and identity(a.source_text) == identity(name)
        )
        if candidates:
            evidence.append(candidates)
    if not evidence:
        return None, "REVISAR PRODUCTO: sin equivalencia segura"
    matches = set.intersection(*evidence)
    if len(matches) != 1:
        return None, "REVISAR PRODUCTO: código, EAN o nombre ambiguo/inconsistente"
    return next(
        p for p in products if str(p.id) in matches
    ), "código o equivalencia exacta"


def normalize(raw, products, profiles, aliases):
    issues = []
    monetary_issues = []

    def numeric(field, monetary=False):
        try:
            return number(raw.get(field))
        except ValueError as exc:
            (monetary_issues if monetary else issues).append(f"{field}: {exc}")
            return None

    kind = KIND_MAP.get(identity(raw.get("kind")))
    if not kind:
        if raw.get("invoice_number"):
            kind = "invoice"
        elif raw.get("order_number"):
            kind = "order"
        else:
            issues.append("Tipo de documento no identificado")
    chain = str(raw.get("chain") or "").strip()
    if not chain:
        issues.append("Cadena no identificada")
    when = parse_date(raw.get("date"))
    if not when:
        issues.append("Fecha ausente o inválida")
    product, match_method = resolve_product(raw, products, profiles, aliases)
    if not product:
        issues.append(match_method)
    units = numeric("total_units")
    quantity = numeric("quantity")
    boxes = numeric("boxes")
    factor = numeric("units_per_box")
    if factor is None and product:
        factor = Decimal(product.units_per_box)
    if factor is not None and (factor <= 0 or factor != factor.to_integral_value()):
        issues.append("Unidades por caja debe ser un entero positivo")
        factor = None
    unit = identity(raw.get("unit"))
    conversion = "Unidades explícitas del documento"
    computed = None
    price_divisor = Decimal(1)
    if unit in ("caja", "cajas", "box", "boxes") or (not unit and boxes is not None):
        box_count = boxes if boxes is not None else quantity
        if factor and box_count is not None:
            computed = box_count * factor
            price_divisor = factor
            conversion = (
                f"{box_count} cajas × {factor} unidades/caja = {computed} unidades"
            )
        else:
            issues.append("Falta cantidad de cajas o unidades por caja")
    elif unit in ("unidad", "unidades", "units", "unit", "u", "und"):
        computed = quantity
        conversion = f"{quantity} unidades (sin conversión)"
    elif unit in ("pack", "packs"):
        if product and "pack" in identity(product.name):
            computed = quantity
            conversion = f"{quantity} packs = {quantity} unidades del SKU pack; no se separan sus componentes"
        else:
            issues.append("El pack no está identificado como presentación del producto")
    elif units is None:
        issues.append("Unidad de cantidad no identificada")
    if units is not None and computed is not None and units != computed:
        issues.append(
            f"Unidades explícitas ({units}) difieren de la conversión ({computed})"
        )
    if units is None:
        units = computed
    if (
        boxes is not None
        and factor is not None
        and units is not None
        and boxes * factor != units
    ):
        issues.append(
            "Cajas × unidades por caja no coincide con las unidades comparables"
        )
    if (
        units is None
        or units < 0
        or units != units.to_integral_value()
        or (units == 0 and kind in ("order", "invoice"))
    ):
        issues.append("Cantidad comparable ausente o inválida")
    price = numeric("unit_price", True)
    amount = numeric("amount", True)
    if (
        price is not None
        and not unit
        and quantity is not None
        and quantity != units
        and boxes is None
    ):
        monetary_issues.append(
            "Base del precio desconocida: cantidad original diferente de unidades comparables"
        )
    if price is not None and price < 0 or amount is not None and amount < 0:
        monetary_issues.append("Importe negativo: revisar devolución o ajuste")
    currency = str(raw.get("currency") or "").upper().strip()
    if (price is not None or amount is not None) and currency not in (
        "USD",
        "DOLAR",
        "DOLARES",
    ):
        monetary_issues.append("Moneda no confirmada como USD")
    normalized_price = price / price_divisor if price is not None else None
    calculated = (
        units * normalized_price
        if units is not None and normalized_price is not None
        else None
    )
    if (
        amount is not None
        and calculated is not None
        and abs(amount - calculated) > Decimal("0.02")
    ):
        monetary_issues.append(
            "Subtotal difiere de cantidad × precio; revisar descuento, impuesto o base del precio"
        )
    if amount is None:
        amount = calculated
    if monetary_issues:
        amount = None
        normalized_price = None
    elif normalized_price is None and amount is not None and units:
        normalized_price = amount / units
    number_field = (
        "order_number"
        if kind == "order"
        else "invoice_number"
        if kind == "invoice"
        else None
    )
    if number_field and not raw.get(number_field):
        issues.append("Número de documento ausente")
    state = identity(raw.get("status") or "activo")
    excluded = state in (
        "anulada",
        "anulado",
        "cancelled",
        "canceled",
        "void",
        "reemplazada",
        "reemplazado",
        "replaced",
        "excluido",
    )
    if state not in (
        "activo",
        "active",
        "confirmed",
        "confirmada",
        "confirmado",
        "open",
        "completed",
        "partially_invoiced",
        "anulada",
        "anulado",
        "cancelled",
        "canceled",
        "void",
        "reemplazada",
        "reemplazado",
        "replaced",
        "excluido",
    ):
        issues.append(f"Estado administrativo requiere revisión: {state}")
    profile = profiles.get(str(product.id), {}) if product else {}
    return {
        "kind": kind,
        "chain": chain,
        "date": when,
        "order_number": str(raw.get("order_number") or "").strip(),
        "invoice_number": str(raw.get("invoice_number") or "").strip(),
        "product_id": str(product.id) if product else None,
        "product_name": product.name
        if product
        else str(raw.get("product_name") or "Sin identificar"),
        "sku": product.sku if product else str(raw.get("code") or ""),
        "line": profile.get("line") or (product.category if product else "Sin línea"),
        "units": float(units) if units is not None else None,
        "unit_price": str(normalized_price) if normalized_price is not None else None,
        "amount": str(amount.quantize(Decimal("0.01"))) if amount is not None else None,
        "conversion": conversion,
        "match_method": match_method,
        "issues": issues,
        "monetary_issues": monetary_issues,
        "excluded": excluded,
        "administrative_status": state,
        "replaces": str(raw.get("replaces") or "").strip(),
    }
