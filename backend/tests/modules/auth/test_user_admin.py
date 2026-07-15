import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.auth.api.router import admin_user_response, require_principal
from app.modules.auth.infrastructure.models import Role, User


def test_require_principal_allows_main_user() -> None:
    require_principal(SimpleNamespace(role=SimpleNamespace(code="principal")))


def test_require_principal_rejects_operator() -> None:
    with pytest.raises(HTTPException) as exc:
        require_principal(SimpleNamespace(role=SimpleNamespace(code="operador")))

    assert exc.value.status_code == 403


def test_admin_user_response_includes_operational_status() -> None:
    role = Role(
        id=uuid.uuid4(),
        code="operador",
        name="Operador",
        is_system=True,
    )
    user = User(
        id=uuid.uuid4(),
        role_id=role.id,
        username="bodega",
        full_name="Bodega Principal",
        email="bodega@example.com",
        password_hash="hash",
        is_active=True,
        must_change_password=False,
        created_at=datetime(2026, 7, 14, 10, 0, tzinfo=UTC),
    )
    user.role = role

    payload = admin_user_response(user)

    assert payload.username == "bodega"
    assert payload.role == "operador"
    assert payload.role_name == "Operador"
    assert payload.is_active is True
