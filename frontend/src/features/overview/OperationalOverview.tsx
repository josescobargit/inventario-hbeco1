import { useEffect, useState } from "react";

import { apiRequest } from "../../api/client";
import type { ModuleId } from "../dashboard/navigation";
import { ProductIdentity } from "../inventory/ProductIdentity";

interface Summary {
  inventory: { products: number; physical: number; reserved: number; invoiced_pending: number; blocked: number; available: number };
  workflow: { pending_dispatch: number; pending_delivery: number; open_incidents: number; active_reservations: number; reserved_units: number; pending_approvals: number };
  attention_invoices: Array<{ id: string; invoice_number: string; customer_name: string; chain_name: string | null; invoice_date: string; dispatch_status: string; delivery_status: string; incident_status: string }>;
  low_stock: Array<{ sku: string; product_name: string; available: number; units_per_box: number }>;
}

const dateLabel = (value: string) => new Intl.DateTimeFormat("es-EC", { dateStyle: "medium" }).format(new Date(`${value}T12:00:00`));

export function OperationalOverview({ onNavigate }: { onNavigate: (module: ModuleId) => void }) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { apiRequest<Summary>("/dashboard/summary").then(setSummary).catch((caught) => setError(caught instanceof Error ? caught.message : "No pudimos cargar el resumen.")); }, []);

  return <main className="dashboard overview-center">
    <section className="welcome-block"><p className="eyebrow">Bodega principal</p><h1>Dashboard</h1><p>Resumen actual del inventario y pendientes operativos.</p></section>
    {error && <div className="message error" role="alert">{error}</div>}
    {!summary && !error && <div className="table-message">Cargando sistema...</div>}
    {summary && <><section className="overview-metrics">
      <button type="button" onClick={() => onNavigate("inventory")}><span>Disponible para facturar</span><strong>{summary.inventory.available}</strong><small>Unidades disponibles</small></button>
      <button type="button" onClick={() => onNavigate("inventory")}><span>Stock físico</span><strong>{summary.inventory.physical}</strong><small>{summary.inventory.products} productos</small></button>
      <button type="button" onClick={() => onNavigate("reservations")}><span>Reservado</span><strong>{summary.inventory.reserved}</strong><small>{summary.workflow.active_reservations} reservas activas</small></button>
      <button type="button" onClick={() => onNavigate("dispatches")}><span>Facturado por despachar</span><strong>{summary.inventory.invoiced_pending}</strong><small>{summary.workflow.pending_dispatch} por despachar</small></button>
      <button className={summary.inventory.blocked > 0 ? "attention" : ""} type="button" onClick={() => onNavigate("deliveries")}><span>Bloqueado</span><strong>{summary.inventory.blocked}</strong><small>{summary.workflow.open_incidents} incidencias</small></button>
      <button className={summary.workflow.open_incidents > 0 ? "attention" : ""} type="button" onClick={() => onNavigate("deliveries")}><span>Incidencias</span><strong>{summary.workflow.open_incidents}</strong><small>Abiertas</small></button>
    </section>
    <section className="workflow-strip" aria-label="Pendientes del flujo"><button type="button" onClick={() => onNavigate("dispatches")}><strong>{summary.workflow.pending_dispatch}</strong><span>Despachos pendientes</span></button><button type="button" onClick={() => onNavigate("deliveries")}><strong>{summary.workflow.pending_delivery}</strong><span>Entregas pendientes</span></button><button type="button" onClick={() => onNavigate("deliveries")}><strong>{summary.workflow.open_incidents}</strong><span>Incidencias abiertas</span></button><button type="button" onClick={() => onNavigate("inventory")}><strong>{summary.workflow.pending_approvals}</strong><span>Ajustes por aprobar</span></button></section>
    <div className="overview-columns">
      <section className="attention-panel"><div className="panel-title"><div><h2>Facturas pendientes</h2><p>Despacho, entrega o incidencia.</p></div><span>{summary.attention_invoices.length}</span></div>{summary.attention_invoices.length === 0 ? <div className="empty-detail compact"><strong>Sin facturas pendientes</strong><span>Sin incidencias abiertas.</span></div> : <div className="attention-list">{summary.attention_invoices.map((item) => <article key={item.id}><div><strong>{item.invoice_number}</strong><span>{item.customer_name} · {item.chain_name ?? "Sin cadena"}</span></div><small>{dateLabel(item.invoice_date)}</small><div className="attention-tags">{["pending", "partial"].includes(item.dispatch_status) && <button type="button" onClick={() => onNavigate("dispatches")}>Despacho {item.dispatch_status === "partial" ? "parcial" : "pendiente"}</button>}{item.delivery_status === "pending" && item.dispatch_status !== "pending" && <button type="button" onClick={() => onNavigate("deliveries")}>Entrega pendiente</button>}{item.incident_status === "open" && <button className="incident" type="button" onClick={() => onNavigate("deliveries")}>Incidencia abierta</button>}</div></article>)}</div>}</section>
      <section className="attention-panel"><div className="panel-title"><div><h2>Stock bajo</h2><p>Disponible igual o menor a una caja.</p></div><span>{summary.low_stock.length}</span></div>{summary.low_stock.length === 0 ? <div className="empty-detail compact"><strong>Sin stock bajo</strong><span>No hay resultados.</span></div> : <div className="low-stock-list">{summary.low_stock.map((item) => <button type="button" key={item.sku} onClick={() => onNavigate("inventory")}><ProductIdentity name={item.product_name} sku={item.sku} /><div><strong>{item.available}</strong><small>umbral {item.units_per_box}</small></div></button>)}</div>}</section>
    </div></>}
  </main>;
}
