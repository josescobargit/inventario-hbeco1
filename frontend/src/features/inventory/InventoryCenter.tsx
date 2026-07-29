import { useEffect, useMemo, useState } from "react";

import { apiRequest, apiUrl } from "../../api/client";
import { ProductIdentity } from "./ProductIdentity";

interface Availability { sku: string; product_name: string; category: string; physical_confirmed: number; reserved: number; invoiced_not_dispatched: number; blocked_by_incident: number; available_to_invoice: number; units_per_box: number; physical_boxes: number; available_boxes: number; status: "available" | "low_stock" | "out_of_stock" | "blocked" }
interface InventoryEffect { sku: string; physical_confirmed: number; available_to_invoice: number }
interface HistoricalItem { product_id: string; product_name: string; sku: string; category: string; inventory_at_cutoff: number; current_inventory: number; difference: number; confirmed_physical_count: number | null; physical_count_at: string | null; difference_vs_physical_count: number | null }
interface HistoricalResult { label: string; cutoff_local: string; theoretical: boolean; items: HistoricalItem[]; total: number }
interface HistoricalLedger { product: { id: string; name: string; sku: string }; items: Array<{ id: string; occurred_at: string; movement_label: string; document: string; entry: number; exit: number; balance: number }> }
const statusLabel = { available: "Disponible", low_stock: "Stock bajo", out_of_stock: "Sin stock", blocked: "Bloqueado" };

export function InventoryCenter() {
  const [products, setProducts] = useState<Availability[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [historicalMode, setHistoricalMode] = useState(false);
  const [cutoffDate, setCutoffDate] = useState(new Date().toLocaleDateString("en-CA"));
  const [showHistoricalZero, setShowHistoricalZero] = useState(true);
  const [showHistoricalNegative, setShowHistoricalNegative] = useState(false);
  const [historical, setHistorical] = useState<HistoricalResult | null>(null);
  const [ledger, setLedger] = useState<HistoricalLedger | null>(null);
  const [historicalLoading, setHistoricalLoading] = useState(false);

  useEffect(() => { let active = true; apiRequest<Availability[]>("/inventory/availability").then((data) => { if (active) { setProducts(data); setError(null); } }).catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "No se pudo cargar la información. Intenta nuevamente."); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, []);
  useEffect(() => {
    const update = (event: Event) => {
      const effects = (event as CustomEvent<InventoryEffect[]>).detail ?? [];
      const bySku = new Map(effects.map((effect) => [effect.sku, effect]));
      setProducts((current) => current.map((product) => {
        const effect = bySku.get(product.sku);
        if (!effect) return product;
        return {
          ...product,
          physical_confirmed: effect.physical_confirmed,
          available_to_invoice: effect.available_to_invoice,
          physical_boxes: effect.physical_confirmed / product.units_per_box,
          available_boxes: effect.available_to_invoice / product.units_per_box,
          status: effect.available_to_invoice <= 0 ? "out_of_stock" : product.status,
        };
      }));
    };
    window.addEventListener("inventario:inventory-changed", update);
    return () => window.removeEventListener("inventario:inventory-changed", update);
  }, []);
  const categories = useMemo(() => Array.from(new Set(products.map((product) => product.category))).sort(), [products]);
  const visibleProducts = useMemo(() => { const term = search.trim().toLocaleLowerCase("es-EC"); return products.filter((product) => {
    const matchesSearch = !term || product.sku.toLocaleLowerCase("es-EC").includes(term) || product.product_name.toLocaleLowerCase("es-EC").includes(term);
    const matchesStatus = !statusFilter || product.status === statusFilter;
    const matchesCategory = !categoryFilter || product.category === categoryFilter;
    const matchesLow = !lowOnly || product.status === "low_stock" || product.status === "out_of_stock";
    return matchesSearch && matchesStatus && matchesCategory && matchesLow;
  }); }, [products, search, statusFilter, categoryFilter, lowOnly]);
  const totals = useMemo(() => ({ products: products.length, physical: products.reduce((sum, product) => sum + product.physical_confirmed, 0), available: products.reduce((sum, product) => sum + product.available_to_invoice, 0), low: products.filter((product) => product.status === "low_stock" || product.status === "out_of_stock").length, blocked: products.reduce((sum, product) => sum + product.blocked_by_incident, 0) }), [products]);
  const loadHistorical = async () => {
    setHistoricalLoading(true);
    setLedger(null);
    try {
      const query = new URLSearchParams({
        cutoff_date: cutoffDate,
        show_zero: String(showHistoricalZero),
        show_negative: String(showHistoricalNegative),
        page_size: "100",
      });
      if (search.trim()) query.set("search", search.trim());
      if (categoryFilter) query.set("category", categoryFilter);
      setHistorical(await apiRequest<HistoricalResult>(`/inventory/history?${query}`));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo reconstruir el inventario histórico.");
    } finally {
      setHistoricalLoading(false);
    }
  };
  const openLedger = async (productId: string) => {
    setHistoricalLoading(true);
    try {
      setLedger(await apiRequest<HistoricalLedger>(`/inventory/history/${productId}/movements?cutoff_date=${cutoffDate}`));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo cargar el historial del producto.");
    } finally {
      setHistoricalLoading(false);
    }
  };
  const historicalExportUrl = () => {
    const query = new URLSearchParams({
      cutoff_date: cutoffDate,
      show_zero: String(showHistoricalZero),
      show_negative: String(showHistoricalNegative),
    });
    if (search.trim()) query.set("search", search.trim());
    if (categoryFilter) query.set("category", categoryFilter);
    return apiUrl(`/inventory/history/export?${query}`);
  };

  return <main className="dashboard inventory-center"><section className="page-heading"><div className="welcome-block"><p className="eyebrow">Bodega principal</p><h1>Inventario</h1><p>Stock físico, disponibilidad y estado por producto.</p></div><button className="secondary-button" type="button" onClick={() => { setHistoricalMode((value) => !value); setLedger(null); }}>{historicalMode ? "Ver inventario actual" : "Inventario a una fecha"}</button></section>
    <section className="metric-grid inventory-kpis" aria-label="Resumen de inventario"><article><span>Productos activos</span><strong>{totals.products}</strong></article><article><span>Stock físico</span><strong>{totals.physical}</strong></article><article><span>Disponible</span><strong>{totals.available}</strong></article><article><span>Stock bajo</span><strong>{totals.low}</strong></article><article><span>Bloqueado</span><strong>{totals.blocked}</strong></article></section>
    {historicalMode ? <section className="inventory-panel historical-inventory"><div className="inventory-toolbar"><div><h2>Inventario a una fecha</h2><p>Reconstrucción teórica basada exclusivamente en movimientos confirmados hasta el final del día en America/Guayaquil.</p></div><div className="inventory-filter-grid"><label className="search-field"><span>Fecha de corte</span><input type="date" value={cutoffDate} onChange={(event) => setCutoffDate(event.target.value)} /></label><label className="search-field"><span>Buscar</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Producto o SKU" /></label><label className="search-field"><span>Categoría</span><select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}><option value="">Todas</option>{categories.map((category) => <option value={category} key={category}>{category}</option>)}</select></label><label className="inventory-check"><input type="checkbox" checked={showHistoricalZero} onChange={(event) => setShowHistoricalZero(event.target.checked)} /><span>Mostrar productos en cero</span></label><label className="inventory-check"><input type="checkbox" checked={showHistoricalNegative} onChange={(event) => setShowHistoricalNegative(event.target.checked)} /><span>Mostrar solo negativos</span></label><button className="primary-button" type="button" disabled={historicalLoading} onClick={() => void loadHistorical()}>{historicalLoading ? "Calculando…" : "Consultar"}</button></div></div>
      {historical && <><div className="message info"><strong>{historical.label}</strong><span> Este resultado representa el inventario teórico del sistema; no sustituye un conteo físico confirmado.</span></div><div className="form-actions"><a className="secondary-button" href={historicalExportUrl()}>Exportar CSV</a></div><div className="table-scroll"><table><thead><tr><th>Producto</th><th>Inventario al corte</th><th>Inventario actual</th><th>Diferencia</th><th>Conteo físico confirmado</th><th>Diferencia vs. conteo</th><th>Acciones</th></tr></thead><tbody>{historical.items.map((item) => <tr key={item.product_id}><td><ProductIdentity name={item.product_name} sku={item.sku} category={item.category} /></td><td>{item.inventory_at_cutoff}</td><td>{item.current_inventory}</td><td>{item.difference > 0 ? `+${item.difference}` : item.difference}</td><td>{item.confirmed_physical_count ?? "—"}{item.physical_count_at && <small>{new Date(item.physical_count_at).toLocaleString("es-EC")}</small>}</td><td>{item.difference_vs_physical_count == null ? "—" : item.difference_vs_physical_count > 0 ? `+${item.difference_vs_physical_count}` : item.difference_vs_physical_count}</td><td><button className="text-button" type="button" onClick={() => void openLedger(item.product_id)}>Abrir historial</button></td></tr>)}</tbody></table></div></>}
      {ledger && <section className="trace-section historical-ledger"><div className="panel-title"><div><h3>{ledger.product.name}</h3><p>SKU: {ledger.product.sku}</p></div><button type="button" className="text-button" onClick={() => setLedger(null)}>Cerrar</button></div><div className="table-scroll"><table><thead><tr><th>Fecha</th><th>Tipo</th><th>Documento</th><th>Entrada</th><th>Salida</th><th>Saldo</th></tr></thead><tbody>{ledger.items.map((item) => <tr key={item.id}><td>{new Date(item.occurred_at).toLocaleString("es-EC")}</td><td>{item.movement_label}</td><td>{item.document}</td><td>{item.entry || "—"}</td><td>{item.exit || "—"}</td><td><strong>{item.balance}</strong></td></tr>)}</tbody></table></div></section>}
    </section> : <section className="inventory-panel"><div className="inventory-toolbar inventory-toolbar-modern"><div><h2>Productos</h2><p>Stock físico, disponibilidad y estado por producto.</p></div><div className="inventory-filter-grid"><label className="search-field"><span>Buscar</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="SKU o nombre" type="search" /></label><label className="search-field"><span>Estado</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="">Todos</option>{Object.entries(statusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="search-field"><span>Categoría</span><select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}><option value="">Todas</option>{categories.map((category) => <option value={category} key={category}>{category}</option>)}</select></label><label className="inventory-check"><input type="checkbox" checked={lowOnly} onChange={(event) => setLowOnly(event.target.checked)} /><span>Solo stock bajo</span></label></div></div>
      {loading && <div className="table-message">Cargando información…</div>}{error && <div className="table-message error" role="alert">{error}</div>}{!loading && !error && <div className="table-scroll"><table><thead><tr><th>Producto</th><th>Físico</th><th>Reservado</th><th>Facturado pendiente</th><th>Bloqueado</th><th>Disponible</th><th>UxC</th><th>Estado</th></tr></thead><tbody>{visibleProducts.map((product) => <tr key={product.sku}><td><ProductIdentity name={product.product_name} sku={product.sku} category={product.category} /></td><td>{product.physical_confirmed}</td><td>{product.reserved}</td><td>{product.invoiced_not_dispatched}</td><td>{product.blocked_by_incident}</td><td><strong>{product.available_to_invoice}</strong><span>{product.available_boxes} cajas</span></td><td>{product.units_per_box}</td><td><span className={`status-pill ${product.status}`}>{statusLabel[product.status]}</span></td></tr>)}</tbody></table>{visibleProducts.length === 0 && <div className="table-message">No hay resultados</div>}</div>}
    </section>}
  </main>;
}
