"""Read-only report for historical purchase-order source document storage."""

import json

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.modules.purchase_orders.infrastructure.models import (
    PurchaseOrderDocumentLink,
    PurchaseOrderSourceDocument,
)


def main() -> None:
    with SessionLocal() as db:
        total, retained, bytes_retained = db.execute(
            select(
                func.count(PurchaseOrderSourceDocument.id),
                func.count(PurchaseOrderSourceDocument.content),
                func.coalesce(func.sum(func.octet_length(PurchaseOrderSourceDocument.content)), 0),
            )
        ).one()
        linked = db.scalar(
            select(func.count()).select_from(PurchaseOrderDocumentLink)
        )
        print(json.dumps({
            "documents_total": int(total or 0),
            "documents_with_historical_binary": int(retained or 0),
            "historical_binary_bytes": int(bytes_retained or 0),
            "purchase_order_links": int(linked or 0),
            "action_taken": "none",
        }))


if __name__ == "__main__":
    main()
