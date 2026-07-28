import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProductCombobox } from "./ProductCombobox";
import { PurchaseOrderCombobox } from "./PurchaseOrderCombobox";

afterEach(cleanup);

const response = (body: unknown) => new Response(JSON.stringify(body), {
  status: 200,
  headers: { "Content-Type": "application/json" },
});

describe("buscadores por teclado", () => {
  it("busca OC en el servidor y permite flechas, Enter y Escape", async () => {
    const onSelect = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      items: [
        { id: "1", order_number: "4500346780", chain_name: "TUTI", status: "open", destination: null, product_count: 4 },
        { id: "2", order_number: "3000927171", chain_name: "Tía", status: "completed", destination: null, product_count: 4 },
      ],
      next_cursor: null,
    })));
    render(<PurchaseOrderCombobox label="Buscar OC" value={null} onSelect={onSelect} />);
    const input = screen.getByRole("combobox", { name: "Buscar OC" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "3000" } });
    expect(await screen.findByRole("option", { name: /3000927171/i })).toBeVisible();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ id: "2" }));
    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input).toHaveAttribute("aria-expanded", "false");
  });

  it("muestra nombre antes del SKU y selecciona productos sin ratón", async () => {
    const onSelect = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response([{
      id: "p1", sku: "AR001", product_name: "SHAMPOO ANA REGENEXT 400 ML",
      barcode: "7860001", contifico_aux_code: null, available_to_invoice: 20, units_per_box: 12,
    }])));
    render(<ProductCombobox label="Producto" value="" products={[]} onSelect={onSelect} />);
    const input = screen.getByRole("combobox", { name: "Producto" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "regenext" } });
    const option = await screen.findByRole("option", { name: /SHAMPOO ANA REGENEXT 400 ML.*SKU: AR001/i });
    expect(option.querySelector("strong")).toHaveTextContent("SHAMPOO ANA REGENEXT 400 ML");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenLastCalledWith("AR001", expect.objectContaining({ sku: "AR001" }));
  });
});
