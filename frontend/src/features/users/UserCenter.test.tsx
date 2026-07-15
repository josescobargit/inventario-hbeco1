import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UserCenter } from "./UserCenter";

const usersPayload = [
  {
    id: "user-1",
    username: "principal",
    full_name: "José Escobar",
    email: null,
    role: "principal",
    role_name: "Principal",
    must_change_password: false,
    is_active: true,
    created_at: "2026-07-14T10:00:00Z",
  },
];

const createdPayload = {
  id: "user-2",
  username: "bodega",
  full_name: "Bodega Principal",
  email: "bodega@example.com",
  role: "operador",
  role_name: "Operador",
  must_change_password: false,
  is_active: true,
  created_at: "2026-07-14T12:00:00Z",
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("UserCenter", () => {
  it("lista usuarios y permite crear un operador", async () => {
    const fetchMock = vi.fn().mockImplementation(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        return new Response(JSON.stringify(createdPayload), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify(usersPayload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<UserCenter />);

    expect(await screen.findByRole("heading", { name: "Usuarios / Responsables" })).toBeVisible();
    expect(await screen.findByText("principal")).toBeVisible();
    expect(screen.getByText("José Escobar")).toBeVisible();

    fireEvent.change(screen.getByPlaceholderText("Ej. Bodega Principal"), { target: { value: "Bodega Principal" } });
    fireEvent.change(screen.getByPlaceholderText("ej. bodega1"), { target: { value: "bodega" } });
    fireEvent.change(screen.getByPlaceholderText("correo@empresa.com"), { target: { value: "bodega@example.com" } });
    fireEvent.change(screen.getByPlaceholderText("Mínimo 12 caracteres"), { target: { value: "clave-segura-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear usuario" }));

    expect(await screen.findByText("Usuario bodega creado correctamente.")).toBeVisible();
    expect(screen.getByText("Bodega Principal")).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/v1/auth/users",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    ));
  });
});
