import { FormEvent, useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";

interface Availability { sku: string; product_name: string; available_to_invoice: number }
interface OrderLine { sku: string; product_name: string; ordered_quantity: number; available: number; suggested_to_invoice: number }
interface Order { id: string; order_number: string; chain_name: string; customer_name: string | null; lines: OrderLine[] }
interface Reservation { id: string; status: string; purchase_order_reference: string | null; customer_name: string | null; lines: Array<{ sku: string; remaining_quantity: number }> }
interface DraftLine { sku: string; quantity: number; unit_price: string }

const sourceLabels: Record<string, string> = {
  purchase_order: "Orden de compra", sale_without_po: "Venta sin OC", internal_consumption: "Consumo interno",
  sample: "Muestra", replacement: "Reposición", other: "Otro fin",
};

export function InvoiceRegistrationForm({ onCreated, onCancel }: { onCreated: (id: string) => Promise<void>; onCancel: () => void }) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [products, setProducts] = useState<Availability[]>([]);
  const [sourceType, setSourceType] = useState("purchase_order");
  const [orderId, setOrderId] = useState("");
  const [selectedReservations, setSelectedReservations] = useState<string[]>([]);
  const [number, setNumber] = useState("");
  const [date, setDate] = useState("");
  const [customer, setCustomer] = useState("");
  const [chain, setChain] = useState("");
  const [authorization, setAuthorization] = useState("");
  const [guide, setGuide] = useState("");
  const [total, setTotal] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([apiRequest<Order[]>("/purchase-orders"), apiRequest<Reservation[]>("/reservations"), apiRequest<Availability[]>("/inventory/availability")])
      .then(([loadedOrders, loadedReservations, loadedProducts]) => { setOrders(loadedOrders); setReservations(loadedReservations); setProducts(loadedProducts); })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No pudimos preparar el formulario."))
      .finally(() => setLoading(false));
  }, []);

  const selectedOrder = orders.find((order) => order.id === orderId) ?? null;
  const availableReservations = useMemo(() => reservations.filter((item) => item.status === "active" && (!selectedOrder || item.purchase_order_reference === selectedOrder.order_number)), [reservations, selectedOrder]);
  const originalBySku = new Map(selectedOrder?.lines.map((line) => [line.sku, line.ordered_quantity]) ?? []);

  const chooseOrder = (id: string) => {
    setOrderId(id); setSelectedReservations([]);
    const order = orders.find((item) => item.id === id);
    if (!order) { setLines([]); return; }
    setCustomer(order.customer_name ?? order.chain_name); setChain(order.chain_name);
    setLines(order.lines.map((line) => ({ sku: line.sku, quantity: line.suggested_to_invoice, unit_price: "" })));
  };

  const updateLine = (index: number, patch: Partial<DraftLine>) => setLines((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, ...patch } : line));
  const addLine = () => setLines((current) => [...current, { sku: "", quantity: 1, unit_price: "" }]);
  const toggleReservation = (id: string) => setSelectedReservations((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(null); setSaving(true);
    try {
      const created = await apiRequest<{ id: string }>("/invoices", { method: "POST", body: JSON.stringify({
        invoice_number: number, invoice_date: date, source_type: sourceType,
        purchase_order_id: sourceType === "purchase_order" ? orderId : null,
        customer_name: customer, chain_name: chain || null, authorization_number: authorization || null,
        remittance_guide: guide || null, total_value: total ? Number(total) : null, notes: notes || null,
        reservation_ids: sourceType === "purchase_order" ? selectedReservations : [],
        lines: lines.map((line) => ({ sku: line.sku, quantity: line.quantity, unit_price: line.unit_price ? Number(line.unit_price) : null })),
      }) });
      await onCreated(created.id);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No pudimos registrar la factura."); }
    finally { setSaving(false); }
  };

  if (loading) return <div className="order-form table-message">Preparando OC, reservas e inventario…</div>;
  return <form className="order-form invoice-form" onSubmit={submit}>
    <div className="form-section-title"><h2>Registrar factura emitida</h2><p>Copia aquí la factura creada en Contífico. Este formulario no genera ni autoriza facturas.</p></div>
    {error && <div className="message error" role="alert">{error}</div>}
    <div className="form-grid">
      <label><span>Origen *</span><select value={sourceType} onChange={(event) => { setSourceType(event.target.value); setOrderId(""); setLines([]); setSelectedReservations([]); }}>{Object.entries(sourceLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {sourceType === "purchase_order" && <label><span>OC vinculada *</span><select required value={orderId} onChange={(event) => chooseOrder(event.target.value)}><option value="">Selecciona manualmente la OC</option>{orders.map((order) => <option key={order.id} value={order.id}>{order.chain_name} · {order.order_number}</option>)}</select></label>}
      <label><span>Número de factura *</span><input required pattern="\d{3}-\d{3}-\d{9}" placeholder="001-001-000000686" value={number} onChange={(event) => setNumber(event.target.value)} /></label>
      <label><span>Fecha *</span><input required type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
      <label><span>Cliente *</span><input required minLength={2} value={customer} onChange={(event) => setCustomer(event.target.value)} /></label>
      <label><span>Cadena</span><input value={chain} onChange={(event) => setChain(event.target.value)} /></label>
      <label><span>Autorización</span><input value={authorization} onChange={(event) => setAuthorization(event.target.value)} /></label>
      <label><span>Guía de remisión</span><input value={guide} onChange={(event) => setGuide(event.target.value)} /></label>
      <label><span>Valor total</span><input min="0" step="0.01" type="number" value={total} onChange={(event) => setTotal(event.target.value)} /></label>
      <label className="wide"><span>Observaciones</span><input value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
    </div>

    {sourceType === "purchase_order" && selectedOrder && <section className="reservation-picker"><h3>Reservas de esta OC</h3>{availableReservations.length === 0 ? <p>No hay reservas activas vinculadas. Puedes continuar usando disponibilidad libre.</p> : availableReservations.map((item) => <label key={item.id}><input type="checkbox" checked={selectedReservations.includes(item.id)} onChange={() => toggleReservation(item.id)} /><span><strong>{item.customer_name ?? `OC ${item.purchase_order_reference}`}</strong><small>{item.lines.map((line) => `${line.sku}: ${line.remaining_quantity}`).join(" · ")}</small></span></label>)}</section>}

    <div className="order-lines"><div className="line-heading"><div><h3>Comparación con la OC</h3><p>Las diferencias se permiten, pero quedarán señaladas como incidencia.</p></div><button className="text-button" type="button" onClick={addLine}>+ Agregar producto</button></div>
      {lines.length === 0 && <div className="table-message">{sourceType === "purchase_order" ? "Selecciona una OC para cargar sus productos." : "Agrega los productos de la factura."}</div>}
      {lines.map((line, index) => { const product = products.find((item) => item.sku === line.sku); const original = originalBySku.get(line.sku); const differs = original !== undefined && line.quantity !== original; const outside = Boolean(line.sku && selectedOrder && original === undefined); return <div className={`invoice-draft-line ${differs || outside ? "has-difference" : ""}`} key={index}>
        <label><span>Producto</span><select required value={line.sku} onChange={(event) => updateLine(index, { sku: event.target.value })}><option value="">Selecciona</option>{products.map((item) => <option key={item.sku} value={item.sku}>{item.sku} · {item.product_name}</option>)}</select></label>
        <div><span>OC original</span><strong>{original ?? "No consta"}</strong></div><div><span>Disponible</span><strong>{product?.available_to_invoice ?? "—"}</strong></div>
        <label><span>Facturado</span><input required min={1} type="number" value={line.quantity} onChange={(event) => updateLine(index, { quantity: Number(event.target.value) })} /></label>
        <label><span>Precio unitario</span><input min="0" step="0.0001" type="number" value={line.unit_price} onChange={(event) => updateLine(index, { unit_price: event.target.value })} /></label>
        <button className="remove-line" type="button" aria-label={`Eliminar producto ${index + 1}`} onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}>×</button>
        {(differs || outside) && <small className="difference-note">{outside ? "Producto fuera de la OC: abrirá incidencia." : "La cantidad difiere de la OC: quedará señalada."}</small>}
      </div>; })}
    </div>
    <div className="form-actions"><button className="secondary-button" type="button" onClick={onCancel}>Cancelar</button><button className="primary-button" disabled={saving || lines.length === 0} type="submit">{saving ? "Registrando…" : "Registrar factura externa"}</button></div>
  </form>;
}
