"""Document recognition is separate from catalog matching and financial comparisons."""

from sqlalchemy import select

from app.modules.commercial.models import CommercialDocument, CommercialRecord
from app.modules.commercial.normalization import KIND_MAP, identity, number, parse_date

PARSER_VERSION = "documents-v5"


def recognition_evidence(row, document):
    raw = {**row.source, **row.corrections}
    if not raw.get("currency"):
        from app.modules.commercial.invoice_extraction import document_currency

        raw["currency"] = document_currency(getattr(document, "extracted_text", None))
    kind = KIND_MAP.get(identity(raw.get("kind")))
    chain = str(raw.get("chain") or "").strip()
    when = parse_date(raw.get("date"))
    issues = []
    if not chain:
        issues.append("Cadena no identificada")
    if not kind:
        issues.append("Tipo de documento no identificado")
    if not when:
        issues.append("Fecha ausente o inválida")
    if kind in ("order", "invoice") and not raw.get(
        "invoice_number" if kind == "invoice" else "order_number"
    ):
        issues.append("Número de documento ausente")
    description = str(raw.get("product_name") or "").strip()
    if not description:
        issues.append("Descripción del producto pendiente")
    try:
        quantity = number(
            raw.get("quantity")
            if raw.get("quantity") is not None
            else raw.get("total_units")
        )
    except ValueError:
        quantity = None
    if quantity is None or quantity <= 0:
        issues.append("Cantidad ausente o inválida")
    unit = str(raw.get("unit") or "").strip()
    if not unit and raw.get("total_units") is not None:
        unit = "unidades"
    if identity(unit) not in {
        "units",
        "unit",
        "un",
        "unidades",
        "unidad",
        "ud",
        "uds",
        "boxes",
        "cajas",
        "caja",
        "cj",
        "packs",
        "pack",
    }:
        issues.append("Unidad de cantidad no identificada")
    extraction_issue = raw.get("extraction_issue")
    if extraction_issue and not raw.get("extraction_confirmed"):
        generic = (
            extraction_issue
            == "Verificar los campos pendientes de la cabecera del documento"
        )
        if not generic or (not issues and document.method != "pdf_text"):
            issues.append(extraction_issue)
    return dict(
        id=str(row.id),
        document_id=str(document.id),
        filename=document.filename,
        source_location=raw.get("source_location", f"Fila {row.row_number}"),
        source_url=f"/commercial/documents/{document.id}/content",
        origin="import",
        kind=kind,
        chain=chain,
        date=when,
        product_id=raw.get("product_id"),
        product_name=description,
        sku=str(raw.get("code") or raw.get("ean") or ""),
        units=float(quantity) if quantity is not None else None,
        amount=None,
        conversion="",
        match_method="Documento original",
        order_number=str(raw.get("order_number") or ""),
        invoice_number=str(raw.get("invoice_number") or ""),
        issues=issues,
        monetary_issues=[],
        excluded=False,
        source={**raw, "unit": unit},
        original_source=row.source,
        revision=row.revision,
        buyer_ruc=raw.get("buyer_ruc"),
        buyer_legal_name=raw.get("buyer_legal_name"),
    )


def processing_records(db):
    return [
        recognition_evidence(row, document)
        for row, document in db.execute(
            select(CommercialRecord, CommercialDocument)
            .join(
                CommercialDocument,
                CommercialDocument.id == CommercialRecord.document_id,
            )
            .where(CommercialRecord.superseded.is_(False))
            .order_by(CommercialDocument.created_at.desc(), CommercialRecord.row_number)
        )
    ]


def refresh_extraction(db, document, parsed, actor_id):
    """Archive prior derived rows, preserving originals and reviewed corrections."""
    import uuid
    from sqlalchemy import func
    from app.modules.audit.infrastructure.models import AuditLog

    mime, method, text, source_rows, warnings = parsed
    existing = list(
        db.scalars(
            select(CommercialRecord)
            .where(
                CommercialRecord.document_id == document.id,
                CommercialRecord.superseded.is_(False),
            )
            .with_for_update()
        )
    )

    def key(raw):
        return (
            str(raw.get("order_number") or raw.get("invoice_number") or ""),
            str(raw.get("code") or raw.get("ean") or ""),
            identity(raw.get("product_name")),
        )

    corrections = {}
    keys = [key(raw) for raw in source_rows]
    for row in existing:
        if row.corrections:
            row_key = key(row.source)
            if keys.count(row_key) != 1 or row_key in corrections:
                raise ValueError(
                    "No se puede trasladar con seguridad una corrección previa; revisa la evidencia antes de reprocesar"
                )
            corrections[row_key] = dict(row.corrections)
    previous_version = document.parser_version
    previous_ids = [str(r.id) for r in existing]
    offset = (
        db.scalar(
            select(func.max(CommercialRecord.row_number)).where(
                CommercialRecord.document_id == document.id
            )
        )
        or 0
    )
    for row in existing:
        row.superseded = True
    for index, raw in enumerate(source_rows, offset + 1):
        db.add(
            CommercialRecord(
                id=uuid.uuid4(),
                document_id=document.id,
                row_number=index,
                source=raw,
                corrections=corrections.get(key(raw), {}),
            )
        )
    document.content_type = mime
    document.method = method
    document.extracted_text = text
    document.warnings = warnings
    document.parser_version = PARSER_VERSION
    db.add(
        AuditLog(
            actor_user_id=actor_id,
            action="commercial.reprocess",
            entity_type="commercial_document",
            entity_id=str(document.id),
            previous_value={
                "parser_version": previous_version,
                "record_ids": previous_ids,
            },
            new_value={"parser_version": PARSER_VERSION, "rows": len(source_rows)},
            reason="Reprocesamiento del original con el motor vigente",
        )
    )
    return len(source_rows)
