import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReservationCenter } from "./ReservationCenter";

describe("ReservationCenter", () => {
  it("explica que una reserva no cambia el stock físico", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<ReservationCenter />);
    expect(screen.getByRole("heading", { name: "Reservas" })).toBeVisible();
    expect(screen.getByText(/sin modificar el conteo físico/i)).toBeVisible();
    expect(await screen.findByText(/todavía no hay reservas/i)).toBeVisible();
  });
});
