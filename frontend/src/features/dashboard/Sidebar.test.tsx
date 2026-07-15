import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Sidebar } from "./Sidebar";

describe("Sidebar", () => {
  it("agrupa la navegación y conserva nombres completos", () => {
    const navigate = vi.fn();
    render(<Sidebar activeModule="dashboard" open={false} onNavigate={navigate} onClose={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Operación" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Ventas y pedidos" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Análisis" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Administración" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Órdenes de compra" }));
    expect(navigate).toHaveBeenCalledWith("orders");
  });
});
