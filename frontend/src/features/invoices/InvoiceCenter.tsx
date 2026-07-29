import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "../../api/client";
import { ProductIdentity } from "../inventory/ProductIdentity";
import { InvoiceInventoryAudit } from "./InvoiceInventoryAudit";
import { InvoiceRegistrationForm, InvoiceTemplate } from "./InvoiceRegistrationForm";

interface InvoiceSummary {
  id: string;
  invoice_number: string;
  invoice_date: string;
  customer_name: string;
  chain_name: string | null;
  purchase_order_id: string | null;
  purchase_order_number: string | null;
  product_count: number;
  units: number;
  administrative_status: string;
  dispatch_status: string;
  delivery_status: string;
  inventory: {
    status: string;
    status_label: string;
    discounted_units: number;
    difference: number;
  };
}
interface InvoiceListing {
  items: InvoiceSummary[];
  page: number;
  pages: number;
  total: number;
  missing_sequences: string[];
  summary: {
    invoices: number;
    missing: number;
    partial: number;
    errors: number;
    discounted: number;
    cancelled: number;
    pending_units: number;
  };
}
interface Traceability {
  invoice: {
    id: string;
    number: string;
    date: string;
    customer: string;
    chain: string | null;
    source_type: string;
    authorization_number: string | null;
    remittance_guide: string | null;
    notes: string | null;
    total_value: string | null;
    net_value: string | number;
    statuses: Record<string, string>;
    inventory: {
      status: string;
      status_label: string;
      discounted_at: string | null;
      discounted_quantity: number;
      movement_ids: string[];
      last_error: string | null;
      attempts: number;
    };
  };
  purchase_order: { id: string; number: string; chain: string } | null;
  lines: Array<{
    sku: string;
    product_name: string;
    ordered: number | null;
    invoiced: number;
    dispatched: number;
    missing: number;
    delivered: number;
    pending_dispatch: number;
    pending_confirmation: number;
    delivery_difference: number;
    outside_purchase_order: boolean;
  }>;
  deliveries: Array<{ id: string; delivery_type: string; delivered_at: string; recipient: string | null; notes: string | null }>;
  incidents: Array<{ id: string; incident_type: string; description: string; affected_quantity: number | null; status: string; decision: string | null }>;
  alerts: Array<{ id: string; alert_type: string; description: string; is_resolved: boolean }>;
  returns: Array<{ id: string; reason: string; returned_at: string; lines: Array<{ sku: string; quantity: number; disposition: string }> }>;
  adjustments: Array<{ id: string; document_type: string; document_number: string; document_date: string; value: string; reason: string }>;
}

const labels: Record<string, string> = {
  administrative: "Administrativo", dispatch: "Despacho", delivery: "Entrega",
  incident: "Incidencias", return: "Devolución", pending: "Pendiente", confirmed: "Confirmado",
  none: "Sin novedad", open: "Abierta", resolved: "Resuelta", closed: "Cerrada",
  partial: "Parcial", total: "Total", delivered: "Entregado", credit_note: "Nota de crédito",
  complete: "Completo", not_applicable: "No aplica",
  debit_note: "Nota de débito", without_issue: "Sin novedad", with_issue: "Con novedad",
  inventory: "Inventario", correct: "Inventario descontado", missing: "Pendiente de descontar",
  duplicate: "Descuento duplicado", over: "Movimiento superior", cancelled_correct: "Revertido",
  cancelled_missing_reversal: "Anulada sin reversión", error: "Error",
};

const label = (value: string) => labels[value] ?? value.replaceAll("_", " ");
const formatDate = (value: string) => new Intl.DateTimeFormat("es-EC", { dateStyle: "medium" }).format(new Date(`${value.slice(0, 10)}T12:00:00`));
const formatMoney = (value: string | number | null) => value == null ? "—" : new Intl.NumberFormat("es-EC", { style: "currency", currency: "USD" }).format(Number(value));

export function InvoiceCenter() {
  const [prepared] = useState(() => {
    const stored = sessionStorage.getItem("inventario.invoiceTemplate");
    if (!stored) return { template: null as InvoiceTemplate | null, error: null as string | null };
    sessionStorage.removeItem("inventario.invoiceTemplate");
    try {
      return { template: JSON.parse(stored) as InvoiceTemplate, error: null };
    } catch {
      return { template: null, error: "No pudimos recuperar la factura preparada desde la OC." };
    }
  });
  const [invoices, setInvoices] = useState<InvoiceSummary[]>([]);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [totalInvoices, setTotalInvoices] = useState(0);
  const [listingSummary, setListingSummary] = useState<InvoiceListing["summary"]>({
    invoices: 0, missing: 0, partial: 0, errors: 0, discounted: 0, cancelled: 0, pending_units: 0,
  });
  const [missingSequences, setMissingSequences] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [trace, setTrace] = useState<Traceability | null>(null);
  const [search, setSearch] = useState("");
  const [orderSearch, setOrderSearch] = useState("");
  const [chainFilter, setChainFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [inventoryFilter, setInventoryFilter] = useState("");
  const [sort, setSort] = useState("sequence");
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(prepared.error);
  const [showForm, setShowForm] = useState(Boolean(prepared.template));
  const [activeView, setActiveView] = useState<"all" | "missing" | "partial" | "error" | "discounted" | "cancelled" | "audit">("all");
  const [template, setTemplate] = useState<InvoiceTemplate | null>(prepared.template);
  const [editing, setEditing] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const loadInvoices = useCallback(() => {
    const query = new URLSearchParams({ page: String(page), page_size: "25", sort });
    if (search.trim()) query.set("search", search.trim());
    if (orderSearch.trim()) query.set("purchase_order", orderSearch.trim());
    if (chainFilter) query.set("chain", chainFilter);
    if (dateFrom) query.set("date_from", dateFrom);
    if (dateTo) query.set("date_to", dateTo);
    if (statusFilter) query.set("status", statusFilter);
    if (inventoryFilter) query.set("inventory_status", inventoryFilter);
    return apiRequest<InvoiceListing>(`/invoices/listing?${query}`)
      .then((data) => {
        const requestedId = sessionStorage.getItem("inventario.openInvoiceId");
        sessionStorage.removeItem("inventario.openInvoiceId");
        setInvoices(data.items);
        setPages(data.pages);
        setTotalInvoices(data.total);
        setListingSummary(data.summary ?? {
          invoices: data.total, missing: 0, partial: 0, errors: 0, discounted: 0, cancelled: 0, pending_units: 0,
        });
        setMissingSequences(data.missing_sequences);
        setListError(false);
        if (requestedId && data.items.some((item) => item.id === requestedId)) {
          setTrace(null);
          setDetailLoading(true);
          setSelectedId(requestedId);
        }
      })
      .catch(() => setListError(true))
      .finally(() => setLoading(false));
  }, [page, sort, search, orderSearch, chainFilter, dateFrom, dateTo, statusFilter, inventoryFilter]);

  useEffect(() => { void loadInvoices(); }, [loadInvoices]);

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    apiRequest<Traceability>(`/invoices/${selectedId}/traceability`)
      .then((data) => { if (active) setTrace(data); })
      .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "No pudimos cargar la trazabilidad."); })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [selectedId]);

  const selectInvoice = (id: string) => {
    setTrace(null);
    setDetailLoading(true);
    setSelectedId(id);
  };
  const selectView = (view: typeof activeView) => {
    setActiveView(view);
    setPage(1);
    if (view === "all") {
      setStatusFilter("");
      setInventoryFilter("");
    } else if (view === "missing") {
      setStatusFilter("confirmed");
      setInventoryFilter("missing");
    } else if (view === "partial") {
      setStatusFilter("confirmed");
      setInventoryFilter("partial");
    } else if (view === "error") {
      setStatusFilter("");
      setInventoryFilter("error");
    } else if (view === "discounted") {
      setStatusFilter("confirmed");
      setInventoryFilter("correct");
    } else if (view === "cancelled") {
      setStatusFilter("cancelled");
      setInventoryFilter("");
    } else {
      setStatusFilter("");
      setInventoryFilter("");
    }
  };

  const invoiceCreated = async (id: string) => {
    // The POST has already committed at this point. Close the form and select
    // the durable id first; a secondary refresh failure must never turn a
    // successful save into an apparent failure or invite a duplicate retry.
    setShowForm(false);
    setTemplate(null);
    setEditing(false);
    selectInvoice(id);
    window.dispatchEvent(new CustomEvent("inventario:invoice-saved", { detail: { id } }));
    setSuccess("Factura registrada correctamente");
    setError(null);
    try {
      await loadInvoices();
    } catch (caught) {
      setError(caught instanceof Error
        ? `La factura se guardó, pero no pudimos actualizar el listado: ${caught.message}`
        : "La factura se guardó, pero no pudimos actualizar el listado.");
    }
  };

  const populateFromTrace = (edit: boolean, source: Traceability | null = trace) => {
    if (!source) return;
    setTemplate({
      id: source.invoice.id,
      number: source.invoice.number,
      date: source.invoice.date,
      customer: source.invoice.customer,
      chain: source.invoice.chain,
      source_type: source.invoice.source_type,
      authorization_number: source.invoice.authorization_number,
      remittance_guide: source.invoice.remittance_guide,
      total_value: source.invoice.total_value,
      notes: source.invoice.notes,
      purchase_order_id: source.purchase_order?.id ?? null,
      lines: source.lines.map((line) => ({ sku: line.sku, invoiced: line.invoiced })),
    });
    setEditing(edit);
    setShowForm(true);
  };

  const editInvoice = async (id: string) => {
    setError(null);
    setDetailLoading(true);
    try {
      const loaded = await apiRequest<Traceability>(`/invoices/${id}/traceability`);
      setSelectedId(id);
      setTrace(loaded);
      populateFromTrace(true, loaded);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos abrir la factura para editar.");
    } finally {
      setDetailLoading(false);
    }
  };

  const cancelInvoiceById = async (id: string, number: string) => {
    if (!window.confirm(`¿Anular la factura ${number} y revertir su salida de inventario?`)) return;
    setCancelling(true);
    setError(null);
    try {
      const result = await apiRequest<{ inventory_affected: Array<{ sku: string; physical_confirmed: number; available_to_invoice: number }> }>(`/invoices/${id}/cancel`, { method: "POST" });
      window.dispatchEvent(new CustomEvent("inventario:inventory-changed", { detail: result.inventory_affected }));
      if (selectedId === id) {
        setTrace(await apiRequest<Traceability>(`/invoices/${id}/traceability`));
      }
      await loadInvoices();
      setSuccess("Factura anulada e inventario restituido");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos anular la factura.");
    } finally {
      setCancelling(false);
    }
  };
  const cancelInvoice = () => trace ? cancelInvoiceById(trace.invoice.id, trace.invoice.number) : Promise.resolve();

  const duplicateInvoice = async (id: string) => {
    setError(null);
    setDetailLoading(true);
    try {
      const loaded = await apiRequest<Traceability>(`/invoices/${id}/traceability`);
      setTrace(loaded);
      setSelectedId(id);
      populateFromTrace(false, loaded);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos preparar el duplicado.");
    } finally {
      setDetailLoading(false);
    }
  };

  return (
    <main className="dashboard invoice-center">
      <section className="module-heading">
        <div className="welcome-block"><p className="eyebrow">Trazabilidad documental y operativa</p><h1>Centro de Facturas</h1><p>Listado secuencial de facturas, estado del inventario y acceso a su trazabilidad.</p></div>
        <div className="invoice-view-actions">{!showForm && <button className="secondary-button" type="button" onClick={() => selectView("audit")}>Abrir auditoría</button>}<button className="primary-button" type="button" onClick={() => { setShowForm((value) => !value); setTemplate(null); setEditing(false); setError(null); }}>{showForm ? "Volver al centro" : "Registrar factura"}</button></div>
      </section>

      {success && <div className="message success" role="status">{success}</div>}
      {error && <div className="message error" role="alert">{error}</div>}
      {showForm ? <InvoiceRegistrationForm onCreated={invoiceCreated} onCancel={() => { setShowForm(false); setTemplate(null); setEditing(false); }} template={template} editing={editing} /> : <section className="invoice-workspace">
        <nav className="invoice-status-tabs" aria-label="Filtrar facturas por inventario">{([
          ["all", "Todas", listingSummary.invoices],
          ["missing", "Sin descontar", listingSummary.missing],
          ["partial", "Parciales", listingSummary.partial],
          ["error", "Con error", listingSummary.errors],
          ["discounted", "Descontadas", listingSummary.discounted],
          ["cancelled", "Anuladas", listingSummary.cancelled],
          ["audit", "Auditoría", listingSummary.missing + listingSummary.partial + listingSummary.errors],
        ] as const).map(([value, text, count]) => <button key={value} type="button" className={activeView === value ? "active" : ""} onClick={() => selectView(value)}>{text}<span>{count}</span></button>)}</nav>
        {activeView === "audit" && <InvoiceInventoryAudit onViewDetail={selectInvoice} />}
        {activeView !== "audit" && <section className="invoice-listing-summary" aria-label="Resumen de facturas"><strong>{listingSummary.invoices} facturas</strong><span>{listingSummary.missing} sin descontar</span><span>{listingSummary.partial} parciales</span><span>{listingSummary.discounted} descontadas</span><span>{listingSummary.pending_units.toLocaleString("es-EC")} unidades pendientes</span></section>}

        {activeView !== "audit" && <section className="invoice-compact-list" aria-label="Facturas registradas">
          <div className="invoice-filter-grid">
            <label className="search-field"><span>Factura</span><input type="search" placeholder="Número de factura" value={search} onChange={(event) => { setPage(1); setSearch(event.target.value); }} /></label>
            <label className="search-field"><span>OC</span><input type="search" placeholder="Número de OC" value={orderSearch} onChange={(event) => { setPage(1); setOrderSearch(event.target.value); }} /></label>
            <label className="search-field"><span>Cadena</span><input value={chainFilter} onChange={(event) => { setPage(1); setChainFilter(event.target.value); }} placeholder="Todas" /></label>
            <label className="search-field"><span>Desde</span><input type="date" value={dateFrom} onChange={(event) => { setPage(1); setDateFrom(event.target.value); }} /></label>
            <label className="search-field"><span>Hasta</span><input type="date" value={dateTo} onChange={(event) => { setPage(1); setDateTo(event.target.value); }} /></label>
            <label className="search-field"><span>Estado</span><select value={statusFilter} onChange={(event) => { setPage(1); setStatusFilter(event.target.value); }}><option value="">Todos</option><option value="confirmed">Confirmadas</option><option value="cancelled">Anuladas</option></select></label>
            <label className="search-field"><span>Inventario</span><select value={inventoryFilter} onChange={(event) => { setPage(1); setInventoryFilter(event.target.value); }}><option value="">Todos</option><option value="correct">Descontado</option><option value="missing">Pendiente</option><option value="partial">Parcial</option><option value="error">Error</option><option value="duplicate">Duplicado</option><option value="cancelled_correct">Revertido</option></select></label>
            <label className="search-field"><span>Orden</span><select value={sort} onChange={(event) => { setPage(1); setSort(event.target.value); }}><option value="sequence">Secuencia ascendente</option><option value="sequence_desc">Secuencia descendente</option><option value="recent">Fecha más reciente</option></select></label>
          </div>
          {missingSequences.length > 0 && <div className="message info">{missingSequences.slice(0, 3).map((number) => <span key={number}>Falta revisar la factura {number}. </span>)}</div>}
          {loading && <div className="table-message">Cargando facturas…</div>}
          {!loading && listError && <div className="table-message error invoice-load-error"><strong>No se pudieron cargar las facturas.</strong><button className="secondary-button" type="button" onClick={() => { setLoading(true); void loadInvoices(); }}>Reintentar</button></div>}
          {!loading && !listError && <div className="table-scroll invoice-table-scroll"><table className="compact-table"><thead><tr><th>Factura</th><th>Fecha</th><th>Cadena</th><th>OC</th><th>Productos</th><th>Unidades</th><th>Estado</th><th>Inventario</th><th>Despacho</th><th><span className="sr-only">Acciones</span></th></tr></thead><tbody>{invoices.map((item) => <tr key={item.id} className={selectedId === item.id ? "selected-row" : ""} tabIndex={0} onClick={() => selectInvoice(item.id)} onKeyDown={(event) => { if (event.key === "Enter") selectInvoice(item.id); }}><td><strong>{item.invoice_number}</strong></td><td>{formatDate(item.invoice_date)}</td><td>{item.chain_name ?? item.customer_name}</td><td>{item.purchase_order_number ?? "—"}</td><td>{item.product_count}</td><td>{item.units}</td><td>{item.administrative_status === "cancelled" ? "Anulada" : "Confirmada"}</td><td><span className={`status-pill invoice-${item.inventory.status}`}>{item.inventory.status_label}</span></td><td><span className={`status-pill dispatch-${item.dispatch_status}`}>{label(item.dispatch_status)}</span></td><td onClick={(event) => event.stopPropagation()}><details className="invoice-action-menu"><summary aria-label={`Acciones de ${item.invoice_number}`}>⋮</summary><div><button type="button" onClick={() => selectInvoice(item.id)}>Ver detalle</button><button type="button" onClick={() => void editInvoice(item.id)}>Editar</button>{item.purchase_order_id && <button type="button" onClick={() => { sessionStorage.setItem("inventario.openPurchaseOrderId", item.purchase_order_id!); window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "orders" })); }}>Ver OC</button>}<button type="button" onClick={() => { sessionStorage.setItem("inventario.movementInvoiceId", item.id); window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "movements" })); }}>Ver movimientos</button>{item.administrative_status === "confirmed" && ["pending", "partial"].includes(item.dispatch_status) && <button type="button" onClick={() => { sessionStorage.setItem("inventario.dispatchInvoiceId", item.id); window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "dispatches" })); }}>Registrar despacho</button>}<button type="button" onClick={() => { sessionStorage.setItem("inventario.deliveryInvoiceId", item.id); window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "deliveries" })); }}>Ver entrega</button><button type="button" onClick={() => void duplicateInvoice(item.id)}>Duplicar</button>{item.administrative_status !== "cancelled" && <button className="danger-text" type="button" disabled={cancelling} onClick={() => void cancelInvoiceById(item.id, item.invoice_number)}>Anular</button>}</div></details></td></tr>)}</tbody></table>{invoices.length === 0 && <div className="table-message">No se encontraron facturas con estos filtros.</div>}</div>}
          {!listError && <div className="pagination-bar"><span>{totalInvoices} facturas</span><button type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Anterior</button><span>Página {page} de {pages}</span><button type="button" disabled={page >= pages} onClick={() => setPage((value) => value + 1)}>Siguiente</button></div>}
        </section>}

        {(selectedId || detailLoading) && <aside className="invoice-detail-drawer" aria-label="Detalle de factura">
          <button className="drawer-close" type="button" aria-label="Cerrar detalle" onClick={() => { setSelectedId(null); setTrace(null); setDetailLoading(false); }}>×</button>
          {detailLoading && <div className="table-message">Armando la trazabilidad…</div>}
          {!detailLoading && trace && <>
            <header className="detail-header">
              <div><p className="eyebrow">Factura externa registrada</p><h2>{trace.invoice.number}</h2><p>{trace.invoice.customer} · {formatDate(trace.invoice.date)}</p></div>
              <div className="value-summary"><span>Valor original <strong>{formatMoney(trace.invoice.total_value)}</strong></span><span>Valor neto <strong>{formatMoney(trace.invoice.net_value)}</strong></span><div className="detail-actions"><button className="secondary-button" type="button" onClick={() => populateFromTrace(false)}>Duplicar</button>{trace.invoice.statuses.dispatch === "pending" && trace.invoice.statuses.administrative === "confirmed" && <><button className="secondary-button" type="button" onClick={() => populateFromTrace(true)}>Editar</button><button className="danger-button" type="button" disabled={cancelling} onClick={cancelInvoice}>{cancelling ? "Anulando…" : "Anular factura"}</button></>}</div></div>
            </header>
            {trace.invoice.statuses.administrative === "confirmed" && trace.invoice.statuses.delivery === "pending" && <div className="message info">Facturada · Entrega pendiente</div>}
            <div className="status-grid">
              {Object.entries(trace.invoice.statuses).map(([name, status]) => <div key={name}><span>{label(name)}</span><strong>{label(status)}</strong></div>)}
            </div>
            <section className="trace-section"><h3>Estado del inventario</h3><div className="status-grid"><div><span>Estado</span><strong>{trace.invoice.inventory.status_label}</strong></div><div><span>Cantidad descontada</span><strong>{trace.invoice.inventory.discounted_quantity}</strong></div><div><span>Fecha del descuento</span><strong>{trace.invoice.inventory.discounted_at ? new Date(trace.invoice.inventory.discounted_at).toLocaleString("es-EC") : "—"}</strong></div><div><span>Intentos</span><strong>{trace.invoice.inventory.attempts}</strong></div></div>{trace.invoice.inventory.last_error && <div className="message error">{trace.invoice.inventory.last_error}</div>}<small>{trace.invoice.inventory.movement_ids.length ? `Movimientos: ${trace.invoice.inventory.movement_ids.join(", ")}` : "Sin movimiento de inventario asociado"}</small></section>
            <section className="trace-section po-summary"><span>Orden de compra vinculada</span><strong>{trace.purchase_order?.number ?? "Factura sin OC"}</strong><small>{trace.purchase_order?.chain ?? "Categoría de excepción"}</small></section>
            <section className="trace-section"><h3>Comparación OC → factura → despacho</h3><div className="table-scroll"><table><thead><tr><th>Producto</th><th>OC</th><th>Facturado</th><th>Despachado</th><th>Faltante</th><th>Pendiente</th></tr></thead><tbody>{trace.lines.map((line) => <tr className={line.outside_purchase_order ? "row-warning" : ""} key={line.sku}><td><ProductIdentity name={line.product_name} sku={line.sku} /></td><td>{line.ordered ?? "—"}</td><td>{line.invoiced}</td><td>{line.dispatched}</td><td>{line.missing}</td><td><strong>{line.pending_dispatch}</strong></td></tr>)}</tbody></table></div></section>
            <section className="trace-section"><h3>Factura → entrega</h3><div className="table-scroll"><table><thead><tr><th>Producto</th><th>Facturado</th><th>Entregado</th><th>Pendiente de confirmar</th><th>Diferencia</th></tr></thead><tbody>{trace.lines.map((line) => <tr key={line.sku}><td><ProductIdentity name={line.product_name} sku={line.sku} /></td><td>{line.invoiced}</td><td>{line.delivered}</td><td>{line.pending_confirmation}</td><td>{line.delivery_difference > 0 ? `+${line.delivery_difference}` : line.delivery_difference}</td></tr>)}</tbody></table></div></section>
            {(trace.alerts.length > 0 || trace.incidents.length > 0) && <section className="trace-section"><h3>Novedades e incidencias</h3><div className="event-list">{trace.alerts.map((item) => <article key={item.id}><strong>{label(item.alert_type)}</strong><p>{item.description}</p><span>{item.is_resolved ? "Resuelta" : "Pendiente"}</span></article>)}{trace.incidents.map((item) => <article key={item.id}><strong>{label(item.incident_type)}</strong><p>{item.description}</p><span>{label(item.status)}{item.affected_quantity ? ` · ${item.affected_quantity} unidades` : ""}</span>{item.decision && <small>Decisión: {item.decision}</small>}</article>)}</div></section>}
            {trace.deliveries.length > 0 && <section className="trace-section"><h3>Entregas al cliente</h3><div className="event-list">{trace.deliveries.map((item) => <article key={item.id}><strong>{label(item.delivery_type)}</strong><p>{formatDate(item.delivered_at)} · {item.recipient ?? "Receptor no indicado"}</p>{item.notes && <small>{item.notes}</small>}</article>)}</div></section>}
            {(trace.returns.length > 0 || trace.adjustments.length > 0) && <section className="trace-section"><h3>Devoluciones y documentos relacionados</h3><div className="event-list">{trace.returns.map((item) => <article key={item.id}><strong>Devolución · {formatDate(item.returned_at)}</strong><p>{item.reason}</p><span>{item.lines.map((line) => `${line.sku}: ${line.quantity} (${label(line.disposition)})`).join(" · ")}</span></article>)}{trace.adjustments.map((item) => <article key={item.id}><strong>{label(item.document_type)} {item.document_number}</strong><p>{item.reason}</p><span>{formatDate(item.document_date)} · {formatMoney(item.value)}</span></article>)}</div></section>}
          </>}
        </aside>}
      </section>}
    </main>
  );
}
