import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsCenter } from "./SettingsCenter";

const settingsPayload = {
  warehouse_name: "Bodega principal",
  low_stock_threshold_mode: "boxes",
  low_stock_threshold_boxes: 1,
  low_stock_threshold_units: 0,
  report_default_days: 30,
  allow_exception_invoices: true,
  suggested_chains: ["Gerardo Ortiz", "Favorita", "Tía"],
  invoice_exception_note: "Factura para otro fin operativo",
  updated_at: "2026-07-14T13:00:00Z",
  updated_by: "José Escobar",
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SettingsCenter", () => {
  it("muestra y guarda configuración operativa", async () => {
    const fetchMock = vi.fn().mockImplementation(async (_input: RequestInfo | URL, init?: RequestInit) => new Response(
      JSON.stringify(init?.method === "PUT" ? { ...settingsPayload, warehouse_name: "Bodega central", low_stock_threshold_mode: "units", low_stock_threshold_boxes: 1, low_stock_threshold_units: 24 } : settingsPayload),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);

    render(<SettingsCenter />);

    expect(await screen.findByRole("heading", { name: "Configuración" })).toBeVisible();
    expect(await screen.findByDisplayValue("Bodega principal")).toBeVisible();
    expect(screen.getByDisplayValue(/Gerardo Ortiz/)).toBeVisible();

    fireEvent.change(screen.getByDisplayValue("Bodega principal"), { target: { value: "Bodega central" } });
    fireEvent.change(screen.getByDisplayValue("Cajas"), { target: { value: "units" } });
    expect(screen.getByDisplayValue("1")).toBeDisabled();
    fireEvent.change(screen.getByDisplayValue("0"), { target: { value: "24" } });
    expect(screen.getAllByRole("button", { name: "Guardar cambios" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));

    expect(await screen.findByText("Configuración operativa guardada correctamente.")).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/v1/settings/operational",
      expect.objectContaining({ method: "PUT", credentials: "include" }),
    ));
  });

  it("explica cuando un usuario no principal no puede editar", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(settingsPayload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));

    render(<SettingsCenter userRole="operador" />);

    expect(await screen.findByText(/modo lectura/i)).toBeVisible();
    expect(screen.getByDisplayValue("Cajas")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Guardar cambios" })).toBeDisabled();
  });
});
