import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";
import { ProductIdentity } from "../inventory/ProductIdentity";

interface AuditMovement {
  id: string;
  occurred_at: string;
  responsible: string;
  movement_type: string;
  reason: string;
  quantity: number | null;
  net_inventory_effect: number;
}

interface AuditProduct {
  product_id: string;
  product_name: string;
  sku: string;
  expected: number;
  discounted: number;
  difference: number;
  expected_movement: number;
  found_movement: number;
  outbound_movements: number;
  pending_units: number;
  excess_units: number;
  status: string;
  status_label: string;
  inventory_current: number | null;
  movements: AuditMovement[];
}

interface AuditInvoice {
  id: string;
  invoice_number: string;
  invoice_date: string;
  customer_name: string;
  chain_name: string | null;
  purchase_order_number: string | null;
  administrative_status: string;
  dispatch_status: string;
  product_count: number;
  invoiced_units: number;
  discounted_units: number;
  difference: number;
  pending_units: number;
  excess_units: number;
  status: string;
  status_label: string;
  products: AuditProduct[];
}

interface AuditResponse {
  summary: {
    reviewed: number;
    correct: number;
    missing: number;
    partial: number;
    excess_or_duplicate: number;
    cancelled_incorrect: number;
    requires_review: number;
    pending_units: number;
    excess_units: number;
    orphan_movements: number;
  };
  items: AuditInvoice[];
  orphan_movements: Array<{
    id: string;
    reference: string | null;
    occurred_at: string;
    product_name: string;
    sku: string;
    responsible: string;
    net_inventory_effect: number;
    status_label: string;
  }>;
  total: number;
  page: number;
  pages: number;
  read_only: boolean;
}

interface CorrectionResult {
  corrected: number;
  errors: number;
  results: Array<{ id: string; status: string; detail?: string }>;
  inventory_affected: Array<{ sku: string; physical_confirmed: number; available_to_invoice: number }>;
}

const number = (value: number) => new Intl.NumberFormat("es-EC").format(value);
const date = (value: string) => new Intl.DateTimeFormat("es-EC", { dateStyle: "medium" }).format(new Date(value.length === 10 ? `${value}T12:00:00` : value));
const correctionAllowed = (item: AuditInvoice) => ["missing", "partial", "over", "cancelled_missing_reversal"].includes(item.status);

export function InvoiceInventoryAudit({ onViewDetail }: { onViewDetail: (id: string) => void }) {
  const [data, setData] = useState<AuditResponse | null>(null);
  const [search, setSearch] = useState("");
  const [chain, setChain] = useState("");
  const [product, setProduct] = useState("");
  const [status, setStatus] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [problemsOnly, setProblemsOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [previewing, setPreviewing] = useState(false);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [correcting, setCorrecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const query = new URLSearchParams({ page: String(page), page_size: "25" });
    if (search.trim()) query.set("search", search.trim());
    if (chain.trim()) query.set("chain", chain.trim());
    if (product.trim()) query.set("product", product.trim());
    if (status) query.set("status", status);
    if (dateFrom) query.set("date_from", dateFrom);
    if (dateTo) query.set("date_to", dateTo);
    if (problemsOnly) query.set("problems_only", "true");
    try {
      const loaded = await apiRequest<AuditResponse>(`/invoices/inventory-audit?${query}`);
      setData(loaded);
      setSelected((current) => current.filter((id) => loaded.items.some((item) => item.id === id)));
      setExpanded((current) => loaded.items.some((item) => item.id === current) ? current : null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo generar la auditoría.");
    } finally {
      setLoading(false);
    }
  }, [chain, dateFrom, dateTo, page, problemsOnly, product, search, status]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 180);
    return () => window.clearTimeout(timer);
  }, [load]);

  const selectedInvoices = useMemo(
    () => (data?.items ?? []).filter((item) => selected.includes(item.id)),
    [data, selected],
  );

  const applyCorrections = async () => {
    if (!selected.length || reason.trim().length < 5) return;
    setCorrecting(true);
    setError(null);
    try {
      const response = await apiRequest<CorrectionResult>("/invoices/inventory-audit/corrections", {
        method: "POST",
        body: JSON.stringify({ confirmation: "CORREGIR", invoice_ids: selected, reason: reason.trim() }),
      });
      const skipped = response.results.filter((item) => item.status === "skipped").length;
      setResult(`${response.corrected} corregidas · ${response.errors} con error · ${skipped} sin cambios`);
      setPreviewing(false);
      setSelected([]);
      setReason("");
      window.dispatchEvent(new CustomEvent("inventario:inventory-changed", { detail: response.inventory_affected }));
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudieron aplicar las correcciones seleccionadas.");
    } finally {
      setCorrecting(false);
    }
  };

  return <section className="pending-inventory-view invoice-full-audit" aria-label="Auditoría de facturas e inventario">
    <div className="panel-title pending-title">
      <div><p className="eyebrow">Primera revisión de solo lectura</p><h2>Auditoría de facturas e inventario</h2><p>Compara cada factura y producto con sus movimientos. Despachos y entregas no intervienen en el cálculo.</p></div>
      <button className="secondary-button" type="button" disabled={loading} onClick={() => void load()}>{loading ? "Auditando…" : "Actualizar auditoría"}</button>
    </div>

    {data && <div className="metric-grid pending-summary">
      <article><span>Facturas revisadas</span><strong>{number(data.summary.reviewed)}</strong></article>
      <article><span>Correctas</span><strong>{number(data.summary.correct)}</strong></article>
      <article><span>Sin descontar</span><strong>{number(data.summary.missing)}</strong></article>
      <article><span>Parciales</span><strong>{number(data.summary.partial)}</strong></article>
      <article><span>Duplicadas o excesivas</span><strong>{number(data.summary.excess_or_duplicate)}</strong></article>
      <article><span>Anuladas incorrectamente</span><strong>{number(data.summary.cancelled_incorrect)}</strong></article>
      <article><span>Requieren revisión</span><strong>{number(data.summary.requires_review)}</strong></article>
      <article><span>Unidades por descontar</span><strong>{number(data.summary.pending_units)}</strong></article>
      <article><span>Unidades descontadas de más</span><strong>{number(data.summary.excess_units)}</strong></article>
    </div>}

    <div className="message info"><strong>Auditoría de solo lectura</strong><span>Consultar, filtrar o abrir detalles no modifica el inventario. Las correcciones requieren selección, vista previa, motivo y confirmación.</span></div>
    {result && <div className="message success" role="status">{result}</div>}
    {error && <div className="message error" role="alert">{error}</div>}

    <div className="invoice-filter-grid pending-filters">
      <label className="search-field"><span>Factura u OC</span><input type="search" value={search} onChange={(event) => { setPage(1); setSearch(event.target.value); }} /></label>
      <label className="search-field"><span>Cliente/cadena</span><input value={chain} onChange={(event) => { setPage(1); setChain(event.target.value); }} /></label>
      <label className="search-field"><span>Producto o SKU</span><input value={product} onChange={(event) => { setPage(1); setProduct(event.target.value); }} /></label>
      <label className="search-field"><span>Estado</span><select value={status} onChange={(event) => { setPage(1); setStatus(event.target.value); }}><option value="">Todos</option><option value="correct">Correcta</option><option value="missing">Sin descontar</option><option value="partial">Descuento parcial</option><option value="over">Descuento excesivo</option><option value="duplicate">Movimiento duplicado</option><option value="product_incorrect">Producto incorrecto</option><option value="cancelled_correct">Anulación correcta</option><option value="cancelled_missing_reversal">Anulación sin reversión</option><option value="error">Requiere revisión</option></select></label>
      <label className="search-field"><span>Desde</span><input type="date" value={dateFrom} onChange={(event) => { setPage(1); setDateFrom(event.target.value); }} /></label>
      <label className="search-field"><span>Hasta</span><input type="date" value={dateTo} onChange={(event) => { setPage(1); setDateTo(event.target.value); }} /></label>
      <label><span>Solo problemas</span><input type="checkbox" checked={problemsOnly} onChange={(event) => { setPage(1); setProblemsOnly(event.target.checked); }} /></label>
    </div>

    <div className="pending-bulk-actions">
      <span>{selected.length} facturas seleccionadas</span>
      <button className="primary-button" type="button" disabled={!selected.length} onClick={() => { setPreviewing(true); setReason(""); }}>Ver corrección propuesta</button>
    </div>

    {loading && <div className="table-message">Revisando facturas y movimientos vinculados…</div>}
    {!loading && data && <div className="table-scroll invoice-table-scroll"><table className="compact-table pending-inventory-table">
      <thead><tr><th aria-label="Seleccionar" /><th>Factura</th><th>Fecha</th><th>Cliente/cadena</th><th>OC</th><th>Productos</th><th>Facturado</th><th>Descontado</th><th>Diferencia</th><th>Inventario</th><th>Despacho</th><th>Acción</th></tr></thead>
      <tbody>{data.items.map((item) => <Fragment key={item.id}>
        <tr>
          <td><input aria-label={`Seleccionar ${item.invoice_number}`} type="checkbox" disabled={!correctionAllowed(item)} checked={selected.includes(item.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} /></td>
          <td><strong>{item.invoice_number}</strong><span>{item.id}</span></td>
          <td>{date(item.invoice_date)}</td><td>{item.chain_name ?? item.customer_name}</td><td>{item.purchase_order_number ?? "—"}</td><td>{item.product_count}</td><td>{number(item.invoiced_units)}</td><td>{number(item.discounted_units)}</td><td>{item.difference > 0 ? `${number(item.difference)} pendientes` : item.difference < 0 ? `${number(-item.difference)} de más` : "0"}</td><td><span className={`status-pill invoice-${item.status}`}>{item.status_label}</span></td><td>{item.dispatch_status === "complete" ? "Completo" : item.dispatch_status === "partial" ? "Parcial" : item.dispatch_status === "pending" ? "Pendiente" : "No aplica"}</td>
          <td><div className="table-actions"><button type="button" onClick={() => setExpanded(expanded === item.id ? null : item.id)}>{expanded === item.id ? "Ocultar detalle" : "Ver detalle"}</button><button type="button" onClick={() => onViewDetail(item.id)}>Abrir factura</button></div></td>
        </tr>
        {expanded === item.id && <tr className="pending-detail-row"><td colSpan={12}><div className="pending-product-detail">
          <div className="message info">{item.status === "correct" ? `Esta factura contiene ${number(item.invoiced_units)} unidades y fueron descontadas correctamente.` : item.pending_units > 0 ? `Esta factura contiene ${number(item.invoiced_units)} unidades. Se descontaron ${number(item.discounted_units)}. Faltan ${number(item.pending_units)} unidades por descontar.` : item.excess_units > 0 ? `Se descontaron ${number(item.excess_units)} unidades más de las facturadas.` : item.status_label}</div>
          <table><thead><tr><th>Producto</th><th>Facturado</th><th>Esperado</th><th>Movimientos encontrados</th><th>Neto descontado</th><th>Diferencia</th><th>Estado</th><th>Fecha y responsable</th></tr></thead><tbody>{item.products.map((line) => <tr key={line.product_id}><td><ProductIdentity name={line.product_name} sku={line.sku} /></td><td>{number(line.expected)}</td><td>{number(line.expected_movement)}</td><td>{line.movements.length}</td><td>{number(line.found_movement)}</td><td>{number(line.difference)}</td><td>{line.status_label}</td><td>{line.movements.length ? line.movements.map((movement) => <span key={movement.id}>{date(movement.occurred_at)} · {movement.responsible} · {movement.net_inventory_effect > 0 ? "+" : ""}{movement.net_inventory_effect}</span>) : "Sin movimientos"}</td></tr>)}</tbody></table>
        </div></td></tr>}
      </Fragment>)}</tbody>
    </table>{data.items.length === 0 && <div className="table-message">No se encontraron facturas con estos filtros.</div>}</div>}

    {data && <div className="pagination-bar"><span>{number(data.total)} facturas</span><button type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Anterior</button><span>Página {page} de {data.pages}</span><button type="button" disabled={page >= data.pages} onClick={() => setPage((value) => value + 1)}>Siguiente</button></div>}

    {data?.orphan_movements.length ? <section className="trace-section"><h3>Movimientos sin factura</h3><div className="message warning">Estos movimientos tienen referencia de factura, pero no existe una factura vinculable de forma segura.</div><div className="event-list">{data.orphan_movements.map((movement) => <article key={movement.id}><strong>{movement.status_label} · {movement.reference ?? "Sin referencia"}</strong><span>{movement.product_name} · SKU {movement.sku}</span><small>{date(movement.occurred_at)} · {movement.responsible} · efecto {movement.net_inventory_effect}</small></article>)}</div></section> : null}

    {previewing && selectedInvoices.length > 0 && <section className="correction-preview pending-correction-preview" aria-label="Vista previa de correcciones">
      <div className="panel-title"><div><h3>Vista previa antes de modificar inventario</h3><p>Solo se aplicará la diferencia comprobada. Ninguna factura no seleccionada será modificada.</p></div><button className="text-button" type="button" onClick={() => setPreviewing(false)}>Cerrar</button></div>
      {selectedInvoices.map((invoice) => <article key={invoice.id}><strong>Factura {invoice.invoice_number}</strong>{invoice.products.filter((line) => line.difference !== 0).map((line) => {
        const adjustment = invoice.status === "cancelled_missing_reversal" ? line.discounted : -line.difference;
        const resulting = line.inventory_current == null ? null : line.inventory_current + adjustment;
        return <span key={line.product_id}>{line.product_name} · SKU {line.sku} · inventario actual {line.inventory_current ?? "—"} · movimiento propuesto {adjustment > 0 ? "+" : ""}{adjustment} · inventario resultante {resulting ?? "—"}</span>;
      })}</article>)}
      <label className="full-field"><span>Motivo de la corrección *</span><textarea rows={3} minLength={5} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      <div className="form-actions"><button className="secondary-button" type="button" onClick={() => setPreviewing(false)}>Volver a revisar</button><button className="primary-button" type="button" disabled={correcting || reason.trim().length < 5} onClick={() => void applyCorrections()}>{correcting ? "Corrigiendo…" : "Confirmar facturas seleccionadas"}</button></div>
    </section>}
  </section>;
}
