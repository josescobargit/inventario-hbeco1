import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InvoiceCenter } from "./InvoiceCenter";

describe("InvoiceCenter", () => {
  it("explica su alcance y muestra un estado vacío útil", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify([]), {
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
      delivery_status: "pending", incident_status: "none",
    };
    const trace = {
      invoice: {
        id: "invoice-1", number: summary.invoice_number, date: summary.invoice_date,
        customer: "Cliente", chain: "Cadena", source_type: "purchase_order",
        authorization_number: null, remittance_guide: null, notes: null,
        total_value: "10", net_value: "10",
        statuses: { administrative: "confirmed", dispatch: "pending", delivery: "pending", incident: "none", return: "none" },
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
      return new Response(JSON.stringify(url.includes("/traceability") ? trace : [summary]), {
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
});
