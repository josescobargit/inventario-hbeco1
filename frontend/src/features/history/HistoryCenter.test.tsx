import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HistoryCenter } from "./HistoryCenter";

const historyPayload = [
  {
    id: "audit-1",
    occurred_at: "2026-07-14T14:30:00Z",
    actor: "José Escobar",
    username: "principal",
    action: "invoice_registered",
    action_label: "Factura registrada",
    entity_type: "invoice",
    module: "Facturación",
    entity_id: "001-001-000000686",
    reason: "Factura vinculada a la OC manualmente",
    summary: "invoice: 001-001-000000686 · chain: Favorita",
    previous_value: null,
    new_value: { invoice: "001-001-000000686", chain: "Favorita", units: 12 },
    ip_address: "127.0.0.1",
  },
];

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("HistoryCenter", () => {
  it("muestra eventos de auditoría y permite aplicar filtros", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(historyPayload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<HistoryCenter />);

    expect(await screen.findByRole("heading", { name: "Historial" })).toBeVisible();
    expect((await screen.findAllByText("Factura registrada")).length).toBeGreaterThan(0);
    expect(screen.getByText("001-001-000000686")).toBeVisible();
    expect(screen.getAllByText("Factura vinculada a la OC manualmente").length).toBeGreaterThan(0);
    expect(screen.getAllByText("José Escobar").length).toBeGreaterThan(0);

    fireEvent.change(screen.getByPlaceholderText("Acción, documento, motivo o usuario"), { target: { value: "Favorita" } });
    fireEvent.click(screen.getByRole("button", { name: "Aplicar filtros" }));

    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith(
      expect.stringContaining("search=Favorita"),
      expect.objectContaining({ credentials: "include" }),
    ));
  });
});
