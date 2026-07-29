import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InvoiceCenter } from "./InvoiceCenter";

describe("InvoiceCenter", () => {
  it("explica su alcance y muestra un estado vacío útil", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [], page: 1, pages: 1, total: 0, missing_sequences: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    render(<InvoiceCenter />);

    expect(screen.getByText(/aquí no se factura/i)).toBeVisible();
    expect(await screen.findByText("No encontramos facturas.")).toBeVisible();
    expect(screen.getByText("Selecciona una factura")).toBeVisible();
  });

  it("muestra la factura como entrega pendiente y calcula la comparación", async () => {
    const summary = {
      id: "invoice-1", invoice_number: "001-001-000000001", invoice_date: "2026-07-28",
      customer_name: "Cliente", chain_name: "Cadena", total_value: "10",
      administrative_status: "confirmed", dispatch_status: "pending",
      delivery_status: "pending", purchase_order_id: "order-1",
      purchase_order_number: "OC-1", product_count: 1, units: 10,
      inventory: { status: "correct", status_label: "Descontada correctamente", discounted_units: 10, difference: 0 },
    };
    const trace = {
      invoice: {
        id: "invoice-1", number: summary.invoice_number, date: summary.invoice_date,
        customer: "Cliente", chain: "Cadena", source_type: "purchase_order",
        authorization_number: null, remittance_guide: null, notes: null,
        total_value: "10", net_value: "10",
        statuses: { administrative: "confirmed", dispatch: "pending", delivery: "pending", incident: "none", return: "none", inventory: "correct" },
        inventory: { status: "correct", status_label: "Descontada correctamente", discounted_at: "2026-07-28T12:00:00Z", discounted_quantity: 10, movement_ids: ["movement-1"], last_error: null, attempts: 1 },
      },
      purchase_order: { id: "order-1", number: "OC-1", chain: "Cadena" },
      lines: [{
        sku: "SKU-1", product_name: "Producto", ordered: 10, invoiced: 10,
        dispatched: 0, missing: 0, delivered: 8, pending_dispatch: 10,
        pending_confirmation: 2, delivery_difference: -2, outside_purchase_order: false,
      }],
      deliveries: [], incidents: [], alerts: [], returns: [], adjustments: [],
    };
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      return new Response(JSON.stringify(url.includes("/traceability") ? trace : { items: [summary], page: 1, pages: 1, total: 1, missing_sequences: [] }), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }));

    render(<InvoiceCenter />);

    expect(await screen.findByText("Facturada · Entrega pendiente")).toBeVisible();
    const table = screen.getByRole("heading", { name: "Factura → entrega" }).nextElementSibling;
    expect(table).toHaveTextContent("Producto");
    expect(table).toHaveTextContent("10");
    expect(table).toHaveTextContent("8");
    expect(table).toHaveTextContent("2");
    expect(table).toHaveTextContent("-2");
  });

  it("audita sin modificar y exige vista previa antes de corregir", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const data = url.includes("correction-preview")
        ? { correctable: [{ id: "invoice-2", invoice_number: "001-001-000000002", status_label: "Sin descontar", units_to_discount: 12 }], blocked: [], will_change_inventory: true }
        : url.includes("inventory-audit")
          ? { summary: { reviewed: 1, correct: 0, missing: 1, partial: 0, duplicate: 0, over: 0, cancelled_correct: 0, cancelled_missing_reversal: 0, errors: 0 }, items: [{ id: "invoice-2", invoice_number: "001-001-000000002", invoice_date: "2026-07-28", invoiced_units: 12, discounted_units: 0, difference: 12, status: "missing", status_label: "Sin descontar" }] }
          : { items: [], page: 1, pages: 1, total: 0, missing_sequences: [] };
      return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    const { container } = render(<InvoiceCenter />);
    fireEvent.click(within(container).getByRole("button", { name: "Auditar facturas" }));
    expect(await within(container).findByText(/001-001-000000002/)).toBeVisible();
    fireEvent.click(within(container).getByRole("button", { name: "Corregir movimientos pendientes" }));
    expect(await within(container).findByText(/salida pendiente de 12 unidades/)).toBeVisible();
    expect(within(container).getByRole("button", { name: "Confirmar y corregir diferencias" })).toBeVisible();
  });
});
