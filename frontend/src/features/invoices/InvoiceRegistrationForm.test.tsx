import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InvoiceRegistrationForm } from "./InvoiceRegistrationForm";

describe("InvoiceRegistrationForm", () => {
  it("deja claro que registra una factura externa", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<InvoiceRegistrationForm onCreated={vi.fn()} onCancel={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "Registrar factura emitida" })).toBeVisible();
    expect(screen.getByText(/no genera ni autoriza facturas/i)).toBeVisible();
  });
});
