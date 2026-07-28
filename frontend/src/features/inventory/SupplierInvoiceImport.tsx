import { ChangeEvent, DragEvent, useEffect, useMemo, useRef, useState } from "react";

import { apiRequest, apiUpload } from "../../api/client";
import { ProductCombobox, type SearchableProduct } from "../purchase-orders/ProductCombobox";

type MatchStatus = "recognized" | "requires_confirmation" | "not_found";

interface SupplierLine {
  line_number: number;
  sku: string | null;
  product_name: string | null;
  supplier_code: string | null;
  barcode: string | null;
  description: string;
  quantity: number | "";
  unit_price: number | null;
  discount: number | null;
  line_total: number | null;
  status: MatchStatus;
  reviewed?: boolean;
  match_method?: string;
}

interface SupplierInvoiceDraft {
  id?: string;
  supplier_ruc: string | null;
  supplier_name: string;
  invoice_number: string | null;
  issued_at: string | null;
  authorization_number: string | null;
  buyer_name: string | null;
  buyer_ruc: string | null;
  subtotal: number | null;
  tax: number | null;
  total: number | null;
  extraction_method?: string | null;
  original_filename?: string | null;
  file_sha256?: string | null;
  status?: string;
  warnings?: string[];
  lines: SupplierLine[];
}

interface RegisteredInvoice extends SupplierInvoiceDraft {
  id: string;
  status: "confirmed" | "cancelled";
  created_at: string;
}

const renumber = (lines: SupplierLine[]) => lines.map((line, index) => ({ ...line, line_number: index + 1 }));
const emptyLine = (lineNumber: number): SupplierLine => ({
  line_number: lineNumber, sku: null, product_name: null, supplier_code: null, barcode: null,
  description: "", quantity: "", unit_price: null, discount: null, line_total: null,
  status: "not_found", reviewed: false,
});

export function SupplierInvoiceImport({ products, onInventoryChanged }: {
  products: SearchableProduct[];
  onInventoryChanged: () => Promise<void>;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [drafts, setDrafts] = useState<SupplierInvoiceDraft[]>([]);
  const [registered, setRegistered] = useState<RegisteredInvoice[]>([]);
  const [filter, setFilter] = useState<"all" | "recognized" | "pending">("all");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadHistory = () => apiRequest<RegisteredInvoice[]>("/supplier-invoices").then(setRegistered);
  useEffect(() => { void loadHistory().catch(() => undefined); }, []);

  const chooseFiles = (selected: File[]) => {
    setError(null); setMessage(null);
    const valid = selected.filter((file) => ["application/pdf", "image/jpeg", "image/png", "image/webp"].includes(file.type) && file.size <= 15 * 1024 * 1024);
    if (valid.length !== selected.length) setError("Usa PDF, PNG, JPG o WEBP de hasta 15 MB por archivo.");
    setFiles(valid);
  };
  const onFileInput = (event: ChangeEvent<HTMLInputElement>) => chooseFiles(Array.from(event.target.files ?? []));
  const onDrop = (event: DragEvent<HTMLDivElement>) => { event.preventDefault(); chooseFiles(Array.from(event.dataTransfer.files)); };

  const analyze = async () => {
    if (!files.length) return;
    setLoading(true); setError(null); setMessage(null);
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    try {
      const found = await apiUpload<SupplierInvoiceDraft[]>("/supplier-invoices/imports/preview", body);
      setDrafts(found.map((draft) => ({
        ...draft,
        lines: draft.lines.map((line) => ({ ...line, reviewed: line.status === "recognized" })),
      })));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudieron procesar los documentos.");
    } finally { setLoading(false); }
  };

  const updateDraft = (draftIndex: number, patch: Partial<SupplierInvoiceDraft>) => setDrafts((current) => current.map((draft, index) => index === draftIndex ? { ...draft, ...patch } : draft));
  const updateLine = (draftIndex: number, lineIndex: number, patch: Partial<SupplierLine>) => setDrafts((current) => current.map((draft, index) => index !== draftIndex ? draft : {
    ...draft, lines: draft.lines.map((line, currentLine) => currentLine === lineIndex ? { ...line, ...patch } : line),
  }));
  const removeLine = (draftIndex: number, lineIndex: number) => setDrafts((current) => current.map((draft, index) => index !== draftIndex ? draft : {
    ...draft, lines: renumber(draft.lines.filter((_, currentLine) => currentLine !== lineIndex)),
  }));
  const duplicateLine = (draftIndex: number, lineIndex: number) => setDrafts((current) => current.map((draft, index) => index !== draftIndex ? draft : {
    ...draft, lines: renumber([...draft.lines.slice(0, lineIndex + 1), { ...draft.lines[lineIndex]! }, ...draft.lines.slice(lineIndex + 1)]),
  }));

  const pending = useMemo(() => drafts.reduce((sum, draft) => sum + draft.lines.filter((line) => !line.reviewed || !line.sku || !line.quantity).length, 0), [drafts]);
  const visible = (line: SupplierLine) => filter === "all" || (filter === "recognized" ? Boolean(line.reviewed && line.sku) : !line.reviewed || !line.sku);

  const payload = (draft: SupplierInvoiceDraft) => ({
    supplier_ruc: draft.supplier_ruc,
    supplier_name: draft.supplier_name,
    invoice_number: draft.invoice_number,
    issued_at: draft.issued_at,
    authorization_number: draft.authorization_number,
    buyer_name: draft.buyer_name,
    buyer_ruc: draft.buyer_ruc,
    subtotal: draft.subtotal,
    tax: draft.tax,
    total: draft.total,
    extraction_method: draft.extraction_method,
    original_filename: draft.original_filename,
    file_sha256: draft.file_sha256,
    lines: draft.lines.map((line) => ({
      line_number: line.line_number, sku: line.sku, supplier_code: line.supplier_code,
      barcode: line.barcode, description: line.description, quantity: line.quantity,
      unit_price: line.unit_price, discount: line.discount, line_total: line.line_total,
      reviewed: Boolean(line.reviewed),
    })),
  });

  const save = async () => {
    setSaving(true); setError(null); setMessage(null);
    try {
      const effects: unknown[] = [];
      for (const draft of drafts) {
        const result = await apiRequest<{ inventory_affected?: unknown[] }>(draft.id ? `/supplier-invoices/${draft.id}` : "/supplier-invoices", {
          method: draft.id ? "PUT" : "POST", body: JSON.stringify(payload(draft)),
        });
        effects.push(...(result.inventory_affected ?? []));
      }
      setDrafts([]); setFiles([]);
      if (input.current) input.current.value = "";
      await Promise.all([loadHistory(), onInventoryChanged()]);
      window.dispatchEvent(new CustomEvent("inventario:inventory-changed", { detail: effects }));
      setMessage("Factura de proveedor registrada e inventario actualizado");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo registrar la factura. Los cambios siguen en pantalla.");
    } finally { setSaving(false); }
  };

  const editInvoice = (invoice: RegisteredInvoice) => {
    setDrafts([{ ...invoice, lines: invoice.lines.map((line) => ({ ...line, status: "recognized", reviewed: true })) }]);
    setFiles([]); setError(null); setMessage(null);
  };
  const cancelInvoice = async (invoice: RegisteredInvoice) => {
    if (!window.confirm(`¿Anular la factura ${invoice.invoice_number}? Se creará una salida compensatoria.`)) return;
    setError(null);
    try {
      const result = await apiRequest<{ inventory_affected?: unknown[] }>(`/supplier-invoices/${invoice.id}/cancel`, { method: "POST" });
      await Promise.all([loadHistory(), onInventoryChanged()]);
      window.dispatchEvent(new CustomEvent("inventario:inventory-changed", { detail: result.inventory_affected ?? [] }));
      setMessage("Factura anulada e inventario compensado");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "No se pudo anular la factura."); }
  };

  return <section className="supplier-invoice-import">
    <div className="panel-title"><div><h2>Ingresar facturas de proveedores</h2><p>Lee PDF, facturas escaneadas e imágenes. Ningún producto se crea automáticamente.</p></div></div>
    {message && <div className="message success">{message}</div>}
    {error && <div className="message error" role="alert">{error}</div>}
    {!drafts.length && <div className="supplier-drop-zone" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
      <strong>Arrastra una o varias facturas aquí</strong><span>PDF, PNG, JPG o WEBP · máximo 15 MB cada una</span>
      <input ref={input} type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.webp" onChange={onFileInput} />
      <button className="secondary-button" type="button" onClick={() => input.current?.click()}>Seleccionar archivos</button>
      {files.length > 0 && <ul>{files.map((file) => <li key={`${file.name}-${file.size}`}>{file.name}</li>)}</ul>}
      <button className="primary-button" type="button" disabled={!files.length || loading} onClick={analyze}>{loading ? "Procesando documentos…" : "Leer y revisar"}</button>
    </div>}
    {drafts.length > 0 && <>
      <div className="review-filters" aria-label="Filtros de revisión">
        <button type="button" className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>Todos</button>
        <button type="button" className={filter === "recognized" ? "active" : ""} onClick={() => setFilter("recognized")}>Relacionados</button>
        <button type="button" className={filter === "pending" ? "active" : ""} onClick={() => setFilter("pending")}>Pendientes ({pending})</button>
      </div>
      {drafts.map((draft, draftIndex) => <article className="supplier-review" key={draft.id ?? draft.original_filename ?? draftIndex}>
        <div className="supplier-header-grid">
          <label><span>Proveedor</span><input value={draft.supplier_name ?? ""} onChange={(event) => updateDraft(draftIndex, { supplier_name: event.target.value })} /></label>
          <label><span>RUC</span><input value={draft.supplier_ruc ?? ""} onChange={(event) => updateDraft(draftIndex, { supplier_ruc: event.target.value })} /></label>
          <label><span>Número de factura</span><input value={draft.invoice_number ?? ""} onChange={(event) => updateDraft(draftIndex, { invoice_number: event.target.value })} /></label>
          <label><span>Fecha de emisión</span><input type="date" value={draft.issued_at ?? ""} onChange={(event) => updateDraft(draftIndex, { issued_at: event.target.value })} /></label>
          <label><span>Autorización</span><input value={draft.authorization_number ?? ""} onChange={(event) => updateDraft(draftIndex, { authorization_number: event.target.value || null })} /></label>
          <label><span>Total</span><input type="number" step="0.01" value={draft.total ?? ""} onChange={(event) => updateDraft(draftIndex, { total: event.target.value ? Number(event.target.value) : null })} /></label>
        </div>
        {draft.warnings?.map((warning) => <p className="message warning" key={warning}>{warning}</p>)}
        <div className="supplier-summary"><span>Líneas detectadas: <strong>{draft.lines.length}</strong></span><span>Relacionadas: <strong>{draft.lines.filter((line) => line.reviewed && line.sku).length}</strong></span><span>Pendientes: <strong>{draft.lines.filter((line) => !line.reviewed || !line.sku).length}</strong></span></div>
        <div className="table-scroll"><table className="supplier-lines"><thead><tr><th>Producto de la factura</th><th>Producto del catálogo</th><th>Cantidad</th><th>Precio unitario</th><th>Total</th><th>Estado</th><th>Acciones</th></tr></thead>
          <tbody>{draft.lines.map((line, lineIndex) => visible(line) && <tr key={line.line_number}>
            <td><strong>{line.description || "Línea agregada manualmente"}</strong><small>Código: {line.supplier_code || "—"} · Barras: {line.barcode || "—"}</small></td>
            <td><ProductCombobox label={`Producto línea ${line.line_number}`} value={line.sku ?? ""} products={line.sku && line.product_name && !products.some((product) => product.sku === line.sku) ? [...products, { sku: line.sku, product_name: line.product_name }] : products} onSelect={(sku, product) => updateLine(draftIndex, lineIndex, { sku: sku || null, product_name: product?.product_name ?? null, reviewed: Boolean(sku), status: sku ? "recognized" : "not_found" })} /></td>
            <td><input aria-label={`Cantidad línea ${line.line_number}`} type="number" min={1} value={line.quantity} onChange={(event) => updateLine(draftIndex, lineIndex, { quantity: event.target.value === "" ? "" : Number(event.target.value) })} /></td>
            <td><input type="number" min={0} step="0.000001" value={line.unit_price ?? ""} onChange={(event) => updateLine(draftIndex, lineIndex, { unit_price: event.target.value ? Number(event.target.value) : null })} /></td>
            <td>{line.line_total ?? "—"}</td>
            <td><span className={`status-pill ${line.reviewed && line.sku ? "success" : "warning"}`}>{line.reviewed && line.sku ? "Revisado" : "Pendiente"}</span></td>
            <td><button className="text-button" type="button" onClick={() => duplicateLine(draftIndex, lineIndex)}>Duplicar</button><button className="text-button danger" type="button" onClick={() => removeLine(draftIndex, lineIndex)}>Eliminar</button></td>
          </tr>)}</tbody></table></div>
        <div className="line-heading"><button className="text-button" type="button" onClick={() => updateDraft(draftIndex, { lines: [...draft.lines, emptyLine(draft.lines.length + 1)] })}>+ Agregar producto</button><button className="text-button" type="button" onClick={() => updateDraft(draftIndex, { lines: draft.lines.map((line) => line.sku ? { ...line, reviewed: true, status: "recognized" } : line) })}>Confirmar todos los relacionados</button></div>
      </article>)}
      <div className="form-actions"><button className="secondary-button" type="button" onClick={() => { setDrafts([]); setError(null); }}>Cancelar</button><button className="primary-button" type="button" disabled={saving || pending > 0 || drafts.some((draft) => !draft.supplier_ruc || !draft.invoice_number || !draft.issued_at || !draft.supplier_name || !draft.lines.length)} onClick={save}>{saving ? "Guardando…" : drafts.some((draft) => draft.id) ? "Guardar corrección" : "Confirmar ingreso e inventario"}</button></div>
    </>}
    <div className="supplier-history"><h3>Facturas de proveedores registradas</h3>{registered.length === 0 ? <p>No hay facturas registradas.</p> : <div className="table-scroll"><table><thead><tr><th>Fecha</th><th>Proveedor</th><th>Factura</th><th>Líneas</th><th>Unidades</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>{registered.map((invoice) => <tr key={invoice.id}><td>{invoice.issued_at}</td><td>{invoice.supplier_name}<small>RUC: {invoice.supplier_ruc}</small></td><td>{invoice.invoice_number}</td><td>{invoice.lines.length}</td><td>{invoice.lines.reduce((sum, line) => sum + Number(line.quantity), 0)}</td><td>{invoice.status === "cancelled" ? "Anulada" : "Confirmada"}</td><td>{invoice.status !== "cancelled" && <><button className="text-button" type="button" onClick={() => editInvoice(invoice)}>Editar</button><button className="text-button danger" type="button" onClick={() => void cancelInvoice(invoice)}>Anular</button></>}</td></tr>)}</tbody></table></div>}</div>
  </section>;
}
