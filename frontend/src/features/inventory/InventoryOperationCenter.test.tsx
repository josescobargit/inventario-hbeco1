import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InventoryOperationCenter } from "./InventoryOperationCenter";

const user = { id: "user-1", username: "principal", full_name: "José Escobar", email: null, role: "principal", must_change_password: false };
const emptyResponse = () => new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
afterEach(cleanup);

describe("InventoryOperationCenter", () => {
  it("mantiene las salidas separadas de los despachos", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => emptyResponse()));
    render(<InventoryOperationCenter operationType="exit" user={user} />);
    expect(screen.getByRole("heading", { name: "Salidas" })).toBeVisible();
    expect(screen.getByText(/despachos a clientes se gestionan en su módulo independiente/i)).toBeVisible();
    expect(await screen.findByText("No se encontraron registros")).toBeVisible();
  });

  it("abre un formulario de entrada con evidencia", () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => emptyResponse()));
    render(<InventoryOperationCenter operationType="entry" user={user} />);
    fireEvent.click(screen.getByRole("button", { name: "Nueva entrada" }));
    expect(screen.getByText("Documento de respaldo *")).toBeVisible();
    expect(screen.getByRole("button", { name: "Guardar movimiento" })).toBeDisabled();
  });
});
