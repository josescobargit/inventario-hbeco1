import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { DocumentWorkspace } from "./DocumentWorkspace";
import { groupDocuments } from "./documentReview";
import type { Evidence } from "./types";
const row: Evidence = { id: "r1", document_id: "d1", filename: "OC.pdf", origin: "import", chain: "", kind: "order", date: "2026-09-08", order_number: "OC-100", invoice_number: "", product_id: "p1", product_name: "Shampoo", sku: "SH1", units: 8, amount: null, conversion: "", match_method: "EAN", source_location: "Página 1", source_url: "/source", issues: ["Cadena no identificada"], monetary_issues: [], excluded: false, source: {}, revision: 1 };
const rows = [row, { ...row, id: "r2", product_name: "Acondicionador" }];
const data = { records: rows };
beforeEach(() => {
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([{ id: "d1", filename: "OC.pdf", warnings: [] }]), { headers: { "Content-Type": "application/json" } })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("agrupa por identidad de documento y cuenta un problema de cabecera una sola vez", () => {
    const groups = groupDocuments([...rows, { ...row, id: "r3", document_id: "d2" }], []);
    expect(groups).toHaveLength(2);
    expect(groups[0]?.records).toHaveLength(2);
    expect(groups[0]?.issues).toEqual(["Cadena no identificada"]);
    expect(groupDocuments([{ ...row, issues: [] }], [])[0]?.status).toBe("OK");
    expect(groupDocuments([], [], [{ filename: "error.pdf", status: "error", message: "No se pudo leer" }])[0]?.status).toBe("ERROR");
});
it("muestra una fila, oculta productos y corrige solo la cadena en todo el documento", async () => {
    const refresh = vi.fn(async () => {});
    render(<DocumentWorkspace data={data} products={[]} loading={false} onRefresh={refresh} />);
    await screen.findByText("OC.pdf");
    expect(screen.getAllByText("OC.pdf")).toHaveLength(1);
    expect(screen.queryByText("Shampoo")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Revisar OC.pdf" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getAllByText("Cadena no identificada")).toHaveLength(1);
    expect(within(dialog).getByText("1 problema")).toBeVisible();
    expect(within(dialog).queryByLabelText("Fecha de OC")).not.toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Cadena"), { target: { value: "TIA" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Aplicar a todo el documento" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const call = vi.mocked(fetch).mock.calls.find(([, options]) => options?.method === "PATCH");
    expect(String(call?.[0])).toContain("/documents/d1/header");
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ values: { chain: "TIA" }, revisions: { r1: 1, r2: 1 } });
});
it("un documento correcto se abre sin pedir confirmación", async () => {
    render(<DocumentWorkspace data={{ records: [{ ...row, issues: [], chain: "TIA" }] }} products={[]} loading={false} onRefresh={async () => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Ver OC.pdf" }));
    expect(screen.getByText("OK · No necesitas confirmar ningún dato.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Aplicar a todo el documento" })).not.toBeInTheDocument();
});
