import { FormEvent, useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";

interface Availability { sku: string; product_name: string; available_to_invoice: number }
interface Order { id: string; order_number: string; chain_name: string }
interface ReservationLine { sku: string; product_name: string; quantity: number; remaining_quantity: number }
interface Reservation {
  id: string; purpose: string; customer_name: string | null; purchase_order_reference: string | null;
  responsible_name: string | null; reason: string; status: string; release_reason: string | null;
  created_at: string; lines: ReservationLine[];
}
interface DraftLine { sku: string; quantity: number }

const purposeLabels: Record<string, string> = {
  purchase_order: "Orden de compra", customer: "Cliente", seller: "Vendedor",
  pending_order: "Pedido pendiente", operational: "Necesidad operativa",
};
const statusLabels: Record<string, string> = { active: "Activa", released: "Liberada", used: "Utilizada", cancelled: "Cancelada" };
const emptyLine = (): DraftLine => ({ sku: "", quantity: 1 });

export function ReservationCenter() {
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [products, setProducts] = useState<Availability[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [purpose, setPurpose] = useState("purchase_order");
  const [customer, setCustomer] = useState("");
  const [orderReference, setOrderReference] = useState("");
  const [responsible, setResponsible] = useState("");
  const [reason, setReason] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([emptyLine()]);
  const [releaseReason, setReleaseReason] = useState("");
  const [releasing, setReleasing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiRequest<Reservation[]>("/reservations"), apiRequest<Availability[]>("/inventory/availability"),
      apiRequest<Order[]>("/purchase-orders"),
    ]).then(([loadedReservations, loadedProducts, loadedOrders]) => {
      setReservations(loadedReservations); setProducts(loadedProducts); setOrders(loadedOrders);
      setSelectedId(loadedReservations[0]?.id ?? null);
    }).catch((caught) => setError(caught instanceof Error ? caught.message : "No pudimos cargar las reservas."))
      .finally(() => setLoading(false));
  }, []);

  const selected = useMemo(() => reservations.find((item) => item.id === selectedId) ?? null, [reservations, selectedId]);
  const selectedSkus = new Set(lines.map((line) => line.sku).filter(Boolean));
  const updateLine = (index: number, patch: Partial<DraftLine>) => setLines((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, ...patch } : line));
  const reset = () => { setPurpose("purchase_order"); setCustomer(""); setOrderReference(""); setResponsible(""); setReason(""); setLines([emptyLine()]); };

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(null); setSaving(true);
    try {
      const created = await apiRequest<Reservation>("/reservations", { method: "POST", body: JSON.stringify({
        purpose, customer_name: purpose === "customer" ? customer : customer || null,
        purchase_order_reference: purpose === "purchase_order" ? orderReference : null,
        responsible_name: responsible || null, reason, lines,
      }) });
      setReservations((current) => [created, ...current]); setSelectedId(created.id); setShowForm(false); reset();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No pudimos crear la reserva."); }
    finally { setSaving(false); }
  };

  const release = async () => {
    if (!selected || releaseReason.trim().length < 5) return;
    setError(null); setSaving(true);
    try {
      const updated = await apiRequest<Reservation>(`/reservations/${selected.id}/release`, { method: "POST", body: JSON.stringify({ reason: releaseReason }) });
      setReservations((current) => current.map((item) => item.id === updated.id ? updated : item));
      setReleaseReason(""); setReleasing(false);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No pudimos liberar la reserva."); }
    finally { setSaving(false); }
  };

  return <main className="dashboard reservation-center">
    <section className="module-heading"><div className="welcome-block"><p className="eyebrow">Compromiso de inventario</p><h1>Reservas</h1><p>Separa unidades disponibles para una OC, cliente u operación, sin modificar el conteo físico.</p></div><button className="primary-button" type="button" onClick={() => { setShowForm((value) => !value); setError(null); }}>{showForm ? "Cancelar" : "Nueva reserva"}</button></section>
    {error && <div className="message error" role="alert">{error}</div>}

    {showForm && <form className="order-form" onSubmit={submit}>
      <div className="form-section-title"><h2>Nueva reserva</h2><p>La disponibilidad baja al confirmar y se recupera si la reserva se libera.</p></div>
      <div className="form-grid">
        <label><span>Propósito *</span><select value={purpose} onChange={(event) => setPurpose(event.target.value)}>{Object.entries(purposeLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        {purpose === "purchase_order" && <label><span>Orden de compra *</span><select required value={orderReference} onChange={(event) => setOrderReference(event.target.value)}><option value="">Selecciona la OC</option>{orders.map((order) => <option key={order.id} value={order.order_number}>{order.chain_name} · {order.order_number}</option>)}</select></label>}
        {purpose === "customer" && <label><span>Cliente *</span><input required value={customer} onChange={(event) => setCustomer(event.target.value)} /></label>}
        {purpose !== "customer" && <label><span>Cliente relacionado</span><input value={customer} onChange={(event) => setCustomer(event.target.value)} /></label>}
        <label><span>Responsable</span><input value={responsible} onChange={(event) => setResponsible(event.target.value)} placeholder="Persona que solicita o supervisa" /></label>
        <label className="wide"><span>Motivo *</span><input required minLength={5} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explica por qué se reserva este stock" /></label>
      </div>
      <div className="order-lines"><div className="line-heading"><h3>Unidades a reservar</h3><button className="text-button" type="button" onClick={() => setLines((current) => [...current, emptyLine()])}>+ Agregar producto</button></div>
        {lines.map((line, index) => { const product = products.find((item) => item.sku === line.sku); return <div className="draft-line" key={index}>
          <label><span>Producto</span><select required value={line.sku} onChange={(event) => updateLine(index, { sku: event.target.value })}><option value="">Selecciona un producto</option>{products.map((item) => <option key={item.sku} value={item.sku} disabled={selectedSkus.has(item.sku) && item.sku !== line.sku}>{item.sku} · {item.product_name}</option>)}</select></label>
          <label><span>Cantidad</span><input required min={1} max={product?.available_to_invoice} type="number" value={line.quantity} onChange={(event) => updateLine(index, { quantity: Number(event.target.value) })} /></label>
          <div className="availability-hint"><span>Disponible</span><strong>{product?.available_to_invoice ?? "—"}</strong></div>
          {lines.length > 1 && <button className="remove-line" aria-label={`Eliminar producto ${index + 1}`} type="button" onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}>×</button>}
        </div>; })}
      </div>
      <div className="form-actions"><button className="primary-button" disabled={saving || orders.length === 0 && purpose === "purchase_order"} type="submit">{saving ? "Reservando…" : "Confirmar reserva"}</button></div>
      {orders.length === 0 && purpose === "purchase_order" && <p className="form-hint">Primero registra una orden de compra o elige otro propósito.</p>}
    </form>}

    {!showForm && <section className="order-workspace">
      <aside className="order-list"><div className="list-title"><strong>Reservas registradas</strong><span>{reservations.filter((item) => item.status === "active").length}</span></div>
        {loading && <div className="table-message">Cargando reservas…</div>}
        {!loading && reservations.map((item) => <button type="button" key={item.id} className={`order-list-item ${selectedId === item.id ? "selected" : ""}`} onClick={() => { setSelectedId(item.id); setReleasing(false); }}><strong>{item.purchase_order_reference ? `OC ${item.purchase_order_reference}` : purposeLabels[item.purpose]}</strong><span>{item.customer_name ?? item.responsible_name ?? "Sin responsable indicado"}</span><small>{statusLabels[item.status]} · {item.lines.reduce((sum, line) => sum + line.remaining_quantity, 0)} unidades pendientes</small></button>)}
        {!loading && reservations.length === 0 && <div className="table-message">Todavía no hay reservas activas o históricas.</div>}
      </aside>
      <div className="order-detail">{!selected && !loading && <div className="empty-detail"><strong>Reserva sólo lo necesario</strong><span>Cada unidad reservada deja de estar disponible para otras facturas.</span></div>}
        {selected && <><header className="detail-header"><div><p className="eyebrow">{purposeLabels[selected.purpose]}</p><h2>{selected.purchase_order_reference ? `Reserva para OC ${selected.purchase_order_reference}` : "Reserva de inventario"}</h2><p>{selected.reason}</p></div><span className={`status-pill ${selected.status === "active" ? "low_stock" : "available"}`}>{statusLabels[selected.status]}</span></header>
          <section className="trace-section"><h3>Productos comprometidos</h3><div className="table-scroll"><table><thead><tr><th>Producto</th><th>Reservado originalmente</th><th>Saldo reservado</th></tr></thead><tbody>{selected.lines.map((line) => <tr key={line.sku}><td><strong>{line.sku}</strong><span>{line.product_name}</span></td><td>{line.quantity}</td><td><strong>{line.remaining_quantity}</strong></td></tr>)}</tbody></table></div></section>
          {selected.status === "active" && <section className="release-panel">{!releasing ? <button className="secondary-button" type="button" onClick={() => setReleasing(true)}>Liberar reserva</button> : <><label><span>Motivo de liberación</span><input autoFocus minLength={5} value={releaseReason} onChange={(event) => setReleaseReason(event.target.value)} placeholder="Explica por qué se libera" /></label><div><button className="secondary-button" type="button" onClick={() => setReleasing(false)}>Cancelar</button><button className="primary-button" disabled={saving || releaseReason.trim().length < 5} type="button" onClick={release}>Confirmar liberación</button></div></>}</section>}
          {selected.release_reason && <div className="message">Liberada: {selected.release_reason}</div>}
        </>}
      </div>
    </section>}
  </main>;
}
