import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MovementCenter } from "./MovementCenter";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("MovementCenter", () => {
  it("muestra movimientos operativos reales con delta y referencia", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([
      {
        id: "mov-1",
        occurred_at: "2026-07-08T15:00:00.000Z",
        movement_type: "general_exit",
        movement_label: "Salida general",
        sku: "SKU-001",
        product_name: "Producto de prueba",
        category: "Línea A",
        affected_field: "physical_confirmed",
        delta: -2,
        reference_type: "inventory_operation",
        reference_id: "op-1",
        reason: "Consumo operativo autorizado",
        actor: "José Escobar",
        before_value: { physical_confirmed: 10, version: 1 },
        after_value: { physical_confirmed: 8, version: 2 },
      },
    ]), { status: 200, headers: { "Content-Type": "application/json" } })));

    render(<MovementCenter />);

    expect(await screen.findByRole("heading", { name: "Movimientos" })).toBeVisible();
    expect((await screen.findAllByText("Salida general")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("SKU-001").length).toBeGreaterThan(0);
    expect(screen.getAllByText("-2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("op-1").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Detalle del movimiento")).toHaveTextContent("Antes");
    expect(screen.getByLabelText("Detalle del movimiento")).toHaveTextContent("Después");
    expect(screen.getByLabelText("Detalle del movimiento")).toHaveTextContent("10");
    expect(screen.getByLabelText("Detalle del movimiento")).toHaveTextContent("8");
  });
});
