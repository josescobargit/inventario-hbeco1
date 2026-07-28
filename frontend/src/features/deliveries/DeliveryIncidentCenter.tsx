import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";
import { ProductIdentity } from "../inventory/ProductIdentity";

interface Invoice { id: string; invoice_number: string; customer_name: string; chain_name: string | null; dispatch_status: string; delivery_status: string }
interface Trace { invoice: { number: string; customer: string }; purchase_order: { number: string; chain: string } | null; lines: Array<{ sku: string; product_name: string; dispatched: number; delivered: number; rejected_delivery: number; pending_delivery: number; pending_dispatch: number }>; deliveries: Array<{ id: string; delivery_type: string; delivered_at: string; recipient: string | null; notes: string | null }> }
interface Incident { id: string; incident_type: string; invoice_number: string | null; sku: string | null; product_name: string | null; affected_quantity: number | null; description: string; status: string; decision: string | null; created_at: string; can_resolve_inventory: boolean }
interface DeliveryDraftLine { sku: string; delivered_quantity: number; rejected_quantity: number; notes: string }

const typeLabels: Record<string, string> = { without_issue: "Entregado sin novedad", confirmed: "Entrega confirmada", with_issue: "Entregado con novedad", missing_stock: "Faltante en despacho", delivery_issue: "Novedad de entrega", product_outside_purchase_order: "Producto fuera de OC", returned_product_review: "Devolución en revisión" };
const decisionLabels: Record<string, string> = { found_available: "Producto encontrado y disponible", retry_dispatch: "Reintentar despacho", confirm_physical_shortage: "Confirmar faltante físico" };
export function DeliveryIncidentCenter() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [deliveryType, setDeliveryType] = useState("without_issue");
  const [deliveryLines, setDeliveryLines] = useState<DeliveryDraftLine[]>([]);
  const [deliveryDate, setDeliveryDate] = useState(() => new Date().toLocaleDateString("en-CA"));
  const [recipient, setRecipient] = useState("");
  const [notes, setNotes] = useState("");
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [decision, setDecision] = useState("found_available");
  const [resolutionReason, setResolutionReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const refresh = async () => {
    const [loadedInvoices, loadedIncidents] = await Promise.all([apiRequest<Invoice[]>("/invoices"), apiRequest<Incident[]>("/incidents")]);
    setInvoices(loadedInvoices); setIncidents(loadedIncidents);
    return loadedInvoices;
  };

  useEffect(() => {
    Promise.all([apiRequest<Invoice[]>("/invoices"), apiRequest<Incident[]>("/incidents")]).then(([loadedInvoices, loadedIncidents]) => {
      setInvoices(loadedInvoices); setIncidents(loadedIncidents);
      setSelectedId(loadedInvoices.find((item) => item.dispatch_status !== "pending" && item.delivery_status === "pending")?.id ?? null);
    }).catch((caught) => setError(caught instanceof Error ? caught.message : "No pudimos cargar entregas e incidencias."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    apiRequest<Trace>(`/invoices/${selectedId}/traceability`).then((data) => {
      if (active) {
        setTrace(data);
        setDeliveryLines(data.lines.filter((line) => line.pending_delivery > 0).map((line) => ({ sku: line.sku, delivered_quantity: line.pending_delivery, rejected_quantity: 0, notes: "" })));
      }
    })
      .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "No pudimos cargar la entrega."); });
    return () => { active = false; };
  }, [selectedId]);

  const deliverable = useMemo(() => invoices.filter((item) => item.dispatch_status !== "pending" && (item.delivery_status === "pending" || item.delivery_status === "partial_delivery")), [invoices]);
  const selected = deliverable.find((item) => item.id === selectedId) ?? null;
  const openIncidents = incidents.filter((item) => item.status === "open" || item.status === "in_review");

  const updateDeliveryLine = (sku: string, patch: Partial<DeliveryDraftLine>) => setDeliveryLines((current) => current.map((line) => line.sku === sku ? { ...line, ...patch } : line));
  const invalidDeliveryLines = deliveryLines.length === 0 || deliveryLines.some((line) => {
    const source = trace?.lines.find((item) => item.sku === line.sku);
    const reported = line.delivered_quantity + line.rejected_quantity;
    return reported <= 0 || reported > (source?.pending_delivery ?? 0) || line.delivered_quantity < 0 || line.rejected_quantity < 0 || (line.rejected_quantity > 0 && line.notes.trim().length < 3);
  });
  const hasRejected = deliveryLines.some((line) => line.rejected_quantity > 0);

  const registerDelivery = async () => {
    if (!selectedId) return;
    setSaving(true); setError(null); setSuccess(null);
    try {
      const result = await apiRequest<{ invoice_number: string }>("/deliveries", { method: "POST", body: JSON.stringify({ invoice_id: selectedId, delivered_at: new Date(`${deliveryDate}T12:00:00`).toISOString(), delivery_type: deliveryType, recipient: recipient || null, notes: notes || null, lines: deliveryLines.map((line) => ({ ...line, notes: line.notes || null })) }) });
      const refreshed = await refresh();
      setSuccess(`${result.invoice_number} quedó marcada como entregada al cliente.`); setRecipient(""); setNotes(""); setTrace(null); setDeliveryLines([]);
      setSelectedId(refreshed.find((item) => item.dispatch_status !== "pending" && (item.delivery_status === "pending" || item.delivery_status === "partial_delivery"))?.id ?? null);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No pudimos registrar la entrega."); }
    finally { setSaving(false); }
  };

  const resolve = async (incidentId: string) => {
    setSaving(true); setError(null); setSuccess(null);
    try {
      await apiRequest(`/incidents/${incidentId}/resolve`, { method: "POST", body: JSON.stringify({ decision, reason: resolutionReason }) });
      await refresh(); setResolvingId(null); setResolutionReason(""); setSuccess("La incidencia fue resuelta y el inventario quedó actualizado.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No pudimos resolver la incidencia."); }
    finally { setSaving(false); }
  };

  return <main className="dashboard delivery-center">
    <section className="welcome-block"><p className="eyebrow">Cierre operativo y novedades</p><h1>Entregas e Incidencias</h1><p>Entregado significa recibido por el cliente —normalmente su centro de distribución—, no solamente que salió de nuestra bodega.</p></section>
    {error && <div className="message error" role="alert">{error}</div>}{success && <div className="message success">{success}</div>}
    <div className="delivery-layout">
      <section className="delivery-panel"><div className="panel-title"><div><h2>Confirmar entrega</h2><p>Facturas con al menos una salida registrada.</p></div><span>{deliverable.length}</span></div>
        {loading && <div className="table-message">Cargando entregas…</div>}
        {!loading && deliverable.length === 0 && <div className="empty-detail compact"><strong>No hay entregas pendientes</strong><span>Primero confirma la salida en Despachos.</span></div>}
        {deliverable.length > 0 && <><label className="full-field"><span>Factura</span><select value={selectedId ?? ""} onChange={(event) => { setSelectedId(event.target.value); setTrace(null); }}><option value="">Selecciona</option>{deliverable.map((item) => <option key={item.id} value={item.id}>{item.invoice_number} · {item.customer_name}</option>)}</select></label>
          {selected && trace && <div className="delivery-summary"><strong>{selected.invoice_number}</strong><span>{selected.customer_name} · {trace.purchase_order?.chain ?? "Sin cadena"}</span><small>{trace.lines.reduce((sum, line) => sum + line.pending_delivery, 0)} unidades pendientes de recibir</small></div>}
          {trace && <div className="delivery-line-list"><h3>Productos recibidos por el cliente</h3>{trace.lines.filter((line) => line.pending_delivery > 0).map((line) => { const draft = deliveryLines.find((item) => item.sku === line.sku); const reported = (draft?.delivered_quantity ?? 0) + (draft?.rejected_quantity ?? 0); const exceeds = reported > line.pending_delivery; return <article className={exceeds ? "has-error" : ""} key={line.sku}><div><ProductIdentity name={line.product_name} sku={line.sku} /><small className="product-metrics">Despachado: {line.dispatched} · Ya recibido: {line.delivered} · Pendiente: {line.pending_delivery}</small></div><label><span>Recibido</span><input type="number" min={0} max={line.pending_delivery} value={draft?.delivered_quantity ?? 0} onChange={(event) => updateDeliveryLine(line.sku, { delivered_quantity: Number(event.target.value) })} /></label><label><span>Rechazado</span><input type="number" min={0} max={line.pending_delivery} value={draft?.rejected_quantity ?? 0} onChange={(event) => updateDeliveryLine(line.sku, { rejected_quantity: Number(event.target.value), notes: Number(event.target.value) > 0 ? draft?.notes ?? "" : "" })} /></label>{(draft?.rejected_quantity ?? 0) > 0 && <label className="delivery-line-note"><span>Motivo del rechazo *</span><input value={draft?.notes ?? ""} onChange={(event) => updateDeliveryLine(line.sku, { notes: event.target.value })} /></label>}{exceeds && <small className="validation-note">No puedes recibir/rechazar más de lo pendiente.</small>}</article>; })}</div>}
          <div className="delivery-type-grid">{Object.entries({ without_issue: "Sin novedad", confirmed: "Confirmada", with_issue: "Con novedad" }).map(([value, label]) => <button className={deliveryType === value ? "selected" : ""} type="button" key={value} onClick={() => setDeliveryType(value)}>{label}</button>)}</div>
          <label className="full-field"><span>Fecha de entrega *</span><input type="date" required value={deliveryDate} onChange={(event) => setDeliveryDate(event.target.value)} /></label>
          <label className="full-field"><span>Recibido por</span><input value={recipient} onChange={(event) => setRecipient(event.target.value)} placeholder="Persona o área receptora" /></label>
          <label className="full-field"><span>{deliveryType === "with_issue" ? "Describe la novedad *" : "Observaciones"}</span><textarea required={deliveryType === "with_issue"} rows={4} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
          <button className="primary-button full-action" type="button" disabled={saving || !selectedId || !deliveryDate || invalidDeliveryLines || ((deliveryType === "with_issue" || hasRejected) && notes.trim().length === 0)} onClick={registerDelivery}>{saving ? "Confirmando…" : "Registrar recepción del cliente"}</button>
        </>}
      </section>

      <section className="incident-panel"><div className="panel-title"><div><h2>Incidencias abiertas</h2><p>Decisiones pendientes y saldos bloqueados.</p></div><span>{openIncidents.length}</span></div>
        {openIncidents.length === 0 && <div className="empty-detail compact"><strong>Sin incidencias abiertas</strong><span>Las novedades de despacho y entrega aparecerán aquí.</span></div>}
        <div className="incident-list">{openIncidents.map((item) => <article key={item.id}><header><div><strong>{typeLabels[item.incident_type] ?? item.incident_type.replaceAll("_", " ")}</strong><span>{item.invoice_number ? `Factura ${item.invoice_number}` : "Sin factura"}{item.sku ? ` · ${item.sku}` : ""}</span></div><span className="status-pill low_stock">Abierta</span></header><p>{item.description}</p>{item.affected_quantity && <small>{item.affected_quantity} unidades afectadas</small>}
          {item.can_resolve_inventory && resolvingId !== item.id && <button className="secondary-button" type="button" onClick={() => { setResolvingId(item.id); setResolutionReason(""); }}>Resolver incidencia</button>}
          {resolvingId === item.id && <div className="resolution-form"><label><span>Decisión</span><select value={decision} onChange={(event) => setDecision(event.target.value)}>{Object.entries(decisionLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><label><span>Explicación *</span><textarea rows={3} minLength={5} value={resolutionReason} onChange={(event) => setResolutionReason(event.target.value)} /></label><div><button className="secondary-button" type="button" onClick={() => setResolvingId(null)}>Cancelar</button><button className="primary-button" type="button" disabled={saving || resolutionReason.trim().length < 5} onClick={() => resolve(item.id)}>Aplicar decisión</button></div></div>}
          {!item.can_resolve_inventory && <small>Requiere seguimiento administrativo; su resolución operativa se incorporará en una siguiente etapa.</small>}
        </article>)}</div>
      </section>
    </div>
  </main>;
}
