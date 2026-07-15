import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";

interface ManagedUser {
  id: string;
  username: string;
  full_name: string;
  email: string | null;
  role: "principal" | "operador";
  role_name: string;
  must_change_password: boolean;
  is_active: boolean;
  created_at: string;
}

const emptyForm = {
  full_name: "",
  username: "",
  email: "",
  password: "",
  role: "operador" as "principal" | "operador",
};

const roleLabel = (role: string) => role === "principal" ? "Principal" : "Operador";
const dateLabel = (value: string) => new Intl.DateTimeFormat("es-EC", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));

export function UserCenter() {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const summary = useMemo(() => ({
    total: users.length,
    active: users.filter((user) => user.is_active).length,
    principals: users.filter((user) => user.role === "principal").length,
    operators: users.filter((user) => user.role === "operador").length,
  }), [users]);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    apiRequest<ManagedUser[]>("/auth/users")
      .then(setUsers)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudieron cargar los usuarios."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    let ignore = false;
    apiRequest<ManagedUser[]>("/auth/users")
      .then((loaded) => { if (!ignore) setUsers(loaded); })
      .catch((caught) => { if (!ignore) setError(caught instanceof Error ? caught.message : "No se pudieron cargar los usuarios."); })
      .finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    setError(null);
    apiRequest<ManagedUser>("/auth/users", {
      method: "POST",
      body: JSON.stringify({
        full_name: form.full_name,
        username: form.username,
        email: form.email.trim() || null,
        password: form.password,
        role: form.role,
      }),
    })
      .then((created) => {
        setUsers((current) => [...current, created]);
        setForm(emptyForm);
        setMessage(`Usuario ${created.username} creado correctamente.`);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudo crear el usuario."))
      .finally(() => setSaving(false));
  };

  return <main className="dashboard users-center">
    <section className="module-heading">
      <div className="welcome-block">
        <p className="eyebrow">Administración</p>
        <h1>Usuarios / Responsables</h1>
        <p>Alta básica de usuarios que operan el inventario y quedan registrados como responsables en la trazabilidad.</p>
      </div>
      <button className="secondary-button" type="button" disabled={loading} onClick={load}>{loading ? "Actualizando…" : "Actualizar"}</button>
    </section>

    <section className="user-summary" aria-label="Resumen de usuarios">
      <article><span>Total</span><strong>{summary.total}</strong><small>usuarios registrados</small></article>
      <article><span>Activos</span><strong>{summary.active}</strong><small>pueden iniciar sesión</small></article>
      <article><span>Principales</span><strong>{summary.principals}</strong><small>administran usuarios</small></article>
      <article><span>Operadores</span><strong>{summary.operators}</strong><small>uso operativo diario</small></article>
    </section>

    {message && <div className="message success" role="status">{message}</div>}
    {error && <div className="message error" role="alert">{error}</div>}

    <div className="users-workspace">
      <form className="user-form" onSubmit={submit}>
        <div className="stock-control-header">
          <div>
            <p className="eyebrow">Nuevo acceso</p>
            <h2>Crear usuario</h2>
            <p>Usa una contraseña inicial segura y compártela por un canal privado.</p>
          </div>
        </div>
        <div className="user-form-grid">
          <label><span>Nombre completo</span><input required minLength={2} maxLength={120} value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} placeholder="Ej. Bodega Principal" /></label>
          <label><span>Usuario</span><input required value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} placeholder="ej. bodega1" /></label>
          <label><span>Correo opcional</span><input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} placeholder="correo@empresa.com" /></label>
          <label><span>Rol</span><select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as "principal" | "operador" })}><option value="operador">Operador</option><option value="principal">Principal</option></select></label>
          <label className="full-field"><span>Contraseña inicial</span><input required minLength={12} maxLength={128} type="password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} placeholder="Mínimo 12 caracteres" /></label>
        </div>
        <button className="primary-button" type="submit" disabled={saving}>{saving ? "Creando…" : "Crear usuario"}</button>
      </form>

      <section className="users-panel">
        <div className="panel-title"><div><h2>Usuarios registrados</h2><p>Listado real de accesos disponibles en el sistema.</p></div><span>{users.length}</span></div>
        {loading && <div className="table-message">Cargando usuarios…</div>}
        {!loading && users.length === 0 && <div className="table-message">No hay usuarios registrados.</div>}
        {users.length > 0 && <div className="table-scroll"><table><thead><tr><th>Usuario</th><th>Nombre</th><th>Rol</th><th>Estado</th><th>Creado</th></tr></thead><tbody>{users.map((user) => <tr key={user.id}><td><strong>{user.username}</strong>{user.email && <span>{user.email}</span>}</td><td>{user.full_name}</td><td><span className={`role-pill ${user.role}`}>{roleLabel(user.role)}</span></td><td><span className={`status-pill ${user.is_active ? "available" : "blocked"}`}>{user.is_active ? "Activo" : "Inactivo"}</span></td><td>{dateLabel(user.created_at)}</td></tr>)}</tbody></table></div>}
      </section>
    </div>
  </main>;
}
