import { type FormEvent, useState } from "react";

import { apiRequest } from "../../api/client";
import type { AuthenticatedUser } from "./types";

interface AuthScreenProps {
  bootstrapRequired: boolean;
  onAuthenticated: (user: AuthenticatedUser) => void;
  onBootstrapCompleted: () => void;
}

interface PasswordFieldProps {
  label: string;
  name: string;
  autoComplete: "current-password" | "new-password";
  minLength?: number;
}

function PasswordField({ label, name, autoComplete, minLength }: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);

  return <label>
    {label}
    <span className="password-field">
      <input
        name={name}
        type={visible ? "text" : "password"}
        autoComplete={autoComplete}
        required
        minLength={minLength}
      />
      <button
        className="password-toggle"
        type="button"
        aria-label={visible ? "Ocultar contraseña" : "Mostrar contraseña"}
        aria-pressed={visible}
        onClick={() => setVisible((value) => !value)}
      >
        {visible
          ? <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M3 3l18 18M10.6 10.7a2 2 0 002.7 2.7M9.9 4.2A10.8 10.8 0 0112 4c5 0 8.5 4 9.5 6.2a4.2 4.2 0 010 3.6 12 12 0 01-2 2.9M6.6 6.6a12.4 12.4 0 00-4.1 5.6 4.2 4.2 0 000 3.6C3.5 18 7 22 12 22a10.6 10.6 0 005.4-1.5" /></svg>
          : <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M2.5 10.2a4.2 4.2 0 000 3.6C3.5 16 7 20 12 20s8.5-4 9.5-6.2a4.2 4.2 0 000-3.6C20.5 8 17 4 12 4S3.5 8 2.5 10.2z" /><circle cx="12" cy="12" r="3" /></svg>}
      </button>
    </span>
  </label>;
}

export function AuthScreen({
  bootstrapRequired,
  onAuthenticated,
  onBootstrapCompleted,
}: AuthScreenProps) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function submitLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    try {
      const user = await apiRequest<AuthenticatedUser>("/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username: form.get("username"),
          password: form.get("password"),
        }),
      });
      onAuthenticated(user);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos ingresar.");
    } finally {
      setSubmitting(false);
    }
  }

  async function submitBootstrap(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password"));
    if (password !== String(form.get("password_confirmation"))) {
      setError("Las contraseñas no coinciden.");
      setSubmitting(false);
      return;
    }
    try {
      await apiRequest<AuthenticatedUser>("/auth/bootstrap", {
        method: "POST",
        body: JSON.stringify({
          username: form.get("username"),
          full_name: form.get("full_name"),
          email: form.get("email") || null,
          password,
        }),
      });
      setNotice("Usuario principal creado. Ya puedes ingresar.");
      onBootstrapCompleted();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "No pudimos preparar el sistema.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-layout">
      <section className="auth-context">
        <div className="brand-mark" aria-hidden="true">IO</div>
        <p className="eyebrow">Sistema interno</p>
        <h1>Inventario Operativo</h1>
        <p className="auth-description">Acceso al sistema</p>
      </section>

      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-card">
          <div className="auth-card-brand"><div className="brand-mark small" aria-hidden="true">IO</div><span>Inventario Operativo</span></div>
          <p className="eyebrow">Acceso</p>
          <h2 id="auth-title">
            {bootstrapRequired ? "Preparar sistema" : "Acceso al sistema"}
          </h2>
          <p className="muted">
            {bootstrapRequired
              ? "Crea la cuenta principal."
              : "Ingresa con tu usuario y contraseña."}
          </p>

          {notice && <div className="message success">{notice}</div>}
          {error && <div className="message error" role="alert">{error}</div>}

          {bootstrapRequired ? (
            <form onSubmit={submitBootstrap} className="auth-form">
              <label>
                Nombre completo
                <input name="full_name" autoComplete="name" required minLength={2} />
              </label>
              <label>
                Usuario
                <input name="username" autoComplete="username" required minLength={3} />
              </label>
              <label>
                Correo electrónico <span className="optional">opcional</span>
                <input name="email" type="email" autoComplete="email" />
              </label>
              <PasswordField label="Contraseña" name="password" autoComplete="new-password" minLength={12} />
              <PasswordField label="Confirmar contraseña" name="password_confirmation" autoComplete="new-password" minLength={12} />
              <button type="submit" disabled={submitting}>
                {submitting ? "Cargando sistema..." : "Crear usuario principal"}
              </button>
            </form>
          ) : (
            <form onSubmit={submitLogin} className="auth-form">
              <label>
                Usuario
                <input name="username" autoComplete="username" required />
              </label>
              <PasswordField label="Contraseña" name="password" autoComplete="current-password" />
              <button type="submit" disabled={submitting}>
                {submitting ? "Validando credenciales..." : "Ingresar"}
              </button>
            </form>
          )}
        </div>
      </section>
    </main>
  );
}
