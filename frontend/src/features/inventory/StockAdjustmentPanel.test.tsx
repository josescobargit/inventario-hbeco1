import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StockAdjustmentPanel } from "./StockAdjustmentPanel";

describe("StockAdjustmentPanel", () => {
  it("explica que el principal no se aprueba a sí mismo", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<StockAdjustmentPanel products={[]} userRole="principal" onApplied={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Ajuste individual" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Nuevo conteo" }));
    expect(screen.getByText(/no tendrás que aprobártelo después/i)).toBeVisible();
    expect(await screen.findByText(/todavía no hay ajustes/i)).toBeVisible();
  });
});
