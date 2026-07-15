import { useEffect, useState } from "react";

import { ApiError, apiRequest } from "./api/client";
import { AuthScreen } from "./features/auth/AuthScreen";
import type { AuthenticatedUser } from "./features/auth/types";
import { Dashboard } from "./features/dashboard/Dashboard";

type AppState =
  | { status: "loading" }
  | { status: "anonymous"; bootstrapRequired: boolean }
  | { status: "authenticated"; user: AuthenticatedUser }
  | { status: "unavailable"; message: string };

export function App() {
  const [state, setState] = useState<AppState>({ status: "loading" });

  useEffect(() => {
    let active = true;
    async function initialize() {
      try {
        const user = await apiRequest<AuthenticatedUser>("/auth/me");
        if (active) setState({ status: "authenticated", user });
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 401) {
          try {
            const bootstrap = await apiRequest<{ required: boolean }>(
              "/auth/bootstrap-status",
            );
            if (active) {
              setState({
                status: "anonymous",
                bootstrapRequired: bootstrap.required,
              });
            }
          } catch {
            if (active) {
              setState({
                status: "unavailable",
                message: "El sistema tardó más de lo esperado. Intenta nuevamente.",
              });
            }
          }
        } else if (active) {
          setState({
            status: "unavailable",
            message: "Estamos preparando los datos. Intenta nuevamente en un momento.",
          });
        }
      }
    }
    void initialize();
    return () => {
      active = false;
    };
  }, []);

  if (state.status === "loading") {
    return (
      <main className="loading-screen" aria-live="polite">
        <div className="loader" />
        <strong>Preparando el sistema…</strong>
        <span>Estamos conectando con los datos.</span>
      </main>
    );
  }

  if (state.status === "unavailable") {
    return (
      <main className="loading-screen">
        <strong>No pudimos iniciar todavía</strong>
        <span>{state.message}</span>
        <button type="button" onClick={() => window.location.reload()}>
          Intentar nuevamente
        </button>
      </main>
    );
  }

  if (state.status === "anonymous") {
    return (
      <AuthScreen
        bootstrapRequired={state.bootstrapRequired}
        onAuthenticated={(user) => setState({ status: "authenticated", user })}
        onBootstrapCompleted={() =>
          setState({ status: "anonymous", bootstrapRequired: false })
        }
      />
    );
  }

  return (
    <Dashboard
      user={state.user}
      onLogout={async () => {
        await apiRequest<void>("/auth/logout", { method: "POST" });
        setState({ status: "anonymous", bootstrapRequired: false });
      }}
    />
  );
}

