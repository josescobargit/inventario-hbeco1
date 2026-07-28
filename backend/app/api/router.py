from fastapi import APIRouter

from app.modules.audit.api.router import router as audit_router
from app.modules.auth.api.router import router as auth_router
from app.modules.catalog.api.router import router as catalog_router
from app.modules.comparisons.api.router import router as comparisons_router
from app.modules.dispatches.api.router import router as dispatches_router
from app.modules.dashboard.api.router import router as dashboard_router
from app.modules.deliveries.api.router import router as deliveries_router
from app.modules.documents.api.router import router as documents_router
from app.modules.returns.api.router import router as returns_router
from app.modules.incidents.api.router import router as incidents_router
from app.modules.inventory.api.router import router as inventory_router
from app.modules.inventory_operations.api.router import (
    router as inventory_operations_router,
)
from app.modules.invoices.api.router import router as invoices_router
from app.modules.invoices.api.trace_router import router as invoice_trace_router
from app.modules.reports.api.router import router as reports_router
from app.modules.reservations.api.router import router as reservations_router
from app.modules.settings.api.router import router as settings_router
from app.modules.purchase_orders.api.router import router as purchase_orders_router
from app.modules.stock_adjustments.api.router import router as stock_adjustments_router
from app.modules.stock_imports.api.router import router as stock_imports_router
from app.modules.stock_imports.api.persistence_router import (
    router as stock_import_persistence_router,
)
from app.modules.supplier_invoices.api.router import router as supplier_invoices_router


api_router = APIRouter()
api_router.include_router(audit_router)
api_router.include_router(auth_router)
api_router.include_router(catalog_router)
api_router.include_router(comparisons_router)
api_router.include_router(dashboard_router)
api_router.include_router(dispatches_router)
api_router.include_router(deliveries_router)
api_router.include_router(documents_router)
api_router.include_router(returns_router)
api_router.include_router(incidents_router)
api_router.include_router(inventory_router)
api_router.include_router(inventory_operations_router)
api_router.include_router(invoices_router)
api_router.include_router(invoice_trace_router)
api_router.include_router(reports_router)
api_router.include_router(reservations_router)
api_router.include_router(settings_router)
api_router.include_router(purchase_orders_router)
api_router.include_router(stock_adjustments_router)
api_router.include_router(stock_imports_router)
api_router.include_router(stock_import_persistence_router)
api_router.include_router(supplier_invoices_router)
