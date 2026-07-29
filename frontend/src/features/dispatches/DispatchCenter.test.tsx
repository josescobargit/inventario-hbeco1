import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DispatchCenter } from "./DispatchCenter";

describe("DispatchCenter", () => {
  it("explica el tratamiento de faltantes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<DispatchCenter />);
    expect(screen.getByRole("heading", { name: "Despachos" })).toBeVisible();
    expect(screen.getByText(/el inventario ya fue descontado/i)).toBeVisible();
    expect(await screen.findByText(/no hay facturas pendientes/i)).toBeVisible();
  });
});
