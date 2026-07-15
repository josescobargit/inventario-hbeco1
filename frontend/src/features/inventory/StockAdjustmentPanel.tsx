import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";
import { ProductIdentity } from "./ProductIdentity";

interface Product { sku: string; product_name: string; physical_confirmed: number; reserved: number; invoiced_not_dispatched: number; blocked_by_incident: number }
interface Adjustment { id: string; sku: string; product_name: string; status: string; previous_physical_confirmed: number; requested_physical_confirmed: number; request_reason: string; decision_reason: string | null; requested_at: string; decided_at: string | null }

const statusLabels: Record<string, string> = { pending: "Pendiente", approved: "Aplicado", rejected: "Rechazado", obsolete: "Obsoleto" };

export function StockAdjustmentPanel({ products, userRole, onApplied }: { products: Product[]; userRole: string; onApplied: () => void }) {
  const [adjustments, setAdjustments] = useState<Adjustment[]>([]);
  const [sku, setSku] = useState("");
  const [counted, setCounted] = useState("");
  const [reason, setReason] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [decisionId, setDecisionId] = useState<string | null>(null);
  const [decisionReason, setDecisionReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => { const data = await apiRequest<Adjustment[]>("/stock-adjustments"); setAdjustments(data); };
  useEffect(() => { apiRequest<Adjustment[]>("/stock-adjustments").then(setAdjustments).catch((caught) => setError(caught instanceof Error ? caught.message : "No pudimos cargar los ajustes.")); }, []);
  const selected = useMemo(() => products.find((item) => item.sku === sku) ?? null, [products, sku]);
  const difference = selected && counted !== "" ? Number(counted) - selected.physical_confirmed : null;
  const adjustmentSummary = useMemo(() => ({
    applied: adjustments.filter((item) => item.status === "approved").length,
    pending: adjustments.filter((item) => item.status === "pending").length,
    differences: adjustments.filter((item) => item.requested_physical_confirmed !== item.previous_physical_confirmed).length,
    latest: adjustments[0]?.requested_at ?? null,
  }), [adjustments]);
  const latestLabel = adjustmentSummary.latest ? new Intl.DateTimeFormat("es-EC", { dateStyle: "medium" }).format(new Date(adjustmentSummary.latest)) : "Sin cargas";

  const submit = async () => {
    setBusy(true); setError(null); setMessage(null);
    try {
      const result = await apiRequest<Adjustment>("/stock-adjustments", { method: "POST", body: JSON.stringify({ sku, requested_physical_confirmed: Number(counted), reason }) });
      await load(); onApplied(); setSku(""); setCounted(""); setReason(""); setShowForm(false);
      setMessage(result.status === "approved" ? "Conteo aplicado directamente y auditado." : "Solicitud enviada al usuario principal.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No pudimos registrar el conteo."); }
    finally { setBusy(false); }
  };

  const decide = async (id: string, action: "approve" | "reject") => {
    setBusy(true); setError(null); setMessage(null);
    try {
      await apiRequest(`/stock-adjustments/${id}/${action}`, { method: "POST", body: JSON.stringify({ reason: decisionReason }) });
      await load(); onApplied(); setDecisionId(null); setDecisionReason(""); setMessage(action === "approve" ? "Ajuste aprobado y aplicado." : "Solicitud rechazada sin cambiar el inventario.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No pudimos decidir la solicitud."); await load(); }
    finally { setBusy(false); }
  };

  return <section className="stock-control-panel">
    <div className="stock-control-header"><div><p className="eyebrow">Corrección controlada</p><h2>Ajuste individual</h2><p>Actualiza únicamente el conteo físico; reservas, facturas pendientes y bloqueos permanecen intactos.</p></div><button className="primary-button" type="button" onClick={() => { setShowForm((value) => !value); setError(null); }}>{showForm ? "Cancelar" : "Nuevo conteo"}</button></div>
    <div className="adjustment-summary" aria-label="Resumen de ajustes"><article><span>Ajustes aplicados</span><strong>{adjustmentSummary.applied}</strong></article><article><span>Ajustes pendientes</span><strong>{adjustmentSummary.pending}</strong></article><article><span>Diferencias detectadas</span><strong>{adjustmentSummary.differences}</strong></article><article><span>Último ajuste</span><strong>{latestLabel}</strong></article></div>
    {message && <div className="message success">{message}</div>}{error && <div className="message error" role="alert">{error}</div>}
    {showForm && <div className="stock-adjustment-form"><label><span>Producto *</span><select value={sku} onChange={(event) => { setSku(event.target.value); setCounted(""); }}><option value="">Selecciona el SKU</option>{products.map((item) => <option key={item.sku} value={item.sku}>{item.sku} · {item.product_name}</option>)}</select></label><label><span>Nuevo conteo físico *</span><input min={0} type="number" value={counted} onChange={(event) => setCounted(event.target.value)} /></label>
      {selected && <div className="adjustment-preview"><div><span>Físico actual</span><strong>{selected.physical_confirmed}</strong></div><div><span>Diferencia</span><strong className={difference && difference < 0 ? "negative" : ""}>{difference === null ? "—" : `${difference > 0 ? "+" : ""}${difference}`}</strong></div><div><span>No se modifica</span><small>Reservado {selected.reserved} · Facturado pendiente {selected.invoiced_not_dispatched} · Bloqueado {selected.blocked_by_incident}</small></div></div>}
      <label className="wide"><span>Motivo *</span><input minLength={5} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explica el conteo y la diferencia" /></label><div className="form-actions"><button className="primary-button" type="button" disabled={busy || !sku || counted === "" || Number(counted) < 0 || reason.trim().length < 5} onClick={submit}>{busy ? "Guardando…" : userRole === "principal" ? "Aplicar conteo" : "Enviar para aprobación"}</button></div>
      {userRole === "principal" && <p className="principal-note">Como usuario principal, el conteo se aplicará inmediatamente. No tendrás que aprobártelo después.</p>}
    </div>}
    <div className="adjustment-history"><div className="list-title"><strong>Historial de ajustes</strong><span>{adjustments.filter((item) => item.status === "pending").length}</span></div>{adjustments.length === 0 ? <div className="table-message">Todavía no hay ajustes individuales.</div> : <div className="table-scroll"><table><thead><tr><th>Producto</th><th>Antes</th><th>Solicitado</th><th>Diferencia</th><th>Motivo</th><th>Estado</th><th>Acción</th></tr></thead><tbody>{adjustments.map((item) => <tr key={item.id}><td><ProductIdentity name={item.product_name} sku={item.sku} /></td><td>{item.previous_physical_confirmed}</td><td>{item.requested_physical_confirmed}</td><td>{item.requested_physical_confirmed - item.previous_physical_confirmed}</td><td className="reason-cell">{item.request_reason}</td><td><span className={`status-pill ${item.status === "pending" ? "low_stock" : item.status === "approved" ? "available" : "out_of_stock"}`}>{statusLabels[item.status]}</span></td><td>{item.status === "pending" && userRole === "principal" ? decisionId === item.id ? <div className="inline-decision"><input autoFocus placeholder="Motivo de la decisión" value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} /><div><button type="button" onClick={() => setDecisionId(null)}>Cancelar</button><button type="button" disabled={busy || decisionReason.trim().length < 5} onClick={() => decide(item.id, "reject")}>Rechazar</button><button type="button" disabled={busy || decisionReason.trim().length < 5} onClick={() => decide(item.id, "approve")}>Aprobar</button></div></div> : <button className="secondary-button" type="button" onClick={() => setDecisionId(item.id)}>Decidir</button> : <span>—</span>}</td></tr>)}</tbody></table></div>}</div>
  </section>;
}
