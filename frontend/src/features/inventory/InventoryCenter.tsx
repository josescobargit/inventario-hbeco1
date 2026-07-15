import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";
import { ProductIdentity } from "./ProductIdentity";

interface Availability { sku: string; product_name: string; category: string; physical_confirmed: number; reserved: number; invoiced_not_dispatched: number; blocked_by_incident: number; available_to_invoice: number; units_per_box: number; physical_boxes: number; available_boxes: number; status: "available" | "low_stock" | "out_of_stock" | "blocked" }
const statusLabel = { available: "Disponible", low_stock: "Stock bajo", out_of_stock: "Sin stock", blocked: "Bloqueado" };

export function InventoryCenter() {
  const [products, setProducts] = useState<Availability[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { let active = true; apiRequest<Availability[]>("/inventory/availability").then((data) => { if (active) { setProducts(data); setError(null); } }).catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "No se pudo cargar la información. Intenta nuevamente."); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, []);
  const categories = useMemo(() => Array.from(new Set(products.map((product) => product.category))).sort(), [products]);
  const visibleProducts = useMemo(() => { const term = search.trim().toLocaleLowerCase("es-EC"); return products.filter((product) => {
    const matchesSearch = !term || product.sku.toLocaleLowerCase("es-EC").includes(term) || product.product_name.toLocaleLowerCase("es-EC").includes(term);
    const matchesStatus = !statusFilter || product.status === statusFilter;
    const matchesCategory = !categoryFilter || product.category === categoryFilter;
    const matchesLow = !lowOnly || product.status === "low_stock" || product.status === "out_of_stock";
    return matchesSearch && matchesStatus && matchesCategory && matchesLow;
  }); }, [products, search, statusFilter, categoryFilter, lowOnly]);
  const totals = useMemo(() => ({ products: products.length, physical: products.reduce((sum, product) => sum + product.physical_confirmed, 0), available: products.reduce((sum, product) => sum + product.available_to_invoice, 0), low: products.filter((product) => product.status === "low_stock" || product.status === "out_of_stock").length, blocked: products.reduce((sum, product) => sum + product.blocked_by_incident, 0) }), [products]);

  return <main className="dashboard inventory-center"><section className="page-heading"><div className="welcome-block"><p className="eyebrow">Bodega principal</p><h1>Inventario</h1><p>Stock físico, disponibilidad y estado por producto.</p></div></section>
    <section className="metric-grid inventory-kpis" aria-label="Resumen de inventario"><article><span>Productos activos</span><strong>{totals.products}</strong></article><article><span>Stock físico</span><strong>{totals.physical}</strong></article><article><span>Disponible</span><strong>{totals.available}</strong></article><article><span>Stock bajo</span><strong>{totals.low}</strong></article><article><span>Bloqueado</span><strong>{totals.blocked}</strong></article></section>
    <section className="inventory-panel"><div className="inventory-toolbar inventory-toolbar-modern"><div><h2>Productos</h2><p>Stock físico, disponibilidad y estado por producto.</p></div><div className="inventory-filter-grid"><label className="search-field"><span>Buscar</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="SKU o nombre" type="search" /></label><label className="search-field"><span>Estado</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="">Todos</option>{Object.entries(statusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="search-field"><span>Categoría</span><select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}><option value="">Todas</option>{categories.map((category) => <option value={category} key={category}>{category}</option>)}</select></label><label className="inventory-check"><input type="checkbox" checked={lowOnly} onChange={(event) => setLowOnly(event.target.checked)} /><span>Solo stock bajo</span></label></div></div>
      {loading && <div className="table-message">Cargando información…</div>}{error && <div className="table-message error" role="alert">{error}</div>}{!loading && !error && <div className="table-scroll"><table><thead><tr><th>Producto</th><th>Físico</th><th>Reservado</th><th>Facturado pendiente</th><th>Bloqueado</th><th>Disponible</th><th>UxC</th><th>Estado</th></tr></thead><tbody>{visibleProducts.map((product) => <tr key={product.sku}><td><ProductIdentity name={product.product_name} sku={product.sku} category={product.category} /></td><td>{product.physical_confirmed}</td><td>{product.reserved}</td><td>{product.invoiced_not_dispatched}</td><td>{product.blocked_by_incident}</td><td><strong>{product.available_to_invoice}</strong><span>{product.available_boxes} cajas</span></td><td>{product.units_per_box}</td><td><span className={`status-pill ${product.status}`}>{statusLabel[product.status]}</span></td></tr>)}</tbody></table>{visibleProducts.length === 0 && <div className="table-message">No hay resultados</div>}</div>}
    </section>
  </main>;
}
