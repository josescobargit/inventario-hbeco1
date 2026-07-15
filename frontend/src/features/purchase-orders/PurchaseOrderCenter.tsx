import { FormEvent, useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";

interface ProductOption {
  sku: string;
  product_name: string;
  available_to_invoice: number;
}

interface OrderLine {
  sku: string;
  product_name: string;
  ordered_quantity: number;
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
}

interface DraftLine { sku: string; quantity: number }
interface OperationalSettings { suggested_chains: string[] }

const emptyLine = (): DraftLine => ({ sku: "", quantity: 1 });
const DEFAULT_CHAINS = ["Favorita", "El Rosado", "Danec", "Tía", "Mega Santa María", "Gerardo Ortiz"];
const normalize = (value: string) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es-EC");

export function PurchaseOrderCenter() {
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [products, setProducts] = useState<ProductOption[]>([]);
  const [suggestedChains, setSuggestedChains] = useState(DEFAULT_CHAINS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
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
        setOrders(loadedOrders);
        setProducts(loadedProducts);
        setSuggestedChains(loadedSettings.suggested_chains);
        setSelectedId(loadedOrders[0]?.id ?? null);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No pudimos cargar las órdenes de compra."))
      .finally(() => setLoading(false));
  }, []);

  const selected = useMemo(() => orders.find((order) => order.id === selectedId) ?? null, [orders, selectedId]);
  const selectedSkus = new Set(lines.map((line) => line.sku).filter(Boolean));
  const chainOptions = useMemo(() => Array.from(new Set([...suggestedChains, ...orders.map((order) => order.chain_name)])).sort((a, b) => a.localeCompare(b, "es-EC")), [orders, suggestedChains]);
  const visibleChains = chainOptions.filter((chain) => normalize(chain).includes(normalize(chainName)));

  const updateLine = (index: number, patch: Partial<DraftLine>) => {
    setLines((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, ...patch } : line));
  };

  const resetForm = () => {
    setChainName(""); setSelectedChain(""); setCustomerName(""); setOrderNumber(""); setOrderDate("");
    setDestination(""); setNotes(""); setLines([emptyLine()]); setError(null);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
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
          lines,
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
        <button className="primary-button" type="button" onClick={() => { setShowForm((value) => !value); setError(null); }}>{showForm ? "Cancelar" : "Nueva OC"}</button>
      </section>

      {error && <div className="message error" role="alert">{error}</div>}

      {showForm && <form className="order-form" onSubmit={submit}>
        <div className="form-section-title"><div><h2>Nueva orden de compra</h2><p>La numeración puede repetirse entre cadenas, pero no dentro de la misma cadena.</p></div></div>
        <div className="form-grid">
          <label className="combobox-field"><span>Cadena *</span><div className="combobox"><input required minLength={2} role="combobox" aria-autocomplete="list" aria-expanded={chainMenuOpen} aria-controls="chain-options" autoComplete="off" value={chainName} onFocus={() => setChainMenuOpen(true)} onBlur={() => window.setTimeout(() => setChainMenuOpen(false), 120)} onChange={(event) => { setChainName(event.target.value); setSelectedChain(""); setChainMenuOpen(true); }} placeholder="Escribe para filtrar o agregar otra" />{selectedChain === chainName && <span className="selected-check" aria-label="Cadena seleccionada">✓</span>}{chainMenuOpen && <div className="combobox-options" id="chain-options" role="listbox">{visibleChains.map((chain) => <button key={chain} type="button" role="option" aria-selected={selectedChain === chain} onMouseDown={(event) => event.preventDefault()} onClick={() => { setChainName(chain); setSelectedChain(chain); setChainMenuOpen(false); }}>{chain}</button>)}{visibleChains.length === 0 && <span>“{chainName}” se guardará como una cadena nueva.</span>}</div>}</div><small>Elige una sugerencia o escribe una cadena nueva.</small></label>
           <label><span>Número de OC *</span><input required value={orderNumber} onChange={(event) => setOrderNumber(event.target.value)} placeholder="Número del documento" /></label>
          <label><span>Cliente o razón social</span><input value={customerName} onChange={(event) => setCustomerName(event.target.value)} /></label>
          <label><span>Fecha de OC</span><input type="date" value={orderDate} onChange={(event) => setOrderDate(event.target.value)} /></label>
          <label className="wide"><span>Destino</span><input value={destination} onChange={(event) => setDestination(event.target.value)} placeholder="CD o lugar de entrega" /></label>
        </div>
        <div className="order-lines"><div className="line-heading"><h3>Productos solicitados</h3><button className="text-button" type="button" onClick={() => setLines((current) => [...current, emptyLine()])}>+ Agregar producto</button></div>
          {lines.map((line, index) => {
            const product = products.find((item) => item.sku === line.sku);
            return <div className="draft-line" key={index}>
              <label><span>Producto</span><select required value={line.sku} onChange={(event) => updateLine(index, { sku: event.target.value })}><option value="">Selecciona un producto</option>{products.map((item) => <option key={item.sku} value={item.sku} disabled={selectedSkus.has(item.sku) && item.sku !== line.sku}>{item.sku} · {item.product_name}</option>)}</select></label>
              <label><span>Cantidad</span><input required min={1} type="number" value={line.quantity} onChange={(event) => updateLine(index, { quantity: Number(event.target.value) })} /></label>
              <div className="availability-hint"><span>Disponible ahora</span><strong>{product?.available_to_invoice ?? "—"}</strong></div>
              {lines.length > 1 && <button className="remove-line" aria-label={`Eliminar producto ${index + 1}`} type="button" onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}>×</button>}
            </div>;
          })}
        </div>
        <label className="notes-field"><span>Observaciones</span><textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} /></label>
        <div className="form-actions"><button className="primary-button" disabled={saving} type="submit">{saving ? "Registrando…" : "Registrar OC"}</button></div>
      </form>}

      {!showForm && <section className="order-workspace">
        <aside className="order-list">
          <div className="list-title"><strong>Órdenes registradas</strong><span>{orders.length}</span></div>
          {loading && <div className="table-message">Cargando órdenes…</div>}
          {!loading && orders.map((order) => <button key={order.id} type="button" className={`order-list-item ${selectedId === order.id ? "selected" : ""}`} onClick={() => setSelectedId(order.id)}><strong>{order.order_number}</strong><span>{order.chain_name}</span><small>{order.lines.length} producto{order.lines.length === 1 ? "" : "s"}</small></button>)}
          {!loading && orders.length === 0 && <div className="table-message">Todavía no hay órdenes. Registra la primera para comenzar el flujo.</div>}
        </aside>
        <div className="order-detail">
          {!selected && !loading && <div className="empty-detail"><strong>La OC inicia la trazabilidad</strong><span>Luego podrás reservar stock y vincular la factura correcta.</span></div>}
          {selected && <><header className="detail-header"><div><p className="eyebrow">{selected.chain_name}</p><h2>OC {selected.order_number}</h2><p>{selected.customer_name ?? "Cliente no especificado"}{selected.destination ? ` · ${selected.destination}` : ""}</p></div><span className="status-pill available">{selected.status}</span></header>
            <section className="trace-section"><h3>Disponibilidad por producto</h3><div className="table-scroll"><table><thead><tr><th>Producto</th><th>Pedido</th><th>Disponible</th><th>Sugerido a facturar</th><th>Faltante</th><th>Resultado</th></tr></thead><tbody>{selected.lines.map((line) => <tr key={line.sku} className={line.complete ? "" : "row-warning"}><td><strong>{line.sku}</strong><span>{line.product_name}</span></td><td>{line.ordered_quantity}</td><td>{line.available}</td><td><strong>{line.suggested_to_invoice}</strong></td><td>{line.shortage}</td><td><span className={`status-pill ${line.complete ? "available" : "low_stock"}`}>{line.complete ? "Completo" : "Con faltante"}</span></td></tr>)}</tbody></table></div></section>
            {selected.notes && <section className="trace-section order-notes"><h3>Observaciones</h3><p>{selected.notes}</p></section>}
          </>}
        </div>
      </section>}
    </main>
  );
}
