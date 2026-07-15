import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InvoiceCenter } from "./InvoiceCenter";

describe("InvoiceCenter", () => {
  it("explica su alcance y muestra un estado vacío útil", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    render(<InvoiceCenter />);

    expect(screen.getByText(/aquí no se factura/i)).toBeVisible();
    expect(await screen.findByText("No encontramos facturas.")).toBeVisible();
    expect(screen.getByText("Selecciona una factura")).toBeVisible();
  });
});
