import pytest

from app.modules.auth.domain.credentials import normalize_username


def test_username_is_normalized() -> None:
    assert normalize_username("  Operador.Uno ") == "operador.uno"


@pytest.mark.parametrize("username", ["ab", "usuario con espacios", "usuario@empresa"])
def test_invalid_username_is_rejected(username: str) -> None:
    with pytest.raises(ValueError):
        normalize_username(username)
