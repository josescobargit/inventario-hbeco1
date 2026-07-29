import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PendingInventoryInvoices } from "./PendingInventoryInvoices";

const pendingResponse = {
  summary: {
    pending_invoices: 1,
    pending_complete: 0,
    pending_partial: 1,
    errors: 0,
    processing: 0,
    pending_units: 6,
  },
  items: [{
    id: "invoice-1",
    invoice_number: "001-001-000000773",
    invoice_date: "2026-07-28",
    chain_name: "Cadena",
    purchase_order_id: "order-1",
    purchase_order_number: "OC-773",
    invoiced_units: 10,
    discounted_units: 4,
    pending_units: 6,
    status: "pending_partial",
    status_label: "Pendiente parcial",
    error: null,
    attempts: 1,
    lines: [{
      product_id: "product-1",
      product_name: "Producto pendiente",
      sku: "SKU-1",
      invoiced_units: 10,
      discounted_units: 4,
      pending_units: 6,
    }],
  }],
  page: 1,
  pages: 1,
  total: 1,
  findings: { possible_duplicates: [], errors: [] },
  read_only: true,
};

const response = (data: unknown) => new Response(JSON.stringify(data), {
  status: 200,
  headers: { "Content-Type": "application/json" },
});

afterEach(() => cleanup());

describe("PendingInventoryInvoices", () => {
  it("muestra resumen y detalle por producto sin ejecutar correcciones", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(pendingResponse));
    vi.stubGlobal("fetch", fetchMock);

    render(<PendingInventoryInvoices onViewDetail={vi.fn()} />);

    expect(await screen.findByText("001-001-000000773")).toBeVisible();
    expect(screen.getByText("6 unidades")).toBeVisible();
    expect(screen.getAllByText("Pendiente parcial").length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Ver productos" }));
    expect(screen.getByText("Producto pendiente")).toBeVisible();
    expect(screen.getAllByText("SKU-1").length).toBeGreaterThan(0);
    expect(fetchMock.mock.calls.every((call) => !call[1]?.method || call[1].method === "GET")).toBe(true);
  });

  it("presenta la diferencia y retira la factura después de corregirla", async () => {
    let corrected = false;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        corrected = true;
        return response({
          results: [{ id: "invoice-1", invoice_number: "001-001-000000773", status: "corrected", units_discounted: 6 }],
          corrected: 1,
          errors: 0,
          inventory_affected: [{ sku: "SKU-1", physical_confirmed: 94, available_to_invoice: 94 }],
        });
      }
      return response(corrected ? {
        ...pendingResponse,
        summary: { pending_invoices: 0, pending_complete: 0, pending_partial: 0, errors: 0, processing: 0, pending_units: 0 },
        items: [],
        total: 0,
      } : pendingResponse);
    }));

    render(<PendingInventoryInvoices onViewDetail={vi.fn()} />);
    const checkbox = await screen.findByRole("checkbox", { name: "Seleccionar 001-001-000000773" });
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: "Descontar seleccionadas" }));

    const preview = screen.getByRole("region", { name: "Vista previa del descuento" });
    expect(within(preview).getByText(/6 unidades pendientes/)).toBeVisible();
    fireEvent.change(within(preview).getByRole("textbox"), { target: { value: "Completar movimiento faltante" } });
    fireEvent.click(within(preview).getByRole("button", { name: "Confirmar diferencias" }));

    expect(await screen.findByText("1 completadas · 0 con error · 0 sin cambios")).toBeVisible();
    expect(await screen.findByText("No se encontraron facturas con estos filtros.")).toBeVisible();
  });
});
