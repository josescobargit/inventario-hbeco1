import { useEffect, useRef, useState } from "react";
import { apiRequest, apiUpload, apiUrl } from "../../api/client";
import type { CommercialData, CommercialProduct, Evidence } from "./types";
import { chains, documentValue, groupDocuments, headerField, kindNames, type DocumentGroup, type ImportResult, type StoredDocument } from "./documentReview";
const fieldLabels: Record<string, string> = { chain: "Cadena", kind: "Tipo de documento", date: "Fecha del documento", order_number: "Número de OC", invoice_number: "Número de factura", currency: "Moneda", product_id: "Producto", product_name: "Descripción del producto", quantity: "Cantidad", unit: "Unidad", units_per_box: "Unidades por caja", total_units: "Unidades totales", amount: "Subtotal", unit_price: "Precio unitario", status: "Estado administrativo", extraction_confirmed: "Extracción verificada con el original" };
const unitName = (value: unknown) => ({ units: "unidades", boxes: "cajas", ambiguous: "Pendiente" }[String(value)] || String(value || "Pendiente"));
const formatDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) ? value.split("-").reverse().join("/") : value;
export function DocumentWorkspace({ data, loading, products, onRefresh }: { data: Pick<CommercialData, "records"> | null; loading: boolean; products: CommercialProduct[]; onRefresh: () => Promise<void> }) {
    const [stored, setStored] = useState<StoredDocument[]>([]);
    const [imports, setImports] = useState<ImportResult[]>([]);
    const [files, setFiles] = useState<File[]>([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [view, setView] = useState("all");
    const [selected, setSelected] = useState<string | null>(null);
    const [page, setPage] = useState(0);
    const input = useRef<HTMLInputElement>(null);
    const results = useRef<HTMLElement>(null);
    useEffect(() => {
        const controller = new AbortController();
        apiRequest<StoredDocument[]>("/commercial/documents", { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setStored(value); }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "No se pudieron consultar los documentos"); });
        return () => controller.abort();
    }, [data]);
    const all = groupDocuments(data?.records ?? [], stored, imports);
    const batchIds = new Set(imports.map(r => r.document_id).filter(Boolean));
    const batch = imports.length ? all.filter(d => batchIds.has(d.id) || d.status === "ERROR") : all;
    const documents = view === "review" ? batch.filter(d => d.status !== "OK") : batch;
    const current = all.find(d => d.id === selected);
    async function process() {
        if (!files.length || busy) return;
        setBusy(true); setError("");
        try {
            const form = new FormData(); files.forEach(f => form.append("files", f));
            const result = await apiUpload<{ files: ImportResult[] }>("/commercial/imports", form);
            setImports(result.files); setFiles([]); if (input.current) input.current.value = "";
            setView("all"); setPage(0); await onRefresh(); results.current?.scrollIntoView({ behavior: "smooth", block: "start" });
        } catch (e) { setError(e instanceof Error ? e.message : "No se pudo procesar la carga"); }
        finally { setBusy(false); }
    }
    return <>
        <section className="commercial-upload simple-upload" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!busy) setFiles(Array.from(e.dataTransfer.files)); }}>
            <h2>Cargar documentos</h2><p>Arrastra un ZIP o tus archivos aquí. También puedes seleccionarlos.</p>
            <input ref={input} aria-label="Archivos comerciales" type="file" multiple disabled={busy} accept=".zip,.pdf,.xlsx,.csv,.png,.jpg,.jpeg,.webp,.tif,.tiff" onChange={e => setFiles(Array.from(e.target.files ?? []))} />
            <button className="commercial-primary" disabled={busy || !files.length} onClick={() => void process()}>{busy ? "Procesando…" : "Procesar"}</button>
            {!!files.length && <p role="status">{files.length === 1 ? files[0]?.name : `${files.length} archivos listos para procesar`}</p>}
        </section>
        {error && <p role="alert" className="commercial-error">{error}</p>}
        <section ref={results} aria-label="Resultados">
            <div className="commercial-section-heading"><h2>Resultados{imports.length ? " de esta carga" : ""}</h2><button aria-pressed={view === "review"} onClick={() => { setView(view === "review" ? "all" : "review"); setPage(0); }}>{view === "review" ? "Ver resultados" : "Revisar problemas"}</button></div>
            {!data && !loading && !busy ? <p className="commercial-empty">No se pudieron consultar los resultados. Reintenta la consulta.</p> : loading || busy ? <p role="status">{busy ? "Procesando documentos…" : "Consultando documentos…"}</p> : <>
                <div className="document-summary" aria-live="polite"><span>Documentos <strong>{batch.filter(d => d.status !== "ERROR").length}</strong></span><span>Procesados correctamente <strong>{batch.filter(d => d.status === "OK").length}</strong></span><span>Requieren revisión <strong>{batch.filter(d => d.status === "REVISAR").length}</strong></span>{batch.some(d => d.status === "ERROR") && <span>Con error <strong>{batch.filter(d => d.status === "ERROR").length}</strong></span>}</div>
                {documents.length ? <div className="commercial-table-wrap"><table><thead><tr>{["Archivo", "Cadena", "Tipo", "Nº documento", "Fecha", "Productos", "Estado", ""].map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{documents.slice(page * 25, page * 25 + 25).map(d => <tr key={d.id}><td><button className="document-filename" onClick={() => setSelected(d.id)}>{d.filename}</button></td><td>{documentValue(d.records, "chain")}</td><td>{kindNames[documentValue(d.records, "kind")] || documentValue(d.records, "kind")}</td><td>{documentValue(d.records, d.records[0]?.kind === "invoice" ? "invoice_number" : "order_number")}</td><td>{formatDate(documentValue(d.records, "date"))}</td><td>{d.records.filter(r => r.product_name).length}</td><td><span className={`commercial-status ${d.status === "OK" ? "ok" : d.status === "ERROR" ? "error" : "review"}`}>{d.status}</span></td><td><button aria-label={`${d.status === "OK" ? "Ver" : "Revisar"} ${d.filename}`} onClick={() => setSelected(d.id)}>{d.status === "OK" ? "Ver detalle" : "Revisar"}</button></td></tr>)}</tbody></table></div> : <p className="commercial-empty">{view === "review" ? "No hay problemas por revisar." : "Carga tus documentos para ver los resultados."}</p>}
                {documents.length > 25 && <div className="commercial-actions"><button disabled={!page} onClick={() => setPage(page - 1)}>Anterior</button><span>{page * 25 + 1}–{Math.min((page + 1) * 25, documents.length)} de {documents.length}</span><button disabled={(page + 1) * 25 >= documents.length} onClick={() => setPage(page + 1)}>Siguiente</button></div>}
                {imports.length > 0 && <button onClick={() => { setImports([]); setPage(0); }}>Ver documentos anteriores</button>}
            </>}
        </section>
        {current && <DocumentDialog key={current.id} document={current} products={products} onClose={() => setSelected(null)} onSaved={async () => { await onRefresh(); }} />}
    </>;
}
export function DocumentDialog({ document: d, products, onClose, onSaved }: { document: DocumentGroup; products: CommercialProduct[]; onClose: () => void; onSaved: () => Promise<void> }) {
    const dialog = useRef<HTMLDialogElement>(null);
    const [values, setValues] = useState<Record<string, string | boolean>>({});
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState("");
    const [editing, setEditing] = useState<Evidence | null>(null);
    useEffect(() => { dialog.current?.showModal(); }, []);
    const headers = [...new Set(d.records.flatMap(r => [...r.issues, ...r.monetary_issues].map(i => headerField(i, r))).filter((f): f is string => !!f))];
    const otherIssues = d.issues.filter(i => !headerField(i, d.records[0]));
    const imported = d.records.length > 0 && d.records.every(r => r.origin === "import");
    async function save(e: React.FormEvent) {
        e.preventDefault(); setSaving(true); setError("");
        try {
            await apiRequest(`/commercial/documents/${d.id}/header`, { method: "PATCH", body: JSON.stringify({ values, reason: "Corrección de campos dudosos desde revisión de documento", revisions: Object.fromEntries(d.records.map(r => [r.id, r.revision])) }) });
            setValues({}); await onSaved();
        } catch (e) { setError(e instanceof Error ? e.message : "No se pudo guardar"); }
        finally { setSaving(false); }
    }
    return <dialog ref={dialog} className="commercial-dialog" onCancel={onClose}><div className="commercial-section-heading"><h2>{d.filename}</h2><button onClick={onClose}>Cerrar</button></div>
        {d.status === "OK" ? <p className="document-success">OK · No necesitas confirmar ningún dato.</p> : <><p><strong>{d.issues.length} {d.issues.length === 1 ? "problema" : "problemas"}</strong></p>{d.issues.filter(i => headerField(i, d.records[0])).map(i => <p key={i} className="commercial-notice">{i}</p>)}</>}
        {!!headers.length && imported && <form onSubmit={save}><div className="commercial-edit-grid">{headers.map(field => <Field key={field} field={field} value={values[field] ?? ""} onChange={value => setValues({ ...values, [field]: value })} products={products} />)}</div><button className="commercial-primary" disabled={saving || !Object.keys(values).length}>{saving ? "Guardando…" : "Aplicar a todo el documento"}</button></form>}
        {otherIssues.map(i => <p className="commercial-notice" key={i}>{i}</p>)}
        {d.needsReprocessing && <button className="commercial-primary" disabled={saving} onClick={async () => { setSaving(true); setError(""); try { await apiRequest(`/commercial/documents/${d.id}/reprocess`, { method: "POST" }); await onSaved(); } catch (e) { setError(e instanceof Error ? e.message : "No se pudo reprocesar"); } finally { setSaving(false); } }}>{saving ? "Procesando…" : "Volver a procesar el original"}</button>}
        {error && <p role="alert">{error}</p>}
        {d.failure && <p>Vuelve a cargar este archivo para reintentar el procesamiento.</p>}
        {!imported && d.records.length > 0 && <p>Este documento pertenece al módulo operativo. Corrígelo desde Órdenes de compra o Facturación en Más opciones.</p>}
        {d.records[0]?.source_url && <a className="commercial-download" href={apiUrl(d.records[0].source_url)}>Ver documento original</a>}
        <details open={d.status === "OK"}><summary>Productos encontrados ({d.records.length})</summary><div className="commercial-table-wrap"><table><thead><tr><th>Producto</th><th>Cantidad</th><th>Unidad</th><th>Estado</th><th></th></tr></thead><tbody>{d.records.map(r => {
            const issues = [...r.issues, ...r.monetary_issues].filter(i => !headerField(i, r));
            return <tr key={r.id}><td>{r.product_name}<small>{r.order_number || r.invoice_number} · {r.chain} · {formatDate(r.date || "Pendiente")}</small></td><td>{String(r.source.quantity ?? r.units ?? "Pendiente")}</td><td>{unitName(r.source.unit || (r.units != null ? "unidades" : "Pendiente"))}</td><td>{issues.length ? "REVISAR" : "OK"}</td><td>{issues.length > 0 && imported && <button onClick={() => setEditing(r)}>Resolver</button>}</td></tr>;
        })}</tbody></table></div></details>
        {editing && <ProductException key={editing.id} record={editing} products={products} onSaved={async () => { setEditing(null); await onSaved(); }} onCancel={() => setEditing(null)} />}
    </dialog>;
}
function Field({ field, value, onChange, products }: { field: string; value: string | boolean; onChange: (value: string | boolean) => void; products: CommercialProduct[] }) {
    const options = field === "chain" ? chains.map(c => [c, c]) : field === "status" ? [["excluido", "Excluir esta copia de los totales"]] : field === "kind" ? Object.entries(kindNames) : field === "product_id" ? products.map(p => [p.id, p.name]) : null;
    return <label>{fieldLabels[field] || field}{options ? <select value={String(value)} onChange={e => onChange(e.target.value)}><option value="">Seleccionar…</option>{options.map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select> : field === "extraction_confirmed" ? <input type="checkbox" checked={value === true} onChange={e => onChange(e.target.checked)} /> : <input type={field === "date" ? "date" : "text"} value={String(value)} onChange={e => onChange(e.target.value)} />}</label>;
}
function ProductException({ record: r, products, onSaved, onCancel }: { record: Evidence; products: CommercialProduct[]; onSaved: () => Promise<void>; onCancel: () => void }) {
    const [values, setValues] = useState<Record<string, string | boolean>>({});
    const [error, setError] = useState("");
    const [saving, setSaving] = useState(false);
    const issues = [...r.issues, ...r.monetary_issues].filter(i => !headerField(i, r));
    const fields = new Set<string>();
    for (const issue of issues) {
        if (/descripci[oó]n/i.test(issue)) fields.add("product_name");
        if (/producto|pack|EAN|código/i.test(issue)) fields.add(r.match_method === "Documento original" ? "product_name" : "product_id");
        if (/cantidad|unidades|cajas|conversión/i.test(issue)) { fields.add("quantity"); fields.add("total_units"); fields.add("units_per_box"); }
        if (/unidad de cantidad|base del precio/i.test(issue)) fields.add("unit");
        if (/precio|importe|subtotal/i.test(issue)) { fields.add("amount"); fields.add("unit_price"); }
        if (/extracción|OCR/i.test(issue)) fields.add("extraction_confirmed");
        if (/estado|duplicad/i.test(issue)) fields.add("status");
    }
    return <form className="commercial-panel" onSubmit={async e => { e.preventDefault(); setSaving(true); setError(""); try { await apiRequest(`/commercial/records/${r.id}`, { method: "PATCH", body: JSON.stringify({ revision: r.revision, values, reason: "Resolución de excepción del producto desde el documento" }) }); await onSaved(); } catch (e) { setError(e instanceof Error ? e.message : "No se pudo guardar"); } finally { setSaving(false); } }}><h3>{r.product_name}</h3>{issues.map(i => <p key={i}>{i}</p>)}<div className="commercial-edit-grid">{[...fields].map(f => <Field key={f} field={f} products={products} value={values[f] ?? String(r.source[f] ?? "")} onChange={value => setValues({ ...values, [f]: value })} />)}</div>{!fields.size && <p>Consulta la evidencia original y las herramientas de Más opciones para resolver esta excepción.</p>}{error && <p role="alert">{error}</p>}<button disabled={saving || !Object.keys(values).length}>Guardar corrección</button><button type="button" onClick={onCancel}>Cancelar</button></form>;
}
