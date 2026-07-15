from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.stock_adjustments.api.router import (
    applies_immediately,
    require_principal,
)


def test_principal_can_decide_adjustment() -> None:
    principal = SimpleNamespace(role=SimpleNamespace(code="principal"))

    require_principal(principal)
    assert applies_immediately(principal) is True


def test_operator_cannot_decide_adjustment() -> None:
    operator = SimpleNamespace(role=SimpleNamespace(code="operador"))
    with pytest.raises(HTTPException) as error:
        require_principal(operator)

    assert error.value.status_code == 403
    assert applies_immediately(operator) is False
