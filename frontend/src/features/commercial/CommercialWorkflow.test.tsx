import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CommercialWorkflow } from "./CommercialWorkflow";
import { apiRequest, apiUpload } from "../../api/client";
vi.mock("../../api/client", () => ({ apiRequest: vi.fn(), apiUpload: vi.fn(), apiUrl: (p: string) => p }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const line = {id:"l1", key:"code:P1", name:"SHAMPOO ROMERO", code:"P1", quantity:10, unit:"unidades", unit_price:2, amount:20, issues:[]};
const order = {id:"o1", document_id:"d1", kind:"order", number:"26003023", chain:"INDUSTRIAL DANEC", date:"2026-09-14", filename:"OC.pdf", origin:"import", lines:[line], quantity:10, quantity_unit:"unidades", amount:20, issues:[], records:[], linked_order_id:null, reference:"", status:"PARCIAL", fulfillment:50, invoices:[{id:"i1", number:"001-001-000000001", date:"2026-09-16", method:"Número de OC explícito"}]};
const invoice = {...order, id:"i1", document_id:"d2", kind:"invoice", number:"001-001-000000001", reference:"26003023", linked_order_id:"o1", status:"OK", link_method:"Número de OC explícito"};
const comparison = {chain:order.chain, order_id:"o1", order_number:order.number, product:line.name, code:line.code, unit:"unidades", ordered:10, invoiced:5, difference:5, missing:5, fulfillment:50, ordered_amount:20, invoiced_amount:10, unbilled_amount:10, status:"PARCIAL"};
const data = {orders:[order], invoices:[invoice], comparisons:[comparison], chains:[{chain:order.chain, orders:1, invoices:1, linked:1, linked_orders:1, pending:0, status:"OK"}], summary:{invoices:1,linked:1,pending:0}};
describe("Flujo comercial", () => {
    it("organiza por cadena y muestra datos, facturas y productos al seleccionar OC", async () => {
        vi.mocked(apiRequest).mockResolvedValue(data);
        render(<CommercialWorkflow mode="orders" advanced={<p>Operación anterior</p>} />);
        const chainTable = await screen.findByRole("table", {name:"Resumen por cadena"});
        fireEvent.click(within(chainTable).getByRole("button", {name:order.chain}));
        expect(screen.queryByText(line.name)).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", {name:/OC 26003023/}));
        expect(screen.getAllByText(line.name).length).toBeGreaterThan(0);
        expect(screen.getByText("001-001-000000001 · 16/09/2026")).toBeVisible();
        expect(screen.getAllByText("50 %")[0]).toBeVisible();
        expect(screen.queryByText("La OC inicia la trazabilidad")).not.toBeInTheDocument();
        expect(screen.queryByText("Operación anterior")).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", {name:"Más opciones"}));
        expect(screen.getByText("Operación anterior")).toBeVisible();
    });
    it("usa datos guardados para comparar sin solicitar archivos", async () => {
        vi.mocked(apiRequest).mockResolvedValue(data);
        render(<CommercialWorkflow mode="comparisons" advanced={null} />);
        const table = await screen.findByRole("table", {name:"Pedido vs Facturado"});
        expect(within(table).getByText("PARCIAL")).toBeVisible();
        expect(screen.queryByText("Procesar")).not.toBeInTheDocument();
        expect(apiRequest).toHaveBeenCalledWith("/commercial/workflow", expect.anything());
        expect(apiUpload).not.toHaveBeenCalled();
    });
    it("Facturación muestra contadores y oc vinculada y permite revisar solo excepciones", async () => {
        vi.mocked(apiRequest).mockResolvedValue(data);
        render(<CommercialWorkflow mode="invoices" advanced={null} />);
        await screen.findByText("Facturas detectadas");
        expect(screen.getByLabelText("Archivos de facturas")).toHaveAttribute("multiple");
        fireEvent.click(screen.getByRole("button", {name:/Factura 001-001-000000001/}));
        expect(screen.getByText("Número de OC explícito")).toBeVisible();
        fireEvent.click(screen.getByRole("button", {name:"Revisar solo excepciones"}));
        expect(screen.getByText("No hay documentos por revisar.")).toBeVisible();
    });
});
