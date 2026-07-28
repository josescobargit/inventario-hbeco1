import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";
import { ProductIdentity } from "../inventory/ProductIdentity";

interface Invoice { id: string; invoice_number: string; customer_name: string; dispatch_status: string; return_status: string; total_value: string | null }
interface TraceLine { sku: string; product_name: string; dispatched: number; returned: number; returnable: number }
interface Trace {
  invoice: { number: string; customer: string; total_value: string | null; net_value: string | number; statuses: Record<string, string> };
  lines: TraceLine[];
  deliveries: Array<{ id: string; delivered_at: string; recipient: string | null }>;
  returns: Array<{ id: string; reason: string; returned_at: string; lines: Array<{ sku: string; quantity: number; disposition: string }> }>;
  adjustments: Array<{ id: string; document_type: string; document_number: string; document_date: string; value: string; reason: string }>;
}
interface ReturnDraft { sku: string; quantity: number; disposition: string; notes: string }

const dispositions: Record<string, string> = {
  available_warehouse: "Disponible en bodega", available_floor: "Disponible en piso",
  blocked: "Bloqueado", damaged: "Dañado", in_review: "En revisión", unusable: "No utilizable",
};
const money = (value: string | number | null) => value == null ? "—" : new Intl.NumberFormat("es-EC", { style: "currency", currency: "USD" }).format(Number(value));
const dateLabel = (value: string) => new Intl.DateTimeFormat("es-EC", { dateStyle: "medium" }).format(new Date(`${value.slice(0, 10)}T12:00:00`));

export function PostSaleCenter() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [drafts, setDrafts] = useState<ReturnDraft[]>([]);
  const [returnReason, setReturnReason] = useState("");
  const [deliveryId, setDeliveryId] = useState("");
  const [documentType, setDocumentType] = useState("credit_note");
  const [documentNumber, setDocumentNumber] = useState("");
  const [documentDate, setDocumentDate] = useState("");
  const [documentValue, setDocumentValue] = useState("");
  const [documentReason, setDocumentReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    apiRequest<Invoice[]>("/invoices").then((data) => {
      const eligible = data.filter((item) => item.dispatch_status !== "pending"); setInvoices(eligible); setSelectedId(eligible[0]?.id ?? null);
    }).catch((caught) => setError(caught instanceof Error ? caught.message : "No pudimos cargar las facturas."))
      .finally(() => setLoading(false));
  }, []);

  const loadTrace = async (id: string) => {
    const data = await apiRequest<Trace>(`/invoices/${id}/traceability`); setTrace(data);
    setDeliveryId(data.deliveries.at(-1)?.id ?? "");
    setDrafts(data.lines.filter((line) => line.returnable > 0).map((line) => ({ sku: line.sku, quantity: 0, disposition: "available_warehouse", notes: "" })));
    return data;
  };

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    apiRequest<Trace>(`/invoices/${selectedId}/traceability`).then((data) => { if (active) { setTrace(data); setDeliveryId(data.deliveries.at(-1)?.id ?? ""); setDrafts(data.lines.filter((line) => line.returnable > 0).map((line) => ({ sku: line.sku, quantity: 0, disposition: "available_warehouse", notes: "" }))); } })
      .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "No pudimos cargar la trazabilidad."); });
    return () => { active = false; };
  }, [selectedId]);

  const selected = useMemo(() => invoices.find((item) => item.id === selectedId) ?? null, [invoices, selectedId]);
  const updateDraft = (index: number, patch: Partial<ReturnDraft>) => setDrafts((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  const returnUnits = drafts.reduce((sum, item) => sum + item.quantity, 0);

  const registerReturn = async () => {
    if (!selectedId) return;
    setSaving(true); setError(null); setSuccess(null);
    try {
      await apiRequest("/returns", { method: "POST", body: JSON.stringify({ invoice_id: selectedId, delivery_id: deliveryId || null, reason: returnReason, lines: drafts.filter((line) => line.quantity > 0) }) });
      await loadTrace(selectedId); setReturnReason(""); setSuccess("Devolución registrada; el inventario y sus bloqueos fueron actualizados.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No pudimos registrar la devolución."); }
    finally { setSaving(false); }
  };

  const registerDocument = async () => {
    if (!selectedId) return;
    setSaving(true); setError(null); setSuccess(null);
    try {
      await apiRequest(`/invoices/${selectedId}/adjustments`, { method: "POST", body: JSON.stringify({ document_type: documentType, document_number: documentNumber, document_date: documentDate, value: Number(documentValue), reason: documentReason }) });
      await loadTrace(selectedId); setDocumentNumber(""); setDocumentDate(""); setDocumentValue(""); setDocumentReason(""); setSuccess("Documento relacionado registrado y valor neto recalculado.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No pudimos registrar el documento."); }
    finally { setSaving(false); }
  };

  return <main className="dashboard post-sale-center">
    <section className="welcome-block"><p className="eyebrow">Trazabilidad posterior a la entrega</p><h1>Devoluciones y Notas</h1><p>Registra lo que regresa físicamente y los documentos emitidos fuera del sistema. Una nota de crédito o débito no cambia el stock.</p></section>
    {error && <div className="message error" role="alert">{error}</div>}{success && <div className="message success">{success}</div>}
    <label className="post-sale-invoice"><span>Factura original</span><select value={selectedId ?? ""} onChange={(event) => { setSelectedId(event.target.value); setTrace(null); setSuccess(null); }}><option value="">Selecciona una factura despachada</option>{invoices.map((item) => <option key={item.id} value={item.id}>{item.invoice_number} · {item.customer_name}</option>)}</select></label>
    {loading && <div className="table-message">Cargando facturas…</div>}
    {!loading && invoices.length === 0 && <div className="empty-detail"><strong>No hay facturas despachadas</strong><span>Las devoluciones sólo pueden registrarse después de una salida física.</span></div>}
    {selected && !trace && <div className="table-message">Preparando historial postventa…</div>}
    {selected && trace && <><section className="post-sale-summary"><div><span>Factura</span><strong>{trace.invoice.number}</strong></div><div><span>Cliente</span><strong>{trace.invoice.customer}</strong></div><div><span>Valor original</span><strong>{money(trace.invoice.total_value)}</strong></div><div><span>Valor neto</span><strong>{money(trace.invoice.net_value)}</strong></div></section>
      <div className="post-sale-grid">
        <section className="post-sale-panel"><h2>Registrar devolución física</h2><p>Solo puedes devolver unidades previamente despachadas.</p>
          {trace.deliveries.length > 0 && <label className="full-field"><span>Entrega relacionada</span><select value={deliveryId} onChange={(event) => setDeliveryId(event.target.value)}><option value="">Sin entrega específica</option>{trace.deliveries.map((delivery) => <option key={delivery.id} value={delivery.id}>{dateLabel(delivery.delivered_at)} · {delivery.recipient ?? "Sin receptor"}</option>)}</select></label>}
          <div className="return-lines">{drafts.map((draft, index) => { const source = trace.lines.find((line) => line.sku === draft.sku)!; return <article className={draft.quantity > 0 && !["available_warehouse", "available_floor"].includes(draft.disposition) ? "has-difference" : ""} key={draft.sku}><header><ProductIdentity name={source.product_name} sku={draft.sku} /><small>Máximo: {source.returnable}</small></header><div><label><span>Cantidad</span><input type="number" min={0} max={source.returnable} value={draft.quantity} onChange={(event) => updateDraft(index, { quantity: Number(event.target.value) })} /></label><label><span>Destino del producto</span><select value={draft.disposition} onChange={(event) => updateDraft(index, { disposition: event.target.value })}>{Object.entries(dispositions).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label></div>{draft.quantity > 0 && !["available_warehouse", "available_floor"].includes(draft.disposition) && <label><span>Detalle de revisión o daño</span><input value={draft.notes} onChange={(event) => updateDraft(index, { notes: event.target.value })} placeholder="Abrirá una incidencia" /></label>}</article>; })}</div>
          {drafts.length === 0 && <div className="table-message">No quedan unidades susceptibles de devolución.</div>}
          <label className="full-field"><span>Motivo general *</span><textarea rows={3} minLength={5} value={returnReason} onChange={(event) => setReturnReason(event.target.value)} /></label>
          <button className="primary-button full-action" type="button" disabled={saving || returnUnits <= 0 || returnReason.trim().length < 5 || drafts.some((item) => item.quantity < 0 || item.quantity > (trace.lines.find((line) => line.sku === item.sku)?.returnable ?? 0))} onClick={registerReturn}>Registrar devolución de {returnUnits} unidades</button>
        </section>

        <section className="post-sale-panel"><h2>Registrar nota relacionada</h2><p>La nota ya fue emitida externamente; aquí conservamos su efecto económico.</p>
          <div className="document-type-grid"><button className={documentType === "credit_note" ? "selected" : ""} type="button" onClick={() => setDocumentType("credit_note")}>Nota de crédito</button><button className={documentType === "debit_note" ? "selected" : ""} type="button" onClick={() => setDocumentType("debit_note")}>Nota de débito</button></div>
          <label className="full-field"><span>Número del documento *</span><input value={documentNumber} onChange={(event) => setDocumentNumber(event.target.value)} /></label><label className="full-field"><span>Fecha *</span><input type="date" value={documentDate} onChange={(event) => setDocumentDate(event.target.value)} /></label><label className="full-field"><span>Valor *</span><input type="number" min={0} step="0.01" value={documentValue} onChange={(event) => setDocumentValue(event.target.value)} /></label><label className="full-field"><span>Motivo *</span><textarea minLength={5} rows={3} value={documentReason} onChange={(event) => setDocumentReason(event.target.value)} /></label>
          <button className="primary-button full-action" type="button" disabled={saving || !documentNumber || !documentDate || documentValue === "" || documentReason.trim().length < 5} onClick={registerDocument}>Registrar documento externo</button>
          <div className="related-history"><h3>Historial documental</h3>{trace.adjustments.length === 0 ? <p>Sin notas registradas.</p> : trace.adjustments.map((item) => <article key={item.id}><strong>{item.document_type === "credit_note" ? "NC" : "ND"} {item.document_number}</strong><span>{dateLabel(item.document_date)} · {money(item.value)}</span><small>{item.reason}</small></article>)}</div>
        </section>
      </div>
      {trace.returns.length > 0 && <section className="return-history"><h2>Historial de devoluciones</h2>{trace.returns.map((item) => <article key={item.id}><strong>{dateLabel(item.returned_at)} · {item.reason}</strong><span>{item.lines.map((line) => `${line.sku}: ${line.quantity} (${dispositions[line.disposition]})`).join(" · ")}</span></article>)}</section>}
    </>}
  </main>;
}
