import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";

interface HistoryItem {
  id: string;
  occurred_at: string;
  actor: string;
  username: string | null;
  action: string;
  action_label: string;
  entity_type: string;
  module: string;
  entity_id: string | null;
  reason: string | null;
  summary: string | null;
  previous_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  ip_address: string | null;
}

const dateLabel = (value: string) => new Intl.DateTimeFormat("es-EC", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
const toIsoBoundary = (value: string, endOfDay = false) => value ? new Date(`${value}T${endOfDay ? "23:59:59" : "00:00:00"}`).toISOString() : "";
const jsonSummary = (value: Record<string, unknown> | null) => {
  if (!value) return "Sin datos";
  return Object.entries(value).slice(0, 8).map(([key, item]) => `${key}: ${String(item)}`).join(" · ");
};

export function HistoryCenter() {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [actor, setActor] = useState("");
  const [module, setModule] = useState("");
  const [action, setAction] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(() => items.find((item) => item.id === selectedId) ?? items[0] ?? null, [items, selectedId]);
  const modules = useMemo(() => Array.from(new Map(items.map((item) => [item.entity_type, item.module])).entries()), [items]);
  const actions = useMemo(() => Array.from(new Map(items.map((item) => [item.action, item.action_label])).entries()), [items]);

  const load = () => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ limit: "150" });
    if (search.trim()) params.set("search", search.trim());
    if (actor.trim()) params.set("actor", actor.trim());
    if (module) params.set("module", module);
    if (action) params.set("action", action);
    if (dateFrom) params.set("date_from", toIsoBoundary(dateFrom));
    if (dateTo) params.set("date_to", toIsoBoundary(dateTo, true));
    apiRequest<HistoryItem[]>(`/audit/history?${params.toString()}`)
      .then((loaded) => { setItems(loaded); setSelectedId((current) => loaded.find((item) => item.id === current)?.id ?? loaded[0]?.id ?? null); })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudo cargar el historial."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    apiRequest<HistoryItem[]>("/audit/history?limit=150")
      .then((loaded) => { setItems(loaded); setSelectedId(loaded[0]?.id ?? null); })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudo cargar el historial."))
      .finally(() => setLoading(false));
  }, []);

  return <main className="dashboard history-center">
    <section className="module-heading">
      <div className="welcome-block">
        <p className="eyebrow">Auditoría</p>
        <h1>Historial</h1>
        <p>Consulta de acciones registradas: usuario, módulo, documento, motivo y cambios relevantes.</p>
      </div>
      <button className="secondary-button" type="button" disabled={loading} onClick={load}>{loading ? "Actualizando…" : "Actualizar"}</button>
    </section>

    <section className="history-filters" aria-label="Filtros de historial">
      <label><span>Buscar</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Acción, documento, motivo o usuario" /></label>
      <label><span>Usuario</span><input value={actor} onChange={(event) => setActor(event.target.value)} placeholder="Nombre" /></label>
      <label><span>Módulo</span><select value={module} onChange={(event) => setModule(event.target.value)}><option value="">Todos</option>{modules.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label><span>Acción</span><select value={action} onChange={(event) => setAction(event.target.value)}><option value="">Todas</option>{actions.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label><span>Desde</span><input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
      <label><span>Hasta</span><input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
      <button className="primary-button" type="button" disabled={loading} onClick={load}>Aplicar filtros</button>
    </section>

    {error && <div className="message error" role="alert">{error}</div>}

    <div className="history-workspace">
      <section className="history-panel">
        <div className="panel-title"><div><h2>Eventos registrados</h2><p>Ordenado del evento más reciente al más antiguo.</p></div><span>{items.length}</span></div>
        {loading && <div className="table-message">Cargando historial…</div>}
        {!loading && items.length === 0 && <div className="table-message">No hay resultados</div>}
        {items.length > 0 && <div className="table-scroll"><table><thead><tr><th>Fecha</th><th>Usuario</th><th>Acción</th><th>Módulo</th><th>Documento</th><th>Motivo / resumen</th></tr></thead><tbody>{items.map((item) => <tr className={selected?.id === item.id ? "selected-row" : undefined} key={item.id} onClick={() => setSelectedId(item.id)}><td>{dateLabel(item.occurred_at)}</td><td><strong>{item.actor}</strong>{item.username && <span>{item.username}</span>}</td><td><span className="history-action">{item.action_label}</span></td><td>{item.module}</td><td>{item.entity_id ?? "—"}</td><td className="reason-cell">{item.reason ?? item.summary ?? "Sin observación"}</td></tr>)}</tbody></table></div>}
      </section>

      <aside className="history-detail" aria-label="Detalle del historial">
        {!selected && <div className="empty-detail compact"><strong>Sin evento seleccionado</strong><span>Selecciona una fila para ver el detalle.</span></div>}
        {selected && <>
          <div className="detail-kicker"><span>{selected.module}</span><strong>{selected.action_label}</strong></div>
          <h2>{selected.actor}</h2>
          <p>{dateLabel(selected.occurred_at)}</p>
          <dl className="movement-meta">
            <div><dt>Acción interna</dt><dd>{selected.action}</dd></div>
            <div><dt>Entidad</dt><dd>{selected.entity_type} · {selected.entity_id ?? "Sin ID"}</dd></div>
            <div><dt>IP</dt><dd>{selected.ip_address ?? "No disponible"}</dd></div>
            <div><dt>Motivo</dt><dd>{selected.reason ?? "Sin motivo registrado"}</dd></div>
          </dl>
          <div className="history-values">
            <article><span>Antes</span><p>{jsonSummary(selected.previous_value)}</p></article>
            <article><span>Después</span><p>{jsonSummary(selected.new_value)}</p></article>
          </div>
        </>}
      </aside>
    </div>
  </main>;
}
