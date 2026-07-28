-- DRAFT ONLY. Do not add this file to the Alembic revision chain without approval.
-- Run backend/scripts/report_purchase_order_document_storage.py first and back up
-- purchase_order_source_documents before approving this irreversible operation.

UPDATE purchase_order_source_documents
SET content = NULL
WHERE content IS NOT NULL;
