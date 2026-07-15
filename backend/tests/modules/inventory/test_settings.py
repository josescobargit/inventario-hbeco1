from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.settings.api.router import (
    DEFAULT_OPERATIONAL_SETTINGS,
    OperationalSettingsInput,
    normalize_payload,
    require_principal,
)
from app.modules.settings.domain.operational import (
    exception_invoices_allowed,
    low_stock_limit_units,
)


def test_settings_normalizes_chain_list_without_duplicates() -> None:
    payload = OperationalSettingsInput(
        warehouse_name="Bodega principal",
        low_stock_threshold_mode="units",
        low_stock_threshold_boxes=1,
        low_stock_threshold_units=5,
        report_default_days=30,
        allow_exception_invoices=True,
        suggested_chains=[" Favorita ", "favorita", "Tía", ""],
        invoice_exception_note="Factura para otro fin operativo",
    )

    assert payload.suggested_chains == ["Favorita", "Tía"]


def test_settings_payload_merges_defaults() -> None:
    payload = normalize_payload({"suggested_chains": ["Danec"]})

    assert payload["warehouse_name"] == DEFAULT_OPERATIONAL_SETTINGS["warehouse_name"]
    assert payload["suggested_chains"] == ["Danec"]


def test_only_principal_can_modify_settings() -> None:
    require_principal(SimpleNamespace(role=SimpleNamespace(code="principal")))
    with pytest.raises(HTTPException) as exc:
        require_principal(SimpleNamespace(role=SimpleNamespace(code="operador")))

    assert exc.value.status_code == 403


def test_exception_invoice_setting_defaults_to_allowed() -> None:
    db = SimpleNamespace(get=lambda *_args: None)

    assert exception_invoices_allowed(db) is True


def test_low_stock_threshold_uses_box_mode() -> None:
    db = SimpleNamespace(
        get=lambda *_args: SimpleNamespace(
            value={
                "low_stock_threshold_mode": "boxes",
                "low_stock_threshold_boxes": 2,
                "low_stock_threshold_units": 5,
            }
        )
    )

    assert low_stock_limit_units(db, units_per_box=12) == 24


def test_low_stock_threshold_uses_unit_mode() -> None:
    db = SimpleNamespace(
        get=lambda *_args: SimpleNamespace(
            value={
                "low_stock_threshold_mode": "units",
                "low_stock_threshold_boxes": 2,
                "low_stock_threshold_units": 5,
            }
        )
    )

    assert low_stock_limit_units(db, units_per_box=12) == 5
