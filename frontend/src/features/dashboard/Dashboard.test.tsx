import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Dashboard } from "./Dashboard";

const user = { id: "user-1", username: "principal", full_name: "José Escobar", email: null, role: "principal", must_change_password: false };
const emptyResponse = () => new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
const summaryResponse = () => new Response(JSON.stringify({ inventory: { products: 0, physical: 0, reserved: 0, invoiced_pending: 0, blocked: 0, available: 0 }, workflow: { pending_dispatch: 0, pending_delivery: 0, open_incidents: 0, active_reservations: 0, reserved_units: 0, pending_approvals: 0 }, attention_invoices: [], low_stock: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
const reportResponse = () => new Response(JSON.stringify({ inventory: { products: 0, physical: 0, reserved: 0, invoiced_pending: 0, blocked: 0, available: 0, low_stock_products: 0 }, workflow: { pending_dispatch: 0, pending_delivery: 0, open_incidents: 0 }, by_chain: [], by_product: [], pending_by_chain: [], missing_products: [], low_stock: [], movements_by_responsible: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
const settingsResponse = () => new Response(JSON.stringify({ warehouse_name: "Bodega principal", low_stock_threshold_boxes: 1, report_default_days: 30, allow_exception_invoices: true, suggested_chains: ["Gerardo Ortiz", "Favorita", "Tía"], invoice_exception_note: "Factura para otro fin operativo", updated_at: null, updated_by: null }), { status: 200, headers: { "Content-Type": "application/json" } });
const mockApi = () => vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
  const path = String(input);
  if (path.includes("/dashboard/summary")) return summaryResponse();
  if (path.includes("/reports/operational")) return reportResponse();
  if (path.includes("/settings/operational")) return settingsResponse();
  return emptyResponse();
});

afterEach(cleanup);

describe("Dashboard", () => {
  it("navega por el sidebar sin alterar el rol interno", async () => {
    vi.stubGlobal("fetch", mockApi());
    render(<Dashboard user={user} onLogout={vi.fn()} />);

    expect(screen.getByText("Administrador")).toBeVisible();
    expect(screen.getByRole("button", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByRole("button", { name: "Inventario" }));
    expect(screen.getByRole("heading", { name: "Inventario" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Inventario" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("heading", { name: "Carga masiva" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Ajuste individual" })).not.toBeInTheDocument();
  });

  it("mantiene las herramientas de corrección exclusivamente en Ajustes", async () => {
    vi.stubGlobal("fetch", mockApi());
    render(<Dashboard user={user} onLogout={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Ajustes" }));
    expect(await screen.findByRole("heading", { name: "Carga masiva" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Ajuste individual" })).toBeVisible();
    expect(screen.getByText("Historial de ajustes")).toBeVisible();
  });

  it("muestra configuración como módulo conectado", async () => {
    vi.stubGlobal("fetch", mockApi());
    render(<Dashboard user={user} onLogout={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Configuración" }));
    expect(screen.getByRole("heading", { name: "Configuración" })).toBeVisible();
    expect(await screen.findByDisplayValue("Bodega principal")).toBeVisible();
  });

  it("usa las acciones rápidas como navegación interna", async () => {
    vi.stubGlobal("fetch", mockApi());
    render(<Dashboard user={user} onLogout={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Factura" }));
    expect(screen.getByRole("button", { name: "Facturación" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByRole("button", { name: "Exportar" }));
    expect(screen.getByRole("heading", { name: "Reportes" })).toBeVisible();
    expect(await screen.findByText("Facturado por cadena")).toBeVisible();
  });

  it("permite colapsar y expandir la barra lateral", () => {
    vi.stubGlobal("fetch", mockApi());
    const { container } = render(<Dashboard user={user} onLogout={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Colapsar barra lateral" }));
    expect(container.querySelector(".authenticated-shell")).toHaveClass("sidebar-collapsed");
    fireEvent.click(screen.getByRole("button", { name: "Expandir barra lateral" }));
    expect(container.querySelector(".authenticated-shell")).not.toHaveClass("sidebar-collapsed");
  });
});
