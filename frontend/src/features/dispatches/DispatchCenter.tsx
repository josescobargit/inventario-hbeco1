import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";

interface PendingInvoice { id: string; invoice_number: string; customer_name: string; dispatch_status: string }
interface TraceLine { sku: string; product_name: string; invoiced: number; dispatched: number; missing: number; pending_dispatch: number }
interface Trace { invoice: { number: string; customer: string; statuses: Record<string, string> }; purchase_order: { number: string; chain: string } | null; lines: TraceLine[] }
interface DispatchLine { sku: string; dispatched_quantity: number; missing_quantity: number; missing_reason: string }

const emptyReports = (trace: Trace): DispatchLine[] => trace.lines.filter((line) => line.pending_dispatch > 0).map((line) => ({ sku: line.sku, dispatched_quantity: line.pending_dispatch, missing_quantity: 0, missing_reason: "" }));

export function DispatchCenter() {
  const [pending, setPending] = useState<PendingInvoice[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [reports, setReports] = useState<DispatchLine[]>([]);
  const [responsible, setResponsible] = useState("");
  const [dispatchDate, setDispatchDate] = useState("");
  const [guideNumber, setGuideNumber] = useState("");
  const [recipient, setRecipient] = useState("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const loadPending = async () => {
    const data = await apiRequest<PendingInvoice[]>("/dispatches/pending");
    setPending(data);
    return data;
  };

  useEffect(() => {
    apiRequest<PendingInvoice[]>("/dispatches/pending").then((data) => {
      const requestedId = sessionStorage.getItem("inventario.dispatchInvoiceId");
      sessionStorage.removeItem("inventario.dispatchInvoiceId");
      setPending(data);
      setSelectedId(data.find((item) => item.id === requestedId)?.id ?? data[0]?.id ?? null);
    })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No pudimos cargar los despachos pendientes."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    apiRequest<Trace>(`/invoices/${selectedId}/traceability`).then((data) => {
      if (active) { setTrace(data); setReports(emptyReports(data)); }
    }).catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "No pudimos cargar la factura."); });
    return () => { active = false; };
  }, [selectedId]);

  const selected = useMemo(() => pending.find((item) => item.id === selectedId) ?? null, [pending, selectedId]);
  const update = (index: number, patch: Partial<DispatchLine>) => setReports((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, ...patch } : line));
  const reportTotal = reports.reduce((sum, line) => sum + line.dispatched_quantity + line.missing_quantity, 0);

  const confirm = async () => {
    if (!selectedId) return;
    setSaving(true); setError(null); setSuccess(null);
    try {
      const result = await apiRequest<{ invoice_number: string; dispatch_status: string }>("/dispatches", { method: "POST", body: JSON.stringify({ invoice_id: selectedId, dispatched_at: dispatchDate ? new Date(dispatchDate).toISOString() : null, guide_number: guideNumber || null, responsible_name: responsible, recipient: recipient || null, notes: notes || null, lines: reports }) });
      const refreshed = await loadPending();
      setSuccess(`Despacho de ${result.invoice_number} registrado como ${result.dispatch_status === "complete" ? "completo" : "parcial"}.`);
      setResponsible(""); setDispatchDate(""); setGuideNumber(""); setRecipient(""); setNotes(""); setTrace(null);
      setSelectedId(refreshed.find((item) => item.id === selectedId)?.id ?? refreshed[0]?.id ?? null);
      if (refreshed.some((item) => item.id === selectedId)) {
        const updatedTrace = await apiRequest<Trace>(`/invoices/${selectedId}/traceability`); setTrace(updatedTrace); setReports(emptyReports(updatedTrace));
      }
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No pudimos confirmar el despacho."); }
    finally { setSaving(false); }
  };

  return <main className="dashboard dispatch-center">
    <section className="welcome-block"><p className="eyebrow">Seguimiento operativo</p><h1>Despachos</h1><p>Registra la salida asociada a la factura. El inventario ya fue descontado al confirmar la factura y no se afecta nuevamente aquí.</p></section>
    {error && <div className="message error" role="alert">{error}</div>}{success && <div className="message success">{success}</div>}
    <section className="order-workspace dispatch-workspace">
      <aside className="order-list"><div className="list-title"><strong>Facturas pendientes</strong><span>{pending.length}</span></div>
        {loading && <div className="table-message">Cargando pendientes…</div>}
        {!loading && pending.map((item) => <button type="button" key={item.id} className={`order-list-item ${selectedId === item.id ? "selected" : ""}`} onClick={() => { setSelectedId(item.id); setSuccess(null); }}><strong>{item.invoice_number}</strong><span>{item.customer_name}</span><small>{item.dispatch_status === "partial" ? "Despacho parcial" : "Pendiente de despacho"}</small></button>)}
        {!loading && pending.length === 0 && <div className="table-message">No hay facturas pendientes de despacho.</div>}
      </aside>
      <div className="order-detail">{!selected && !loading && <div className="empty-detail"><strong>Todo está despachado</strong><span>Las facturas nuevas aparecerán aquí automáticamente.</span></div>}
        {selected && !trace && <div className="table-message">Preparando cantidades pendientes…</div>}
        {selected && trace && <><header className="detail-header"><div><p className="eyebrow">{trace.purchase_order ? `OC ${trace.purchase_order.number} · ${trace.purchase_order.chain}` : "Factura excepcional"}</p><h2>{trace.invoice.number}</h2><p>{trace.invoice.customer}</p></div><span className="status-pill low_stock">{selected.dispatch_status === "partial" ? "Parcial" : "Pendiente"}</span></header>
          <div className="dispatch-fields"><label><span>Fecha del despacho</span><input type="datetime-local" value={dispatchDate} onChange={(event) => setDispatchDate(event.target.value)} /></label><label><span>Número de guía</span><input value={guideNumber} onChange={(event) => setGuideNumber(event.target.value)} /></label><label><span>Responsable del despacho *</span><input required minLength={2} value={responsible} onChange={(event) => setResponsible(event.target.value)} /></label><label><span>Destinatario o transportista</span><input value={recipient} onChange={(event) => setRecipient(event.target.value)} /></label></div>
          <section className="trace-section"><h3>Reporte de salida</h3><div className="dispatch-lines">{reports.map((report, index) => { const source = trace.lines.find((line) => line.sku === report.sku)!; const exceeds = report.dispatched_quantity + report.missing_quantity > source.pending_dispatch; return <article className={report.missing_quantity > 0 || exceeds ? "has-difference" : ""} key={report.sku}><div className="dispatch-product"><strong>{report.sku}</strong><span>{source.product_name}</span><small>Pendiente: {source.pending_dispatch}</small></div><label><span>Despachado</span><input min={0} max={source.pending_dispatch} type="number" value={report.dispatched_quantity} onChange={(event) => update(index, { dispatched_quantity: Number(event.target.value) })} /></label><label><span>Faltante</span><input min={0} max={source.pending_dispatch} type="number" value={report.missing_quantity} onChange={(event) => update(index, { missing_quantity: Number(event.target.value) })} /></label>{report.missing_quantity > 0 && <label className="missing-reason"><span>Motivo del faltante *</span><input required value={report.missing_reason} onChange={(event) => update(index, { missing_reason: event.target.value })} /></label>}{exceeds && <small className="validation-note">La suma supera las {source.pending_dispatch} unidades pendientes.</small>}</article>; })}</div></section>
          <label className="notes-field"><span>Observaciones del despacho</span><textarea rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
          <div className="dispatch-confirm"><span>Se reportarán <strong>{reportTotal}</strong> unidades</span><button className="primary-button" type="button" disabled={saving || responsible.trim().length < 2 || reports.length === 0 || reports.some((report) => report.dispatched_quantity + report.missing_quantity <= 0 || report.dispatched_quantity + report.missing_quantity > trace.lines.find((line) => line.sku === report.sku)!.pending_dispatch || report.missing_quantity > 0 && report.missing_reason.trim().length === 0)} onClick={confirm}>{saving ? "Confirmando…" : "Confirmar salida de bodega"}</button></div>
        </>}
      </div>
    </section>
  </main>;
}
