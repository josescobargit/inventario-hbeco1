from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.catalog.api.router import ProductInput, require_principal


def test_catalog_product_input_normalizes_sku_and_optional_text() -> None:
    payload = ProductInput(
        sku=" ae010 ",
        name=" Producto Nuevo ",
        description=" ",
        category=" Cuidado Capilar ",
        barcode=" 786000 ",
        contifico_aux_code=" ",
        cost=Decimal("1.2500"),
        units_per_box=12,
    )

    assert payload.sku == "AE010"
    assert payload.name == "Producto Nuevo"
    assert payload.description is None
    assert payload.category == "Cuidado Capilar"
    assert payload.barcode == "786000"
    assert payload.contifico_aux_code is None


def test_only_principal_can_modify_catalog() -> None:
    require_principal(SimpleNamespace(role=SimpleNamespace(code="principal")))

    with pytest.raises(HTTPException) as exc:
        require_principal(SimpleNamespace(role=SimpleNamespace(code="operador")))

    assert exc.value.status_code == 403
