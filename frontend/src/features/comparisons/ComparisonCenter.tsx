import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";
import { ProductIdentity } from "../inventory/ProductIdentity";

interface ComparisonRow {
  chain_name: string | null;
  customer_name: string | null;
  order_number: string | null;
  order_date: string | null;
  source_type: string;
  sku: string;
  product_name: string;
  ordered_quantity: number;
  invoiced_quantity: number;
  dispatched_quantity: number;
  delivered_quantity: number;
  rejected_delivery_quantity: number;
  missing_quantity: number;
  pending_to_invoice: number;
  pending_to_dispatch: number;
  pending_to_deliver: number;
  invoice_numbers: string[];
  delivery_statuses: string[];
  outside_purchase_order: boolean;
  status: string;
}

const STATUS_LABELS: Record<string, string> = {
  ok: "Cuadrado",
  pending_invoice: "Pendiente facturar",
  pending_dispatch: "Pendiente despachar",
  pending_delivery: "Pendiente entregar",
  with_incident: "Con incidencia",
  outside_purchase_order: "Fuera de OC",
};

const SOURCE_LABELS: Record<string, string> = {
  purchase_order: "OC",
  sale_without_po: "Venta sin OC",
  internal_consumption: "Consumo interno",
  sample: "Muestra",
  replacement: "Reposición",
  other: "Otro",
};

const dateLabel = (value: string | null) =>
  value ? new Intl.DateTimeFormat("es-EC", { dateStyle: "medium" }).format(new Date(`${value}T00:00:00`)) : "—";

export function ComparisonCenter() {
  const [rows, setRows] = useState<ComparisonRow[]>([]);
  const [search, setSearch] = useState("");
  const [chain, setChain] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const summary = useMemo(() => ({
    total: rows.length,
    pendingInvoice: rows.filter((row) => row.status === "pending_invoice").length,
    pendingDispatch: rows.filter((row) => row.status === "pending_dispatch").length,
    pendingDelivery: rows.filter((row) => row.status === "pending_delivery").length,
    incidents: rows.filter((row) => row.status === "with_incident" || row.status === "outside_purchase_order").length,
  }), [rows]);

  const load = () => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (search.trim()) params.set("search", search.trim());
    if (chain.trim()) params.set("chain", chain.trim());
    if (status) params.set("status", status);
    apiRequest<ComparisonRow[]>(`/comparisons?${params.toString()}`)
      .then(setRows)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudieron cargar los comparativos."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    apiRequest<ComparisonRow[]>("/comparisons")
      .then(setRows)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudieron cargar los comparativos."))
      .finally(() => setLoading(false));
  }, []);

  return <main className="dashboard comparison-center">
    <section className="module-heading">
      <div className="welcome-block">
        <p className="eyebrow">Control entre etapas</p>
        <h1>Comparativos</h1>
        <p>Compara la OC original con lo facturado externamente, lo despachado y el estado de entrega. Esta vista ayuda a detectar diferencias antes de tomar decisiones.</p>
      </div>
      <button className="secondary-button" type="button" disabled={loading} onClick={load}>{loading ? "Actualizando…" : "Actualizar"}</button>
    </section>

    <section className="comparison-summary" aria-label="Resumen comparativo">
      <article><span>Filas</span><strong>{summary.total}</strong></article>
      <article><span>Pendiente facturar</span><strong>{summary.pendingInvoice}</strong></article>
      <article><span>Pendiente despachar</span><strong>{summary.pendingDispatch}</strong></article>
      <article><span>Pendiente entregar</span><strong>{summary.pendingDelivery}</strong></article>
      <article><span>Diferencias / incidencias</span><strong>{summary.incidents}</strong></article>
    </section>

    <section className="comparison-filters" aria-label="Filtros comparativos">
      <label><span>Buscar</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="OC, factura, SKU o producto" /></label>
      <label><span>Cadena</span><input value={chain} onChange={(event) => setChain(event.target.value)} placeholder="Favorita, Tía, Rosado…" /></label>
      <label><span>Estado</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">Todos</option>{Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <button className="primary-button" type="button" disabled={loading} onClick={load}>Aplicar filtros</button>
    </section>

    {error && <div className="message error" role="alert">{error}</div>}

    <section className="comparison-panel">
      <div className="panel-title">
        <div><h2>OC vs Factura vs Despacho</h2><p>Entrega se muestra como estado por factura; las cantidades entregadas por SKU quedan para la siguiente etapa.</p></div>
        <span>{rows.length}</span>
      </div>
      {loading && <div className="table-message">Cargando comparativos…</div>}
      {!loading && rows.length === 0 && <div className="table-message">No hay diferencias o registros para los filtros seleccionados.</div>}
      {rows.length > 0 && <div className="table-scroll"><table>
        <thead><tr><th>OC / Factura</th><th>Cadena</th><th>Producto</th><th>Pedido</th><th>Facturado</th><th>Despachado</th><th>Entregado</th><th>Faltante</th><th>Pendiente</th><th>Entrega</th><th>Estado</th></tr></thead>
        <tbody>{rows.map((row, index) => <tr className={row.status !== "ok" ? "comparison-warning" : undefined} key={`${row.order_number ?? "sin-oc"}-${row.sku}-${index}`}>
          <td><strong>{row.order_number ?? SOURCE_LABELS[row.source_type] ?? "Sin OC"}</strong><span>{row.invoice_numbers.length ? row.invoice_numbers.join(", ") : "Sin factura"}</span><span>{dateLabel(row.order_date)}</span></td>
          <td>{row.chain_name ?? "—"}</td>
          <td><ProductIdentity name={row.product_name} sku={row.sku} /></td>
          <td>{row.ordered_quantity}</td>
          <td>{row.invoiced_quantity}</td>
          <td>{row.dispatched_quantity}</td>
          <td><span>{row.delivered_quantity}</span>{row.rejected_delivery_quantity > 0 && <span>Rechazado: {row.rejected_delivery_quantity}</span>}</td>
          <td>{row.missing_quantity}</td>
          <td><span>Facturar: {row.pending_to_invoice}</span><span>Despachar: {row.pending_to_dispatch}</span><span>Entregar: {row.pending_to_deliver}</span></td>
          <td>{row.delivery_statuses.length ? row.delivery_statuses.join(", ") : "—"}</td>
          <td><span className={`comparison-status ${row.status}`}>{STATUS_LABELS[row.status] ?? row.status}</span></td>
        </tr>)}</tbody>
      </table></div>}
    </section>
  </main>;
}
