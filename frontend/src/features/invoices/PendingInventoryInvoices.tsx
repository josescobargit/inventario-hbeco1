import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";
import { ProductIdentity } from "../inventory/ProductIdentity";

interface PendingLine {
  product_id: string;
  product_name: string;
  sku: string;
  invoiced_units: number;
  discounted_units: number;
  pending_units: number;
}

interface PendingInvoice {
  id: string;
  invoice_number: string;
  invoice_date: string;
  chain_name: string;
  purchase_order_id: string | null;
  purchase_order_number: string | null;
  invoiced_units: number;
  discounted_units: number;
  pending_units: number;
  status: "pending_complete" | "pending_partial" | "error" | "processing";
  status_label: string;
  error: string | null;
  attempts: number;
  lines: PendingLine[];
}

interface PendingResponse {
  summary: {
    pending_invoices: number;
    pending_complete: number;
    pending_partial: number;
    errors: number;
    processing: number;
    pending_units: number;
  };
  items: PendingInvoice[];
  page: number;
  pages: number;
  total: number;
  findings: {
    possible_duplicates: Array<{ id: string; invoice_number: string; status_label: string; difference: number }>;
    errors: Array<{ id: string; invoice_number: string; error: string | null }>;
  };
  read_only: boolean;
}

interface CorrectionResult {
  results: Array<{ id: string; invoice_number: string; status: "corrected" | "error" | "skipped"; detail?: string; units_discounted?: number }>;
  corrected: number;
  errors: number;
  inventory_affected: Array<{ sku: string; physical_confirmed: number; available_to_invoice: number }>;
}

const number = (value: number) => new Intl.NumberFormat("es-EC").format(value);
const date = (value: string) => new Intl.DateTimeFormat("es-EC", { dateStyle: "medium" }).format(new Date(`${value}T12:00:00`));

export function PendingInventoryInvoices({ onViewDetail }: { onViewDetail: (id: string) => void }) {
  const [data, setData] = useState<PendingResponse | null>(null);
  const [search, setSearch] = useState("");
  const [sequence, setSequence] = useState("");
  const [purchaseOrder, setPurchaseOrder] = useState("");
  const [chain, setChain] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [previewIds, setPreviewIds] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resultMessage, setResultMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    const query = new URLSearchParams({ page: String(page), page_size: "25" });
    if (search.trim()) query.set("search", search.trim());
    if (sequence.trim()) query.set("sequence", sequence.trim());
    if (purchaseOrder.trim()) query.set("purchase_order", purchaseOrder.trim());
    if (chain.trim()) query.set("chain", chain.trim());
    if (dateFrom) query.set("date_from", dateFrom);
    if (dateTo) query.set("date_to", dateTo);
    if (status) query.set("status", status);
    try {
      const loaded = await apiRequest<PendingResponse>(`/invoices/inventory-pending?${query}`);
      setData(loaded);
      setLoadError(false);
      setSelected((current) => current.filter((id) => loaded.items.some((item) => item.id === id)));
      setExpanded((current) => loaded.items.some((item) => item.id === current) ? current : null);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [chain, dateFrom, dateTo, page, purchaseOrder, search, sequence, status]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 180);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    const refresh = () => void load();
    window.addEventListener("inventario:invoice-saved", refresh);
    return () => window.removeEventListener("inventario:invoice-saved", refresh);
  }, [load]);

  const previewInvoices = useMemo(
    () => (data?.items ?? []).filter((item) => previewIds.includes(item.id)),
    [data, previewIds],
  );
  const selectable = (data?.items ?? []).filter((item) => item.status !== "processing");
  const allSelected = selectable.length > 0 && selectable.every((item) => selected.includes(item.id));

  const prepareCorrection = (ids: string[]) => {
    if (!ids.length) return;
    setPreviewIds(ids);
    setReason("");
    setResultMessage(null);
  };

  const applyCorrection = async () => {
    if (!previewIds.length || reason.trim().length < 5) return;
    setCorrecting(true);
    setError(null);
    try {
      const result = await apiRequest<CorrectionResult>("/invoices/inventory-audit/corrections", {
        method: "POST",
        body: JSON.stringify({
          confirmation: "CORREGIR",
          invoice_ids: previewIds,
          reason: reason.trim(),
        }),
      });
      const skipped = result.results.filter((item) => item.status === "skipped").length;
      setResultMessage(`${result.corrected} completadas · ${result.errors} con error · ${skipped} sin cambios`);
      window.dispatchEvent(new CustomEvent("inventario:inventory-changed", { detail: result.inventory_affected }));
      setPreviewIds([]);
      setSelected([]);
      setReason("");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos aplicar los descuentos pendientes.");
    } finally {
      setCorrecting(false);
    }
  };

  return <section className="pending-inventory-view" aria-label="Pendientes de inventario">
    <div className="panel-title pending-title">
      <div><p className="eyebrow">Auditoría inicial de solo lectura</p><h2>Pendientes de inventario</h2><p>Solo aparecen facturas activas cuya diferencia pendiente es mayor que cero.</p></div>
      <button className="secondary-button" type="button" disabled={loading} onClick={() => void load()}>{loading ? "Actualizando…" : "Actualizar auditoría"}</button>
    </div>

    {data && <div className="metric-grid pending-summary">
      <article><span>Facturas pendientes</span><strong>{number(data.summary.pending_invoices)}</strong></article>
      <article><span>Sin ningún descuento</span><strong>{number(data.summary.pending_complete)}</strong></article>
      <article><span>Descontadas parcialmente</span><strong>{number(data.summary.pending_partial)}</strong></article>
      <article><span>Con error</span><strong>{number(data.summary.errors)}</strong></article>
      <article><span>En procesamiento</span><strong>{number(data.summary.processing)}</strong></article>
      <article><span>Unidades pendientes</span><strong>{number(data.summary.pending_units)}</strong></article>
    </div>}

    {data?.findings.possible_duplicates.length ? <div className="message warning"><strong>Movimientos que requieren revisión manual</strong><span>{data.findings.possible_duplicates.map((item) => `${item.invoice_number}: ${item.status_label}`).join(" · ")}</span></div> : null}
    {resultMessage && <div className="message success" role="status">{resultMessage}</div>}
    {error && <div className="message error" role="alert">{error}</div>}

    <div className="invoice-filter-grid pending-filters">
      <label className="search-field"><span>Factura</span><input type="search" value={search} onChange={(event) => { setPage(1); setSearch(event.target.value); }} placeholder="Número de factura" /></label>
      <label className="search-field"><span>Secuencia</span><input value={sequence} onChange={(event) => { setPage(1); setSequence(event.target.value); }} placeholder="Ej. 000000773" /></label>
      <label className="search-field"><span>OC</span><input value={purchaseOrder} onChange={(event) => { setPage(1); setPurchaseOrder(event.target.value); }} placeholder="Número de OC" /></label>
      <label className="search-field"><span>Cadena</span><input value={chain} onChange={(event) => { setPage(1); setChain(event.target.value); }} placeholder="Todas" /></label>
      <label className="search-field"><span>Desde</span><input type="date" value={dateFrom} onChange={(event) => { setPage(1); setDateFrom(event.target.value); }} /></label>
      <label className="search-field"><span>Hasta</span><input type="date" value={dateTo} onChange={(event) => { setPage(1); setDateTo(event.target.value); }} /></label>
      <label className="search-field"><span>Estado</span><select value={status} onChange={(event) => { setPage(1); setStatus(event.target.value); }}><option value="">Todos</option><option value="pending_complete">Pendiente completa</option><option value="pending_partial">Pendiente parcial</option><option value="error">Error al descontar</option><option value="processing">En procesamiento</option></select></label>
    </div>

    <div className="pending-bulk-actions">
      <label><input type="checkbox" checked={allSelected} onChange={(event) => setSelected(event.target.checked ? selectable.map((item) => item.id) : [])} /> Seleccionar visibles</label>
      <button className="primary-button" type="button" disabled={!selected.length} onClick={() => prepareCorrection(selected)}>Descontar seleccionadas</button>
    </div>

    {loading && <div className="table-message">Auditando facturas y movimientos…</div>}
    {!loading && loadError && <div className="table-message error invoice-load-error"><strong>No se pudieron cargar las facturas.</strong><button className="secondary-button" type="button" onClick={() => void load()}>Reintentar</button></div>}
    {!loading && !loadError && data && <div className="table-scroll invoice-table-scroll"><table className="compact-table pending-inventory-table">
      <thead><tr><th aria-label="Seleccionar" /><th>Factura</th><th>Fecha</th><th>Cadena</th><th>OC</th><th>Facturado</th><th>Descontado</th><th>Pendiente</th><th>Estado</th><th>Error</th><th>Acción</th></tr></thead>
      <tbody>{data.items.map((item) => <Fragment key={item.id}>
        <tr>
          <td><input aria-label={`Seleccionar ${item.invoice_number}`} type="checkbox" disabled={item.status === "processing"} checked={selected.includes(item.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} /></td>
          <td><strong>{item.invoice_number}</strong></td><td>{date(item.invoice_date)}</td><td>{item.chain_name}</td><td>{item.purchase_order_number ?? "—"}</td><td>{number(item.invoiced_units)}</td><td>{number(item.discounted_units)}</td><td><strong>{number(item.pending_units)} unidades</strong></td><td><span className={`status-pill invoice-${item.status}`}>{item.status_label}</span></td><td title={item.error ?? undefined}>{item.error ?? "—"}</td>
          <td><div className="table-actions"><button type="button" onClick={() => onViewDetail(item.id)}>Ver detalle</button><button type="button" disabled={item.status === "processing"} onClick={() => prepareCorrection([item.id])}>Reintentar descuento</button>{item.error && <button type="button" onClick={() => setExpanded(expanded === item.id ? null : item.id)}>Revisar error</button>}<button type="button" onClick={() => setExpanded(expanded === item.id ? null : item.id)}>{expanded === item.id ? "Ocultar productos" : "Ver productos"}</button></div></td>
        </tr>
        {expanded === item.id && <tr className="pending-detail-row"><td colSpan={11}><div className="pending-product-detail">{item.error && <div className="message error"><strong>Error técnico</strong><span>{item.error}</span><small>Intentos registrados: {item.attempts}</small></div>}<table><thead><tr><th>Producto</th><th>SKU</th><th>Facturado</th><th>Descontado</th><th>Pendiente</th></tr></thead><tbody>{item.lines.map((line) => <tr key={line.product_id}><td><ProductIdentity name={line.product_name} sku={line.sku} /></td><td>{line.sku}</td><td>{number(line.invoiced_units)}</td><td>{number(line.discounted_units)}</td><td><strong>{number(line.pending_units)}</strong></td></tr>)}</tbody></table></div></td></tr>}
      </Fragment>)}</tbody>
    </table>{data.items.length === 0 && <div className="table-message">No se encontraron facturas con estos filtros.</div>}</div>}

    {!loadError && data && <div className="pagination-bar"><span>{number(data.total)} facturas pendientes</span><button type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Anterior</button><span>Página {page} de {data.pages}</span><button type="button" disabled={page >= data.pages} onClick={() => setPage((value) => value + 1)}>Siguiente</button></div>}

    {previewInvoices.length > 0 && <section className="correction-preview pending-correction-preview" aria-label="Vista previa del descuento">
      <div className="panel-title"><div><h3>Vista previa del descuento</h3><p>Se creará únicamente la diferencia pendiente de cada producto.</p></div><button className="text-button" type="button" onClick={() => setPreviewIds([])}>Cerrar</button></div>
      {previewInvoices.map((invoice) => <article key={invoice.id}><strong>{invoice.invoice_number} · {number(invoice.pending_units)} unidades pendientes</strong>{invoice.lines.filter((line) => line.pending_units > 0).map((line) => <span key={line.product_id}>{line.product_name} · SKU {line.sku}: {number(line.pending_units)} unidades</span>)}</article>)}
      <label className="full-field"><span>Motivo de la corrección *</span><textarea rows={3} minLength={5} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explica por qué se reintenta el descuento" /></label>
      <div className="form-actions"><button className="secondary-button" type="button" onClick={() => setPreviewIds([])}>Volver</button><button className="primary-button" type="button" disabled={correcting || reason.trim().length < 5} onClick={() => void applyCorrection()}>{correcting ? "Procesando una por una…" : "Confirmar diferencias"}</button></div>
    </section>}
  </section>;
}
