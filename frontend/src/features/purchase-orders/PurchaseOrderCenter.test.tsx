import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PurchaseOrderCenter } from "./PurchaseOrderCenter";

afterEach(cleanup);

const emptyResponse = () => new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
const settingsResponse = () => new Response(JSON.stringify({ suggested_chains: ["Gerardo Ortiz", "Favorita", "Rosado", "Danec", "Tía"] }), { status: 200, headers: { "Content-Type": "application/json" } });
const mockApi = () => vi.fn().mockImplementation(async (input: RequestInfo | URL) => String(input).includes("/settings/operational") ? settingsResponse() : emptyResponse());

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
});
