import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.router import api_router  # noqa: F401 - registers every model
from app.core.database import Base
from app.main import app
from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.infrastructure.models import (
    InventoryMovement,
    InventoryPositionModel,
    Warehouse,
)
from app.modules.supplier_invoices.api.router import (
    SupplierInvoiceInput,
    cancel_supplier_invoice,
    register_supplier_invoice,
    update_supplier_invoice,
)
from app.modules.supplier_invoices.domain.extraction import extract_supplier_invoice
from app.modules.supplier_invoices.infrastructure.models import (
    SupplierInvoice,
    SupplierInvoiceLine,
)


@pytest.fixture
def supplier_db():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = SimpleNamespace(id=uuid.uuid4())
    warehouse = Warehouse(code="principal", name="Bodega principal")
    product = Product(
        sku="SKU-1",
        name="Elixir de prueba",
        barcode="7862133169602",
        contifico_aux_code="IECPELX0034",
        category="Pruebas",
        cost=Decimal("1.00"),
        units_per_box=1,
    )
    db.add_all([warehouse, product])
    db.flush()
    position = InventoryPositionModel(
        warehouse_id=warehouse.id,
        product_id=product.id,
        physical_confirmed=10,
    )
    db.add(position)
    db.commit()
    yield db, user, product, position
    db.close()


def payload(*quantities: int) -> SupplierInvoiceInput:
    return SupplierInvoiceInput(
        supplier_ruc="1791414667001",
        supplier_name="GOLDERIE TRADING S.A",
        invoice_number="001-003-000057409",
        issued_at=date(2026, 7, 22),
        authorization_number="2207202601179141466700120010030000574091234567816",
        subtotal=Decimal("10"),
        tax=Decimal("1.50"),
        total=Decimal("11.50"),
        lines=[
            {
                "line_number": index,
                "sku": "SKU-1",
                "supplier_code": "IECPELX0034",
                "barcode": "7862133169602",
                "description": "ELIXIR TRATAMIENTO CAPILAR",
                "quantity": quantity,
                "unit_price": Decimal("1"),
                "discount": Decimal("0"),
                "line_total": Decimal(quantity),
                "reviewed": True,
            }
            for index, quantity in enumerate(quantities, 1)
        ],
    )


def test_repeated_lines_are_preserved_and_inventory_is_applied_once(supplier_db):
    db, user, product, position = supplier_db
    created = register_supplier_invoice(payload(3, 4), user, db)
    retried = register_supplier_invoice(payload(3, 4), user, db)
    db.refresh(position)

    assert position.physical_confirmed == 17
    assert created["duplicate"] is False
    assert retried["duplicate"] is True
    assert db.scalar(select(func.count(SupplierInvoiceLine.id))) == 2
    assert (
        db.scalar(
            select(func.count(InventoryMovement.id)).where(
                InventoryMovement.product_id == product.id,
                InventoryMovement.movement_type == "supplier_invoice_registered",
            )
        )
        == 2
    )


def test_edit_applies_aggregated_difference_and_cancel_reverses_once(supplier_db):
    db, user, product, position = supplier_db
    created = register_supplier_invoice(payload(3, 4), user, db)
    update_supplier_invoice(created["id"], payload(2, 2), user, db)
    db.refresh(position)
    assert position.physical_confirmed == 14

    first = cancel_supplier_invoice(created["id"], user, db)
    repeated = cancel_supplier_invoice(created["id"], user, db)
    db.refresh(position)
    assert position.physical_confirmed == 10
    assert first["duplicate"] is False
    assert repeated["duplicate"] is True
    assert (
        db.scalar(
            select(func.count(InventoryMovement.id)).where(
                InventoryMovement.product_id == product.id
            )
        )
        == 4
    )


def test_unreviewed_line_does_not_create_partial_invoice(supplier_db):
    db, user, _product, position = supplier_db
    invalid = payload(5)
    invalid.lines[0].reviewed = False

    with pytest.raises(Exception):
        register_supplier_invoice(invalid, user, db)

    assert db.scalar(select(func.count(SupplierInvoice.id))) == 0
    db.refresh(position)
    assert position.physical_confirmed == 10


@pytest.mark.parametrize(
    ("filename", "expected_lines"),
    [
        ("Factura_001003000057409.pdf", 7),
        ("Factura_001003000057453.pdf", 5),
        ("Factura_001003000057458.pdf", 1),
    ],
)
def test_real_supplier_invoices(filename: str, expected_lines: int):
    path = Path("/Users/joseescobar/Downloads") / filename
    if not path.exists():
        pytest.skip("Documento real disponible solo en la validación local.")

    extracted = extract_supplier_invoice(
        path.read_bytes(), "application/pdf", path.name
    )

    assert extracted["supplier_name"] == "GOLDERIE TRADING S.A"
    assert extracted["supplier_ruc"] == "1791414667001"
    assert len(extracted["lines"]) == expected_lines


def test_frontend_supplier_invoice_route_matches_backend_contract():
    frontend = (
        Path(__file__).parents[4]
        / "frontend/src/features/inventory/SupplierInvoiceImport.tsx"
    ).read_text(encoding="utf-8")

    helper = (Path(__file__).parents[4] / "frontend/src/api/documentJobs.ts").read_text(
        encoding="utf-8"
    )
    assert 'kind: "supplier_invoice"' in frontend
    assert '"/document-jobs"' in helper
    assert "/api/v1/document-jobs" in app.openapi()["paths"]
    assert "post" in app.openapi()["paths"]["/api/v1/document-jobs"]


def test_supplier_invoice_import_requires_authenticated_user():
    response = TestClient(app).post(
        "/api/v1/supplier-invoices/imports/preview",
        files={"files": ("factura.pdf", b"%PDF-1.7", "application/pdf")},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Debes iniciar sesión para continuar."
