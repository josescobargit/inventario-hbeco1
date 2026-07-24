import { FormEvent, useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";
import {
  applyConfirmedAlias, parseInvoiceBlocks, parseProductLines,
  QuickBlock, QuickLine, retryProductRecognition,
} from "./quickEntry";

interface Availability {
  id: string; sku: string; product_name: string; barcode: string | null;
  contifico_aux_code: string | null; available_to_invoice: number;
}
interface OrderLine {
  sku: string; product_name: string; ordered_quantity: number; invoiced_quantity: number;
  remaining_quantity: number; available: number; suggested_to_invoice: number;
}
interface Order { id: string; order_number: string; chain_name: string; customer_name: string | null; lines: OrderLine[] }
interface Reservation { id: string; status: string; purchase_order_reference: string | null; customer_name: string | null; lines: Array<{ sku: string; remaining_quantity: number }> }
interface InvoiceSummary { invoice_number: string }
interface DraftLine { sku: string; quantity: number; unit_price: string }
interface BulkDraft extends QuickBlock {
  order_id: string; invoice_date: string; authorization: string; guide: string;
  total: string; notes: string;
}
export interface InvoiceTemplate {
  id: string; number: string; date: string; customer: string; chain: string | null;
  source_type: string; authorization_number: string | null; remittance_guide: string | null;
  total_value: string | null; notes: string | null;
  purchase_order_id: string | null;
  lines: Array<{ sku: string; invoiced: number }>;
}

const sourceLabels: Record<string, string> = {
  purchase_order: "Orden de compra", sale_without_po: "Venta sin OC", internal_consumption: "Consumo interno",
  sample: "Muestra", replacement: "Reposición", other: "Otro fin",
};
const today = () => new Date().toLocaleDateString("en-CA");
const invoicePattern = /^\d{3}-\d{3}-\d{9}$/;

export function InvoiceRegistrationForm({ onCreated, onCancel, template, editing = false }: { onCreated: (id: string) => Promise<void>; onCancel: () => void; template?: InvoiceTemplate | null; editing?: boolean }) {
  const [mode, setMode] = useState<"individual" | "bulk">("individual");
  const [orders, setOrders] = useState<Order[]>([]);
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [products, setProducts] = useState<Availability[]>([]);
  const [registeredNumbers, setRegisteredNumbers] = useState<Set<string>>(new Set());
  const [sourceType, setSourceType] = useState(template?.source_type ?? "purchase_order");
  const [orderId, setOrderId] = useState(template?.purchase_order_id ?? "");
  const [selectedReservations, setSelectedReservations] = useState<string[]>([]);
  const [number, setNumber] = useState(editing ? template?.number ?? "" : "");
  const [date, setDate] = useState(editing && template ? template.date.slice(0, 10) : today());
  const [customer, setCustomer] = useState(template?.customer ?? "");
  const [chain, setChain] = useState(template?.chain ?? "");
  const [authorization, setAuthorization] = useState(template?.authorization_number ?? "");
  const [guide, setGuide] = useState(template?.remittance_guide ?? "");
  const [total, setTotal] = useState(template?.total_value ?? "");
  const [notes, setNotes] = useState(template?.notes ?? "");
  const [lines, setLines] = useState<DraftLine[]>(template?.lines.map((line) => ({ sku: line.sku, quantity: line.invoiced, unit_price: "" })) ?? []);
  const [confirmed, setConfirmed] = useState(false);
  const [replacementText, setReplacementText] = useState("");
  const [bulkText, setBulkText] = useState("");
  const [blocks, setBlocks] = useState<BulkDraft[]>([]);
  const [bulkConfirmed, setBulkConfirmed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiRequest<Order[]>("/purchase-orders"), apiRequest<Reservation[]>("/reservations"),
      apiRequest<Availability[]>("/inventory/availability"), apiRequest<InvoiceSummary[]>("/invoices"),
    ]).then(([loadedOrders, loadedReservations, loadedProducts, invoices]) => {
      setOrders(loadedOrders); setReservations(loadedReservations); setProducts(loadedProducts);
      setRegisteredNumbers(new Set(invoices.map((item) => item.invoice_number)));
    }).catch((caught) => setError(caught instanceof Error ? caught.message : "No pudimos preparar el formulario."))
      .finally(() => setLoading(false));
  }, []);

  const selectedOrder = orders.find((order) => order.id === orderId) ?? null;
  const availableReservations = useMemo(() => reservations.filter((item) => item.status === "active" && (!selectedOrder || item.purchase_order_reference === selectedOrder.order_number)), [reservations, selectedOrder]);
  const originalBySku = new Map(selectedOrder?.lines.map((line) => [line.sku, line]) ?? []);

  const chooseOrder = (id: string) => {
    setOrderId(id); setSelectedReservations([]); setConfirmed(false);
    const order = orders.find((item) => item.id === id);
    if (!order) { setLines([]); setCustomer(""); setChain(""); return; }
    setCustomer(order.customer_name ?? order.chain_name); setChain(order.chain_name);
    setLines(order.lines.map((line) => ({ sku: line.sku, quantity: line.suggested_to_invoice, unit_price: "" })));
  };
  const updateLine = (index: number, patch: Partial<DraftLine>) => {
    setConfirmed(false);
    setLines((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, ...patch } : line));
  };
  const toggleReservation = (id: string) => setSelectedReservations((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(null);
    const activeLines = lines.filter((line) => line.quantity > 0);
    if (!confirmed) { setError("Revisa la vista previa y confirma antes de guardar."); return; }
    if (!activeLines.length) { setError("La factura activa debe contener al menos un producto."); return; }
    setSaving(true);
    try {
      const created = await apiRequest<{ id: string }>(editing && template ? `/invoices/${template.id}` : "/invoices", { method: editing ? "PUT" : "POST", body: JSON.stringify({
        invoice_number: number, invoice_date: date, source_type: sourceType,
        purchase_order_id: sourceType === "purchase_order" ? orderId : null,
        customer_name: customer, chain_name: chain || null, authorization_number: authorization || null,
        remittance_guide: guide || null, total_value: total ? Number(total) : null, notes: notes || null,
        reservation_ids: sourceType === "purchase_order" ? selectedReservations : [],
        lines: activeLines.map((line) => ({ sku: line.sku, quantity: line.quantity, unit_price: line.unit_price ? Number(line.unit_price) : null })),
      }) });
      await onCreated(created.id);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No pudimos registrar la factura."); }
    finally { setSaving(false); }
  };

  const processBlocks = () => {
    const parsed = parseInvoiceBlocks(bulkText, products);
    setBlocks(parsed.map((block) => ({ ...block, order_id: "", invoice_date: today(), authorization: "", guide: "", total: "", notes: "" })));
    setBulkConfirmed(false);
    setError(parsed.length ? null : "No encontramos encabezados con el formato FAC 001-001-000000758.");
  };
  const patchBlock = (id: string, patch: Partial<BulkDraft>) => {
    setBulkConfirmed(false);
    setBlocks((current) => current.map((block) => block.id === id ? { ...block, ...patch } : block));
  };
  const patchBlockLine = (blockId: string, lineId: string, patch: Partial<QuickLine>) => {
    setBulkConfirmed(false);
    setBlocks((current) => current.map((block) => block.id === blockId
      ? { ...block, lines: block.lines.map((line) => line.id === lineId ? { ...line, ...patch } : line) } : block));
  };
  const confirmBulkProduct = (lineId: string, raw: string, sku: string) => {
    if (!sku) return;
    setBulkConfirmed(false);
    setBlocks((current) => {
      const allLines = current.flatMap((block) => block.lines);
      const updated = new Map(applyConfirmedAlias(allLines, raw, sku).map((line) => [line.id, line]));
      return current.map((block) => ({
        ...block,
        lines: block.lines.map((line) => line.id === lineId ? { ...line, sku, error: null, suggestions: [] } : updated.get(line.id) ?? line),
      }));
    });
  };
  const retryBlocks = () => {
    setBlocks((current) => current.map((block) => ({
      ...block,
      lines: retryProductRecognition(block.lines, products),
    })));
    setBulkConfirmed(false);
  };
  const duplicateBlock = (block: BulkDraft) => {
    setBulkConfirmed(false);
    setBlocks((current) => [...current, {
      ...block, id: `${block.id}-copy-${Date.now()}`, invoice_number: "",
      lines: block.lines.map((line) => ({ ...line, id: `${line.id}-copy-${Date.now()}` })),
    }]);
  };
  const numberCounts = blocks.reduce<Record<string, number>>((counts, block) => {
    if (block.invoice_number) counts[block.invoice_number] = (counts[block.invoice_number] ?? 0) + 1;
    return counts;
  }, {});
  const blockErrors = (block: BulkDraft) => {
    const errors: string[] = [];
    if (!invoicePattern.test(block.invoice_number)) errors.push("Número de factura inválido.");
    if ((numberCounts[block.invoice_number] ?? 0) > 1) errors.push("Número repetido dentro de esta carga.");
    if (registeredNumbers.has(block.invoice_number)) errors.push("Esta factura ya está registrada.");
    if (!block.order_id) errors.push("Selecciona la OC.");
    if (!block.invoice_date) errors.push("Selecciona la fecha.");
    if (!block.is_void && !block.lines.length) errors.push("La factura activa necesita productos.");
    if (!block.is_void && block.lines.some((line) => !line.sku || !line.quantity || line.quantity <= 0)) errors.push("Corrige los productos y cantidades marcados.");
    return errors;
  };
  const differenceCount = (block: BulkDraft) => {
    const order = orders.find((item) => item.id === block.order_id);
    if (!order || block.is_void) return 0;
    const bySku = new Map(order.lines.map((line) => [line.sku, line.remaining_quantity]));
    return block.lines.filter((line) => line.sku && line.quantity !== bySku.get(line.sku)).length;
  };
  const allErrors = blocks.reduce((sum, block) => sum + blockErrors(block).length, 0);
  const totalUnits = blocks.reduce((sum, block) => sum + block.lines.reduce((lineSum, line) => lineSum + (line.quantity ?? 0), 0), 0);
  const previousBySku = new Map(template?.lines.map((line) => [line.sku, line.invoiced]) ?? []);
  const changedLines = editing ? lines.filter((line) => previousBySku.get(line.sku) !== line.quantity).length : 0;
  const addEmptyBlock = () => {
    setBlocks((current) => [...current, {
      id: `block-new-${Date.now()}`, invoice_number: "", is_void: false, lines: [],
      order_id: "", invoice_date: today(), authorization: "", guide: "", total: "", notes: "",
    }]);
    setBulkConfirmed(false);
  };

  const saveBulk = async () => {
    if (!bulkConfirmed || allErrors || !blocks.length) return;
    setSaving(true); setError(null);
    try {
      const created = await apiRequest<{ invoices: Array<{ id: string }> }>("/invoices/bulk", {
        method: "POST", body: JSON.stringify({ invoices: blocks.map((block) => ({
          invoice_number: block.invoice_number, invoice_date: block.invoice_date,
          purchase_order_id: block.order_id, is_void: block.is_void,
          authorization_number: block.authorization || null, remittance_guide: block.guide || null,
          total_value: block.total ? Number(block.total) : null, notes: block.notes || null,
          lines: block.is_void ? [] : block.lines.map((line) => ({ sku: line.sku, quantity: line.quantity })),
        })) }),
      });
      await onCreated(created.invoices[0]!.id);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No pudimos guardar la carga."); }
    finally { setSaving(false); }
  };

  if (loading) return <div className="order-form table-message">Preparando OC, reservas e inventario…</div>;
  return <section className="order-form invoice-form">
    <div className="form-section-title"><div><h2>{editing ? "Editar factura emitida" : template ? "Duplicar factura emitida" : "Registrar factura emitida"}</h2><p>Registra documentos ya creados externamente; este módulo no genera ni autoriza facturas.</p></div>
      <div className="mode-switch" role="group" aria-label="Modo de factura"><button type="button" className={mode === "individual" ? "active" : ""} onClick={() => setMode("individual")}>Factura individual</button><button type="button" className={mode === "bulk" ? "active" : ""} onClick={() => setMode("bulk")}>Carga rápida por bloques</button></div>
    </div>
    {error && <div className="message error" role="alert">{error}</div>}

    {mode === "individual" && <form onSubmit={submit}>
      <div className="form-grid">
        <label><span>Origen *</span><select value={sourceType} onChange={(event) => { setSourceType(event.target.value); setOrderId(""); setLines([]); setSelectedReservations([]); setConfirmed(false); }}>{Object.entries(sourceLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        {sourceType === "purchase_order" && <label><span>OC vinculada *</span><select required value={orderId} onChange={(event) => chooseOrder(event.target.value)}><option value="">Selecciona la OC</option>{orders.map((order) => <option key={order.id} value={order.id}>{order.chain_name} · {order.order_number}</option>)}</select></label>}
        <label><span>Número de factura *</span><input required pattern="\d{3}-\d{3}-\d{9}" placeholder="001-001-000000686" value={number} onChange={(event) => { setNumber(event.target.value); setConfirmed(false); }} /></label>
        <label><span>Fecha *</span><input required type="date" value={date} onChange={(event) => { setDate(event.target.value); setConfirmed(false); }} /></label>
        <label><span>{sourceType === "purchase_order" ? "Cliente/Cadena *" : "Cliente *"}</span><input required minLength={2} readOnly={sourceType === "purchase_order"} value={customer} onChange={(event) => setCustomer(event.target.value)} /></label>
        {sourceType !== "purchase_order" && <label><span>Cadena</span><input value={chain} onChange={(event) => setChain(event.target.value)} /></label>}
        <label><span>Autorización</span><input value={authorization} onChange={(event) => setAuthorization(event.target.value)} /></label>
        <label><span>Guía de remisión</span><input value={guide} onChange={(event) => setGuide(event.target.value)} /></label>
        <label><span>Valor total</span><input min="0" step="0.01" type="number" value={total} onChange={(event) => setTotal(event.target.value)} /></label>
        <label className="wide"><span>Observaciones</span><input value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
      </div>
      {sourceType === "purchase_order" && selectedOrder && <section className="reservation-picker"><h3>Reservas de esta OC</h3>{availableReservations.length === 0 ? <p>No hay reservas activas vinculadas. Puedes continuar usando disponibilidad libre.</p> : availableReservations.map((item) => <label key={item.id}><input type="checkbox" checked={selectedReservations.includes(item.id)} onChange={() => toggleReservation(item.id)} /><span><strong>{item.customer_name ?? `OC ${item.purchase_order_reference}`}</strong><small>{item.lines.map((line) => `${line.sku}: ${line.remaining_quantity}`).join(" · ")}</small></span></label>)}</section>}
      {editing && <section className="quick-paste-panel"><label><span>Reemplazar detalle pegando nuevamente los productos</span><textarea rows={5} value={replacementText} onChange={(event) => setReplacementText(event.target.value)} placeholder="120.00 SHAMPOO ANA REGENEXT 400 ML - SHA400" /></label><button type="button" className="secondary-button" onClick={() => { const parsed = parseProductLines(replacementText, products); setLines(parsed.map((line) => ({ sku: line.sku, quantity: line.quantity ?? 0, unit_price: "" }))); setConfirmed(false); }}>Procesar y reemplazar detalle</button></section>}
      <div className="order-lines"><div className="line-heading"><div><h3>Vista previa y comparación con la OC</h3><p>{editing ? `${changedLines} línea${changedLines === 1 ? "" : "s"} cambiada${changedLines === 1 ? "" : "s"} frente a la versión registrada.` : "Pon en cero o elimina lo no facturado. Las diferencias permitidas abrirán una incidencia."}</p></div>{sourceType !== "purchase_order" && <button className="text-button" type="button" onClick={() => setLines((current) => [...current, { sku: "", quantity: 1, unit_price: "" }])}>+ Agregar producto</button>}</div>
        {lines.length === 0 && <div className="table-message">{sourceType === "purchase_order" ? "Selecciona una OC para cargar todos sus productos." : "Agrega los productos de la factura."}</div>}
        {lines.map((line, index) => { const product = products.find((item) => item.sku === line.sku); const original = originalBySku.get(line.sku); const difference = original ? original.remaining_quantity - line.quantity : null; return <div className={`invoice-draft-line ${difference !== null && difference !== 0 ? "has-difference" : ""}`} key={`${line.sku}-${index}`}>
          <label><span>Producto</span><select required value={line.sku} disabled={sourceType === "purchase_order" && !editing} onChange={(event) => updateLine(index, { sku: event.target.value })}><option value="">Selecciona</option>{products.map((item) => <option key={item.sku} value={item.sku}>{item.sku} · {item.product_name}</option>)}</select></label>
          <div><span>Cantidad OC</span><strong>{original?.ordered_quantity ?? "No consta"}</strong></div>
          <div><span>Ya facturado</span><strong>{original?.invoiced_quantity ?? 0}</strong></div>
          <label><span>Esta factura</span><input required min={0} type="number" value={line.quantity} onChange={(event) => updateLine(index, { quantity: Number(event.target.value) })} /></label>
          <div><span>Diferencia</span><strong>{difference ?? "—"}</strong></div>
          <div><span>Disponible</span><strong>{product?.available_to_invoice ?? "—"}</strong></div>
          {sourceType !== "purchase_order" && <button className="remove-line" type="button" aria-label={`Eliminar producto ${index + 1}`} onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}>×</button>}
          {editing && previousBySku.get(line.sku) !== line.quantity && <small className="difference-note">Cambio: antes {previousBySku.get(line.sku) ?? 0} → ahora {line.quantity} unidades.</small>}
          {difference !== null && difference !== 0 && <small className="difference-note">Difiere del saldo de la OC; se conservará como incidencia.</small>}
        </div>; })}
      </div>
      {lines.length > 0 && <label className="preview-confirm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>Revisé número, OC, cantidades y diferencias antes de guardar.</span></label>}
      <div className="form-actions"><button className="secondary-button" type="button" onClick={onCancel}>Cancelar</button><button className="primary-button" disabled={saving || !confirmed || !lines.some((line) => line.quantity > 0)} type="submit">{saving ? "Guardando…" : editing ? "Confirmar cambios" : "Confirmar y registrar factura"}</button></div>
    </form>}

    {mode === "bulk" && <div className="bulk-entry">
      <section className="quick-paste-panel"><label><span>Pega una o varias facturas</span><textarea rows={10} value={bulkText} onChange={(event) => { setBulkText(event.target.value); setBulkConfirmed(false); }} placeholder={"FAC 001-001-000000758\n480.00 TOALLITAS HÚMEDAS ANA X 100 - ACP001\n\nFAC 001-001-000000759\nANULADA"} /></label><button className="secondary-button" type="button" onClick={processBlocks}>Pegar y procesar información</button></section>
      <div className="line-heading bulk-toolbar"><h3>Vista previa por factura</h3><div><button className="text-button" type="button" onClick={retryBlocks}>Reintentar reconocimiento</button><button className="text-button" type="button" onClick={addEmptyBlock}>+ Agregar bloque</button></div></div>
      {blocks.length > 0 && <div className="bulk-summary"><div><span>Total facturas</span><strong>{blocks.length}</strong></div><div><span>Válidas</span><strong>{blocks.filter((block) => !block.is_void && !blockErrors(block).length).length}</strong></div><div><span>Anuladas</span><strong>{blocks.filter((block) => block.is_void).length}</strong></div><div><span>Con errores</span><strong>{blocks.filter((block) => blockErrors(block).length).length}</strong></div><div><span>Total unidades</span><strong>{totalUnits}</strong></div></div>}
      <div className="invoice-blocks">{blocks.map((block, index) => { const order = orders.find((item) => item.id === block.order_id); const errors = blockErrors(block); const differences = differenceCount(block); return <article className={`invoice-block ${errors.length ? "with-errors" : block.is_void ? "is-void" : differences ? "with-warning" : "valid"}`} key={block.id}>
        <header><div><span className="status-pill">{block.is_void ? "Anulada" : errors.length ? "Con errores" : differences ? "Con observaciones" : "Válida"}</span><h3>Factura {index + 1}</h3></div><div className="block-actions">{!block.is_void && <button type="button" onClick={() => patchBlock(block.id, { lines: [...block.lines, { id: `line-new-${Date.now()}`, raw: "Producto agregado", quantity: 1, sku: "", error: "Selecciona un producto.", suggestions: [] }] })}>Agregar producto</button>}<button type="button" onClick={() => duplicateBlock(block)}>Duplicar</button><button type="button" onClick={() => patchBlock(block.id, { is_void: !block.is_void })}>{block.is_void ? "Activar" : "Anular"}</button><button type="button" onClick={() => setBlocks((current) => current.filter((item) => item.id !== block.id))}>Eliminar</button></div></header>
        <div className="form-grid compact"><label><span>Número *</span><input value={block.invoice_number} onChange={(event) => patchBlock(block.id, { invoice_number: event.target.value })} /></label><label><span>OC *</span><select value={block.order_id} onChange={(event) => patchBlock(block.id, { order_id: event.target.value })}><option value="">Selecciona la OC</option>{orders.map((item) => <option key={item.id} value={item.id}>{item.chain_name} · {item.order_number}</option>)}</select></label><label><span>Cliente/Cadena</span><input readOnly value={order ? order.customer_name ?? order.chain_name : ""} /></label><label><span>Fecha *</span><input type="date" value={block.invoice_date} onChange={(event) => patchBlock(block.id, { invoice_date: event.target.value })} /></label><label><span>Autorización</span><input value={block.authorization} onChange={(event) => patchBlock(block.id, { authorization: event.target.value })} /></label><label><span>Guía</span><input value={block.guide} onChange={(event) => patchBlock(block.id, { guide: event.target.value })} /></label><label><span>Valor total</span><input type="number" min="0" step="0.01" value={block.total} onChange={(event) => patchBlock(block.id, { total: event.target.value })} /></label></div>
        {!block.is_void && <div className="block-lines">{block.lines.map((line) => <div className={!line.sku || !line.quantity ? "unrecognized-line" : ""} key={line.id}><label><span>{line.raw}</span><select value={line.sku} onChange={(event) => confirmBulkProduct(line.id, line.raw, event.target.value)}><option value="">Producto no reconocido</option>{products.map((product) => <option key={product.id} value={product.sku}>{product.sku} · {product.product_name}</option>)}</select>{line.suggestions.length > 0 && <small>Sugerencias: {line.suggestions.join(", ")}</small>}</label><label><span>Unidades</span><input type="number" min={1} value={line.quantity ?? ""} onChange={(event) => patchBlockLine(block.id, line.id, { quantity: Number(event.target.value) })} /></label><button type="button" aria-label="Eliminar línea" onClick={() => patchBlock(block.id, { lines: block.lines.filter((item) => item.id !== line.id) })}>×</button>{line.error && <small className="field-error">{line.error}</small>}</div>)}</div>}
        <footer><span>{block.lines.length} productos · {block.lines.reduce((sum, line) => sum + (line.quantity ?? 0), 0)} unidades</span><span>{differences} diferencias frente a la OC</span></footer>
        {errors.length > 0 && <ul className="block-errors">{errors.map((item) => <li key={item}>{item}</li>)}</ul>}
      </article>; })}</div>
      {blocks.length > 0 && <label className="preview-confirm"><input type="checkbox" checked={bulkConfirmed} disabled={allErrors > 0} onChange={(event) => setBulkConfirmed(event.target.checked)} /><span>{allErrors ? "Corrige todos los errores obligatorios para confirmar." : "Revisé todos los bloques y confirmo las advertencias y diferencias permitidas."}</span></label>}
      <div className="form-actions"><button className="secondary-button" type="button" onClick={onCancel}>Cancelar</button><button className="primary-button" type="button" disabled={saving || !blocks.length || allErrors > 0 || !bulkConfirmed} onClick={saveBulk}>{saving ? "Guardando carga…" : "Confirmar y guardar todas"}</button></div>
    </div>}
  </section>;
}
