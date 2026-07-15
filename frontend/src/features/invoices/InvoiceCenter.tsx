import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";
import { ProductIdentity } from "../inventory/ProductIdentity";
import { InvoiceRegistrationForm } from "./InvoiceRegistrationForm";

interface InvoiceSummary {
  id: string;
  invoice_number: string;
  invoice_date: string;
  customer_name: string;
  chain_name: string | null;
  total_value: string | null;
  administrative_status: string;
  dispatch_status: string;
  delivery_status: string;
  incident_status: string;
}

interface Traceability {
  invoice: {
    number: string;
    date: string;
    customer: string;
    total_value: string | null;
    net_value: string | number;
    statuses: Record<string, string>;
  };
  purchase_order: { number: string; chain: string } | null;
  lines: Array<{
    sku: string;
    product_name: string;
    ordered: number | null;
    invoiced: number;
    dispatched: number;
    missing: number;
    pending_dispatch: number;
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
  debit_note: "Nota de débito", without_issue: "Sin novedad", with_issue: "Con novedad",
};

const label = (value: string) => labels[value] ?? value.replaceAll("_", " ");
const formatDate = (value: string) => new Intl.DateTimeFormat("es-EC", { dateStyle: "medium" }).format(new Date(`${value.slice(0, 10)}T12:00:00`));
const formatMoney = (value: string | number | null) => value == null ? "—" : new Intl.NumberFormat("es-EC", { style: "currency", currency: "USD" }).format(Number(value));

export function InvoiceCenter() {
  const [invoices, setInvoices] = useState<InvoiceSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [trace, setTrace] = useState<Traceability | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  useEffect(() => {
    apiRequest<InvoiceSummary[]>("/invoices")
      .then((data) => { setInvoices(data); setSelectedId(data[0]?.id ?? null); if (data.length === 0) setDetailLoading(false); })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No pudimos cargar las facturas."))
      .finally(() => setLoading(false));
  }, []);

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

  const visible = useMemo(() => {
    const term = search.trim().toLocaleLowerCase("es-EC");
    return invoices.filter((item) => !term || [item.invoice_number, item.customer_name, item.chain_name ?? ""].some((value) => value.toLocaleLowerCase("es-EC").includes(term)));
  }, [invoices, search]);

  const invoiceCreated = async (id: string) => {
    const refreshed = await apiRequest<InvoiceSummary[]>("/invoices");
    setInvoices(refreshed);
    setShowForm(false);
    selectInvoice(id);
  };

  return (
    <main className="dashboard invoice-center">
      <section className="module-heading">
        <div className="welcome-block"><p className="eyebrow">Trazabilidad documental y operativa</p><h1>Centro de Facturas</h1><p>Aquí no se factura: se verifica qué ocurrió desde la OC hasta la entrega, incluyendo diferencias, incidencias y devoluciones.</p></div>
        <button className="primary-button" type="button" onClick={() => { setShowForm((value) => !value); setError(null); }}>{showForm ? "Volver al centro" : "Registrar factura"}</button>
      </section>

      {error && <div className="message error" role="alert">{error}</div>}
      {showForm ? <InvoiceRegistrationForm onCreated={invoiceCreated} onCancel={() => setShowForm(false)} /> : <section className="invoice-workspace">
        <aside className="invoice-list" aria-label="Facturas registradas">
          <label className="search-field invoice-search"><span>Buscar factura</span><input type="search" placeholder="Número, cliente o cadena" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
          {loading && <div className="table-message">Cargando facturas…</div>}
          {!loading && visible.map((item) => (
            <button type="button" key={item.id} className={`invoice-list-item ${selectedId === item.id ? "selected" : ""}`} onClick={() => selectInvoice(item.id)}>
              <span><strong>{item.invoice_number}</strong><small>{formatDate(item.invoice_date)}</small></span>
              <span>{item.customer_name}</span>
              <small>{item.chain_name ?? "Sin cadena"} · {label(item.dispatch_status)}</small>
            </button>
          ))}
          {!loading && visible.length === 0 && <div className="table-message">No encontramos facturas.</div>}
        </aside>

        <div className="invoice-detail">
          {detailLoading && <div className="table-message">Armando la trazabilidad…</div>}
          {!detailLoading && !trace && <div className="empty-detail"><strong>Selecciona una factura</strong><span>Verás su OC, productos, despacho, entrega y novedades.</span></div>}
          {!detailLoading && trace && <>
            <header className="detail-header">
              <div><p className="eyebrow">Factura externa registrada</p><h2>{trace.invoice.number}</h2><p>{trace.invoice.customer} · {formatDate(trace.invoice.date)}</p></div>
              <div className="value-summary"><span>Valor original <strong>{formatMoney(trace.invoice.total_value)}</strong></span><span>Valor neto <strong>{formatMoney(trace.invoice.net_value)}</strong></span></div>
            </header>
            <div className="status-grid">
              {Object.entries(trace.invoice.statuses).map(([name, status]) => <div key={name}><span>{label(name)}</span><strong>{label(status)}</strong></div>)}
            </div>
            <section className="trace-section po-summary"><span>Orden de compra vinculada</span><strong>{trace.purchase_order?.number ?? "Factura sin OC"}</strong><small>{trace.purchase_order?.chain ?? "Categoría de excepción"}</small></section>
            <section className="trace-section"><h3>Comparación OC → factura → despacho</h3><div className="table-scroll"><table><thead><tr><th>Producto</th><th>OC</th><th>Facturado</th><th>Despachado</th><th>Faltante</th><th>Pendiente</th></tr></thead><tbody>{trace.lines.map((line) => <tr className={line.outside_purchase_order ? "row-warning" : ""} key={line.sku}><td><ProductIdentity name={line.product_name} sku={line.sku} /></td><td>{line.ordered ?? "—"}</td><td>{line.invoiced}</td><td>{line.dispatched}</td><td>{line.missing}</td><td><strong>{line.pending_dispatch}</strong></td></tr>)}</tbody></table></div></section>
            {(trace.alerts.length > 0 || trace.incidents.length > 0) && <section className="trace-section"><h3>Novedades e incidencias</h3><div className="event-list">{trace.alerts.map((item) => <article key={item.id}><strong>{label(item.alert_type)}</strong><p>{item.description}</p><span>{item.is_resolved ? "Resuelta" : "Pendiente"}</span></article>)}{trace.incidents.map((item) => <article key={item.id}><strong>{label(item.incident_type)}</strong><p>{item.description}</p><span>{label(item.status)}{item.affected_quantity ? ` · ${item.affected_quantity} unidades` : ""}</span>{item.decision && <small>Decisión: {item.decision}</small>}</article>)}</div></section>}
            {trace.deliveries.length > 0 && <section className="trace-section"><h3>Entregas al cliente</h3><div className="event-list">{trace.deliveries.map((item) => <article key={item.id}><strong>{label(item.delivery_type)}</strong><p>{formatDate(item.delivered_at)} · {item.recipient ?? "Receptor no indicado"}</p>{item.notes && <small>{item.notes}</small>}</article>)}</div></section>}
            {(trace.returns.length > 0 || trace.adjustments.length > 0) && <section className="trace-section"><h3>Devoluciones y documentos relacionados</h3><div className="event-list">{trace.returns.map((item) => <article key={item.id}><strong>Devolución · {formatDate(item.returned_at)}</strong><p>{item.reason}</p><span>{item.lines.map((line) => `${line.sku}: ${line.quantity} (${label(line.disposition)})`).join(" · ")}</span></article>)}{trace.adjustments.map((item) => <article key={item.id}><strong>{label(item.document_type)} {item.document_number}</strong><p>{item.reason}</p><span>{formatDate(item.document_date)} · {formatMoney(item.value)}</span></article>)}</div></section>}
          </>}
        </div>
      </section>}
    </main>
  );
}
