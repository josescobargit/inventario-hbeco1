import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AuthScreen } from "./AuthScreen";

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
});
