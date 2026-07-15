import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";
import type { AuthenticatedUser } from "../auth/types";

interface Availability { sku: string; product_name: string; available_to_invoice: number; physical_confirmed: number }
interface OperationLine { sku: string; product_name: string; quantity: number }
interface Operation { id: string; operation_type: "entry" | "exit"; responsible_name: string; occurred_at: string; document_reference: string; reason: string; notes: string | null; registered_by: string; lines: OperationLine[] }
interface DraftLine { sku: string; quantity: number }

const localDateTime = () => {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
};
const dateLabel = (value: string) => new Intl.DateTimeFormat("es-EC", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));

export function InventoryOperationCenter({ operationType, user }: { operationType: "entry" | "exit"; user: AuthenticatedUser }) {
  const isEntry = operationType === "entry";
  const [products, setProducts] = useState<Availability[]>([]);
  const [operations, setOperations] = useState<Operation[]>([]);
  const [responsible, setResponsible] = useState(user.full_name);
  const [occurredAt, setOccurredAt] = useState(localDateTime());
  const [documentReference, setDocumentReference] = useState("");
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([{ sku: "", quantity: 1 }]);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = async () => {
    const [loadedProducts, loadedOperations] = await Promise.all([
      apiRequest<Availability[]>("/inventory/availability"),
      apiRequest<Operation[]>(`/inventory-operations?operation_type=${operationType}`),
    ]);
    setProducts(loadedProducts); setOperations(loadedOperations);
  };

  useEffect(() => {
    Promise.all([apiRequest<Availability[]>("/inventory/availability"), apiRequest<Operation[]>(`/inventory-operations?operation_type=${operationType}`)])
      .then(([loadedProducts, loadedOperations]) => { setProducts(loadedProducts); setOperations(loadedOperations); })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudo cargar la información. Intenta nuevamente."))
      .finally(() => setLoading(false));
  }, [operationType]);

  const selectedSkus = useMemo(() => new Set(lines.map((line) => line.sku).filter(Boolean)), [lines]);
  const updateLine = (index: number, patch: Partial<DraftLine>) => setLines((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, ...patch } : line));
  const reset = () => { setResponsible(user.full_name); setOccurredAt(localDateTime()); setDocumentReference(""); setReason(""); setNotes(""); setLines([{ sku: "", quantity: 1 }]); };
  const invalidExit = !isEntry && lines.some((line) => line.sku && line.quantity > (products.find((item) => item.sku === line.sku)?.available_to_invoice ?? 0));

  const submit = async () => {
    setSaving(true); setError(null); setMessage(null);
    try {
      await apiRequest<Operation>("/inventory-operations", { method: "POST", body: JSON.stringify({ operation_type: operationType, responsible_name: responsible, occurred_at: new Date(occurredAt).toISOString(), document_reference: documentReference, reason, notes: notes || null, lines }) });
      await load(); reset(); setShowForm(false); setMessage("Movimiento guardado");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No se pudo guardar el movimiento. Intenta nuevamente."); }
    finally { setSaving(false); }
  };

  return <main className="dashboard operation-center"><section className="module-heading"><div className="welcome-block"><p className="eyebrow">Movimiento general de inventario</p><h1>{isEntry ? "Entradas" : "Salidas"}</h1><p>{isEntry ? "Registra producto que ingresa físicamente a la bodega." : "Registra egresos generales. Los despachos a clientes se gestionan en su módulo independiente."}</p></div><button className="primary-button" type="button" onClick={() => { setShowForm((value) => !value); setError(null); }}>{showForm ? "Cancelar" : isEntry ? "Nueva entrada" : "Nueva salida"}</button></section>
    {message && <div className="message success">{message}</div>}{error && <div className="message error" role="alert">{error}</div>}
    {showForm && <section className="operation-form"><div className="operation-form-grid"><label><span>Responsable *</span><input minLength={2} value={responsible} onChange={(event) => setResponsible(event.target.value)} /></label><label><span>Fecha y hora *</span><input type="datetime-local" value={occurredAt} onChange={(event) => setOccurredAt(event.target.value)} /></label><label><span>Documento de respaldo *</span><input value={documentReference} onChange={(event) => setDocumentReference(event.target.value)} placeholder={isEntry ? "Factura, guía o acta de ingreso" : "Vale, acta o autorización"} /></label><label><span>Motivo *</span><input minLength={5} value={reason} onChange={(event) => setReason(event.target.value)} /></label></div>
      <div className="operation-lines"><div className="line-heading"><h3>Productos</h3><button className="text-button" type="button" onClick={() => setLines((current) => [...current, { sku: "", quantity: 1 }])}>+ Agregar producto</button></div>{lines.map((line, index) => { const product = products.find((item) => item.sku === line.sku); const exceeds = !isEntry && Boolean(product) && line.quantity > product!.available_to_invoice; return <div className={`operation-line ${exceeds ? "has-error" : ""}`} key={index}><label><span>Producto</span><select required value={line.sku} onChange={(event) => updateLine(index, { sku: event.target.value })}><option value="">Selecciona</option>{products.map((item) => <option key={item.sku} value={item.sku} disabled={selectedSkus.has(item.sku) && item.sku !== line.sku}>{item.sku} · {item.product_name}</option>)}</select></label><label><span>Cantidad</span><input type="number" min={1} value={line.quantity} onChange={(event) => updateLine(index, { quantity: Number(event.target.value) })} /></label><div><span>{isEntry ? "Físico actual" : "Disponible"}</span><strong>{product ? isEntry ? product.physical_confirmed : product.available_to_invoice : "—"}</strong></div>{lines.length > 1 && <button className="remove-line" type="button" aria-label={`Eliminar producto ${index + 1}`} onClick={() => setLines((current) => current.filter((_, lineIndex) => lineIndex !== index))}>×</button>}{exceeds && <small>La cantidad ingresada supera el stock disponible.</small>}</div>; })}</div>
      <label className="notes-field"><span>Observación</span><textarea rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} /></label><div className="form-actions"><button className="primary-button" type="button" disabled={saving || responsible.trim().length < 2 || !occurredAt || !documentReference.trim() || reason.trim().length < 5 || lines.some((line) => !line.sku || line.quantity <= 0) || invalidExit} onClick={submit}>{saving ? "Guardando…" : "Guardar movimiento"}</button></div>
    </section>}
    <section className="operation-history"><div className="panel-title"><div><h2>{isEntry ? "Entradas registradas" : "Salidas registradas"}</h2><p>Movimientos generales con respaldo documental.</p></div><span>{operations.length}</span></div>{loading && <div className="table-message">Cargando información…</div>}{!loading && operations.length === 0 && <div className="table-message">No se encontraron registros</div>}{operations.length > 0 && <div className="table-scroll"><table><thead><tr><th>Fecha</th><th>Documento</th><th>Responsable</th><th>Productos</th><th>Unidades</th><th>Motivo</th><th>Registrado por</th></tr></thead><tbody>{operations.map((item) => <tr key={item.id}><td>{dateLabel(item.occurred_at)}</td><td>{item.document_reference}</td><td>{item.responsible_name}</td><td>{item.lines.map((line) => line.sku).join(", ")}</td><td>{item.lines.reduce((sum, line) => sum + line.quantity, 0)}</td><td className="reason-cell">{item.reason}</td><td>{item.registered_by}</td></tr>)}</tbody></table></div>}</section>
  </main>;
}
