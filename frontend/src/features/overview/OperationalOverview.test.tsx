import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OperationalOverview } from "./OperationalOverview";

const dashboard = {
  period: {
    key: "month",
    start: "2026-07-01",
    end: "2026-07-29",
    last_updated: "2026-07-29T18:00:00Z",
  },
  metrics: {
    available_units: 850,
    products_with_stock: 42,
    entries_units: 300,
    supplier_invoices: 3,
    sales_units: 144,
    sales_invoices: 1,
    invoiced_value: "761.88",
    out_of_stock: 2,
    low_stock: 3,
    attention: 4,
  },
  attention: [{
    type: "invoice_inventory",
    title: "Factura 001-001-000000758",
    description: "El descuento de inventario requiere revisión.",
    date: "2026-07-29T17:00:00Z",
    target: "invoices",
    target_id: "invoice-1",
    severity: "error",
  }],
  recent_activity: [{
    date: "2026-07-29T17:00:00Z",
    type: "Factura de venta",
    document: "Factura 001-001-000000758",
    description: "Cadena",
    quantity: -144,
    user: "Usuario",
    result: "Inventario descontado",
    target: "invoices",
    target_id: "invoice-1",
  }],
};

afterEach(() => cleanup());

describe("OperationalOverview", () => {
  it("presenta el panel limpio mientras carga", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => undefined)));
    render(<OperationalOverview onNavigate={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Panel de control" })).toBeVisible();
    expect(screen.getByText("Cargando indicadores…")).toBeVisible();
  });

  it("muestra seis métricas útiles sin despacho ni entrega", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(dashboard), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    const navigate = vi.fn();

    render(<OperationalOverview onNavigate={navigate} />);

    expect(await screen.findByText("Inventario disponible")).toBeVisible();
    expect(screen.getByText("Entradas del período")).toBeVisible();
    expect(screen.getByText("Salidas por facturación")).toBeVisible();
    expect(screen.getByText("Valor facturado")).toBeVisible();
    expect(screen.getByText("Stock crítico")).toBeVisible();
    expect(screen.getByText("Atención requerida")).toBeVisible();
    expect(screen.queryByText(/despacho pendiente/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/entrega pendiente/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByText("Factura 001-001-000000758")[0]!);
    expect(sessionStorage.getItem("inventario.openInvoiceId")).toBe("invoice-1");
    expect(navigate).toHaveBeenCalledWith("invoices");
  });
});
