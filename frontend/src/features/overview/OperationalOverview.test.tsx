import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OperationalOverview } from "./OperationalOverview";

describe("OperationalOverview", () => {
  it("presenta el resumen como estado operativo", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => undefined)));
    render(<OperationalOverview onNavigate={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    expect(screen.getByText(/resumen actual del inventario/i)).toBeVisible();
  });
});
