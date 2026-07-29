import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InvoiceInventoryAudit } from "./InvoiceInventoryAudit";

const auditResponse = {
  summary: {
    reviewed: 1, correct: 0, missing: 0, partial: 1,
    excess_or_duplicate: 0, cancelled_incorrect: 0, requires_review: 0,
    pending_units: 6, excess_units: 0, orphan_movements: 0,
  },
  items: [{
    id: "invoice-1", invoice_number: "001-001-000000773", invoice_date: "2026-07-28",
    customer_name: "Cliente", chain_name: "Cadena", purchase_order_number: "OC-773",
    administrative_status: "confirmed", dispatch_status: "pending", product_count: 1,
    invoiced_units: 10, discounted_units: 4, difference: 6, pending_units: 6, excess_units: 0,
    status: "partial", status_label: "Parcial",
    products: [{
      product_id: "product-1", product_name: "Producto pendiente", sku: "SKU-1",
      expected: 10, discounted: 4, difference: 6, expected_movement: -10,
      found_movement: -4, outbound_movements: 1, pending_units: 6, excess_units: 0,
      status: "quantity_incorrect", status_label: "Cantidad incorrecta",
      inventory_current: 96,
      movements: [{
        id: "movement-1", occurred_at: "2026-07-28T12:00:00Z",
        responsible: "Usuario auditor", movement_type: "invoice_registered",
        reason: "Salida por factura", quantity: 4, net_inventory_effect: -4,
      }],
    }],
  }],
  orphan_movements: [],
  total: 1, page: 1, pages: 1, read_only: true,
};

const response = (data: unknown) => new Response(JSON.stringify(data), {
  status: 200,
  headers: { "Content-Type": "application/json" },
});

afterEach(() => cleanup());

describe("InvoiceInventoryAudit", () => {
  it("presenta el reporte completo sin modificar inventario", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(auditResponse));
    vi.stubGlobal("fetch", fetchMock);

    render(<InvoiceInventoryAudit onViewDetail={vi.fn()} />);

    expect(await screen.findByText("001-001-000000773")).toBeVisible();
    expect(screen.getByText("6 pendientes")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Ver detalle" }));
    expect(screen.getByText("Producto pendiente")).toBeVisible();
    expect(screen.getByText(/Usuario auditor/)).toBeVisible();
    expect(fetchMock.mock.calls.every((call) => !call[1]?.method || call[1].method === "GET")).toBe(true);
  });

  it("exige selección, vista previa y motivo antes de corregir", async () => {
    const fetchMock = vi.fn().mockImplementation(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        return response({
          corrected: 1, errors: 0,
          results: [{ id: "invoice-1", status: "corrected" }],
          inventory_affected: [{ sku: "SKU-1", physical_confirmed: 90, available_to_invoice: 90 }],
        });
      }
      return response(auditResponse);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<InvoiceInventoryAudit onViewDetail={vi.fn()} />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Seleccionar 001-001-000000773" }));
    fireEvent.click(screen.getByRole("button", { name: "Ver corrección propuesta" }));

    const preview = screen.getByRole("region", { name: "Vista previa de correcciones" });
    expect(within(preview).getByText(/inventario actual 96 · movimiento propuesto -6 · inventario resultante 90/)).toBeVisible();
    expect(within(preview).getByRole("button", { name: "Confirmar facturas seleccionadas" })).toBeDisabled();
    fireEvent.change(within(preview).getByRole("textbox"), { target: { value: "Completar diferencia auditada" } });
    fireEvent.click(within(preview).getByRole("button", { name: "Confirmar facturas seleccionadas" }));

    expect(await screen.findByText("1 corregidas · 0 con error · 0 sin cambios")).toBeVisible();
    expect(fetchMock.mock.calls.filter((call) => call[1]?.method === "POST")).toHaveLength(1);
  });
});
