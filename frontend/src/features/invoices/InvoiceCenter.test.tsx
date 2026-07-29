import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InvoiceCenter } from "./InvoiceCenter";

afterEach(() => cleanup());

describe("InvoiceCenter", () => {
  it("muestra únicamente la lista y un estado vacío útil", async () => {
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

    expect(screen.getByText(/listado secuencial de facturas/i)).toBeVisible();
    expect(await screen.findByText("No se encontraron facturas con estos filtros.")).toBeVisible();
    expect(screen.queryByLabelText("Detalle de factura")).not.toBeInTheDocument();
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

    fireEvent.click(await screen.findByText(summary.invoice_number));
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
    fireEvent.click(within(container).getByRole("button", { name: "Revisar y descontar pendientes" }));
    expect((await within(container).findAllByText(/001-001-000000002/))[0]).toBeVisible();
    expect(await within(container).findByText(/descontar únicamente 12 unidades pendientes/)).toBeVisible();
    expect(within(container).getByRole("button", { name: "Confirmar y descontar pendientes" })).toBeVisible();
  });

  it("usa GET y convierte un 405 en un error recuperable", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Method Not Allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json", Allow: "PUT" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    render(<InvoiceCenter />);

    expect(await screen.findByText("No se pudieron cargar las facturas.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeVisible();
    expect(screen.queryByText("Method Not Allowed")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBeUndefined();
  });

  it("cambia entre todas, sin descontar, parciales, errores, descontadas y anuladas", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => {
      const data = { items: [], page: 1, pages: 1, total: 0, missing_sequences: [], summary: { invoices: 0, missing: 0, partial: 0, errors: 0, discounted: 0, cancelled: 0, pending_units: 0 } };
      return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<InvoiceCenter />);
    expect(await screen.findByText("No se encontraron facturas con estos filtros.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Sin descontar/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("inventory_status=missing"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: /Parciales/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("inventory_status=partial"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: /Descontadas/ }));
    await waitFor(() => expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("inventory_status=correct"))).toBe(true));
    expect(screen.getByRole("button", { name: /Con error/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /Anuladas/ })).toBeVisible();
  });
});
