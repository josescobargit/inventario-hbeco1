from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).parents[2]
client = TestClient(app)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/invoices/listing",
        "/api/v1/invoices/inventory-pending",
        "/api/v1/invoices/inventory-audit",
    ],
)
def test_invoice_read_contract_accepts_get_and_rejects_post(path: str) -> None:
    get_response = client.get(path)
    post_response = client.post(path)

    assert get_response.status_code == 401
    assert get_response.status_code != 405
    assert post_response.status_code == 405
    assert post_response.headers["allow"] == "GET"


def test_invoice_listing_exposes_filters_and_pagination() -> None:
    operation = app.openapi()["paths"]["/api/v1/invoices/listing"]["get"]
    parameters = {parameter["name"] for parameter in operation["parameters"]}

    assert {
        "search",
        "purchase_order",
        "chain",
        "date_from",
        "date_to",
        "status",
        "inventory_status",
        "sort",
        "page",
        "page_size",
    } <= parameters


def test_invoice_preflight_allows_get_from_frontend() -> None:
    response = client.options(
        "/api/v1/invoices/listing",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type,x-requested-with",
        },
    )

    assert response.status_code == 200
    assert "GET" in response.headers["access-control-allow-methods"]


def test_frontend_invoice_routes_match_backend_get_contract() -> None:
    invoice_source = (
        ROOT / "frontend/src/features/invoices/InvoiceCenter.tsx"
    ).read_text(encoding="utf-8")
    pending_source = (
        ROOT / "frontend/src/features/invoices/PendingInventoryInvoices.tsx"
    ).read_text(encoding="utf-8")
    paths = app.openapi()["paths"]

    assert 'apiRequest<InvoiceListing>(`/invoices/listing?${query}`)' in invoice_source
    assert (
        'apiRequest<PendingResponse>(`/invoices/inventory-pending?${query}`)'
        in pending_source
    )
    assert "get" in paths["/api/v1/invoices/listing"]
    assert "get" in paths["/api/v1/invoices/inventory-pending"]
    assert "get" in paths["/api/v1/invoices/inventory-audit"]
