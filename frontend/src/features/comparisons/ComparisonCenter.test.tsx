import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ComparisonCenter } from "./ComparisonCenter";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ComparisonCenter", () => {
  it("muestra diferencias entre OC, factura y despacho", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([
      {
        chain_name: "Favorita",
        customer_name: null,
        order_number: "OC-123",
        order_date: "2026-07-08",
        source_type: "purchase_order",
        sku: "SKU-001",
        product_name: "Producto de prueba",
        ordered_quantity: 10,
        invoiced_quantity: 8,
        dispatched_quantity: 5,
        delivered_quantity: 0,
        rejected_delivery_quantity: 0,
        missing_quantity: 0,
        pending_to_invoice: 2,
        pending_to_dispatch: 3,
        pending_to_deliver: 5,
        invoice_numbers: ["001-001-000000686"],
        delivery_statuses: ["pending"],
        outside_purchase_order: false,
        status: "pending_invoice",
      },
    ]), { status: 200, headers: { "Content-Type": "application/json" } })));

    render(<ComparisonCenter />);

    expect(await screen.findByRole("heading", { name: "Comparativos" })).toBeVisible();
    expect(await screen.findByText("OC-123")).toBeVisible();
    expect(screen.getByText("001-001-000000686")).toBeVisible();
    expect(screen.getAllByText("Pendiente facturar").length).toBeGreaterThan(0);
    expect(screen.getByText("Facturar: 2")).toBeVisible();
    expect(screen.getByText("Despachar: 3")).toBeVisible();
    expect(screen.getByText("Entregar: 5")).toBeVisible();
  });
});
