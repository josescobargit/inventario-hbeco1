import { FormEvent, useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";

interface CatalogProduct {
  id: string;
  sku: string;
  name: string;
  description: string | null;
  category: string;
  barcode: string | null;
  contifico_aux_code: string | null;
  cost: string;
  units_per_box: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  physical_confirmed: number;
  reserved: number;
  invoiced_not_dispatched: number;
  blocked_by_incident: number;
}

interface ProductForm {
  sku: string;
  name: string;
  description: string;
  category: string;
  barcode: string;
  contifico_aux_code: string;
  cost: string;
  units_per_box: number;
  is_active: boolean;
}

const emptyForm: ProductForm = {
  sku: "",
  name: "",
  description: "",
  category: "",
  barcode: "",
  contifico_aux_code: "",
  cost: "0.0000",
  units_per_box: 12,
  is_active: true,
};

const toForm = (product: CatalogProduct): ProductForm => ({
  sku: product.sku,
  name: product.name,
  description: product.description ?? "",
  category: product.category,
  barcode: product.barcode ?? "",
  contifico_aux_code: product.contifico_aux_code ?? "",
  cost: product.cost,
  units_per_box: product.units_per_box,
  is_active: product.is_active,
});

const payloadFrom = (form: ProductForm) => ({
  sku: form.sku,
  name: form.name,
  description: form.description.trim() || null,
  category: form.category,
  barcode: form.barcode.trim() || null,
  contifico_aux_code: form.contifico_aux_code.trim() || null,
  cost: form.cost || "0",
  units_per_box: form.units_per_box,
  is_active: form.is_active,
});

export function CatalogCenter() {
  const [products, setProducts] = useState<CatalogProduct[]>([]);
  const [selectedSku, setSelectedSku] = useState<string | null>(null);
  const [createForm, setCreateForm] = useState<ProductForm>(emptyForm);
  const [editForm, setEditForm] = useState<ProductForm | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<"all" | "active" | "inactive">("all");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(() => products.find((product) => product.sku === selectedSku) ?? products[0] ?? null, [products, selectedSku]);
  const categories = useMemo(() => Array.from(new Set(products.map((product) => product.category))).sort((a, b) => a.localeCompare(b, "es-EC")), [products]);
  const visibleProducts = useMemo(() => {
    const term = search.trim().toLocaleLowerCase("es-EC");
    return products.filter((product) => {
      const matchesSearch = !term || [product.sku, product.name, product.category, product.barcode ?? "", product.contifico_aux_code ?? ""].some((value) => value.toLocaleLowerCase("es-EC").includes(term));
      const matchesStatus = status === "all" || (status === "active" ? product.is_active : !product.is_active);
      return matchesSearch && matchesStatus;
    });
  }, [products, search, status]);

  const load = () => {
    setLoading(true);
    setError(null);
    apiRequest<CatalogProduct[]>("/catalog/products")
      .then((loaded) => {
        setProducts(loaded);
        const next = loaded.find((product) => product.sku === selectedSku) ?? loaded[0] ?? null;
        setSelectedSku(next?.sku ?? null);
        setEditForm(next ? toForm(next) : null);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudo cargar el catálogo."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    let ignore = false;
    apiRequest<CatalogProduct[]>("/catalog/products")
      .then((loaded) => {
        if (ignore) return;
        setProducts(loaded);
        setSelectedSku(loaded[0]?.sku ?? null);
        setEditForm(loaded[0] ? toForm(loaded[0]) : null);
      })
      .catch((caught) => {
        if (!ignore) setError(caught instanceof Error ? caught.message : "No se pudo cargar el catálogo.");
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => { ignore = true; };
  }, []);

  const createProduct = (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    setError(null);
    apiRequest<CatalogProduct>("/catalog/products", { method: "POST", body: JSON.stringify(payloadFrom(createForm)) })
      .then((created) => {
        setProducts((current) => [...current, created].sort((a, b) => a.sku.localeCompare(b.sku, "es-EC")));
        setSelectedSku(created.sku);
        setEditForm(toForm(created));
        setCreateForm(emptyForm);
        setMessage(`Producto ${created.sku} creado correctamente.`);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudo crear el producto."))
      .finally(() => setSaving(false));
  };

  const updateProduct = (event: FormEvent) => {
    event.preventDefault();
    if (!selected || !editForm) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    const values = payloadFrom(editForm);
    const payload = {
      name: values.name,
      description: values.description,
      category: values.category,
      barcode: values.barcode,
      contifico_aux_code: values.contifico_aux_code,
      cost: values.cost,
      units_per_box: values.units_per_box,
      is_active: values.is_active,
    };
    apiRequest<CatalogProduct>(`/catalog/products/${selected.sku}`, { method: "PUT", body: JSON.stringify(payload) })
      .then((updated) => {
        setProducts((current) => current.map((product) => product.sku === updated.sku ? updated : product));
        setEditForm(toForm(updated));
        setMessage(`Producto ${updated.sku} actualizado correctamente.`);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudo actualizar el producto."))
      .finally(() => setSaving(false));
  };

  return <main className="dashboard catalog-center">
    <section className="module-heading">
      <div className="welcome-block">
        <p className="eyebrow">Datos maestros</p>
        <h1>Catálogo</h1>
        <p>Administra los productos inventariables usados por órdenes, reservas, facturas, movimientos y reportes.</p>
      </div>
      <button className="secondary-button" type="button" disabled={loading} onClick={load}>{loading ? "Actualizando…" : "Actualizar"}</button>
    </section>

    <section className="catalog-kpis" aria-label="Resumen de catálogo">
      <article><span>Productos</span><strong>{products.length}</strong><small>SKU registrados</small></article>
      <article><span>Activos</span><strong>{products.filter((product) => product.is_active).length}</strong><small>disponibles para operación</small></article>
      <article><span>Categorías</span><strong>{categories.length}</strong><small>líneas de producto</small></article>
      <article><span>Con stock/saldo</span><strong>{products.filter((product) => product.physical_confirmed + product.reserved + product.invoiced_not_dispatched + product.blocked_by_incident > 0).length}</strong><small>no deben desactivarse</small></article>
    </section>

    {message && <div className="message success" role="status">{message}</div>}
    {error && <div className="message error" role="alert">{error}</div>}

    <div className="catalog-workspace">
      <section className="catalog-panel catalog-list-panel">
        <div className="panel-title"><div><h2>Productos</h2><p>Busca por SKU, nombre, categoría, código de barras o auxiliar.</p></div><span>{visibleProducts.length}</span></div>
        <div className="catalog-filters">
          <label><span>Buscar</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="SKU, nombre o código" /></label>
          <label><span>Estado</span><select value={status} onChange={(event) => setStatus(event.target.value as "all" | "active" | "inactive")}><option value="all">Todos</option><option value="active">Activos</option><option value="inactive">Inactivos</option></select></label>
        </div>
        {loading && <div className="table-message">Cargando catálogo…</div>}
        {!loading && visibleProducts.length === 0 && <div className="table-message">No hay productos para esos filtros.</div>}
        {visibleProducts.length > 0 && <div className="catalog-product-list">{visibleProducts.map((product) => <button type="button" className={selected?.sku === product.sku ? "selected" : ""} key={product.sku} onClick={() => { setSelectedSku(product.sku); setEditForm(toForm(product)); }}><strong>{product.sku}</strong><span>{product.name}</span><small>{product.category} · UxC {product.units_per_box}</small></button>)}</div>}
      </section>

      <form className="catalog-panel catalog-form" onSubmit={createProduct}>
        <div className="panel-title"><div><h2>Nuevo producto</h2><p>Se creará con stock físico en cero en la bodega principal.</p></div></div>
        <ProductFields form={createForm} onChange={setCreateForm} includeSku />
        <button className="primary-button" type="submit" disabled={saving}>{saving ? "Guardando…" : "Crear producto"}</button>
      </form>

      <form className="catalog-panel catalog-form" onSubmit={updateProduct}>
        <div className="panel-title"><div><h2>Editar seleccionado</h2><p>El SKU no se cambia para no romper trazabilidad histórica.</p></div></div>
        {!selected || !editForm ? <div className="empty-detail compact"><strong>Sin producto seleccionado</strong><span>Selecciona un SKU para editarlo.</span></div> : <>
          <label><span>SKU</span><input value={editForm.sku} disabled /></label>
          <ProductFields form={editForm} onChange={setEditForm} />
          <button className="primary-button" type="submit" disabled={saving}>{saving ? "Guardando…" : "Guardar cambios"}</button>
        </>}
      </form>
    </div>
  </main>;
}

function ProductFields({ form, onChange, includeSku = false }: { form: ProductForm; onChange: (value: ProductForm) => void; includeSku?: boolean }) {
  return <div className="catalog-form-grid">
    {includeSku && <label><span>SKU *</span><input required maxLength={50} value={form.sku} onChange={(event) => onChange({ ...form, sku: event.target.value })} placeholder="AE010" /></label>}
    <label><span>Nombre *</span><input required minLength={2} maxLength={200} value={form.name} onChange={(event) => onChange({ ...form, name: event.target.value })} /></label>
    <label><span>Categoría *</span><input required minLength={2} maxLength={100} value={form.category} onChange={(event) => onChange({ ...form, category: event.target.value })} /></label>
    <label><span>Costo</span><input required min={0} step="0.0001" type="number" value={form.cost} onChange={(event) => onChange({ ...form, cost: event.target.value })} /></label>
    <label><span>Unidades por caja *</span><input required min={1} type="number" value={form.units_per_box} onChange={(event) => onChange({ ...form, units_per_box: Number(event.target.value) })} /></label>
    <label><span>Código de barras</span><input maxLength={80} value={form.barcode} onChange={(event) => onChange({ ...form, barcode: event.target.value })} /></label>
    <label><span>Código auxiliar Contífico</span><input maxLength={80} value={form.contifico_aux_code} onChange={(event) => onChange({ ...form, contifico_aux_code: event.target.value })} /></label>
    <label className="toggle-row"><input type="checkbox" checked={form.is_active} onChange={(event) => onChange({ ...form, is_active: event.target.checked })} /><span>Producto activo</span></label>
    <label className="wide"><span>Descripción</span><textarea maxLength={2000} rows={3} value={form.description} onChange={(event) => onChange({ ...form, description: event.target.value })} /></label>
  </div>;
}
