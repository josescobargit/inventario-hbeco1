import { FormEvent, useEffect, useMemo, useState } from "react";

import { apiRequest, apiUrl } from "../../api/client";
import {
  applyConfirmedAlias, parseProductLines, retryProductRecognition,
} from "../invoices/quickEntry";
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

interface DraftLine { sku: string; quantity: number; raw?: string; error?: string | null; suggestions?: string[] }
interface OperationalSettings { suggested_chains: string[] }

const emptyLine = (): DraftLine => ({ sku: "", quantity: 1 });
const DEFAULT_CHAINS = ["Favorita", "El Rosado", "Danec", "Tía", "Mega Santa María", "Gerardo Ortiz"];
const normalize = (value: string) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es-EC");
const fulfillmentLabels: Record<string, string> = {
  not_processed: "No procesado", pending: "Pendiente",
  invoicing_partial: "Facturación parcial", dispatch_partial: "Despacho parcial",
  delivery_partial: "Entrega parcial", delivered_complete: "Entregado completo",
  delivered_excess: "Entregado con exceso", with_return: "Con devolución",
  with_incident: "Con incidencia",
};

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
  const [detailPane, setDetailPane] = useState<"document" | "data" | "comparison">("comparison");
  const [selectedDocumentToken, setSelectedDocumentToken] = useState<string | null>(null);
  const [chainName, setChainName] = useState("");
  const [selectedChain, setSelectedChain] = useState("");
  const [chainMenuOpen, setChainMenuOpen] = useState(false);
  const [customerName, setCustomerName] = useState("");
  const [orderNumber, setOrderNumber] = useState("");
  const [orderDate, setOrderDate] = useState("");
  const [destination, setDestination] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([emptyLine()]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
  const chainOptions = useMemo(() => Array.from(new Set([...suggestedChains, ...orders.map((order) => order.chain_name)])).sort((a, b) => a.localeCompare(b, "es-EC")), [orders, suggestedChains]);
  const visibleChains = chainOptions.filter((chain) => normalize(chain).includes(normalize(chainName)));

  const updateLine = (index: number, patch: Partial<DraftLine>) => {
    setLines((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, ...patch } : line));
  };
  const confirmQuickProduct = (index: number, sku: string) => {
    const selected = lines[index];
    if (!selected?.raw || !sku) { updateLine(index, { sku, error: null }); return; }
    setLines((current) => applyConfirmedAlias(current.map((line, lineIndex) => ({
      id: `order-alias-${lineIndex}`, raw: line.raw ?? "", quantity: line.quantity, sku: line.sku,
      error: line.error ?? null, suggestions: line.suggestions ?? [],
    })), selected.raw!, sku).map((line) => ({
      sku: line.sku, quantity: line.quantity ?? 0, raw: line.raw,
      error: line.error, suggestions: line.suggestions,
    })));
  };
  const retryRecognition = () => {
    setLines((current) => retryProductRecognition(current.map((line, index) => ({
      id: `order-line-${index}`, raw: line.raw ?? "", quantity: line.quantity, sku: line.sku,
      error: line.error ?? null, suggestions: line.suggestions ?? [],
    })), products).map((line) => ({ sku: line.sku, quantity: line.quantity ?? 0, raw: line.raw, error: line.error, suggestions: line.suggestions })));
  };

  const resetForm = () => {
    setChainName(""); setSelectedChain(""); setCustomerName(""); setOrderNumber(""); setOrderDate("");
    setDestination(""); setNotes(""); setLines([emptyLine()]); setQuickText(""); setQuickProcessed(false);
    setConfirmedPreview(false); setQuickMode(false); setError(null);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (quickMode && (!quickProcessed || !confirmedPreview || lines.some((line) => !line.sku || line.quantity <= 0))) {
      setError("Procesa el texto, corrige todas las líneas y confirma la vista previa.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      const created = await apiRequest<PurchaseOrder>("/purchase-orders", {
        method: "POST",
        body: JSON.stringify({
          chain_name: chainName,
          customer_name: customerName || null,
          order_number: orderNumber,
          order_date: orderDate || null,
          destination: destination || null,
          notes: notes || null,
          lines: lines.map(({ sku, quantity }) => ({ sku, quantity })),
        }),
      });
      setOrders((current) => [created, ...current]);
      setSelectedId(created.id);
      setShowForm(false);
      resetForm();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos registrar la OC.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="dashboard order-center">
      <section className="module-heading">
        <div className="welcome-block"><p className="eyebrow">Documento de origen</p><h1>Órdenes de Compra</h1><p>Registra el pedido original de cada cadena y contrástalo con el inventario realmente disponible.</p></div>
        <div className="heading-actions">{!showDocumentImport && <button className="secondary-button" type="button" onClick={() => { setShowDocumentImport(true); setShowForm(false); setError(null); }}>Crear OC desde PDF, imagen o pedido</button>}{!showDocumentImport && <button className="primary-button" type="button" onClick={() => { setShowForm((value) => !value); setError(null); }}>{showForm ? "Cancelar" : "Nueva OC"}</button>}</div>
      </section>

      {error && <div className="message error" role="alert">{error}</div>}

      {showDocumentImport && <PurchaseOrderDocumentImport products={products} orders={orders} onCreated={(created) => { setOrders((current) => [created as PurchaseOrder, ...current]); setSelectedId(created.id); }} onCancel={() => setShowDocumentImport(false)} />}

      {!showDocumentImport && showForm && <form className="order-form" onSubmit={submit}>
        <div className="form-section-title"><div><h2>Nueva orden de compra</h2><p>La numeración puede repetirse entre cadenas, pero no dentro de la misma cadena.</p></div>
          <div className="mode-switch" role="group" aria-label="Modo de registro"><button type="button" className={!quickMode ? "active" : ""} onClick={() => { setQuickMode(false); setLines([emptyLine()]); }}>Ingreso manual</button><button type="button" className={quickMode ? "active" : ""} onClick={() => { setQuickMode(true); setLines([]); }}>Registro rápido</button></div>
        </div>
        <div className="form-grid">
          <label className="combobox-field"><span>{quickMode ? "Cliente/Cadena *" : "Cadena *"}</span><div className="combobox"><input required minLength={2} role="combobox" aria-autocomplete="list" aria-expanded={chainMenuOpen} aria-controls="chain-options" autoComplete="off" value={chainName} onFocus={() => setChainMenuOpen(true)} onBlur={() => window.setTimeout(() => setChainMenuOpen(false), 120)} onChange={(event) => { setChainName(event.target.value); setSelectedChain(""); setChainMenuOpen(true); }} placeholder="Escribe para filtrar o agregar otra" />{selectedChain === chainName && <span className="selected-check" aria-label="Cadena seleccionada">✓</span>}{chainMenuOpen && <div className="combobox-options" id="chain-options" role="listbox">{visibleChains.map((chain) => <button key={chain} type="button" role="option" aria-selected={selectedChain === chain} onMouseDown={(event) => event.preventDefault()} onClick={() => { setChainName(chain); setSelectedChain(chain); setChainMenuOpen(false); }}>{chain}</button>)}{visibleChains.length === 0 && <span>“{chainName}” se guardará como una cadena nueva.</span>}</div>}</div><small>Elige una sugerencia o escribe una cadena nueva.</small></label>
           <label><span>Número de OC *</span><input required value={orderNumber} onChange={(event) => setOrderNumber(event.target.value)} placeholder="Número del documento" /></label>
          {!quickMode && <label><span>Cliente o razón social</span><input value={customerName} onChange={(event) => setCustomerName(event.target.value)} /></label>}
          <label><span>Fecha de OC</span><input type="date" value={orderDate} onChange={(event) => setOrderDate(event.target.value)} /></label>
          <label className="wide"><span>Destino</span><input value={destination} onChange={(event) => setDestination(event.target.value)} placeholder="CD o lugar de entrega" /></label>
        </div>
        {quickMode && <section className="quick-paste-panel"><label><span>Pega productos y cantidades</span><textarea rows={7} value={quickText} onChange={(event) => { setQuickText(event.target.value); setQuickProcessed(false); setConfirmedPreview(false); }} placeholder={"480.00 TOALLITAS HÚMEDAS ANA X 100 - ACP001\n120.00 SHAMPOO ANA REGENEXT 400 ML"} /></label><button className="secondary-button" type="button" onClick={() => { const parsed = parseProductLines(quickText, products); setLines(parsed.map((line) => ({ sku: line.sku, quantity: line.quantity ?? 0, raw: line.raw, error: line.error, suggestions: line.suggestions }))); setQuickProcessed(true); setConfirmedPreview(false); }}>Pegar y procesar</button></section>}
        <div className="order-lines"><div className="line-heading"><div><h3>{quickMode ? "Vista previa de productos" : "Productos solicitados"}</h3>{quickMode && <p>Corrige en la tabla cualquier coincidencia no reconocida.</p>}</div>{quickMode ? <button className="text-button" type="button" onClick={retryRecognition}>Reintentar reconocimiento</button> : <button className="text-button" type="button" onClick={() => setLines((current) => [...current, emptyLine()])}>+ Agregar producto</button>}</div>
          {quickMode && !quickProcessed && <div className="table-message">Pega la lista y pulsa “Pegar y procesar” para generar la vista previa.</div>}
          {lines.map((line, index) => {
            const product = products.find((item) => item.sku === line.sku);
            return <div className={`draft-line ${quickMode && !line.sku ? "unrecognized-line" : ""}`} key={index}>
              <label><span>{quickMode ? line.raw || "Producto" : "Producto"}</span><select required value={line.sku} onChange={(event) => quickMode ? confirmQuickProduct(index, event.target.value) : updateLine(index, { sku: event.target.value, error: null })}><option value="">Selecciona un producto</option>{products.map((item) => <option key={item.id} value={item.sku} disabled={selectedSkus.has(item.sku) && item.sku !== line.sku}>{item.sku} · {item.product_name}</option>)}</select>{line.suggestions?.length ? <small>Sugerencias: {line.suggestions.join(", ")}</small> : null}{line.error && <small className="field-error">{line.error}</small>}</label>
              <label><span>Cantidad</span><input required min={1} type="number" value={line.quantity} onChange={(event) => updateLine(index, { quantity: Number(event.target.value) })} /></label>
              <div className="availability-hint"><span>Disponible ahora</span><strong>{product?.available_to_invoice ?? "—"}</strong></div>
              {lines.length > 1 && <button className="remove-line" aria-label={`Eliminar producto ${index + 1}`} type="button" onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}>×</button>}
            </div>;
          })}
        </div>
        {quickMode && quickProcessed && lines.length > 0 && <label className="preview-confirm"><input type="checkbox" checked={confirmedPreview} onChange={(event) => setConfirmedPreview(event.target.checked)} /><span>Revisé la vista previa y confirmo esta orden de compra.</span></label>}
        <label className="notes-field"><span>Observaciones</span><textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} /></label>
        <div className="form-actions"><button className="primary-button" disabled={saving || (quickMode && (!quickProcessed || !confirmedPreview || lines.length === 0 || lines.some((line) => !line.sku || line.quantity <= 0)))} type="submit">{saving ? "Registrando…" : quickMode ? "Confirmar y registrar OC" : "Registrar OC"}</button></div>
      </form>}

      {!showDocumentImport && !showForm && <section className="order-workspace">
        <aside className="order-list">
          <div className="list-title"><strong>Órdenes registradas</strong><span>{orders.length}</span></div>
          {loading && <div className="table-message">Cargando órdenes…</div>}
          {!loading && orders.map((order) => <button key={order.id} type="button" className={`order-list-item ${selectedId === order.id ? "selected" : ""}`} onClick={() => { setSelectedId(order.id); setSelectedDocumentToken(order.source_documents[0]?.token ?? null); setDetailPane("comparison"); }}><strong>{order.order_number}</strong><span>{order.chain_name}</span><small>{order.lines.length} producto{order.lines.length === 1 ? "" : "s"}</small></button>)}
          {!loading && orders.length === 0 && <div className="table-message">Todavía no hay órdenes. Registra la primera para comenzar el flujo.</div>}
        </aside>
        <div className="order-detail">
          {!selected && !loading && <div className="empty-detail"><strong>La OC inicia la trazabilidad</strong><span>Luego podrás reservar stock y vincular la factura correcta.</span></div>}
          {selected && <><header className="detail-header"><div><p className="eyebrow">{selected.chain_name}</p><h2>OC {selected.order_number}</h2><p>{selected.customer_name ?? "Cliente no especificado"}{selected.destination ? ` · ${selected.destination}` : ""}</p></div><span className="status-pill available">{selected.status}</span></header>
            <div className="mobile-detail-tabs" role="group" aria-label="Vista de la orden"><button type="button" className={detailPane === "document" ? "active" : ""} onClick={() => setDetailPane("document")}>Documento original</button><button type="button" className={detailPane === "data" ? "active" : ""} onClick={() => setDetailPane("data")}>Datos reconocidos</button><button type="button" className={detailPane === "comparison" ? "active" : ""} onClick={() => setDetailPane("comparison")}>Comparación</button></div>
            <section className={`trace-section detail-data-pane mobile-pane-${detailPane}`}><h3>Disponibilidad por producto</h3><div className="table-scroll"><table><thead><tr><th>Producto</th><th>Pedido</th><th>Disponible</th><th>Sugerido a facturar</th><th>Faltante</th><th>Resultado</th></tr></thead><tbody>{selected.lines.map((line) => <tr key={line.sku} className={line.complete ? "" : "row-warning"}><td><strong>{line.sku}</strong><span>{line.product_name}</span></td><td>{line.ordered_quantity}</td><td>{line.available}</td><td><strong>{line.suggested_to_invoice}</strong></td><td>{line.shortage}</td><td><span className={`status-pill ${line.complete ? "available" : "low_stock"}`}>{line.complete ? "Completo" : "Con faltante"}</span></td></tr>)}</tbody></table></div></section>
            <section className="po-document-comparison">
              <aside className={`po-original-panel mobile-pane-${detailPane}`}><h3>Documento original de la orden de compra</h3>{selected.source_documents.length > 1 && <div className="document-selector">{selected.source_documents.map((document) => <button type="button" className={selectedDocument?.token === document.token ? "active" : ""} key={document.token} onClick={() => setSelectedDocumentToken(document.token)}>{document.filename}</button>)}</div>}{selectedDocument ? <DocumentViewer document={selectedDocument} url={apiUrl(`/purchase-orders/imports/${selectedDocument.token}/content`)} /> : <div className="table-message">Esta OC no fue creada desde un documento.</div>}</aside>
              <div className={`po-comparison-panel mobile-pane-${detailPane}`}><div className="line-heading"><div><h3>Comparación: pedido vs. cumplimiento</h3><p>Las entregas se muestran en bruto; las devoluciones permanecen separadas según la regla actual.</p></div><label className="difference-filter"><input type="checkbox" checked={differenceOnly} onChange={(event) => setDifferenceOnly(event.target.checked)} /> Solo con diferencias</label></div>
                {comparisonSummary && <div className="fulfillment-summary"><div><span>Productos</span><strong>{comparisonSummary.products}</strong></div><div><span>Unidades pedidas</span><strong>{comparisonSummary.ordered}</strong></div><div><span>Facturadas</span><strong>{comparisonSummary.invoiced}</strong></div><div><span>Despachadas</span><strong>{comparisonSummary.dispatched}</strong></div><div><span>Entregadas</span><strong>{comparisonSummary.delivered}</strong></div><div><span>Pendiente</span><strong>{comparisonSummary.pending}</strong></div><div><span>Con diferencias</span><strong>{comparisonSummary.differences}</strong></div></div>}
                <div className="table-scroll"><table className="fulfillment-table"><thead><tr><th>Código / Producto</th><th>Pedido</th><th>Facturado</th><th>Despachado</th><th>Entregado</th><th>Devuelto</th><th>Neto</th><th>Pendiente</th><th>Diferencia</th><th>Estado</th></tr></thead><tbody>{comparisonLines.map((line) => <tr key={line.sku} className={line.difference !== 0 || line.returned_quantity || line.has_incident ? "row-warning" : ""}><td><strong>{line.sku}</strong><span>{line.product_name}</span></td><td>{line.ordered_quantity}</td><td>{line.invoiced_quantity}</td><td>{line.dispatched_quantity}</td><td>{line.delivered_quantity}</td><td>{line.returned_quantity}</td><td>{line.net_delivered_quantity}</td><td>{line.pending_delivery}</td><td>{line.difference > 0 ? `+${line.difference}` : line.difference}</td><td><span className={`fulfillment-status ${line.fulfillment_status}`}>{fulfillmentLabels[line.fulfillment_status] ?? line.fulfillment_status}</span></td></tr>)}</tbody></table>{!comparisonLines.length && <div className="table-message">No hay productos con diferencias.</div>}</div>
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
