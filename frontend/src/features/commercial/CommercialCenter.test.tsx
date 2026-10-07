import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { CommercialCenter } from "./CommercialCenter";
const totals = { ordered: 24, invoiced: 12, missing: 12, difference: 12, fulfillment: 50, ordered_amount: null, invoiced_amount: 24, unbilled_amount: null };
const record = { id: "row1", document_id: "doc1", filename: "pedido.csv", source_location: "CSV, fila 2", source_url: "/commercial/documents/doc1/content", origin: "import", kind: "order", chain: "Cadena A", date: "2026-10-01", product_id: "p1", product_name: "Shampoo Romero", sku: "SH001", units: 24, amount: null, conversion: "2 cajas × 12 = 24 unidades", match_method: "EAN exacto", order_number: "OC-1", invoice_number: "", issues: ["Moneda por revisar"], monetary_issues: [], excluded: false, source: { kind: "OC", chain: "Cadena A" }, revision: 1 };
const fixture = { summary: { ...totals, review_records: 1, excluded_records: 0, sell_in_units: null, sell_out_units: null }, rows: [{ ...totals, chain: "Cadena A", product_name: "Shampoo Romero", sku: "SH001", order_number: "OC-1", status: "PARCIAL", order_records: [record], invoices: [], pending_records: [] }], chains: [{ ...totals, chain: "Cadena A" }], products: [], by_chain_product: [], records: [record], alerts: [{ level: "REVISIÓN", code: "valuation", message: "Moneda por revisar", record_ids: ["row1"] }], sales: [], sell_comparison: [], sales_by_line: [], sales_movements: [], evolution: [], rankings: {}, basis: "Cifras confirmadas; los datos dudosos no se suman.", executive_report: ["Quedaron 12 unidades pendientes."] };
beforeEach(() => {
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
        const path = String(input);
        const payload = path.includes("/commercial/dashboard") ? fixture : path.includes("/commercial/products") ? [] : path.includes("/commercial/imports") ? { files: [{ filename: "ventas.csv", status: "processed", message: "Procesado", rows: 1 }] } : path.includes("/commercial/assistant") ? { answer: ["Quedaron 12 unidades pendientes."], mode: "local", filters: {}, sources: [], limitations: "Solo datos almacenados." } : options?.method === "PATCH" ? { revision: 2 } : {};
        return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("Control comercial", () => {
    it("distingue importes desconocidos y permite auditar el cálculo", async () => {
        render(<CommercialCenter />);
        fireEvent.click(screen.getByRole("button", { name: "Más opciones" }));
        expect(await screen.findByText("1 registros necesitan revisión.")).toBeVisible();
        expect(screen.getAllByText("Sin dato").length).toBeGreaterThan(0);
        fireEvent.click(screen.getByRole("button", { name: "OC vs facturas" }));
        fireEvent.click(screen.getByText("OC → facturas"));
        fireEvent.click(screen.getByRole("button", { name: /OC OC-1 · 24 unidades/ }));
        expect(screen.getByRole("dialog")).toBeVisible();
        expect(screen.getByText("2 cajas × 12 = 24 unidades")).toBeVisible();
        expect(screen.getByRole("link", { name: "Descargar documento original" })).toHaveAttribute("href", "/api/v1/commercial/documents/doc1/content");
        fireEvent.change(screen.getByLabelText("Moneda"), { target: { value: "USD" } });
        fireEvent.change(screen.getByLabelText("Motivo y evidencia de la corrección"), { target: { value: "USD consta en el original" } });
        fireEvent.click(screen.getByRole("button", { name: "Guardar corrección y recalcular" }));
        await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
        expect(vi.mocked(fetch).mock.calls.some(([url, options]) => String(url).endsWith("/records/row1") && JSON.parse(String(options?.body)).revision === 1)).toBe(true);
    });
    it("el Dashboard conserva indicadores y abre el procesador como otro módulo", async () => {
        render(<CommercialCenter />);
        expect(await screen.findByText("Pedido total")).toBeVisible();
        expect(screen.queryByLabelText("Archivos comerciales")).not.toBeInTheDocument();
        const navigate = vi.fn();
        window.addEventListener("inventario:navigate", navigate);
        fireEvent.click(screen.getByRole("button", { name: "Procesar documentos" }));
        expect(navigate.mock.calls[0]?.[0].detail).toBe("processing");
        window.removeEventListener("inventario:navigate", navigate);
        fireEvent.click(screen.getByRole("button", { name: "Sell In / Sell Out" }));
        expect(screen.getByRole("heading", { name: "Sell In y Sell Out" })).toBeVisible();
    });
    it("envía filtros al asistente y a las exportaciones", async () => {
        render(<CommercialCenter />);
        fireEvent.click(screen.getByRole("button", { name: "Más opciones" }));
        await screen.findByText("1 registros necesitan revisión.");
        fireEvent.change(screen.getByLabelText("Cadena"), { target: { value: "Cadena A" } });
        fireEvent.click(screen.getByRole("button", { name: "Aplicar filtros" }));
        await screen.findByText("1 registros necesitan revisión.");
        fireEvent.click(screen.getByRole("button", { name: "Asistente" }));
        fireEvent.click(screen.getByRole("button", { name: "Dime qué debería revisar" }));
        expect(await screen.findByText("Quedaron 12 unidades pendientes.")).toBeVisible();
        expect(vi.mocked(fetch).mock.calls.some(([url, options]) => String(url).endsWith("/assistant") && JSON.parse(String(options?.body)).chain === "Cadena A")).toBe(true);
        fireEvent.click(screen.getByRole("button", { name: "Reporte" }));
        expect(screen.getByRole("link", { name: "Descargar Excel general" })).toHaveAttribute("href", expect.stringContaining("chain=Cadena+A"));
    });
    it("muestra el error de carga sin reutilizar indicadores anteriores", async () => {
        render(<CommercialCenter />);
        fireEvent.click(screen.getByRole("button", { name: "Más opciones" }));
        await screen.findByText("1 registros necesitan revisión.");
        vi.mocked(fetch).mockImplementation(async () => new Response(JSON.stringify({ detail: "Base temporalmente no disponible" }), { status: 503 }));
        fireEvent.click(screen.getByRole("button", { name: "Aplicar filtros" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("Base temporalmente no disponible");
        expect(screen.queryByText("1 registros necesitan revisión.")).not.toBeInTheDocument();
        expect(within(screen.getByRole("alert")).getByRole("button", { name: "Reintentar" })).toBeVisible();
    });
});
