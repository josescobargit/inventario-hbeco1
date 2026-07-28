import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PurchaseOrderCenter } from "./PurchaseOrderCenter";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const emptyResponse = () => new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
const settingsResponse = () => new Response(JSON.stringify({ suggested_chains: ["Gerardo Ortiz", "Favorita", "Rosado", "Danec", "Tía"] }), { status: 200, headers: { "Content-Type": "application/json" } });
const mockApi = () => vi.fn().mockImplementation(async (input: RequestInfo | URL) => String(input).includes("/settings/operational") ? settingsResponse() : emptyResponse());
const product = { id: "p1", sku: "ACP001", product_name: "Toallitas Húmedas Ana x 100", barcode: null, contifico_aux_code: null, available_to_invoice: 80, units_per_box: 12 };
const order = {
  id: "o1", chain_name: "Favorita", customer_name: "Favorita", order_number: "OC-10",
  order_date: null, destination: "CD Norte", status: "open", notes: null, source_documents: [],
  related_reservations: [], has_related_operations: false, manually_modified: false,
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
    fireEvent.click(screen.getByRole("button", { name: "Cerrar notificación" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Nueva orden de compra" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Número de OC *" })).toHaveValue("");
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Número de OC *" })).toHaveFocus());
    const body = JSON.parse(String(fetchMock.mock.calls.find((call) => call[1]?.method === "POST")?.[1]?.body));
    expect(body.customer_name).toBe("Favorita");
    expect(body.lines).toEqual([{ sku: "ACP001", quantity: 1 }]);
  });

  it("muestra una sola notificación y la desmonta automáticamente a los 3 segundos", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/settings/operational")) return settingsResponse();
      if (url.includes("/inventory/availability")) return jsonResponse([product]);
      if (url.endsWith("/purchase-orders") && init?.method === "POST") return jsonResponse({ ...order, id: "created" }, 201);
      return emptyResponse();
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<PurchaseOrderCenter />);
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByRole("button", { name: "Nueva OC" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Cadena" }), { target: { value: "Favorita" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Número de OC *" }), { target: { value: "OC-12" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Producto" }), { target: { value: "ACP001" } });
    fireEvent.click(screen.getByRole("option", { name: /ACP001/i }));
    fireEvent.click(screen.getByRole("button", { name: "Registrar OC" }));
    await act(async () => { await Promise.resolve(); });

    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent("OC registrada correctamente");
    expect(screen.getByRole("button", { name: "Cerrar notificación" })).toBeVisible();
    act(() => vi.advanceTimersByTime(2999));
    expect(screen.getByRole("status")).toBeVisible();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
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

  it("abre una OC existente en el formulario y permite cancelar sin guardar", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/settings/operational")) return settingsResponse();
      if (url.includes("/inventory/availability")) return jsonResponse([product]);
      if (url.endsWith("/purchase-orders")) return jsonResponse([order]);
      return emptyResponse();
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<PurchaseOrderCenter />);
    await screen.findByText("OC-10");

    fireEvent.click(screen.getAllByRole("button", { name: "Editar OC" })[0]!);
    expect(screen.getByRole("heading", { name: "Editar OC OC-10" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Número de OC *" })).toHaveValue("OC-10");
    expect(screen.getByRole("combobox", { name: "Producto" })).toHaveValue("Toallitas Húmedas Ana x 100 · SKU: ACP001");
    fireEvent.change(screen.getByRole("textbox", { name: "Destino" }), { target: { value: "Destino temporal" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(screen.getByRole("heading", { name: "OC OC-10" })).toBeVisible();
    expect(screen.getByText("CD Norte")).toBeVisible();
    expect(fetchMock.mock.calls.some((call) => call[1]?.method === "PUT")).toBe(false);
  });

  it("resume los cambios, guarda por PUT y actualiza el detalle sin recargar", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/settings/operational")) return settingsResponse();
      if (url.includes("/inventory/availability")) return jsonResponse([product]);
      if (url.endsWith("/purchase-orders") && !init?.method) return jsonResponse([order]);
      if (url.endsWith("/purchase-orders/o1") && init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        return jsonResponse({
          ...order,
          order_number: body.order_number,
          destination: body.destination,
          manually_modified: true,
          lines: [{ ...order.lines[0], ordered_quantity: body.lines[0].quantity }],
        });
      }
      return emptyResponse();
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<PurchaseOrderCenter />);
    await screen.findByText("OC-10");

    fireEvent.click(screen.getAllByRole("button", { name: "Editar OC" })[0]!);
    fireEvent.change(screen.getByRole("textbox", { name: "Número de OC *" }), { target: { value: "OC-11" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Destino" }), { target: { value: "CD Sur" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Cantidad" }), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Revisar cambios" }));

    const summary = screen.getByLabelText("Resumen de cambios");
    expect(summary).toHaveTextContent("Número de OCcambiado");
    expect(summary).toHaveTextContent("Destinocambiado");
    expect(summary).toHaveTextContent("Cantidades modificadas1");
    fireEvent.click(screen.getByRole("button", { name: "Confirmar y guardar" }));

    expect(await screen.findByRole("status")).toHaveTextContent("OC actualizada correctamente");
    expect(screen.getByRole("heading", { name: "OC OC-11" })).toBeVisible();
    const putCall = fetchMock.mock.calls.find((call) => call[1]?.method === "PUT");
    expect(JSON.parse(String(putCall?.[1]?.body)).lines[0].quantity).toBe(20);
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).endsWith("/purchase-orders") && !call[1]?.method)).toHaveLength(1);
  });

  it("mantiene la edición y muestra el error real al reducir bajo lo facturado", async () => {
    const relatedOrder = {
      ...order,
      has_related_operations: true,
      related_invoices: [{
        id: "i1", invoice_number: "001-001-000000001", administrative_status: "confirmed",
        dispatch_status: "partial", delivery_status: "pending", dispatches: [], deliveries: [],
      }],
      lines: [{ ...order.lines[0], invoiced_quantity: 8, dispatched_quantity: 4 }],
    };
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/settings/operational")) return settingsResponse();
      if (url.includes("/inventory/availability")) return jsonResponse([product]);
      if (url.endsWith("/purchase-orders") && !init?.method) return jsonResponse([relatedOrder]);
      if (init?.method === "PUT") return jsonResponse({ detail: "No puedes reducir ACP001 a 5 unidades porque ya se facturaron 8." }, 409);
      return emptyResponse();
    }));
    render(<PurchaseOrderCenter />);
    await screen.findByText("OC-10");

    fireEvent.click(screen.getAllByRole("button", { name: "Editar OC" })[0]!);
    expect(screen.getByText(/ya tiene operaciones relacionadas/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Eliminar producto 1" })).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: "Cantidad" }), { target: { value: "5" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Motivo de la edición *" }), { target: { value: "Corrección solicitada por el cliente" } });
    fireEvent.click(screen.getByRole("button", { name: "Revisar cambios" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar y guardar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No puedes reducir ACP001 a 5 unidades porque ya se facturaron 8.");
    expect(screen.getByRole("heading", { name: "Editar OC OC-10" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Cantidad" })).toHaveValue("5");
  });

  it("consulta y muestra el historial de cambios desde el detalle", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/settings/operational")) return settingsResponse();
      if (url.includes("/inventory/availability")) return jsonResponse([product]);
      if (url.endsWith("/purchase-orders")) return jsonResponse([{ ...order, manually_modified: true }]);
      if (url.endsWith("/purchase-orders/o1/history")) return jsonResponse([{
        id: "h1", occurred_at: "2026-07-27T18:00:00Z", actor: "José Escobar",
        field: "Destino", previous_value: "CD Norte", new_value: "CD Sur", reason: null,
      }]);
      return emptyResponse();
    }));
    render(<PurchaseOrderCenter />);
    await screen.findByText("OC-10");

    fireEvent.click(screen.getByRole("button", { name: "Historial de cambios" }));
    expect(await screen.findByText("José Escobar")).toBeVisible();
    expect(screen.getByText("CD Sur")).toBeVisible();
    expect(screen.getByText(/modificaciones manuales posteriores/i)).toBeVisible();
  });
});
