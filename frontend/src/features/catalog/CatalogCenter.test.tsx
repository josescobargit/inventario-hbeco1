import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CatalogCenter } from "./CatalogCenter";

const productsPayload = [
  {
    id: "product-1",
    sku: "AE001",
    name: "Shampoo Romero",
    description: "Producto base",
    category: "Cuidado Capilar",
    barcode: "786001",
    contifico_aux_code: "AUX-1",
    cost: "3.2980",
    units_per_box: 12,
    is_active: true,
    created_at: "2026-07-14T10:00:00Z",
    updated_at: "2026-07-14T10:00:00Z",
    physical_confirmed: 0,
    reserved: 0,
    invoiced_not_dispatched: 0,
    blocked_by_incident: 0,
  },
];

const createdPayload = {
  ...productsPayload[0],
  id: "product-2",
  sku: "AE010",
  name: "Nuevo Producto",
  barcode: null,
  contifico_aux_code: null,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("CatalogCenter", () => {
  it("lista, crea y actualiza productos del catálogo", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (init?.method === "POST") {
        return new Response(JSON.stringify(createdPayload), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      if (init?.method === "PUT") {
        return new Response(JSON.stringify({ ...productsPayload[0], name: "Shampoo Romero Editado" }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (path.includes("/catalog/products")) {
        return new Response(JSON.stringify(productsPayload), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CatalogCenter />);

    expect(await screen.findByRole("heading", { name: "Catálogo" })).toBeVisible();
    expect(await screen.findByText("Shampoo Romero")).toBeVisible();

    fireEvent.change(screen.getByPlaceholderText("SKU, nombre o código"), { target: { value: "AE001" } });
    expect(screen.getByText("Cuidado Capilar · UxC 12")).toBeVisible();

    fireEvent.change(screen.getByPlaceholderText("AE010"), { target: { value: "AE010" } });
    const createNameInput = screen.getAllByLabelText("Nombre *")[0] as HTMLElement;
    const createCategoryInput = screen.getAllByLabelText("Categoría *")[0] as HTMLElement;
    fireEvent.change(createNameInput, { target: { value: "Nuevo Producto" } });
    fireEvent.change(createCategoryInput, { target: { value: "Cuidado Capilar" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear producto" }));

    expect(await screen.findByText("Producto AE010 creado correctamente.")).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/catalog/products",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    ));

    fireEvent.click(screen.getByRole("button", { name: /AE001/ }));
    const editNameInput = screen.getAllByLabelText("Nombre *")[1] as HTMLElement;
    fireEvent.change(editNameInput, { target: { value: "Shampoo Romero Editado" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));

    expect(await screen.findByText("Producto AE001 actualizado correctamente.")).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/catalog/products/AE001",
      expect.objectContaining({ method: "PUT", credentials: "include" }),
    ));
  });
});
