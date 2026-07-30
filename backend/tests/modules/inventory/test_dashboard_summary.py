import uuid
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.router import api_router  # noqa: F401
from app.core.database import Base
from app.modules.catalog.infrastructure.models import Product
from app.modules.dashboard.api.router import period_start, summary
from app.modules.inventory.infrastructure.models import (
    InventoryPositionModel,
    Warehouse,
)


def test_period_start_supports_only_the_small_dashboard_ranges() -> None:
    from datetime import date

    today = date(2026, 7, 29)
    assert period_start("today", today) == today
    assert period_start("week", today) == date(2026, 7, 27)
    assert period_start("month", today) == date(2026, 7, 1)


def test_dashboard_focuses_on_inventory_and_real_attention() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    warehouse = Warehouse(code="principal", name="Principal")
    product = Product(
        sku="DASH-1",
        name="Producto del panel",
        category="Prueba",
        cost=1,
        units_per_box=12,
    )
    db.add_all([warehouse, product])
    db.flush()
    db.add(
        InventoryPositionModel(
            warehouse_id=warehouse.id,
            product_id=product.id,
            physical_confirmed=100,
            reserved=10,
            invoiced_not_dispatched=25,
            blocked_by_incident=5,
        )
    )
    db.commit()

    result = summary(SimpleNamespace(id=uuid.uuid4()), db, "month")

    assert result["metrics"]["available_units"] == 85
    assert result["metrics"]["products_with_stock"] == 1
    assert "workflow" not in result
    assert "attention_invoices" not in result
    assert "pending_dispatch" not in str(result)
    assert "pending_delivery" not in str(result)
    db.close()
