import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReportCenter } from "./ReportCenter";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ReportCenter", () => {
  it("muestra el reporte operativo con datos existentes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      inventory: { products: 2, physical: 100, reserved: 10, invoiced_pending: 15, blocked: 1, available: 74, low_stock_products: 1 },
      workflow: { pending_dispatch: 2, pending_delivery: 1, open_incidents: 1 },
      by_chain: [{ chain_name: "Favorita", invoice_count: 2, units: 40 }],
      by_product: [{ sku: "SKU-001", product_name: "Producto A", category: "Línea A", units: 25 }],
      pending_by_chain: [{ chain_name: "Favorita", invoice_count: 1, units: 12 }],
      missing_products: [{ sku: "SKU-002", product_name: "Producto B", missing_units: 3, events: 1 }],
      low_stock: [{ sku: "SKU-003", product_name: "Producto C", category: "Línea C", available: 2, units_per_box: 6, status: "low_stock" }],
      movements_by_responsible: [{ responsible: "José Escobar", movements: 5 }],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    render(<ReportCenter />);

    expect(await screen.findByRole("heading", { name: "Reportes" })).toBeVisible();
    expect((await screen.findAllByText("Favorita")).length).toBeGreaterThan(0);
    expect(screen.getByText("SKU-001")).toBeVisible();
    expect(screen.getByText("SKU-002")).toBeVisible();
    expect(screen.getByText("José Escobar")).toBeVisible();
  });
});
