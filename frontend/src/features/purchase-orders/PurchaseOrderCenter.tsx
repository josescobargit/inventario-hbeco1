import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import { apiRequest, apiUrl } from "../../api/client";
import {
  applyConfirmedAlias, parseProductLines, retryProductRecognition,
} from "../invoices/quickEntry";
import { ProductIdentity } from "../inventory/ProductIdentity";
import { PurchaseOrderDocumentImport } from "./PurchaseOrderDocumentImport";
import { DocumentViewer, ViewableDocument } from "./DocumentViewer";

interface ProductOption {
  id: string;
  sku: string;
  product_name: string;
  barcode: string | null;
  contifico_aux_code: string | null;
  available_to_invoice: number;
  units_per_box: number;
}

interface OrderLine {
  sku: string;
  product_name: string;
  ordered_quantity: number;
  invoiced_quantity: number;
  dispatched_quantity: number;
  delivered_quantity: number;
  returned_quantity: number;
  net_delivered_quantity: number;
  pending_delivery: number;
  difference: number;
  fulfillment_status: string;
  has_incident: boolean;
  available: number;
  suggested_to_invoice: number;
  shortage: number;
  complete: boolean;
  billing_result?: string;
  units_per_box?: number | null;
}

interface PurchaseOrder {
  id: string;
  chain_name: string;
  customer_name: string | null;
  order_number: string;
  order_date: string | null;
  destination: string | null;
  status: string;
  notes: string | null;
  lines: OrderLine[];
  source_documents: Array<ViewableDocument & { extraction_method: string }>;
  related_invoices: Array<{
    id: string; invoice_number: string; administrative_status: string;
    dispatch_status: string; delivery_status: string;
    dispatches: Array<{ id: string; dispatched_at: string }>;
    deliveries: Array<{ id: string; delivered_at: string }>;
  }>;
}

interface DraftLine { id: number; sku: string; quantity: string; units_per_box?: number | null; raw?: string; error?: string | null; suggestions?: string[] }
interface OperationalSettings { suggested_chains: string[] }

let nextDraftLineId = 1;
const emptyLine = (): DraftLine => ({ id: nextDraftLineId++, sku: "", quantity: "1" });
const DEFAULT_CHAINS = ["Favorita", "Rosado", "Danec", "Tía", "TUTI", "Mega Santa María", "Gerardo Ortiz"];
const normalize = (value: string) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es-EC");
const chainIdentity = (value: string) => ["tuti", "tiendas tuti"].includes(normalize(value).trim()) ? "tuti" : normalize(value).trim();
const fulfillmentLabels: Record<string, string> = {
  not_processed: "No procesado", pending: "Pendiente",
  invoicing_partial: "Facturación parcial", dispatch_partial: "Despacho parcial",
  delivery_partial: "Entrega parcial", delivered_complete: "Entregado completo",
  delivered_excess: "Entregado con exceso", with_return: "Con devolución",
  with_incident: "Con incidencia",
};

function ProductSearch({ products, value, disabledSkus, onChange, label }: {
  products: ProductOption[]; value: string; disabledSkus: Set<string>;
  onChange: (sku: string) => void; label: string;
}) {
  const selected = products.find((item) => item.sku === value);
  const [query, setQuery] = useState(selected ? `${selected.product_name} · SKU: ${selected.sku}` : "");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const matches = useMemo(() => {
    const terms = normalize(query).trim().split(/\s+/).filter(Boolean);
    return products.map((item) => {
      if (disabledSkus.has(item.sku) && item.sku !== value) return null;
      const sku = normalize(item.sku);
      const name = normalize(item.product_name);
      const text = `${sku} ${name} ${normalize(item.barcode ?? "")} ${normalize(item.contifico_aux_code ?? "")}`;
      if (terms.some((term) => !text.includes(term))) return null;
      const score = terms.reduce((sum, term) => sum + (sku === term ? 100 : sku.startsWith(term) ? 60 : name.startsWith(term) ? 35 : 10), 0);
      return { item, score };
    }).filter((entry): entry is { item: ProductOption; score: number } => entry !== null)
      .sort((a, b) => b.score - a.score || a.item.sku.localeCompare(b.item.sku))
      .slice(0, 8).map(({ item }) => item);
  }, [disabledSkus, products, query, value]);
  const choose = (sku: string) => {
    const product = products.find((item) => item.sku === sku);
    setQuery(product ? `${product.product_name} · SKU: ${product.sku}` : "");
    onChange(sku); setOpen(false); setActive(0);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") { event.preventDefault(); setOpen(true); setActive((current) => Math.min(current + 1, Math.max(matches.length - 1, 0))); }
    if (event.key === "ArrowUp") { event.preventDefault(); setActive((current) => Math.max(current - 1, 0)); }
    if (event.key === "Enter" && open && matches[active]) { event.preventDefault(); choose(matches[active].sku); }
    if (event.key === "Escape") setOpen(false);
  };
  return <label className="product-combobox"><span>{label}</span><div className="combobox">
    <input required role="combobox" aria-label={label} aria-autocomplete="list" aria-expanded={open} aria-controls="product-options"
      autoComplete="off" value={query} placeholder="Busca por nombre, SKU, variante o tamaño"
      onFocus={() => { setOpen(true); setActive(0); }}
      onBlur={() => window.setTimeout(() => setOpen(false), 120)}
      onKeyDown={onKeyDown}
      onChange={(event) => { setQuery(event.target.value); onChange(""); setOpen(true); setActive(0); }} />
    {value && <button className="combobox-clear" type="button" aria-label="Limpiar producto"
      onMouseDown={(event) => event.preventDefault()} onClick={() => { setQuery(""); onChange(""); setOpen(true); }}>×</button>}
    {open && <div className="combobox-options product-options" id="product-options" role="listbox">
      {matches.map((item, index) => <button key={item.id} type="button" role="option" aria-selected={index === active}
        onMouseDown={(event) => event.preventDefault()} onMouseEnter={() => setActive(index)} onClick={() => choose(item.sku)}>
        <strong>{item.product_name}</strong><span>SKU: {item.sku}</span>
      </button>)}
      {!matches.length && <span>No hay coincidencias en el catálogo.</span>}
    </div>}
  </div></label>;
}

export function PurchaseOrderCenter() {
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [products, setProducts] = useState<ProductOption[]>([]);
  const [suggestedChains, setSuggestedChains] = useState(DEFAULT_CHAINS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [showDocumentImport, setShowDocumentImport] = useState(false);
  const [quickMode, setQuickMode] = useState(false);
  const [quickText, setQuickText] = useState("");
  const [quickProcessed, setQuickProcessed] = useState(false);
  const [confirmedPreview, setConfirmedPreview] = useState(false);
  const [differenceOnly, setDifferenceOnly] = useState(false);
  const [billingFilter, setBillingFilter] = useState<"all" | "billable" | "shortage" | "no_stock" | "review">("all");
  const [detailPane, setDetailPane] = useState<"document" | "data" | "comparison">("comparison");
  const [selectedDocumentToken, setSelectedDocumentToken] = useState<string | null>(null);
  const [chainName, setChainName] = useState("");
  const [selectedChain, setSelectedChain] = useState("");
  const [chainMenuOpen, setChainMenuOpen] = useState(false);
  const [orderNumber, setOrderNumber] = useState("");
  const [orderDate, setOrderDate] = useState("");
  const [destination, setDestination] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([emptyLine()]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [keepChainDestination, setKeepChainDestination] = useState(false);
  const [templateConfirmed, setTemplateConfirmed] = useState(false);
  const [copyOrderId, setCopyOrderId] = useState("");
  const orderNumberRef = useRef<HTMLInputElement>(null);
  const submitLock = useRef(false);

  useEffect(() => {
    Promise.all([
      apiRequest<PurchaseOrder[]>("/purchase-orders"),
      apiRequest<ProductOption[]>("/inventory/availability"),
      apiRequest<OperationalSettings>("/settings/operational"),
    ])
      .then(([loadedOrders, loadedProducts, loadedSettings]) => {
        setOrders(loadedOrders.map((order) => ({
          ...order,
          source_documents: order.source_documents ?? [],
          related_invoices: order.related_invoices ?? [],
          lines: order.lines.map((line) => ({
            ...line,
            invoiced_quantity: line.invoiced_quantity ?? 0,
            dispatched_quantity: line.dispatched_quantity ?? 0,
            delivered_quantity: line.delivered_quantity ?? 0,
            returned_quantity: line.returned_quantity ?? 0,
            net_delivered_quantity: line.net_delivered_quantity ?? 0,
            pending_delivery: line.pending_delivery ?? line.ordered_quantity,
            difference: line.difference ?? -line.ordered_quantity,
            fulfillment_status: line.fulfillment_status ?? "not_processed",
            has_incident: line.has_incident ?? false,
          })),
        })));
        setProducts(loadedProducts);
        setSuggestedChains(loadedSettings.suggested_chains);
        setSelectedId(loadedOrders[0]?.id ?? null);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No pudimos cargar las órdenes de compra."))
      .finally(() => setLoading(false));
  }, []);

  const selected = useMemo(() => orders.find((order) => order.id === selectedId) ?? null, [orders, selectedId]);
  const billingLines = selected?.lines.filter((line) => {
    const pending = Math.max(line.ordered_quantity - line.invoiced_quantity, 0);
    if (billingFilter === "billable") return line.suggested_to_invoice > 0;
    if (billingFilter === "shortage") return line.shortage > 0;
    if (billingFilter === "no_stock") return pending > 0 && line.suggested_to_invoice === 0;
    if (billingFilter === "review") return !line.sku || !Number.isFinite(line.ordered_quantity) || line.ordered_quantity <= 0;
    return true;
  }) ?? [];
  const comparisonLines = selected?.lines.filter((line) => !differenceOnly || line.difference !== 0 || line.returned_quantity > 0 || line.has_incident) ?? [];
  const comparisonSummary = selected ? {
    products: selected.lines.length,
    ordered: selected.lines.reduce((sum, line) => sum + line.ordered_quantity, 0),
    invoiced: selected.lines.reduce((sum, line) => sum + line.invoiced_quantity, 0),
    dispatched: selected.lines.reduce((sum, line) => sum + line.dispatched_quantity, 0),
    delivered: selected.lines.reduce((sum, line) => sum + line.delivered_quantity, 0),
    pending: selected.lines.reduce((sum, line) => sum + Math.max(0, line.pending_delivery), 0),
    differences: selected.lines.filter((line) => line.difference !== 0 || line.returned_quantity > 0 || line.has_incident).length,
  } : null;
  const selectedDocument = selected?.source_documents.find((document) => document.token === selectedDocumentToken)
    ?? selected?.source_documents[0] ?? null;
  const selectedSkus = new Set(lines.map((line) => line.sku).filter(Boolean));
  const chainOptions = useMemo(() => {
    const unique = new Map<string, string>();
    for (const chain of [...DEFAULT_CHAINS, ...suggestedChains, ...orders.map((order) => order.chain_name)]) {
      const identity = chainIdentity(chain);
      if (!unique.has(identity)) unique.set(identity, identity === "tuti" ? "TUTI" : chain);
    }
    return [...unique.values()].sort((a, b) => a.localeCompare(b, "es-EC"));
  }, [orders, suggestedChains]);
  const visibleChains = chainOptions.filter((chain) => normalize(chain).includes(normalize(chainName)));

  const updateLine = (index: number, patch: Partial<DraftLine>) => {
    setLines((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, ...patch } : line));
  };
  const confirmQuickProduct = (index: number, sku: string) => {
    const selected = lines[index];
    if (!selected?.raw || !sku) { updateLine(index, { sku, error: null }); return; }
    setLines((current) => applyConfirmedAlias(current.map((line, lineIndex) => ({
      id: `order-alias-${lineIndex}`, raw: line.raw ?? "", quantity: Number(line.quantity) || null, sku: line.sku,
      error: line.error ?? null, suggestions: line.suggestions ?? [],
    })), selected.raw!, sku).map((line, lineIndex) => ({
      id: current[lineIndex]!.id, sku: line.sku, quantity: String(line.quantity ?? ""), raw: line.raw,
      error: line.error, suggestions: line.suggestions,
    })));
  };
  const retryRecognition = () => {
    setLines((current) => retryProductRecognition(current.map((line, index) => ({
      id: `order-line-${index}`, raw: line.raw ?? "", quantity: Number(line.quantity) || null, sku: line.sku,
      error: line.error ?? null, suggestions: line.suggestions ?? [],
    })), products).map((line, index) => ({ id: current[index]!.id, sku: line.sku, quantity: String(line.quantity ?? ""), raw: line.raw, error: line.error, suggestions: line.suggestions })));
  };

  const resetForm = (preserveContext = false) => {
    if (!preserveContext) { setChainName(""); setSelectedChain(""); setDestination(""); }
    setOrderNumber(""); setOrderDate(""); setNotes(""); setLines([emptyLine()]); setQuickText(""); setQuickProcessed(false);
    setConfirmedPreview(false); setTemplateConfirmed(false); setCopyOrderId(""); setQuickMode(false); setError(null);
  };
  const applyOrderTemplate = (order: PurchaseOrder) => {
    setShowDocumentImport(false); setShowForm(true); setQuickMode(false); setSuccess(null);
    setChainName(order.chain_name); setSelectedChain(order.chain_name); setDestination(order.destination ?? "");
    setOrderNumber(""); setOrderDate(""); setNotes("");
    setLines(order.lines.map((line) => ({ id: nextDraftLineId++, sku: line.sku, quantity: String(line.ordered_quantity), units_per_box: line.units_per_box })));
    setCopyOrderId(order.id); setTemplateConfirmed(false);
    window.setTimeout(() => orderNumberRef.current?.focus(), 0);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitLock.current) return;
    if (lines.some((line) => !line.sku || !/^[1-9]\d*$/.test(line.quantity.trim()))) {
      setError("Cada producto necesita una cantidad entera mayor que cero.");
      return;
    }
    if (copyOrderId && !templateConfirmed) {
      setError("Revisa y confirma la vista previa copiada antes de guardar.");
      return;
    }
    if (quickMode && (!quickProcessed || !confirmedPreview)) {
      setError("Procesa el texto, corrige todas las líneas y confirma la vista previa.");
      return;
    }
    setError(null);
    setSuccess(null);
    submitLock.current = true;
    setSaving(true);
    try {
      const created = await apiRequest<PurchaseOrder>("/purchase-orders", {
        method: "POST",
        body: JSON.stringify({
          chain_name: chainName,
          customer_name: chainName,
          order_number: orderNumber,
          order_date: orderDate || null,
          destination: destination || null,
          notes: notes || null,
          lines: lines.map(({ sku, quantity, units_per_box }) => ({ sku, quantity: Number(quantity), units_per_box })),
        }),
      });
      setOrders((current) => [created, ...current]);
      setSuccess("OC registrada correctamente");
      resetForm(keepChainDestination);
      window.setTimeout(() => orderNumberRef.current?.focus(), 0);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos registrar la OC.");
    } finally {
      submitLock.current = false;
      setSaving(false);
    }
  };
  const prepareInvoice = (order: PurchaseOrder) => {
    sessionStorage.setItem("inventario.invoiceTemplate", JSON.stringify({
      id: "", number: "", date: "", customer: order.chain_name, chain: order.chain_name,
      source_type: "purchase_order", authorization_number: null, remittance_guide: null,
      total_value: null, notes: order.source_documents[0] ? `Documento original: ${order.source_documents[0].filename}` : null,
      purchase_order_id: order.id,
      lines: order.lines.filter((line) => line.suggested_to_invoice > 0).map((line) => ({ sku: line.sku, invoiced: line.suggested_to_invoice })),
    }));
    window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "invoices" }));
  };

  return (
    <main className="dashboard order-center">
      <section className="module-heading">
        <div className="welcome-block"><p className="eyebrow">Documento de origen</p><h1>Órdenes de Compra</h1><p>Registra el pedido original de cada cadena y contrástalo con el inventario realmente disponible.</p></div>
        <div className="heading-actions">{!showDocumentImport && <button className="secondary-button" type="button" onClick={() => { setShowDocumentImport(true); setShowForm(false); setError(null); setSuccess(null); }}>Leer PDF o imagen</button>}{!showDocumentImport && <button className="primary-button" type="button" onClick={() => { setShowForm((value) => !value); setError(null); setSuccess(null); }}>{showForm ? "Cancelar" : "Nueva OC"}</button>}</div>
      </section>

      {error && <div className="message error" role="alert">{error}</div>}
      {success && <div className="message success po-toast" role="status">{success}</div>}

      {showDocumentImport && <PurchaseOrderDocumentImport products={products} orders={orders} onCreated={(created) => {
        setOrders((current) => [created as PurchaseOrder, ...current]);
        setShowDocumentImport(false); setShowForm(true); setSuccess("OC registrada correctamente");
        resetForm(keepChainDestination);
        window.setTimeout(() => orderNumberRef.current?.focus(), 0);
      }} onCancel={() => { setShowDocumentImport(false); setShowForm(true); }} />}

      {!showDocumentImport && showForm && <form className="order-form" onSubmit={submit}>
        <div className="form-section-title"><div><h2>Nueva orden de compra</h2><p>La numeración puede repetirse entre cadenas, pero no dentro de la misma cadena.</p></div>
          <div className="mode-switch" role="group" aria-label="Modo de registro"><button type="button" className={!quickMode ? "active" : ""} onClick={() => { setQuickMode(false); setLines([emptyLine()]); }}>Ingreso manual</button><button type="button" onClick={() => { setShowDocumentImport(true); setShowForm(false); }}>Leer PDF o imagen</button><button type="button" className={quickMode ? "active" : ""} onClick={() => { setQuickMode(true); setLines([]); }}>Pegar líneas</button></div>
        </div>
        <div className="form-grid">
          <label className="combobox-field"><span>Cadena *</span><div className="combobox"><input required minLength={2} role="combobox" aria-label="Cadena" aria-autocomplete="list" aria-expanded={chainMenuOpen} aria-controls="chain-options" autoComplete="off" value={chainName} onFocus={() => setChainMenuOpen(true)} onBlur={() => window.setTimeout(() => setChainMenuOpen(false), 120)} onChange={(event) => { setChainName(event.target.value); setSelectedChain(""); setChainMenuOpen(true); }} placeholder="Escribe para filtrar o agregar otra" />{chainName && selectedChain === chainName ? <span className="selected-check" aria-label="Cadena seleccionada">✓</span> : null}{chainMenuOpen && <div className="combobox-options" id="chain-options" role="listbox">{visibleChains.map((chain) => <button key={chain} type="button" role="option" aria-selected={selectedChain === chain} onMouseDown={(event) => event.preventDefault()} onClick={() => { setChainName(chain); setSelectedChain(chain); setChainMenuOpen(false); }}>{chain}</button>)}{visibleChains.length === 0 && <span>“{chainName}” se guardará como una cadena nueva.</span>}</div>}</div><small>Elige una sugerencia o escribe una cadena nueva.</small></label>
           <label><span>Número de OC *</span><input ref={orderNumberRef} required value={orderNumber} onChange={(event) => setOrderNumber(event.target.value)} placeholder="Número del documento" /></label>
          <label><span>Fecha de OC</span><input type="date" value={orderDate} onChange={(event) => setOrderDate(event.target.value)} /></label>
          <label className="wide"><span>Destino</span><input value={destination} onChange={(event) => setDestination(event.target.value)} placeholder="CD o lugar de entrega" /></label>
        </div>
        {!quickMode && <label className="copy-order-field"><span>Copiar productos de otra OC</span><select value={copyOrderId} onChange={(event) => { const order = orders.find((item) => item.id === event.target.value); if (order) applyOrderTemplate(order); else { setCopyOrderId(""); setTemplateConfirmed(false); } }}><option value="">No copiar</option>{orders.map((order) => <option key={order.id} value={order.id}>{order.chain_name} · {order.order_number}</option>)}</select></label>}
        {quickMode && <section className="quick-paste-panel"><label><span>Pega productos y cantidades</span><textarea rows={7} value={quickText} onChange={(event) => { setQuickText(event.target.value); setQuickProcessed(false); setConfirmedPreview(false); }} placeholder={"372 | AR004\n300 | SHAMPOO REGENEXT ARGAN 400 ML"} /><small>Formato admitido: cantidad | código o nombre del producto. Una línea por producto.</small></label><button className="secondary-button" type="button" onClick={() => { const parsed = parseProductLines(quickText, products); setLines(parsed.map((line) => ({ id: nextDraftLineId++, sku: line.sku, quantity: String(line.quantity ?? ""), raw: line.raw, error: line.error, suggestions: line.suggestions }))); setQuickProcessed(true); setConfirmedPreview(false); }}>Pegar y procesar</button></section>}
        <div className="order-lines"><div className="line-heading"><div><h3>{quickMode ? "Vista previa de productos" : "Productos solicitados"}</h3>{quickMode && <p>Corrige en la tabla cualquier coincidencia no reconocida.</p>}</div>{quickMode ? <button className="text-button" type="button" onClick={retryRecognition}>Reintentar reconocimiento</button> : <button className="text-button" type="button" onClick={() => setLines((current) => [...current, emptyLine()])}>+ Agregar producto</button>}</div>
          {quickMode && !quickProcessed && <div className="table-message">Pega la lista y pulsa “Pegar y procesar” para generar la vista previa.</div>}
          {lines.map((line, index) => {
            const product = products.find((item) => item.sku === line.sku);
            return <div className={`draft-line ${quickMode && !line.sku ? "unrecognized-line" : ""}`} key={line.id}>
              <ProductSearch products={products} value={line.sku} disabledSkus={selectedSkus} label={quickMode ? line.raw || "Producto" : "Producto"} onChange={(sku) => quickMode ? confirmQuickProduct(index, sku) : updateLine(index, { sku, error: null })} />
              <label><span>Cantidad</span><input required inputMode="numeric" value={line.quantity} aria-invalid={line.quantity !== "" && !/^[1-9]\d*$/.test(line.quantity)} onFocus={(event) => event.currentTarget.select()} onChange={(event) => updateLine(index, { quantity: event.target.value })} onBlur={() => { if (!/^[1-9]\d*$/.test(line.quantity)) updateLine(index, { error: "Ingresa una cantidad mayor que cero." }); }} />{line.error && <small className="field-error">{line.error}</small>}</label>
              <div className="availability-hint"><span>Disponible ahora</span><strong>{product?.available_to_invoice ?? "—"}</strong></div>
              {lines.length > 1 && <button className="remove-line" aria-label={`Eliminar producto ${index + 1}`} type="button" onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}>×</button>}
            </div>;
          })}
        </div>
        {quickMode && quickProcessed && lines.length > 0 && <label className="preview-confirm"><input type="checkbox" checked={confirmedPreview} onChange={(event) => setConfirmedPreview(event.target.checked)} /><span>Revisé la vista previa y confirmo esta orden de compra.</span></label>}
        {copyOrderId && <label className="preview-confirm"><input type="checkbox" checked={templateConfirmed} onChange={(event) => setTemplateConfirmed(event.target.checked)} /><span>Revisé los productos y cantidades copiados y confirmo esta nueva OC.</span></label>}
        <label className="notes-field"><span>Observaciones</span><textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} /></label>
        <label className="keep-context"><input type="checkbox" checked={keepChainDestination} onChange={(event) => setKeepChainDestination(event.target.checked)} /><span>Conservar cadena y destino para la siguiente OC</span></label>
        <div className="form-actions"><button className="primary-button" disabled={saving || (quickMode && (!quickProcessed || !confirmedPreview || lines.length === 0)) || (copyOrderId !== "" && !templateConfirmed)} type="submit">{saving ? "Registrando…" : quickMode ? "Confirmar y registrar OC" : "Registrar OC"}</button></div>
      </form>}

      {!showDocumentImport && !showForm && <section className="order-workspace">
        <aside className="order-list">
          <div className="list-title"><strong>Órdenes registradas</strong><span>{orders.length}</span></div>
          {loading && <div className="table-message">Cargando órdenes…</div>}
          {!loading && orders.map((order) => <div className="order-list-entry" key={order.id}><button type="button" className={`order-list-item ${selectedId === order.id ? "selected" : ""}`} onClick={() => { setSelectedId(order.id); setSelectedDocumentToken(order.source_documents[0]?.token ?? null); setDetailPane("comparison"); }}><strong>{order.order_number}</strong><span>{order.chain_name}</span><small>{order.lines.length} producto{order.lines.length === 1 ? "" : "s"}</small></button><button className="template-link" type="button" onClick={() => applyOrderTemplate(order)}>Usar como plantilla</button></div>)}
          {!loading && orders.length === 0 && <div className="table-message">Todavía no hay órdenes. Registra la primera para comenzar el flujo.</div>}
        </aside>
        <div className="order-detail">
          {!selected && !loading && <div className="empty-detail"><strong>La OC inicia la trazabilidad</strong><span>Luego podrás reservar stock y vincular la factura correcta.</span></div>}
          {selected && <><header className="detail-header"><div><p className="eyebrow">{selected.chain_name}</p><h2>OC {selected.order_number}</h2><p>{selected.destination ?? "Sin destino especificado"}</p></div><div className="detail-actions"><span className="status-pill available">{selected.status === "open" ? "Abierta" : selected.status === "partially_invoiced" ? "Facturada parcialmente" : selected.status === "completed" ? "Completamente facturada" : "Cancelada"}</span><button className="secondary-button" type="button" onClick={() => applyOrderTemplate(selected)}>Usar como plantilla</button><button className="primary-button" type="button" disabled={!selected.lines.some((line) => line.suggested_to_invoice > 0)} onClick={() => prepareInvoice(selected)}>Preparar factura</button></div></header>
            <div className="mobile-detail-tabs" role="group" aria-label="Vista de la orden"><button type="button" className={detailPane === "document" ? "active" : ""} onClick={() => setDetailPane("document")}>Documento original</button><button type="button" className={detailPane === "data" ? "active" : ""} onClick={() => setDetailPane("data")}>Datos reconocidos</button><button type="button" className={detailPane === "comparison" ? "active" : ""} onClick={() => setDetailPane("comparison")}>Comparación</button></div>
            <section className={`trace-section detail-data-pane mobile-pane-${detailPane}`}><div className="line-heading"><h3>Disponibilidad y facturación</h3><div className="billing-filters" role="group" aria-label="Filtrar disponibilidad">{([["all", "Todos"], ["billable", "Facturables"], ["shortage", "Con faltantes"], ["no_stock", "Sin inventario"], ["review", "Pendientes de revisión"]] as const).map(([value, label]) => <button type="button" className={billingFilter === value ? "active" : ""} key={value} onClick={() => setBillingFilter(value)}>{label}</button>)}</div></div><div className="table-scroll"><table><thead><tr><th>Producto</th><th>Pedido</th><th>Ya facturado</th><th>Pendiente</th><th>Disponible</th><th>Sugerido a facturar</th><th>Faltante</th><th>Resultado</th></tr></thead><tbody>{billingLines.map((line) => <tr key={line.sku} className={line.complete ? "" : "row-warning"}><td><ProductIdentity name={line.product_name} sku={line.sku} /></td><td>{line.ordered_quantity}</td><td>{line.invoiced_quantity}</td><td>{Math.max(line.ordered_quantity - line.invoiced_quantity, 0)}</td><td>{line.available}</td><td><strong>{line.suggested_to_invoice}</strong></td><td>{line.shortage}</td><td><span className={`status-pill ${line.complete ? "available" : "low_stock"}`}>{line.billing_result ?? (line.complete ? "Lista para facturar completa" : "Con faltante")}</span></td></tr>)}</tbody></table>{billingLines.length === 0 && <div className="table-message">No hay productos en este filtro.</div>}</div></section>
            <section className="po-document-comparison">
              <aside className={`po-original-panel mobile-pane-${detailPane}`}><h3>Documento original de la orden de compra</h3>{selected.source_documents.length > 1 && <div className="document-selector">{selected.source_documents.map((document) => <button type="button" className={selectedDocument?.token === document.token ? "active" : ""} key={document.token} onClick={() => setSelectedDocumentToken(document.token)}>{document.filename}</button>)}</div>}{selectedDocument ? <DocumentViewer document={selectedDocument} url={apiUrl(`/purchase-orders/imports/${selectedDocument.token}/content`)} /> : <div className="table-message">Esta OC no fue creada desde un documento.</div>}</aside>
              <div className={`po-comparison-panel mobile-pane-${detailPane}`}><div className="line-heading"><div><h3>Comparación: pedido vs. cumplimiento</h3><p>Las entregas se muestran en bruto; las devoluciones permanecen separadas según la regla actual.</p></div><label className="difference-filter"><input type="checkbox" checked={differenceOnly} onChange={(event) => setDifferenceOnly(event.target.checked)} /> Solo con diferencias</label></div>
                {comparisonSummary && <div className="fulfillment-summary"><div><span>Productos</span><strong>{comparisonSummary.products}</strong></div><div><span>Unidades pedidas</span><strong>{comparisonSummary.ordered}</strong></div><div><span>Facturadas</span><strong>{comparisonSummary.invoiced}</strong></div><div><span>Despachadas</span><strong>{comparisonSummary.dispatched}</strong></div><div><span>Entregadas</span><strong>{comparisonSummary.delivered}</strong></div><div><span>Pendiente</span><strong>{comparisonSummary.pending}</strong></div><div><span>Con diferencias</span><strong>{comparisonSummary.differences}</strong></div></div>}
                <div className="table-scroll"><table className="fulfillment-table"><thead><tr><th>Producto</th><th>Pedido</th><th>Facturado</th><th>Despachado</th><th>Entregado</th><th>Devuelto</th><th>Neto</th><th>Pendiente</th><th>Diferencia</th><th>Estado</th></tr></thead><tbody>{comparisonLines.map((line) => <tr key={line.sku} className={line.difference !== 0 || line.returned_quantity || line.has_incident ? "row-warning" : ""}><td><ProductIdentity name={line.product_name} sku={line.sku} /></td><td>{line.ordered_quantity}</td><td>{line.invoiced_quantity}</td><td>{line.dispatched_quantity}</td><td>{line.delivered_quantity}</td><td>{line.returned_quantity}</td><td>{line.net_delivered_quantity}</td><td>{line.pending_delivery}</td><td>{line.difference > 0 ? `+${line.difference}` : line.difference}</td><td><span className={`fulfillment-status ${line.fulfillment_status}`}>{fulfillmentLabels[line.fulfillment_status] ?? line.fulfillment_status}</span></td></tr>)}</tbody></table>{!comparisonLines.length && <div className="table-message">No hay productos con diferencias.</div>}</div>
                {selected.related_invoices.length > 0 && <section className="related-operations"><h4>Documentos y operaciones relacionadas</h4>{selected.related_invoices.map((invoice) => <article key={invoice.id}><div><strong>Factura {invoice.invoice_number}</strong><span>{invoice.dispatch_status} · {invoice.delivery_status}</span></div><div className="operation-links"><button type="button" onClick={() => { sessionStorage.setItem("inventario.openInvoiceId", invoice.id); window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "invoices" })); }}>Abrir factura</button>{invoice.dispatches.length > 0 && <button type="button" onClick={() => window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "dispatches" }))}>Ver despachos</button>}{invoice.deliveries.length > 0 && <button type="button" onClick={() => window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "deliveries" }))}>Ver entregas</button>}</div><small>{invoice.dispatches.length} despachos · {invoice.deliveries.length} entregas</small></article>)}</section>}
              </div>
            </section>
            {selected.notes && <section className="trace-section order-notes"><h3>Observaciones</h3><p>{selected.notes}</p></section>}
          </>}
        </div>
      </section>}
    </main>
  );
}
