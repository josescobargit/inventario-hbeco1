import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest } from "../../api/client";
import { AuthScreen } from "./AuthScreen";

vi.mock("../../api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("../../api/client")>();
  return { ...original, apiRequest: vi.fn() };
});

const mockedApiRequest = vi.mocked(apiRequest);

afterEach(() => {
  cleanup();
  mockedApiRequest.mockReset();
});

function submitCredentials() {
  fireEvent.change(screen.getByLabelText("Usuario"), { target: { value: "usuario" } });
  fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: "clave" } });
  fireEvent.click(screen.getByRole("button", { name: "Ingresar" }));
}

describe("AuthScreen", () => {
  it("permite mostrar y ocultar la contraseña de forma accesible", () => {
    render(<AuthScreen bootstrapRequired={false} onAuthenticated={vi.fn()} onBootstrapCompleted={vi.fn()} />);

    const password = screen.getByLabelText("Contraseña");
    const toggle = screen.getByRole("button", { name: "Mostrar contraseña" });
    expect(password).toHaveAttribute("type", "password");

    fireEvent.click(toggle);
    expect(password).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Ocultar contraseña" })).toHaveAttribute("aria-pressed", "true");
  });

  it("muestra el error real cuando las credenciales son rechazadas", async () => {
    mockedApiRequest.mockRejectedValueOnce(
      new ApiError("Usuario o contraseña incorrectos.", 401),
    );
    render(<AuthScreen bootstrapRequired={false} onAuthenticated={vi.fn()} onBootstrapCompleted={vi.fn()} />);

    submitCredentials();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Usuario o contraseña incorrectos.",
    );
    expect(mockedApiRequest).toHaveBeenCalledTimes(1);
  });

  it("distingue un fallo al conservar la sesión después de ingresar", async () => {
    mockedApiRequest
      .mockResolvedValueOnce({
        id: "1",
        username: "usuario",
        full_name: "Usuario de prueba",
        email: null,
        role: "admin",
        must_change_password: false,
      })
      .mockRejectedValueOnce(new ApiError("No autenticado.", 401));
    const onAuthenticated = vi.fn();
    render(<AuthScreen bootstrapRequired={false} onAuthenticated={onAuthenticated} onBootstrapCompleted={vi.fn()} />);

    submitCredentials();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Los datos son correctos, pero el navegador no pudo conservar la sesión.",
    );
    await waitFor(() => expect(mockedApiRequest).toHaveBeenCalledTimes(2));
    expect(onAuthenticated).not.toHaveBeenCalled();
  });
});
