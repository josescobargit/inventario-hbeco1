import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";

interface ReportRowByChain { chain_name: string; invoice_count: number; units: number }
interface ReportRowByProduct { sku: string; product_name: string; category: string; units: number }
interface MissingProduct { sku: string; product_name: string; missing_units: number; events: number }
interface LowStockProduct { sku: string; product_name: string; category: string; available: number; units_per_box: number; status: string }
interface ResponsibleMovement { responsible: string; movements: number }
interface OperationalReport {
  inventory: { products: number; physical: number; reserved: number; invoiced_pending: number; blocked: number; available: number; low_stock_products: number };
  workflow: { pending_dispatch: number; pending_delivery: number; open_incidents: number };
  by_chain: ReportRowByChain[];
  by_product: ReportRowByProduct[];
  pending_by_chain: ReportRowByChain[];
  missing_products: MissingProduct[];
  low_stock: LowStockProduct[];
  movements_by_responsible: ResponsibleMovement[];
}

const statusLabel: Record<string, string> = { low_stock: "Stock bajo", out_of_stock: "Sin stock", blocked: "Bloqueado", available: "Disponible" };

export function ReportCenter() {
  const [report, setReport] = useState<OperationalReport | null>(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [chain, setChain] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const maxProductUnits = useMemo(() => Math.max(1, ...(report?.by_product.map((item) => item.units) ?? [1])), [report]);
  const maxChainUnits = useMemo(() => Math.max(1, ...(report?.by_chain.map((item) => item.units) ?? [1])), [report]);

  const load = () => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (chain.trim()) params.set("chain", chain.trim());
    apiRequest<OperationalReport>(`/reports/operational?${params.toString()}`)
      .then(setReport)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudieron cargar los reportes."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    apiRequest<OperationalReport>("/reports/operational")
      .then(setReport)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudieron cargar los reportes."))
      .finally(() => setLoading(false));
  }, []);

  return <main className="dashboard report-center">
    <section className="module-heading">
      <div className="welcome-block">
        <p className="eyebrow">Análisis operativo</p>
        <h1>Reportes</h1>
        <p>Consultas de inventario, facturación, pendientes, faltantes y movimientos por responsable.</p>
      </div>
      <button className="secondary-button" type="button" disabled={loading} onClick={load}>{loading ? "Actualizando…" : "Actualizar"}</button>
    </section>

    <section className="report-filters" aria-label="Filtros de reportes">
      <label><span>Desde</span><input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
      <label><span>Hasta</span><input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
      <label><span>Cadena</span><input value={chain} onChange={(event) => setChain(event.target.value)} placeholder="Favorita, Tía, Rosado…" /></label>
      <button className="primary-button" type="button" disabled={loading} onClick={load}>Aplicar filtros</button>
    </section>

    {error && <div className="message error" role="alert">{error}</div>}
    {loading && !report && <div className="table-message">Cargando reportes…</div>}

    {report && <>
      <section className="report-kpis" aria-label="Resumen de reportes">
        <article><span>Disponible</span><strong>{report.inventory.available}</strong><small>unidades</small></article>
        <article><span>Stock físico</span><strong>{report.inventory.physical}</strong><small>{report.inventory.products} productos</small></article>
        <article><span>Stock bajo</span><strong>{report.inventory.low_stock_products}</strong><small>productos</small></article>
        <article><span>Pendiente despacho</span><strong>{report.workflow.pending_dispatch}</strong><small>facturas</small></article>
        <article><span>Pendiente entrega</span><strong>{report.workflow.pending_delivery}</strong><small>facturas</small></article>
        <article><span>Incidencias</span><strong>{report.workflow.open_incidents}</strong><small>abiertas</small></article>
      </section>

      <div className="report-grid">
        <section className="report-panel wide">
          <div className="panel-title"><div><h2>Facturado por cadena</h2><p>Unidades registradas en facturas externas.</p></div><span>{report.by_chain.length}</span></div>
          {report.by_chain.length === 0 ? <div className="empty-detail compact"><strong>No hay resultados</strong><span>Ajusta los filtros.</span></div> : <div className="bar-list">{report.by_chain.map((item) => <article key={item.chain_name}><div><strong>{item.chain_name}</strong><span>{item.invoice_count} facturas · {item.units} unidades</span></div><div className="bar-track"><span style={{ width: `${Math.max(6, item.units / maxChainUnits * 100)}%` }} /></div></article>)}</div>}
        </section>

        <section className="report-panel">
          <div className="panel-title"><div><h2>Productos más facturados</h2><p>Ranking por unidades.</p></div><span>{report.by_product.length}</span></div>
          {report.by_product.length === 0 ? <div className="empty-detail compact"><strong>No hay resultados</strong><span>Sin facturas en el rango.</span></div> : <div className="bar-list compact">{report.by_product.map((item) => <article key={item.sku}><div><strong>{item.sku}</strong><span>{item.product_name} · {item.units}</span></div><div className="bar-track"><span style={{ width: `${Math.max(6, item.units / maxProductUnits * 100)}%` }} /></div></article>)}</div>}
        </section>

        <section className="report-panel">
          <div className="panel-title"><div><h2>Pendientes por cadena</h2><p>Facturas por despachar o entregar.</p></div><span>{report.pending_by_chain.length}</span></div>
          {report.pending_by_chain.length === 0 ? <div className="empty-detail compact"><strong>Sin pendientes</strong><span>No hay facturas pendientes.</span></div> : <div className="table-scroll compact-table"><table><thead><tr><th>Cadena</th><th>Facturas</th><th>Unidades</th></tr></thead><tbody>{report.pending_by_chain.map((item) => <tr key={item.chain_name}><td>{item.chain_name}</td><td>{item.invoice_count}</td><td>{item.units}</td></tr>)}</tbody></table></div>}
        </section>

        <section className="report-panel">
          <div className="panel-title"><div><h2>Faltantes</h2><p>Productos con faltantes en despacho.</p></div><span>{report.missing_products.length}</span></div>
          {report.missing_products.length === 0 ? <div className="empty-detail compact"><strong>Sin faltantes</strong><span>No hay eventos registrados.</span></div> : <div className="table-scroll compact-table"><table><thead><tr><th>Producto</th><th>Unidades</th><th>Eventos</th></tr></thead><tbody>{report.missing_products.map((item) => <tr key={item.sku}><td><strong>{item.sku}</strong><span>{item.product_name}</span></td><td>{item.missing_units}</td><td>{item.events}</td></tr>)}</tbody></table></div>}
        </section>

        <section className="report-panel">
          <div className="panel-title"><div><h2>Stock bajo</h2><p>Productos por debajo del umbral.</p></div><span>{report.low_stock.length}</span></div>
          {report.low_stock.length === 0 ? <div className="empty-detail compact"><strong>Sin stock bajo</strong><span>No hay resultados.</span></div> : <div className="table-scroll compact-table"><table><thead><tr><th>Producto</th><th>Disponible</th><th>Estado</th></tr></thead><tbody>{report.low_stock.map((item) => <tr key={item.sku}><td><strong>{item.sku}</strong><span>{item.product_name}</span></td><td>{item.available}</td><td><span className={`status-pill ${item.status}`}>{statusLabel[item.status] ?? item.status}</span></td></tr>)}</tbody></table></div>}
        </section>

        <section className="report-panel">
          <div className="panel-title"><div><h2>Movimientos por responsable</h2><p>Actividad registrada en inventario.</p></div><span>{report.movements_by_responsible.length}</span></div>
          {report.movements_by_responsible.length === 0 ? <div className="empty-detail compact"><strong>Sin movimientos</strong><span>No hay registros.</span></div> : <div className="table-scroll compact-table"><table><thead><tr><th>Responsable</th><th>Movimientos</th></tr></thead><tbody>{report.movements_by_responsible.map((item) => <tr key={item.responsible}><td>{item.responsible}</td><td>{item.movements}</td></tr>)}</tbody></table></div>}
        </section>
      </div>
    </>}
  </main>;
}
