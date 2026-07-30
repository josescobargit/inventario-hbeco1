import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "../../api/client";
import type { ModuleId } from "../dashboard/navigation";

type Period = "today" | "week" | "month";

interface Summary {
  period: { key: Period; start: string; end: string; last_updated: string };
  metrics: {
    available_units: number;
    products_with_stock: number;
    entries_units: number;
    supplier_invoices: number;
    sales_units: number;
    sales_invoices: number;
    invoiced_value: string | number;
    out_of_stock: number;
    low_stock: number;
    attention: number;
  };
  attention: Array<{
    type: string;
    title: string;
    description: string;
    date: string;
    target: ModuleId;
    target_id: string | null;
    severity: "warning" | "error";
  }>;
  recent_activity: Array<{
    date: string;
    type: string;
    document: string;
    description: string;
    quantity: number;
    user: string;
    result: string;
    target: ModuleId;
    target_id: string;
  }>;
}

const periodLabels: Record<Period, string> = {
  today: "Hoy",
  week: "Esta semana",
  month: "Este mes",
};
const units = (value: number) => new Intl.NumberFormat("es-EC").format(value);
const money = (value: string | number) => new Intl.NumberFormat("es-EC", { style: "currency", currency: "USD" }).format(Number(value));
const dateTime = (value: string) => new Intl.DateTimeFormat("es-EC", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));

export function OperationalOverview({ onNavigate }: { onNavigate: (module: ModuleId) => void }) {
  const [period, setPeriod] = useState<Period>("month");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await apiRequest<Summary>(`/dashboard/summary?period=${period}`));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos cargar el panel de control.");
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    let active = true;
    apiRequest<Summary>(`/dashboard/summary?period=${period}`)
      .then((loaded) => { if (active) { setSummary(loaded); setError(null); } })
      .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "No pudimos cargar el panel de control."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [period]);

  const navigate = (target: ModuleId, targetId?: string | null) => {
    if (target === "invoices" && targetId) sessionStorage.setItem("inventario.openInvoiceId", targetId);
    onNavigate(target);
  };

  return <main className="dashboard overview-center">
    <section className="overview-heading">
      <div className="welcome-block"><p className="eyebrow">Bodega principal</p><h1>Panel de control</h1><p>{periodLabels[period]}{summary ? ` · Última actualización ${dateTime(summary.period.last_updated)}` : ""}</p></div>
      <div className="overview-controls">
        <label><span>Período</span><select value={period} onChange={(event) => { setLoading(true); setPeriod(event.target.value as Period); }}><option value="today">Hoy</option><option value="week">Esta semana</option><option value="month">Este mes</option></select></label>
        <button className="secondary-button" type="button" disabled={loading} onClick={() => void load()}>{loading ? "Actualizando…" : "Actualizar datos"}</button>
      </div>
    </section>

    {error && <div className="message error" role="alert">{error}<button type="button" onClick={() => void load()}>Reintentar</button></div>}
    {!summary && loading && <div className="table-message">Cargando indicadores…</div>}
    {summary && <><section className="overview-metrics overview-control-metrics">
      <button type="button" onClick={() => navigate("inventory")}><span>Inventario disponible</span><strong>{units(summary.metrics.available_units)}</strong><small>Existencia actual · {units(summary.metrics.products_with_stock)} productos</small></button>
      <button type="button" onClick={() => navigate("entries")}><span>Entradas del período</span><strong>+{units(summary.metrics.entries_units)}</strong><small>{units(summary.metrics.supplier_invoices)} facturas de proveedor</small></button>
      <button type="button" onClick={() => navigate("invoices")}><span>Salidas por facturación</span><strong>-{units(summary.metrics.sales_units)}</strong><small>{units(summary.metrics.sales_invoices)} facturas efectivas</small></button>
      <button type="button" onClick={() => navigate("invoices")}><span>Valor facturado</span><strong>{money(summary.metrics.invoiced_value)}</strong><small>No representa dinero cobrado</small></button>
      <button className={summary.metrics.out_of_stock + summary.metrics.low_stock > 0 ? "attention" : ""} type="button" onClick={() => navigate("inventory")}><span>Stock crítico</span><strong>{units(summary.metrics.out_of_stock + summary.metrics.low_stock)}</strong><small>{summary.metrics.out_of_stock} agotados · {summary.metrics.low_stock} bajo mínimo</small></button>
      <button className={summary.metrics.attention > 0 ? "attention" : ""} type="button" onClick={() => navigate("invoices")}><span>Atención requerida</span><strong>{units(summary.metrics.attention)}</strong><small>Problemas reales por revisar</small></button>
    </section>

    <div className="overview-columns control-overview-columns">
      <section className="attention-panel"><div className="panel-title"><div><h2>Requiere atención</h2><p>Errores de inventario, stock crítico e incidencias reales.</p></div><span>{summary.attention.length}</span></div>{summary.attention.length === 0 ? <div className="empty-detail compact"><strong>Sin problemas pendientes</strong><span>No hay diferencias que requieran acción.</span></div> : <div className="attention-list">{summary.attention.map((item, index) => <button type="button" key={`${item.type}-${item.target_id ?? index}`} className={`control-attention-item ${item.severity}`} onClick={() => navigate(item.target, item.target_id)}><div><strong>{item.title}</strong><span>{item.description}</span></div><small>{dateTime(item.date)}</small></button>)}</div>}</section>
      <section className="attention-panel activity-panel"><div className="panel-title"><div><h2>Actividad reciente</h2><p>Entradas y facturas registradas durante el período.</p></div><span>{summary.recent_activity.length}</span></div>{summary.recent_activity.length === 0 ? <div className="empty-detail compact"><strong>Sin actividad en el período</strong><span>Prueba seleccionando otro período.</span></div> : <div className="table-scroll"><table className="compact-table"><thead><tr><th>Fecha</th><th>Tipo</th><th>Documento</th><th>Descripción</th><th>Cantidad</th><th>Usuario</th><th>Resultado</th></tr></thead><tbody>{summary.recent_activity.map((item) => <tr key={`${item.type}-${item.target_id}`} tabIndex={0} onClick={() => navigate(item.target, item.target_id)} onKeyDown={(event) => { if (event.key === "Enter") navigate(item.target, item.target_id); }}><td>{dateTime(item.date)}</td><td>{item.type}</td><td><strong>{item.document}</strong></td><td>{item.description}</td><td><strong className={item.quantity < 0 ? "negative-delta" : "positive-delta"}>{item.quantity > 0 ? "+" : ""}{units(item.quantity)}</strong></td><td>{item.user}</td><td>{item.result}</td></tr>)}</tbody></table></div>}</section>
    </div></>}
  </main>;
}
