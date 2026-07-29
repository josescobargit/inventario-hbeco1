import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InventoryCenter } from "./InventoryCenter";

describe("InventoryCenter", () => {
  it("actualiza el inventario confirmado sin recargar la página", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([{
      sku: "SKU-1", product_name: "Producto", category: "Categoría",
      physical_confirmed: 100, reserved: 0, invoiced_not_dispatched: 0,
      blocked_by_incident: 0, available_to_invoice: 100, units_per_box: 10,
      physical_boxes: 10, available_boxes: 10, status: "available",
    }]), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<InventoryCenter />);
    expect((await screen.findAllByText("100")).length).toBeGreaterThan(0);

    act(() => {
      window.dispatchEvent(new CustomEvent("inventario:inventory-changed", {
        detail: [{ sku: "SKU-1", physical_confirmed: 88, available_to_invoice: 88 }],
      }));
    });

    expect(screen.getAllByText("88")).toHaveLength(4);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("consulta el inventario histórico y abre el saldo cronológico", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const data = url.includes("/movements")
        ? { product: { id: "product-1", name: "Producto", sku: "SKU-1" }, items: [{ id: "movement-1", occurred_at: "2026-06-17T13:00:00Z", movement_label: "Saldo inicial", document: "Conteo", entry: 90, exit: 0, balance: 90 }] }
        : url.includes("/inventory/history?")
          ? { label: "Inventario según el sistema al 17/06/2026", cutoff_local: "2026-06-17T23:59:59-05:00", theoretical: true, total: 1, items: [{ product_id: "product-1", product_name: "Producto", sku: "SKU-1", category: "Categoría", inventory_at_cutoff: 90, current_inventory: 80, difference: -10 }] }
          : [{ sku: "SKU-1", product_name: "Producto", category: "Categoría", physical_confirmed: 80, reserved: 0, invoiced_not_dispatched: 0, blocked_by_incident: 0, available_to_invoice: 80, units_per_box: 10, physical_boxes: 8, available_boxes: 8, status: "available" }];
      return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    const { container } = render(<InventoryCenter />);
    await within(container).findAllByText("80");
    fireEvent.click(within(container).getByRole("button", { name: "Inventario a una fecha" }));
    fireEvent.change(within(container).getByLabelText("Fecha de corte"), { target: { value: "2026-06-17" } });
    fireEvent.click(within(container).getByRole("button", { name: "Consultar" }));

    expect(await within(container).findByText("Inventario según el sistema al 17/06/2026")).toBeVisible();
    expect(within(container).getByText("-10")).toBeVisible();
    fireEvent.click(within(container).getByRole("button", { name: "Abrir historial" }));
    expect(await within(container).findByText("Saldo inicial")).toBeVisible();
    expect(within(container).getByText("Conteo")).toBeVisible();
  });
});
