import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DeliveryIncidentCenter } from "./DeliveryIncidentCenter";

describe("DeliveryIncidentCenter", () => {
  it("diferencia entrega al cliente de despacho", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<DeliveryIncidentCenter />);
    expect(screen.getByRole("heading", { name: "Entregas e Incidencias" })).toBeVisible();
    expect(screen.getByText(/recibido por el cliente/i)).toBeVisible();
    expect(await screen.findByText("No hay entregas pendientes")).toBeVisible();
  });
});
