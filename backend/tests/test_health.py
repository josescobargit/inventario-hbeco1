from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app


def test_health_endpoint() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "inventario-operativo-api",
    }


def test_database_failure_has_a_non_technical_message() -> None:
    path = "/test-only/database-unavailable"

    if not any(getattr(route, "path", None) == path for route in app.routes):

        @app.get(path)
        def raise_database_error() -> None:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    response = TestClient(app, raise_server_exceptions=False).get(path)

    assert response.status_code == 503
    assert response.json() == {
        "detail": (
            "Estamos conectando con los datos. "
            "El sistema tardó más de lo esperado; intenta nuevamente."
        )
    }


def test_inventory_requires_an_authenticated_session() -> None:
    response = TestClient(app).get("/api/v1/inventory/availability")

    assert response.status_code == 401
    assert response.json() == {"detail": "Debes iniciar sesión para continuar."}


def test_reservations_require_an_authenticated_session() -> None:
    response = TestClient(app).get("/api/v1/reservations")
    assert response.status_code == 401
