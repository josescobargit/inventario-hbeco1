import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.modules.purchase_orders.api.router import list_orders
from app.modules.purchase_orders.infrastructure.models import (
    PurchaseOrder,
    PurchaseOrderLine,
)


def populated_session(order_count: int) -> tuple[Session, object]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PurchaseOrder.__table__.create(engine)
    PurchaseOrderLine.__table__.create(engine)
    now = datetime.now(timezone.utc)
    rows = [
        {
            "id": uuid.uuid4(),
            "chain_name": ["Favorita", "Rosado", "Tía", "TUTI"][index % 4],
            "customer_name": None,
            "order_number": f"OC-{index:06d}",
            "order_date": (now - timedelta(days=index % 365)).date(),
            "destination": f"Destino {index % 20}",
            "status": "open",
            "notes": None,
            "secondary_reference": None,
            "local_name": None,
            "created_by_user_id": uuid.uuid4(),
            "created_at": now - timedelta(seconds=index),
        }
        for index in range(order_count)
    ]
    with engine.begin() as connection:
        connection.execute(PurchaseOrder.__table__.insert(), rows)
    return Session(engine), engine


def test_first_page_of_40_orders_uses_one_query_and_returns_only_summaries() -> None:
    db, engine = populated_session(40)
    query_count = 0

    def count_query(*_args) -> None:
        nonlocal query_count
        query_count += 1

    event.listen(engine, "before_cursor_execute", count_query)
    response = list_orders(None, db, limit=25)

    assert query_count == 1
    assert len(response["items"]) == 25
    assert response["next_cursor"]
    assert "lines" not in response["items"][0]
    assert "source_documents" not in response["items"][0]
    assert len(json.dumps(response, default=str).encode()) < 10_000


def test_search_over_10000_orders_is_bounded_and_under_300_ms() -> None:
    db, _engine = populated_session(10_000)
    started = time.perf_counter()
    response = list_orders(None, db, search="OC-009999", limit=25)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert [item["order_number"] for item in response["items"]] == ["OC-009999"]
    assert elapsed_ms < 300


def test_cursor_paginates_1000_orders_without_duplicates() -> None:
    db, _engine = populated_session(1_000)
    first = list_orders(None, db, limit=50)
    second = list_orders(None, db, limit=50, cursor=first["next_cursor"])

    first_ids = {item["id"] for item in first["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert len(first_ids) == len(second_ids) == 50
    assert first_ids.isdisjoint(second_ids)
