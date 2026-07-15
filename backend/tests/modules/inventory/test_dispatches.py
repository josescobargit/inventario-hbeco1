import pytest
from pydantic import ValidationError
from app.modules.dispatches.api.router import DispatchLineInput


def test_missing_dispatch_requires_reason() -> None:
    with pytest.raises(ValidationError):
        DispatchLineInput(sku="AE001", dispatched_quantity=0, missing_quantity=2)


def test_partial_dispatch_is_valid() -> None:
    line = DispatchLineInput(
        sku="AE001",
        dispatched_quantity=8,
        missing_quantity=4,
        missing_reason="No encontrado en bodega",
    )
    assert line.dispatched_quantity + line.missing_quantity == 12
