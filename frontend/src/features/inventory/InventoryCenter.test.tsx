import { act, render, screen } from "@testing-library/react";
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
});
