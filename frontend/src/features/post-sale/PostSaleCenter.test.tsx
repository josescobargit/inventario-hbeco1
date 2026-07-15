import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PostSaleCenter } from "./PostSaleCenter";

describe("PostSaleCenter", () => {
  it("separa el movimiento físico del ajuste económico", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<PostSaleCenter />);
    expect(screen.getByRole("heading", { name: "Devoluciones y Notas" })).toBeVisible();
    expect(screen.getByText(/una nota de crédito o débito no cambia el stock/i)).toBeVisible();
    expect(await screen.findByText("No hay facturas despachadas")).toBeVisible();
  });
});
