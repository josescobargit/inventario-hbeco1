import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";
import { ProductIdentity } from "./ProductIdentity";

interface Movement {
  id: string;
  occurred_at: string;
  movement_type: string;
  movement_label: string;
  sku: string;
  product_name: string;
  category: string;
  affected_field: string;
  delta: number;
  reference_type: string | null;
  reference_id: string | null;
  reason: string;
  actor: string;
  before_value: Record<string, number | string | null>;
  after_value: Record<string, number | string | null>;
}

const FIELD_LABELS: Record<string, string> = {
  physical_confirmed: "Físico confirmado",
  reserved: "Reservado",
  invoiced_not_dispatched: "Facturado pendiente",
  blocked_by_incident: "Bloqueado por incidencia",
  sin_cambio: "Sin cambio",
};

const dateLabel = (value: string) =>
  new Intl.DateTimeFormat("es-EC", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));

const toIsoBoundary = (value: string, endOfDay = false) => {
  if (!value) return "";
  return new Date(`${value}T${endOfDay ? "23:59:59" : "00:00:00"}`).toISOString();
};

export function MovementCenter() {
  const [movements, setMovements] = useState<Movement[]>([]);
  const [selectedMovementId, setSelectedMovementId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [movementType, setMovementType] = useState("");
  const [actor, setActor] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const movementTypes = useMemo(
    () => Array.from(new Map(movements.map((item) => [item.movement_type, item.movement_label])).entries()),
    [movements],
  );
  const selectedMovement = useMemo(
    () => movements.find((item) => item.id === selectedMovementId) ?? movements[0] ?? null,
    [movements, selectedMovementId],
  );

  const movementPath = () => {
    const params = new URLSearchParams({ limit: "150" });
    if (search.trim()) params.set("search", search.trim());
    if (movementType) params.set("movement_type", movementType);
    if (actor.trim()) params.set("actor", actor.trim());
    if (dateFrom) params.set("date_from", toIsoBoundary(dateFrom));
    if (dateTo) params.set("date_to", toIsoBoundary(dateTo, true));
    return `/inventory/movements?${params.toString()}`;
  };

  const load = () => {
    setLoading(true);
    setError(null);
    apiRequest<Movement[]>(movementPath())
      .then((loaded) => {
        setMovements(loaded);
        setSelectedMovementId((current) => loaded.find((item) => item.id === current)?.id ?? loaded[0]?.id ?? null);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudieron cargar los movimientos."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    apiRequest<Movement[]>("/inventory/movements?limit=150")
      .then((loaded) => {
        setMovements(loaded);
        setSelectedMovementId(loaded[0]?.id ?? null);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudieron cargar los movimientos."))
      .finally(() => setLoading(false));
  }, []);

  return <main className="dashboard movements-center">
    <section className="module-heading">
      <div className="welcome-block">
        <p className="eyebrow">Bitácora operativa</p>
        <h1>Movimientos</h1>
        <p>Consulta consolidada de los cambios reales del inventario: entradas, salidas, reservas, facturas, despachos, ajustes, incidencias y devoluciones.</p>
      </div>
      <button className="secondary-button" type="button" onClick={load} disabled={loading}>{loading ? "Actualizando…" : "Actualizar"}</button>
    </section>

    <section className="movement-filters" aria-label="Filtros de movimientos">
      <label><span>Buscar producto/documento</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="SKU, producto, referencia o motivo" /></label>
      <label><span>Tipo</span><select value={movementType} onChange={(event) => setMovementType(event.target.value)}><option value="">Todos</option>{movementTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label><span>Responsable</span><input value={actor} onChange={(event) => setActor(event.target.value)} placeholder="Nombre del usuario" /></label>
      <label><span>Desde</span><input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
      <label><span>Hasta</span><input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
      <button className="primary-button" type="button" onClick={load} disabled={loading}>Aplicar filtros</button>
    </section>

    {error && <div className="message error" role="alert">{error}</div>}

    <div className="movement-workspace">
      <section className="movement-panel">
        <div className="panel-title">
          <div><h2>Libro de movimientos</h2><p>Ordenado del evento más reciente al más antiguo. Haz clic en una fila para ver el detalle.</p></div>
          <span>{movements.length}</span>
        </div>
        {loading && <div className="table-message">Cargando movimientos…</div>}
        {!loading && movements.length === 0 && <div className="table-message">No hay movimientos para los filtros seleccionados.</div>}
        {movements.length > 0 && <div className="table-scroll"><table>
          <thead><tr><th>Fecha</th><th>Tipo</th><th>Producto</th><th>Campo</th><th>Cantidad</th><th>Responsable</th><th>Documento / Referencia</th><th>Observación</th></tr></thead>
          <tbody>{movements.map((item) => <tr className={selectedMovement?.id === item.id ? "selected-row" : undefined} key={item.id} onClick={() => setSelectedMovementId(item.id)}>
            <td>{dateLabel(item.occurred_at)}</td>
            <td><span className="movement-type">{item.movement_label}</span></td>
            <td><ProductIdentity name={item.product_name} sku={item.sku} category={item.category} /></td>
            <td>{FIELD_LABELS[item.affected_field] ?? item.affected_field}</td>
            <td><strong className={item.delta < 0 ? "negative-delta" : item.delta > 0 ? "positive-delta" : undefined}>{item.delta > 0 ? `+${item.delta}` : item.delta}</strong></td>
            <td>{item.actor}</td>
            <td><strong>{item.reference_type ?? "—"}</strong><span>{item.reference_id ?? "Sin referencia"}</span></td>
            <td className="reason-cell">{item.reason}</td>
          </tr>)}</tbody>
        </table></div>}
      </section>

      <aside className="movement-detail" aria-label="Detalle del movimiento">
        {!selectedMovement && <div className="empty-detail compact"><strong>Sin movimiento seleccionado</strong><span>Cuando existan registros, podrás inspeccionar el antes y después aquí.</span></div>}
        {selectedMovement && <>
          <div className="detail-kicker"><span>{selectedMovement.movement_label}</span><strong>{selectedMovement.delta > 0 ? `+${selectedMovement.delta}` : selectedMovement.delta}</strong></div>
          <ProductIdentity name={selectedMovement.product_name} sku={selectedMovement.sku} category={selectedMovement.category} />
          <dl className="movement-meta">
            <div><dt>Fecha</dt><dd>{dateLabel(selectedMovement.occurred_at)}</dd></div>
            <div><dt>Responsable</dt><dd>{selectedMovement.actor}</dd></div>
            <div><dt>Campo afectado</dt><dd>{FIELD_LABELS[selectedMovement.affected_field] ?? selectedMovement.affected_field}</dd></div>
            <div><dt>Referencia</dt><dd>{selectedMovement.reference_type ?? "—"} · {selectedMovement.reference_id ?? "Sin referencia"}</dd></div>
          </dl>
          <div className="before-after-grid">
            <div><span>Antes</span><strong>{selectedMovement.before_value[selectedMovement.affected_field] ?? "—"}</strong></div>
            <div><span>Después</span><strong>{selectedMovement.after_value[selectedMovement.affected_field] ?? "—"}</strong></div>
          </div>
          <div className="movement-reason"><span>Observación</span><p>{selectedMovement.reason}</p></div>
        </>}
      </aside>
    </div>
  </main>;
}
