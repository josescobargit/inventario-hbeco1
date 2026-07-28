import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InventoryOperationCenter } from "./InventoryOperationCenter";

const user = { id: "user-1", username: "principal", full_name: "José Escobar", email: null, role: "principal", must_change_password: false };
const emptyResponse = () => new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
afterEach(cleanup);

describe("InventoryOperationCenter", () => {
  it("mantiene las salidas separadas de los despachos", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => emptyResponse()));
    render(<InventoryOperationCenter operationType="exit" user={user} />);
    expect(screen.getByRole("heading", { name: "Salidas" })).toBeVisible();
    expect(screen.getByText(/despachos a clientes se gestionan en su módulo independiente/i)).toBeVisible();
    expect(await screen.findByText("No se encontraron registros")).toBeVisible();
  });

  it("abre un formulario de entrada con evidencia y ofrece importar facturas", () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => emptyResponse()));
    const { container } = render(<InventoryOperationCenter operationType="entry" user={user} />);
    expect(screen.getByRole("heading", { name: "Ingresar facturas de proveedores" })).toBeVisible();
    expect(container.querySelector('input[type="file"][multiple]')).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Nueva entrada manual" }));
    expect(screen.getByText("Documento de respaldo *")).toBeVisible();
    expect(screen.getByRole("button", { name: "Guardar movimiento" })).toBeDisabled();
  });

  it("envía varias facturas como multipart y conserva líneas repetidas para revisión", async () => {
    const preview = [{
      supplier_ruc: "1791414667001", supplier_name: "GOLDERIE TRADING S.A",
      invoice_number: "001-003-000057409", issued_at: "2026-07-22",
      authorization_number: "clave", buyer_name: null, buyer_ruc: null,
      subtotal: 10, tax: 1.5, total: 11.5, original_filename: "factura.pdf",
      lines: [1, 2].map((line_number) => ({
        line_number, sku: "SKU-1", product_name: "ELIXIR", supplier_code: "IECPELX0034",
        barcode: "7862133169602", description: "ELIXIR TRATAMIENTO CAPILAR",
        quantity: 3, unit_price: 1, discount: 0, line_total: 3, status: "recognized",
      })),
    }];
    const fetchMock = vi.fn().mockImplementation(async (request: string, init?: RequestInit) => {
      if (String(request).includes("/supplier-invoices/imports/preview")) {
        expect(init?.body).toBeInstanceOf(FormData);
        return new Response(JSON.stringify(preview), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return emptyResponse();
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<InventoryOperationCenter operationType="entry" user={user} />);
    const fileInput = container.querySelector('input[type="file"][multiple]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [new File(["pdf"], "factura.pdf", { type: "application/pdf" })] } });
    fireEvent.click(screen.getByRole("button", { name: "Leer y revisar" }));

    expect(await screen.findByText("Líneas detectadas:")).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Duplicar" })).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/supplier-invoices/imports/preview"),
      expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
    );
  });
});
