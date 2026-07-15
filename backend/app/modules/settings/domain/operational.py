from typing import Any

from sqlalchemy.orm import Session

from app.modules.settings.infrastructure.models import AppSetting


OPERATIONAL_KEY = "operational"
DEFAULT_CHAINS = ["Gerardo Ortiz", "Favorita", "Rosado", "Danec", "Tía"]
DEFAULT_OPERATIONAL_SETTINGS: dict[str, Any] = {
    "warehouse_name": "Bodega principal",
    "low_stock_threshold_mode": "boxes",
    "low_stock_threshold_boxes": 1,
    "low_stock_threshold_units": 0,
    "report_default_days": 30,
    "allow_exception_invoices": True,
    "suggested_chains": DEFAULT_CHAINS,
    "invoice_exception_note": "Usar excepción cuando la factura no corresponde a una OC normal o tiene otro fin operativo.",
}


def operational_values(db: Session) -> dict[str, Any]:
    setting = db.get(AppSetting, OPERATIONAL_KEY)
    if setting is None:
        return DEFAULT_OPERATIONAL_SETTINGS.copy()
    return {**DEFAULT_OPERATIONAL_SETTINGS, **(setting.value or {})}


def low_stock_limit_units(db: Session, units_per_box: int) -> int:
    values = operational_values(db)
    threshold_mode = str(values.get("low_stock_threshold_mode") or "boxes")
    threshold_boxes = int(values.get("low_stock_threshold_boxes") or 1)
    threshold_units = int(values.get("low_stock_threshold_units") or 0)
    if threshold_mode == "units":
        return max(0, threshold_units)
    return max(0, threshold_boxes) * units_per_box


def exception_invoices_allowed(db: Session) -> bool:
    values = operational_values(db)
    return bool(values.get("allow_exception_invoices", True))
