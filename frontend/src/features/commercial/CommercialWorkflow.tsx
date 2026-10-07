import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { apiRequest, apiUpload } from "../../api/client";
import { DocumentDialog } from "./DocumentWorkspace";
import { groupDocuments, type ImportResult } from "./documentReview";
import type { Evidence } from "./types";
import "./commercial.css";
import "./workflow.css";

type Mode = "orders" | "invoices" | "comparisons";
type Line = { id: string; key: string; name: string; code: string; quantity: number | null; unit: string; unit_price: number | null; currency?: string | null; amount: number | null; issues: string[] };
type Doc = { id: string; document_id: string; kind: string; number: string; chain: string; date: string | null; filename: string; origin: string; lines: Line[]; quantity: number | null; quantity_unit: string; currency?: string | null; amount: number | null; issues: string[]; records: Evidence[]; linked_order_id: string | null; link_method: string | null; reference: string; status: string; fulfillment: number | null; versions?: { id: string; document_id: string; filename: string; date: string | null; origin: string; lines: Line[]; records: Evidence[] }[]; invoices?: { id: string; number: string; date: string; method: string }[] };
type Comparison = { chain: string; order_id: string; order_number: string; product: string; code: string; unit: string; ordered: number | null; invoiced: number | null; difference: number | null; missing: number | null; fulfillment: number | null; ordered_amount: number | null; invoiced_amount: number | null; unbilled_amount: number | null; currency?: string | null; invoiced_currency?: string | null; status: string };
type Workflow = { orders: Doc[]; invoices: Doc[]; comparisons: Comparison[]; chains: { chain: string; orders: number; invoices: number; linked: number; linked_orders: number; pending: number; status: string }[]; summary: { invoices: number; linked: number; pending: number } };
const titles = { orders: "Órdenes de compra", invoices: "Facturación", comparisons: "Comparativo OC vs Facturado" };
const n = (v: number | null | undefined) => v == null ? "Pendiente" : new Intl.NumberFormat("es-EC", { maximumFractionDigits: 2 }).format(v);
const money = (v: number | null | undefined, currency?: string | null) => v == null ? "Sin dato" : currency && /^[A-Z]{3}$/.test(currency) ? new Intl.NumberFormat("es-EC", { style: "currency", currency }).format(v) : `${n(v)} · moneda pendiente`;
const date = (v: string | null) => v ? v.split("-").reverse().join("/") : "Pendiente";
function Status({ value }: { value: string }) { return <span className={`commercial-status ${["OK", "COMPLETO"].includes(value) ? "ok" : "review"}`}>{value}</span>; }

export function CommercialWorkflow({ mode, advanced }: { mode: Mode; advanced: ReactNode }) {
    const [data, setData] = useState<Workflow | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [chain, setChain] = useState<string | null>(null);
    const [selected, setSelected] = useState<string | null>(() => sessionStorage.getItem(`commercial.open.${mode}`));
    const [review, setReview] = useState(false);
    const [advancedOpen, setAdvancedOpen] = useState(false);
    const [documentId, setDocumentId] = useState<string | null>(null);
    const [files, setFiles] = useState<File[]>([]);
    const [busy, setBusy] = useState(false);
    const [imports, setImports] = useState<ImportResult[]>([]);
    const [linkTarget, setLinkTarget] = useState("");
    const input = useRef<HTMLInputElement>(null);
    const generation = useRef(0);
    const refresh = useCallback(async (signal?: AbortSignal) => {
        const gen = ++generation.current; setLoading(true); setError("");
        try { const result = await apiRequest<Workflow>("/commercial/workflow", { signal }); if (gen === generation.current && !signal?.aborted) setData(result); }
        catch (e) { if (!signal?.aborted && gen === generation.current) setError(e instanceof Error ? e.message : "No se pudieron consultar los documentos"); }
        finally { if (!signal?.aborted && gen === generation.current) setLoading(false); }
    }, []);
    useEffect(() => { sessionStorage.removeItem(`commercial.open.${mode}`); }, [mode]);
    useEffect(() => { const c = new AbortController(); const t = window.setTimeout(() => void refresh(c.signal), 0); return () => { window.clearTimeout(t); c.abort(); }; }, [refresh]);
    const docs = mode === "orders" ? data?.orders ?? [] : data?.invoices ?? [];
    const scopedChain = chain ?? (selected ? [...data?.orders ?? [], ...data?.invoices ?? []].find(d => d.id === selected)?.chain || null : null);
    const allRecords = [...new Map([...data?.orders ?? [], ...data?.invoices ?? []].flatMap(d => [...d.records, ...d.versions?.flatMap(v => v.records) ?? []]).map(r => [r.id, r])).values()];
    const detail = groupDocuments(allRecords, [], []).find(d => d.id === documentId);
    const visible = docs.filter(d => (scopedChain == null || (d.chain || "Sin identificar") === scopedChain) && (!review || (mode === "orders" ? d.issues.length > 0 || d.status === "REVISAR" : d.status === "REVISAR")));
    const current = visible.find(d => d.id === selected);
    const comparisons = (data?.comparisons ?? []).filter(r => (scopedChain == null || (r.chain || "Sin identificar") === scopedChain) && (!selected || r.order_id === selected) && (!review || r.status === "REVISAR"));
    async function process() {
        if (!files.length || busy) return;
        setBusy(true); setError("");
        try { const form = new FormData(); files.forEach(f => form.append("files", f)); const result = await apiUpload<{ files: ImportResult[] }>("/commercial/imports", form); setImports(result.files); setFiles([]); if (input.current) input.current.value = ""; await refresh(); }
        catch (e) { setError(e instanceof Error ? e.message : "No se pudo procesar la carga"); }
        finally { setBusy(false); }
    }
    async function link(invoice: Doc) {
        const target = data?.orders.find(o => o.id === linkTarget); if (!target) return;
        setBusy(true); setError("");
        try {
            await apiRequest(`/commercial/documents/${invoice.document_id}/header`, { method: "PATCH", body: JSON.stringify({ values: { order_number: target.number, chain: target.chain }, revisions: Object.fromEntries(invoice.records.map(r => [r.id, r.revision])), reason: "Vinculación de factura a OC seleccionada en revisión de excepción" }) });
            setLinkTarget(""); await refresh();
        } catch (e) { setError(e instanceof Error ? e.message : "No se pudo vincular"); }
        finally { setBusy(false); }
    }
    function openRelated(target: Mode, id: string) {
        sessionStorage.setItem(`commercial.open.${target}`, id);
        window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: target }));
    }
    async function chooseVersion(doc: Doc, recordId: string) {
        setBusy(true); setError("");
        try { await apiRequest("/commercial/workflow/version", { method: "POST", body: JSON.stringify({ record_id: recordId, reason: "Versión elegida después de revisar los documentos originales", revisions: Object.fromEntries(doc.versions?.flatMap(v => v.records).map(r => [r.id, r.revision]) ?? []) }) }); await refresh(); }
        catch (e) { setError(e instanceof Error ? e.message : "No se pudo elegir la versión"); }
        finally { setBusy(false); }
    }
    return <main className="commercial-center commercial-workflow">
        <header className="commercial-header"><div><span className="commercial-eyebrow">OC → FACTURACIÓN → COMPARATIVO</span><h1>{titles[mode]}</h1><p>{mode === "orders" ? "¿Qué pidió cada cadena? Carga la OC y queda guardada." : mode === "invoices" ? "¿Qué se facturó realmente? Carga, vincula y revisa solo excepciones." : "¿Cuál fue la diferencia? Resultado de las OC y facturas ya guardadas."}</p></div><div className="commercial-actions"><button disabled={loading || busy} onClick={() => void refresh()}>Actualizar</button><button aria-expanded={advancedOpen} onClick={() => setAdvancedOpen(!advancedOpen)}>Más opciones</button></div></header>
        {advancedOpen ? <section className="workflow-advanced"><button onClick={() => setAdvancedOpen(false)}>Volver al flujo comercial</button>{advanced}</section> : <>
            {mode !== "comparisons" && <section className="commercial-upload simple-upload" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!busy) setFiles(Array.from(e.dataTransfer.files)); }}><h2>{mode === "orders" ? "Cargar OC" : "Cargar facturas"}</h2><p>Arrastra PDF, imágenes o ZIP. Se guardan automáticamente al procesar.</p><input ref={input} aria-label={mode === "orders" ? "Archivos de OC" : "Archivos de facturas"} type="file" multiple accept=".pdf,.zip,.png,.jpg,.jpeg,.webp,.tif,.tiff,.csv,.xlsx" disabled={busy} onChange={e => setFiles(Array.from(e.target.files ?? []))} /><button className="commercial-primary" disabled={busy || !files.length} onClick={() => void process()}>{busy ? "Procesando…" : "Procesar"}</button>{!!files.length && <p>{files.length} archivo(s) listo(s)</p>}</section>}
            {imports.length > 0 && <p role="status">Última carga: {imports.filter(i => i.status === "processed").length} procesados · {imports.filter(i => i.status === "duplicate").length} ya registrados · {imports.filter(i => i.status === "error").length} errores</p>}
            {imports.some(i => i.document_id && (mode === "orders" ? data?.invoices : data?.orders)?.some(d => d.document_id === i.document_id)) && <p className="commercial-notice">También se detectaron {mode === "orders" ? "facturas, disponibles en Facturación" : "OC, disponibles en Órdenes de compra"}.</p>}
            {imports.filter(i => i.status === "error").map((i, index) => <p role="alert" key={index} className="commercial-error">{i.filename}: {i.message}</p>)}
            {mode === "invoices" && data && <div className="document-summary"><span>Facturas detectadas <strong>{data.summary.invoices}</strong></span><span>Vinculadas automáticamente <strong>{data.summary.linked}</strong></span><span>Requieren revisión <strong>{data.summary.pending}</strong></span></div>}
            {error && <p role="alert" className="commercial-error">{error}</p>}{loading && <p role="status">Consultando documentos guardados…</p>}
            {data && <><div className="commercial-section-heading"><h2>{scopedChain ?? "Cadenas"}</h2><div className="commercial-actions">{scopedChain !== null && <button onClick={() => { setChain(null); setSelected(null); }}>Todas las cadenas</button>}<button aria-pressed={review} onClick={() => setReview(!review)}>{review ? "Ver todos" : "Revisar solo excepciones"}</button></div></div>
                <div className="commercial-table-wrap"><table aria-label="Resumen por cadena"><thead><tr><th>Cadena</th><th>OC</th><th>Facturas</th><th>OC vinculadas</th><th>Pendientes</th><th>Estado</th></tr></thead><tbody>{data.chains.filter(c => (mode !== "invoices" || c.invoices > 0) && (scopedChain == null || c.chain === scopedChain) && (!review || (mode === "invoices" ? c.pending > 0 : c.status === "REVISAR"))).map(c => <tr key={c.chain}><td><button className="document-filename" onClick={() => { setChain(c.chain); setSelected(null); }}>{c.chain}</button></td><td>{c.orders}</td><td>{c.invoices}</td><td>{c.linked_orders}</td><td>{c.pending}</td><td><Status value={mode === "invoices" ? c.pending ? "REVISAR" : "OK" : c.status} /></td></tr>)}</tbody></table>{!(mode === "invoices" ? data.summary.invoices : data.chains.length) && <p className="commercial-empty">{mode === "invoices" ? "Carga tus facturas para vincularlas con las OC guardadas." : "Carga tu primera OC para comenzar."}</p>}</div>
                {mode === "comparisons" ? <><label className="workflow-order-filter">Orden de compra<select aria-label="Filtrar por OC" value={selected ?? ""} onChange={e => setSelected(e.target.value || null)}><option value="">Todas las OC</option>{data.orders.filter(o => chain == null || (o.chain || "Sin identificar") === chain).map(o => <option key={o.id} value={o.id}>{o.chain} · OC {o.number}</option>)}</select></label><ComparisonTable rows={comparisons} />{data.summary.pending > 0 && <p className="commercial-notice">{data.summary.pending} factura(s) pendientes de vincular. Revísalas en Facturación para completar el comparativo.</p>}</> : <div className="workflow-columns"><section className="workflow-documents" aria-label="Documentos por cadena">{visible.length ? Object.entries(visible.reduce<Record<string, Doc[]>>((groups, d) => { const key = d.chain || "Sin identificar"; (groups[key] ??= []).push(d); groups[key].sort((a, b) => (a.linked_order_id || a.reference).localeCompare(b.linked_order_id || b.reference)); return groups; }, {})).map(([name, grouped]) => <div key={name}><h3>{name}</h3>{grouped?.map((d, index) => <div key={d.id}>{mode === "invoices" && (index === 0 || grouped[index - 1]?.linked_order_id !== d.linked_order_id || grouped[index - 1]?.reference !== d.reference) && <h4>OC {data.orders.find(o => o.id === d.linked_order_id)?.number || d.reference || "pendiente"}</h4>}<button className={`workflow-document ${current?.id === d.id ? "selected" : ""}`} key={d.id} onClick={() => { setSelected(d.id); setLinkTarget(""); }}><span><strong>{mode === "orders" ? "OC" : "Factura"} {d.number || "Pendiente"}</strong><small>{date(d.date)} · {d.lines.filter(l => l.name).length} productos</small>{mode === "invoices" && <small>OC: {data.orders.find(o => o.id === d.linked_order_id)?.number || d.reference || "Pendiente"}</small>}</span><Status value={mode === "orders" ? d.issues.length ? "REVISAR" : "OK" : d.status} /></button></div>)}</div>) : <p className="commercial-empty">{review ? "No hay documentos por revisar." : "No hay documentos en esta vista."}</p>}</section>
                    <section className="workflow-detail" aria-label="Detalle del documento">{current ? <><div className="commercial-section-heading"><div><p className="commercial-eyebrow">{current.chain || "Sin identificar"}</p><h2>{current.kind === "order" ? "OC" : "Factura"} {current.number || "Pendiente"}</h2></div><Status value={current.status} /></div><p>{date(current.date)} · {current.filename}</p><div className="document-summary"><span>Productos <strong>{current.lines.filter(l => l.name).length}</strong></span><span>Cantidad total <strong>{n(current.quantity)} {current.quantity != null ? current.quantity_unit : ""}</strong></span><span>Valor total <strong>{money(current.amount, current.currency)}</strong></span>{mode === "orders" && <span>Facturado <strong>{current.fulfillment == null ? "Pendiente" : `${n(current.fulfillment)} %`}</strong></span>}</div>
                        {current.issues.length > 0 && <div className="commercial-notice"><strong>{current.issues.length} excepción(es)</strong>{current.issues.map(i => <p key={i}>{i}</p>)}</div>}
                        {current.versions && <section className="commercial-panel"><h3>Versiones del documento</h3><p>Hay diferencias entre las copias. Consulta los originales y elige la válida para continuar.</p>{current.versions.map(v => <div className="workflow-version" key={v.id}><strong>{v.filename}</strong><span>{date(v.date)} · {v.lines.length} productos · {v.lines.map(l => `${n(l.quantity)} ${l.unit}`).join(" / ")}</span>{v.origin === "import" && <button onClick={() => setDocumentId(v.document_id)}>Ver original y detalle</button>}{current.versions?.every(item => item.origin === "import") && <button disabled={busy || !v.records[0]} onClick={() => void chooseVersion(current, v.records[0]!.id)}>Usar esta versión</button>}</div>)}</section>}
                        {mode === "orders" && <><h3>Facturas vinculadas ({current.invoices?.length ?? 0})</h3>{current.invoices?.length ? current.invoices.map(i => <p key={i.id}><button className="document-filename" onClick={() => openRelated("invoices", i.id)}>{i.number} · {date(i.date)}</button><small>{i.method}</small></p>) : <p>Sin facturas vinculadas todavía.</p>}</>}
                        {mode === "invoices" && <p>OC: {current.linked_order_id ? <button className="document-filename" onClick={() => openRelated("orders", current.linked_order_id!)}>{data.orders.find(o => o.id === current.linked_order_id)?.number}</button> : <strong>{current.reference || "Pendiente"}</strong>}{current.link_method && <small>{current.link_method}</small>}</p>}
                        {mode === "invoices" && current.status === "REVISAR" && current.origin === "import" && <div className="workflow-link"><label>Vincular a OC<select aria-label="OC para vincular" value={linkTarget} onChange={e => setLinkTarget(e.target.value)}><option value="">Seleccionar OC…</option>{data.orders.filter(o => !o.issues.length && (!current.chain || o.chain === current.chain)).map(o => <option value={o.id} key={o.id}>{o.chain} · OC {o.number} · {date(o.date)}</option>)}</select></label><button disabled={!linkTarget || busy} onClick={() => void link(current)}>Guardar vínculo</button></div>}
                        {current.origin === "import" && <button onClick={() => setDocumentId(current.document_id)}>{current.issues.length ? "Revisar campos del documento" : "Ver documento y evidencia"}</button>}
                        <h3>Productos</h3><div className="commercial-table-wrap"><table><thead><tr><th>Producto</th><th>Cantidad</th><th>Unidad</th><th>Precio</th><th>Valor</th></tr></thead><tbody>{current.lines.map(l => <tr key={l.id}><td>{l.name || "Pendiente"}<small>{l.code}</small></td><td>{n(l.quantity)}</td><td>{l.unit || "Pendiente"}</td><td>{money(l.unit_price, l.currency)}</td><td>{money(l.amount, l.currency)}</td></tr>)}</tbody></table></div>
                        {mode === "orders" && <><div className="commercial-section-heading"><h3>Pedido vs Facturado</h3><button onClick={() => openRelated("comparisons", current.id)}>Ver comparativo de esta OC</button></div><ComparisonTable rows={data.comparisons.filter(r => r.order_id === current.id)} /></>}
                    </> : <p className="commercial-empty">Selecciona {mode === "orders" ? "una OC" : "una factura"} para ver sus productos y {mode === "orders" ? "facturas vinculadas" : "OC relacionada"}.</p>}</section></div>}
            </>}
        </>}
        {detail && <DocumentDialog key={detail.id} document={detail} products={[]} onClose={() => setDocumentId(null)} onSaved={refresh} />}
    </main>;
}
function ComparisonTable({ rows }: { rows: Comparison[] }) {
    return <div className="commercial-table-wrap"><table aria-label="Pedido vs Facturado"><thead><tr>{["Cadena / OC", "Producto", "Unidad", "Pedido OC", "Facturado", "Diferencia", "% entrega", "Faltante", "Valor pedido", "Valor facturado", "Dinero no facturado", "Estado"].map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((r, i) => <tr key={`${r.order_id}-${i}`}><td>{r.chain}<small>OC {r.order_number}</small></td><td>{r.product}<small>{r.code}</small></td><td>{r.unit}</td><td>{n(r.ordered)}</td><td>{n(r.invoiced)}</td><td>{n(r.difference)}</td><td>{r.fulfillment == null ? "Pendiente" : `${n(r.fulfillment)} %`}</td><td>{n(r.missing)}</td><td>{money(r.ordered_amount, r.currency)}</td><td>{money(r.invoiced_amount, r.invoiced_currency)}</td><td>{money(r.unbilled_amount, r.currency)}</td><td><Status value={r.status} /></td></tr>)}</tbody></table>{!rows.length && <p className="commercial-empty">No hay productos para esta selección. El comparativo usa los documentos guardados.</p>}</div>;
}
