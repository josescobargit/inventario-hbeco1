import pytest
from pydantic import ValidationError

from app.modules.inventory_operations.api.router import OperationInput


def test_entry_requires_document_and_reason() -> None:
    with pytest.raises(ValidationError):
        OperationInput(
            operation_type="entry",
            responsible_name="Bodega",
            occurred_at="2026-07-07T09:00:00-05:00",
            document_reference="",
            reason="abc",
            lines=[{"sku": "AE001", "quantity": 2}],
        )


def test_general_exit_is_distinct_from_dispatch() -> None:
    operation = OperationInput(
        operation_type="exit",
        responsible_name="José Escobar",
        occurred_at="2026-07-07T09:00:00-05:00",
        document_reference="EG-001",
        reason="Consumo operativo autorizado",
        lines=[{"sku": "AE001", "quantity": 2}],
    )
    assert operation.operation_type == "exit"
    assert operation.lines[0].quantity == 2
