import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PurchaseOrderCenter } from "./PurchaseOrderCenter";

afterEach(cleanup);

const emptyResponse = () => new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
const settingsResponse = () => new Response(JSON.stringify({ suggested_chains: ["Gerardo Ortiz", "Favorita", "Rosado", "Danec", "Tía"] }), { status: 200, headers: { "Content-Type": "application/json" } });
const mockApi = () => vi.fn().mockImplementation(async (input: RequestInfo | URL) => String(input).includes("/settings/operational") ? settingsResponse() : emptyResponse());
const product = { id: "p1", sku: "ACP001", product_name: "Toallitas Húmedas Ana x 100", barcode: null, contifico_aux_code: null, available_to_invoice: 80, units_per_box: 12 };
const order = {
  id: "o1", chain_name: "Favorita", customer_name: "Favorita", order_number: "OC-10",
  order_date: null, destination: "CD Norte", status: "open", notes: null, source_documents: [],
  related_invoices: [], lines: [{ sku: "ACP001", product_name: product.product_name, ordered_quantity: 12,
    invoiced_quantity: 0, dispatched_quantity: 0, delivered_quantity: 0, returned_quantity: 0,
    net_delivered_quantity: 0, pending_delivery: 12, difference: -12, fulfillment_status: "not_processed",
    has_incident: false, available: 80, suggested_to_invoice: 12, shortage: 0, complete: true, units_per_box: 12 }],
};
const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("PurchaseOrderCenter", () => {
  it("explica la OC como documento de origen", async () => {
    vi.stubGlobal("fetch", mockApi());
    render(<PurchaseOrderCenter />);
    expect(screen.getByRole("heading", { name: "Órdenes de Compra" })).toBeVisible();
    expect(await screen.findByText(/la OC inicia la trazabilidad/i)).toBeVisible();
  });

  it("filtra cadenas y deja la elección en manos del usuario", async () => {
    vi.stubGlobal("fetch", mockApi());
    render(<PurchaseOrderCenter />);
    fireEvent.click(screen.getByRole("button", { name: "Nueva OC" }));
    const chainInput = screen.getByRole("combobox", { name: /cadena/i });
    fireEvent.change(chainInput, { target: { value: "fa" } });
    expect(screen.getByRole("option", { name: "Favorita" })).toBeVisible();
    expect(screen.queryByRole("option", { name: /El Rosado/i })).not.toBeInTheDocument();
    expect(chainInput).toHaveValue("fa");
    fireEvent.click(screen.getByRole("option", { name: "Favorita" }));
    expect(chainInput).toHaveValue("Favorita");
    fireEvent.change(chainInput, { target: { value: "Cadena Nueva" } });
    expect(screen.getByText(/se guardará como una cadena nueva/i)).toBeVisible();
    expect(chainInput).toHaveValue("Cadena Nueva");
  });

  it("busca por código o nombre y permite reemplazar completamente la cantidad", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/settings/operational")) return settingsResponse();
      if (url.includes("/inventory/availability")) return jsonResponse([product]);
      return emptyResponse();
    }));
    render(<PurchaseOrderCenter />);
    fireEvent.click(screen.getByRole("button", { name: "Nueva OC" }));
    const productInput = screen.getByRole("combobox", { name: "Producto" });
    fireEvent.change(productInput, { target: { value: "toallitas ana" } });
    fireEvent.click(await screen.findByRole("option", { name: /ACP001/i }));
    expect(productInput).toHaveValue("Toallitas Húmedas Ana x 100 · SKU: ACP001");
    const quantity = screen.getByRole("textbox", { name: "Cantidad" });
    fireEvent.change(quantity, { target: { value: "" } });
    expect(quantity).toHaveValue("");
    fireEvent.change(quantity, { target: { value: "7" } });
    expect(quantity).toHaveValue("7");
  });

  it("guarda y deja un formulario limpio listo para otra OC", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/settings/operational")) return settingsResponse();
      if (url.includes("/inventory/availability")) return jsonResponse([product]);
      if (url.endsWith("/purchase-orders") && init?.method === "POST") return jsonResponse({ ...order, id: "created", order_number: "OC-11" }, 201);
      return emptyResponse();
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<PurchaseOrderCenter />);
    fireEvent.click(screen.getByRole("button", { name: "Nueva OC" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Cadena" }), { target: { value: "Favorita" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Número de OC *" }), { target: { value: "OC-11" } });
    const productInput = screen.getByRole("combobox", { name: "Producto" });
    fireEvent.change(productInput, { target: { value: "ACP001" } });
    fireEvent.click(await screen.findByRole("option", { name: /ACP001/i }));
    fireEvent.click(screen.getByRole("button", { name: "Registrar OC" }));
    expect(await screen.findByRole("status")).toHaveTextContent("OC registrada correctamente");
    expect(screen.getByRole("heading", { name: "Nueva orden de compra" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Número de OC *" })).toHaveValue("");
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Número de OC *" })).toHaveFocus());
    const body = JSON.parse(String(fetchMock.mock.calls.find((call) => call[1]?.method === "POST")?.[1]?.body));
    expect(body.customer_name).toBe("Favorita");
    expect(body.lines).toEqual([{ sku: "ACP001", quantity: 1 }]);
  });

  it("copia una OC como plantilla, exige confirmación y abre el lector funcional", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/settings/operational")) return settingsResponse();
      if (url.includes("/inventory/availability")) return jsonResponse([product]);
      if (url.endsWith("/purchase-orders")) return jsonResponse([order]);
      return emptyResponse();
    }));
    render(<PurchaseOrderCenter />);
    await screen.findByText("OC-10");
    fireEvent.click(screen.getAllByRole("button", { name: "Usar como plantilla" })[0]!);
    expect(screen.getByRole("textbox", { name: "Número de OC *" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Producto" })).toHaveValue("Toallitas Húmedas Ana x 100 · SKU: ACP001");
    expect(screen.getByRole("button", { name: "Registrar OC" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /productos y cantidades copiados/i }));
    expect(screen.getByRole("button", { name: "Registrar OC" })).toBeEnabled();
    fireEvent.click(screen.getAllByRole("button", { name: "Leer PDF o imagen" })[0]!);
    expect(screen.getByRole("heading", { name: "Crear OC desde PDF, imagen o pedido" })).toBeVisible();
  });
});
