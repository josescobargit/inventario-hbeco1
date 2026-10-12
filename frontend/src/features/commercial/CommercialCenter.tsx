import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest, apiUrl } from "../../api/client";
import type { Alert, CommercialData, CommercialProduct, ComparisonRow, Evidence, Filters } from "./types";
import "./commercial.css";
const n = (v: number | null | undefined) => v == null ? "Sin dato" : new Intl.NumberFormat("es-EC", { maximumFractionDigits: 2 }).format(v);
const usd = (v: number | null | undefined) => v == null ? "Sin dato" : new Intl.NumberFormat("es-EC", { style: "currency", currency: "USD" }).format(v);
const labels: Record<string, string> = { order: "Pedido", invoice: "Facturado", sell_in: "Sell In", sell_out: "Sell Out", ordered: "Unidades pedidas", invoiced: "Unidades facturadas", missing: "Unidades faltantes", ordered_amount: "Dinero pedido", invoiced_amount: "Dinero facturado", unbilled_amount: "Dinero no facturado", sell_in_units: "Sell In", sell_out_units: "Sell Out" };
const tabs = ["Resumen", "OC vs facturas", "Por cadena", "Sell In / Sell Out", "Histórico", "Maestro", "Asistente", "Reporte"] as const;
type Tab = typeof tabs[number];
const initialFilters: Filters = { date_from: "", date_to: "", chain: "", product_id: "", line: "", target: "95", economic_threshold: "1000" };
function params(filters: Filters) { return new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== "")).toString(); }
function bodyFilters(filters: Filters) { return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== "").map(([key, value]) => [key, key === "target" || key === "economic_threshold" ? Number(value) : value])); }
export function CommercialCenter({ initialTab = "Resumen" }: { initialTab?: Tab } = {}) {
    const [advanced, setAdvanced] = useState(false);
    const [tab, setTab] = useState<Tab>(initialTab);
    const [filters, setFilters] = useState(initialFilters);
    const [draftFilters, setDraftFilters] = useState(initialFilters);
    const [data, setData] = useState<CommercialData | null>(null);
    const [products, setProducts] = useState<CommercialProduct[]>([]);
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState<Evidence | null>(null);
    const generation = useRef(0);
    const refresh = useCallback(async (signal?: AbortSignal) => {
        const request = ++generation.current;
        setLoading(true);
        setError("");
        try {
            const [result, catalog] = await Promise.all([apiRequest<CommercialData>(`/commercial/dashboard?${params(filters)}`, {signal}), apiRequest<CommercialProduct[]>("/commercial/products", {signal})]);
            if (request === generation.current && !signal?.aborted) {
                setData(result);
                setProducts(catalog);
            }
        }
        catch (e) {
            if (request === generation.current && !signal?.aborted) {
                setData(null);
                setError(e instanceof Error ? e.message : "No se pudieron consultar los datos");
            }
        }
        finally {
            if (request === generation.current && !signal?.aborted)
                setLoading(false);
        }
    }, [filters]);
    useEffect(() => {
        const controller = new AbortController();
        const timer = window.setTimeout(() => void refresh(controller.signal), 0);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [refresh]);
    function openAlert(alert: Alert) { const record = data?.records.find(r => alert.record_ids.includes(r.id)); if (record)
        setSelected(record); }
    return <section className="commercial-center">
    <header className="commercial-header"><div><span className="commercial-eyebrow">GERENCIA COMERCIAL</span><h1>{initialTab === "Sell In / Sell Out" ? "Sell In / Sell Out" : "Dashboard comercial"}</h1><p>Indicadores, cumplimiento y oportunidades por cadena.</p></div><div className="commercial-actions"><button className="commercial-primary" onClick={() => window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "processing" }))}>Procesar documentos</button><button aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>Más opciones</button></div></header>
    <nav className="commercial-tabs" aria-label="Control comercial">{tabs.filter(t => !["Histórico", "Maestro"].includes(t)).map(t => <button key={t} aria-label={t} onClick={() => setTab(t)} aria-current={tab === t ? "page" : undefined}>{t}</button>)}</nav>
    {advanced && <><div className="commercial-actions">{(["Histórico", "Maestro"] as const).map(t => <button key={t} onClick={() => setTab(t)}>{t}</button>)}</div>
    <form className="commercial-filters" onSubmit={e => { e.preventDefault(); setFilters({ ...draftFilters }); }}>
      <label>Desde<input type="date" value={draftFilters.date_from} onChange={e => setDraftFilters({ ...draftFilters, date_from: e.target.value })}/></label>
      <label>Hasta<input type="date" value={draftFilters.date_to} min={draftFilters.date_from} onChange={e => setDraftFilters({ ...draftFilters, date_to: e.target.value })}/></label>
      <label>Cadena<input placeholder="Todas las cadenas" value={draftFilters.chain} onChange={e => setDraftFilters({ ...draftFilters, chain: e.target.value })}/></label>
      <label>Producto<select value={draftFilters.product_id} onChange={e => setDraftFilters({ ...draftFilters, product_id: e.target.value })}><option value="">Todos los productos</option>{products.map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</select></label>
      <label>Línea<input placeholder="Todas las líneas" value={draftFilters.line} onChange={e => setDraftFilters({ ...draftFilters, line: e.target.value })}/></label>
      <label>Objetivo %<input type="number" min="0" max="100" step="0.1" required value={draftFilters.target} onChange={e => setDraftFilters({ ...draftFilters, target: e.target.value })}/></label>
      <label>Alerta económica USD<input type="number" min="0" step="0.01" required value={draftFilters.economic_threshold} onChange={e => setDraftFilters({ ...draftFilters, economic_threshold: e.target.value })}/></label>
      <button disabled={loading}>Aplicar filtros</button><button type="button" disabled={loading} onClick={() => { setFilters(initialFilters); setDraftFilters(initialFilters); }}>Ver histórico completo</button>
    </form></>}
    {error && <p role="alert" className="commercial-error">{error} <button onClick={() => void refresh()}>Reintentar</button></p>}
    {loading && <p role="status">Consultando documentos y recalculando resultados…</p>}
    {!loading && data?.summary && <>
      {tab === "Resumen" && <>
        <div className="commercial-kpis">{[["Pedido total", usd(data.summary.ordered_amount)], ["Facturado de estas OC", usd(data.summary.invoiced_amount)], ["Dinero no facturado", usd(data.summary.unbilled_amount)], ["Cumplimiento", data.summary.fulfillment == null ? "Sin dato" : `${n(data.summary.fulfillment)}%`], ["Unidades pedidas", n(data.summary.ordered)], ["Unidades facturadas", n(data.summary.invoiced)], ["Unidades faltantes", n(data.summary.missing)], ["Sell In / Sell Out", `${n(data.summary.sell_in_units)} / ${n(data.summary.sell_out_units)}`]].map(([label, value]) => <article key={label}><span>{label}</span><strong>{value}</strong></article>)}</div>
        {data.summary.review_records > 0 && <div className="commercial-notice"><strong>{data.summary.review_records} registros necesitan revisión.</strong> Los totales solo incluyen cantidades verificables. <button onClick={() => setTab("OC vs facturas")}>Revisar cruce comercial</button></div>}
        <div className="commercial-grid"><BarChart title="Pedido vs facturado por cadena" items={data.chains.map(c => ({ label: c.chain, value: c.ordered, secondary: c.invoiced }))}/><BarChart title="Dinero pendiente por cadena · USD" items={data.chains.map(c => ({ label: c.chain, value: c.unbilled_amount }))}/><BarChart title="Cumplimiento por cadena · %" items={data.chains.map(c => ({ label: c.chain, value: c.fulfillment }))}/><BarChart title="Unidades faltantes por cadena" items={data.chains.map(c => ({ label: c.chain, value: c.missing }))}/></div>
        <div className="commercial-grid">{Object.entries(data.rankings).map(([key, rows]) => <article className="commercial-panel" key={key}><h2>{{ chains_billed: "Cadenas con mayor facturación", chains_low_fulfillment: "Menor cumplimiento", chains_missing: "Mayor faltante por cadena", products_ordered: "Productos más pedidos", products_billed: "Productos más facturados", products_missing: "Productos con mayor faltante", products_impact: "Impacto económico por producto" }[key] ?? key}</h2>{rows.length ? <ol className="commercial-ranking">{rows.map((r, i) => <li key={i}><span>{r.chain || r.product_name}</span><strong>{key.includes("impact") ? usd(r.unbilled_amount) : key === "chains_billed" ? usd(r.invoiced_amount) : key.includes("fulfillment") ? `${n(r.fulfillment)}%` : key.includes("ordered") ? n(r.ordered) : key === "products_billed" ? n(r.invoiced) : n(r.missing)}</strong></li>)}</ol> : <Empty />}</article>)}</div>
        <Alerts alerts={data.alerts} onOpen={openAlert}/>
      </>}
      {tab === "OC vs facturas" && <><div className="commercial-section-heading"><h2>Pedido, facturación y faltantes</h2><ExportLink filters={filters} view="detail"/></div><ComparisonTable key={params(filters)} rows={data.rows} onEvidence={setSelected}/></>}
      {tab === "Por cadena" && <><h2>Consolidado por cadena y producto</h2><p>Selecciona una cadena en los filtros para exportar su resultado.</p><ExportLink filters={filters} view="chain"/><ComparisonTable key={params(filters)} rows={data.by_chain_product} onEvidence={setSelected}/></>}
      {tab === "Sell In / Sell Out" && <Sales data={data}/>}
      {tab === "Histórico" && <History key={params(filters)} filters={filters} data={data}/>}
      {tab === "Maestro" && <Master products={products} onSaved={refresh}/>}
      {tab === "Asistente" && <Assistant key={params(filters)} filters={filters} onEvidence={setSelected} records={data.records}/>}
      {tab === "Reporte" && <section className="commercial-panel"><h2>Resumen para gerencia</h2>{data.executive_report.map((text, i) => <p key={i}>{text}</p>)}<div className="commercial-actions"><ExportLink filters={filters} view="general"/><ExportLink filters={filters} view="missing"/><ExportLink filters={filters} view="report" format="pdf"/></div></section>}
      <footer className="commercial-basis"><strong>Base de cálculo.</strong> {data.basis}</footer>
    </>}
    {selected && <EvidenceDialog record={selected} products={products} onClose={() => setSelected(null)} onSaved={async () => { setSelected(null); await refresh(); }}/>}
  </section>;
}
function Empty({ text = "No hay datos confirmados para estos filtros." }: {
    text?: string;
}) { return <p className="commercial-empty">{text}</p>; }
function Status({ value }: {
    value: string;
}) { return <span className={`commercial-status ${value === "COMPLETO" || value === "VALIDADO" ? "ok" : "review"}`}>{value}</span>; }
function Pagination({ page, total, onChange }: {
    page: number;
    total: number;
    onChange: (p: number) => void;
}) { return total > 50 ? <div className="commercial-actions"><button disabled={!page} onClick={() => onChange(page - 1)}>Anterior</button><span>{page * 50 + 1}–{Math.min(page * 50 + 50, total)} de {total}</span><button disabled={(page + 1) * 50 >= total} onClick={() => onChange(page + 1)}>Siguiente</button></div> : null; }
function ExportLink({ filters, view, format = "xlsx" }: {
    filters: Filters;
    view: string;
    format?: string;
}) { return <a className="commercial-download" href={apiUrl(`/commercial/export?${params(filters)}&view=${view}&format=${format}`)}>{format === "pdf" ? "Descargar PDF gerencial" : view === "missing" ? "Excel de faltantes" : view === "chain" ? "Excel por cadena" : view === "detail" ? "Excel OC vs factura" : "Descargar Excel general"}</a>; }
function BarChart({ title, items }: {
    title: string;
    items: {
        label: string;
        value: number | null;
        secondary?: number;
    }[];
}) {
    const max = Math.max(1, ...items.flatMap(i => [i.value ?? 0, i.secondary ?? 0]));
    return <article className="commercial-panel"><h2>{title}</h2>{items.some(i => i.secondary != null) && <p className="commercial-legend">■ Pedido <span>■ Facturado</span></p>}{!items.length && <Empty />}{items.slice(0, 12).map((item, i) => <div className="commercial-bar-row" key={i}><div><span>{item.label}</span><strong>{n(item.value)}{item.secondary != null && ` / ${n(item.secondary)}`}</strong></div><div className="commercial-track"><span style={{ width: `${(item.value ?? 0) / max * 100}%` }}/></div>{item.secondary != null && <div className="commercial-track secondary"><span style={{ width: `${item.secondary / max * 100}%` }}/></div>}</div>)}</article>;
}
function Alerts({ alerts, onOpen }: {
    alerts: Alert[];
    onOpen: (a: Alert) => void;
}) { const [all, setAll] = useState(false); return <section className="commercial-panel"><h2>Lo que necesita atención <small>({alerts.length})</small></h2>{!alerts.length && <Empty text="No se detectaron alertas en los datos disponibles."/>}{(all ? alerts : alerts.slice(0, 15)).map((a, i) => <button className="commercial-alert" key={i} onClick={() => onOpen(a)}><span className={a.level === "ALTA" ? "high" : ""}>{a.level}</span><span>{a.message}</span><span>Ver evidencia →</span></button>)}{alerts.length > 15 && <button onClick={() => setAll(!all)}>{all ? "Mostrar menos" : "Ver todas las alertas"}</button>}</section>; }
function ComparisonTable({ rows, onEvidence }: {
    rows: ComparisonRow[];
    onEvidence: (e: Evidence) => void;
}) { const [page, setPage] = useState(0); return <><div className="commercial-table-wrap"><table><thead><tr>{["Cadena / OC", "Producto", "Pedido", "Facturado", "Diferencia", "% entrega", "Faltante", "$ pedido", "$ facturado", "$ no facturado", "Estado", "Trazabilidad"].map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{rows.slice(page * 50, page * 50 + 50).map((r, i) => <tr key={i}><td>{r.chain}<small>{r.order_number}</small></td><td>{r.product_name}<small>{r.sku}</small></td><td>{n(r.ordered)}</td><td>{n(r.invoiced)}</td><td>{n(r.difference)}</td><td>{n(r.fulfillment)}{r.fulfillment != null && "%"}</td><td>{n(r.missing)}</td><td>{usd(r.ordered_amount)}</td><td>{usd(r.invoiced_amount)}</td><td>{usd(r.unbilled_amount)}</td><td><Status value={r.status}/></td><td>{r.order_records && <details><summary>OC → facturas</summary>{[...r.order_records, ...r.invoices, ...r.pending_records].map(e => <button className="commercial-evidence-link" key={e.id} onClick={() => onEvidence(e)}>{e.kind === "order" ? `OC ${e.order_number}` : `Factura ${e.invoice_number}`} · {n(e.units)} unidades</button>)}</details>}</td></tr>)}</tbody></table></div>{!rows.length && <Empty />}<Pagination page={page} total={rows.length} onChange={setPage}/></>; }
function EvidenceDialog({ record, products, onClose, onSaved }: {
    record: Evidence;
    products: CommercialProduct[];
    onClose: () => void;
    onSaved: () => Promise<void>;
}) {
    const [values, setValues] = useState<Record<string, unknown>>({});
    const [reason, setReason] = useState("");
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState("");
    const [text, setText] = useState<string | null>(null);
    const dialog = useRef<HTMLDialogElement>(null);
    useEffect(() => { dialog.current?.showModal(); }, []);
    const fields: [
        string,
        string
    ][] = [["kind", "Tipo (OC, factura, Sell In, Sell Out)"], ["chain", "Cadena"], ["date", "Fecha (AAAA-MM-DD)"], ["order_number", "Número de OC"], ["invoice_number", "Número de factura"], ["product_name", "Descripción del documento"], ["code", "Código"], ["ean", "EAN"], ["quantity", "Cantidad original"], ["unit", "Unidad (unidades, cajas, packs)"], ["boxes", "Cajas"], ["total_units", "Unidades totales"], ["units_per_box", "Unidades por caja"], ["unit_price", "Precio por unidad original"], ["amount", "Subtotal neto"], ["currency", "Moneda"], ["status", "Estado (activo, anulada, reemplazada, excluido)"], ["replaces", "Factura que reemplaza"]];
    async function save(e: React.FormEvent) { e.preventDefault(); setSaving(true); setError(""); try {
        await apiRequest(`/commercial/records/${record.id}`, { method: "PATCH", body: JSON.stringify({ revision: record.revision, reason, values }) });
        await onSaved();
    }
    catch (e) {
        setError(e instanceof Error ? e.message : "No se pudo guardar");
    }
    finally {
        setSaving(false);
    } }
    return <dialog ref={dialog} className="commercial-dialog" onCancel={onClose}><div className="commercial-section-heading"><h2>Evidencia del cálculo</h2><button onClick={onClose} aria-label="Cerrar evidencia">Cerrar ×</button></div><p><strong>{record.filename}</strong> · {record.source_location}</p><p>{record.conversion}</p><p>Producto: {record.match_method}</p>{[...record.issues, ...record.monetary_issues].map((t, i) => <p className="commercial-notice" key={i}>{t}</p>)}
    {record.origin === "import" ? <><a href={apiUrl(record.source_url)}>Descargar documento original</a><button onClick={async () => { try {
        const r = await apiRequest<{
            text: string | null;
        }>(`/commercial/documents/${record.document_id}/text`);
        setText(r.text ?? "Este archivo se extrajo como tabla; consulta las celdas originales.");
    }
    catch (e) {
        setError(e instanceof Error ? e.message : "No se pudo leer el texto");
    } }}>Ver texto extraído</button></> : <p>Registro operativo. Abre {record.kind === "order" ? "Órdenes de compra" : "Facturación"} para consultar su documento y modificarlo.</p>}
    {text && <pre>{text}</pre>}<details><summary>Datos originales (sin modificaciones)</summary><pre>{JSON.stringify(record.original_source ?? record.source, null, 2)}</pre></details>
    {record.origin === "import" && <form onSubmit={save}><h3>Corregir únicamente los datos dudosos</h3><div className="commercial-edit-grid">{fields.map(([key, label]) => <label key={key}>{label}<input value={String(values[key] ?? record.source[key] ?? "")} onChange={e => setValues({ ...values, [key]: e.target.value })}/></label>)}<label>Producto confirmado<select value={String(values.product_id ?? record.source.product_id ?? "")} onChange={e => setValues({ ...values, product_id: e.target.value })}><option value="">Conservar reconocimiento automático</option>{products.map(p => <option key={p.id} value={p.id}>{p.sku} · {p.name}</option>)}</select></label></div><label className="commercial-checkbox"><input type="checkbox" checked={Boolean(values.extraction_confirmed ?? record.source.extraction_confirmed)} onChange={e => setValues({ ...values, extraction_confirmed: e.target.checked })}/> Verifiqué la extracción contra el documento original</label><label>Motivo y evidencia de la corrección<textarea required minLength={5} maxLength={2000} value={reason} onChange={e => setReason(e.target.value)}/></label><button className="commercial-primary" disabled={saving || !Object.keys(values).length}>{saving ? "Guardando…" : "Guardar corrección y recalcular"}</button><button type="button" disabled={saving || reason.trim().length < 5 || !Object.keys(values).some(k => ["kind", "chain", "date", "currency", "order_number", "invoice_number"].includes(k))} onClick={async () => { setSaving(true); setError(""); try {
        const headers = Object.fromEntries(Object.entries(values).filter(([k, v]) => ["kind", "chain", "date", "currency", "order_number", "invoice_number"].includes(k) && v));
        await apiRequest(`/commercial/documents/${record.document_id}/missing-header`, { method: "PATCH", body: JSON.stringify({ reason, values: headers }) });
        await onSaved();
    }
    catch (e) {
        setError(e instanceof Error ? e.message : "No se pudo completar la cabecera");
    }
    finally {
        setSaving(false);
    } }}>Aplicar cabecera a campos vacíos de este documento</button></form>}{error && <p role="alert">{error}</p>}</dialog>;
}
function Sales({ data }: {
    data: CommercialData;
}) { return <><h2>Sell In y Sell Out</h2><p>Se usan los reportes cargados explícitamente como Sell In/Out. La ausencia de un reporte no equivale a cero ventas.</p><div className="commercial-grid">{["sell_in", "sell_out"].map(kind => <BarChart key={kind} title={`${labels[kind]} · unidades por producto`} items={data.sales.filter(s => s.kind === kind).sort((a, b) => b.units - a.units).map(s => ({ label: `${s.chain} · ${s.product_name}`, value: s.units }))}/>)}</div><div className="commercial-table-wrap"><table><thead><tr>{["Reporte", "Cadena", "Producto", "Línea", "Unidades", "USD", "Participación"].map(t => <th key={t}>{t}</th>)}</tr></thead><tbody>{data.sales.map((s, i) => <tr key={i}><td>{labels[s.kind]}</td><td>{s.chain}</td><td>{s.product_name}</td><td>{s.line}</td><td>{n(s.units)}</td><td>{usd(s.amount)}</td><td>{n(s.share)}%</td></tr>)}</tbody></table></div><h2>Abastecimiento y movimiento</h2><div className="commercial-table-wrap"><table><thead><tr><th>Cadena / producto</th><th>Sell In</th><th>Sell Out</th><th>Diferencia comparable</th><th>Hipótesis para revisión</th></tr></thead><tbody>{data.sell_comparison.map((s, i) => <tr key={i}><td>{s.chain}<small>{s.product_name}</small></td><td>{n(s.sell_in)}</td><td>{n(s.sell_out)}</td><td>{n(s.difference)}</td><td>{s.hypothesis}</td></tr>)}</tbody></table></div>{!data.sales.length && <Empty />}<div className="commercial-grid">{["sell_in", "sell_out"].map(kind => <BarChart key={kind} title={`${labels[kind]} · ventas por línea USD`} items={data.sales_by_line.filter(s => s.kind === kind).map(s => ({ label: s.line, value: s.amount }))}/>)}</div><h2>Movimientos mensuales registrados</h2><p>Comparación de los dos últimos meses consecutivos disponibles por producto. La cobertura parcial puede explicar una variación.</p><div className="commercial-table-wrap"><table><thead><tr><th>Reporte / cadena</th><th>Producto</th><th>Períodos</th><th>Unidades anteriores / actuales</th><th>Variación</th></tr></thead><tbody>{data.sales_movements.map((s, i) => <tr key={i}><td>{labels[s.kind]}<small>{s.chain}</small></td><td>{s.product_name}</td><td>{s.previous_period} → {s.period}</td><td>{n(s.previous)} / {n(s.current)}</td><td>{n(s.variation)}{s.variation != null && "%"}</td></tr>)}</tbody></table></div></>; }
function History({ filters, data }: {
    filters: Filters;
    data: CommercialData;
}) {
    const [from, setFrom] = useState("");
    const [to, setTo] = useState("");
    const [grain, setGrain] = useState("month");
    const [comparison, setComparison] = useState<{
        changes: {
            metric: string;
            current: number | null;
            previous: number | null;
            difference: number | null;
            variation: number | null;
        }[];
        sales_changes: {
            kind: string;
            chain: string;
            product_name: string;
            current: number | null;
            previous: number | null;
            variation: number | null;
        }[];
        caveat: string;
    } | null>(null);
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    return <><h2>Evolución y comparación de períodos</h2><label>Agrupar<select value={grain} onChange={e => setGrain(e.target.value)}><option value="month">Mensual</option><option value="week">Semanal</option></select></label><div className="commercial-grid">{["order", "invoice", "sell_in", "sell_out"].map(kind => <BarChart key={kind} title={`${labels[kind]} · unidades`} items={data.evolution.filter(p => p.grain === grain && p.kind === kind).map(p => ({ label: p.period, value: p.units }))}/>)}</div><section className="commercial-panel"><h2>Comparar con otro período</h2><p>El período actual es el de los filtros superiores. Define ambas fechas para compararlo.</p><form className="commercial-actions" onSubmit={async (e) => { e.preventDefault(); setError(""); setBusy(true); try {
        setComparison(await apiRequest("/commercial/compare", { method: "POST", body: JSON.stringify({ ...bodyFilters(filters), previous_from: from, previous_to: to }) }));
    }
    catch (e) {
        setError(e instanceof Error ? e.message : "Error en la comparación");
    }
    finally {
        setBusy(false);
    } }}><label>Período anterior desde<input type="date" required value={from} onChange={e => setFrom(e.target.value)}/></label><label>Hasta<input type="date" required min={from} value={to} onChange={e => setTo(e.target.value)}/></label><button disabled={busy || !filters.date_from || !filters.date_to}>Comparar períodos</button></form>{error && <p role="alert">{error}</p>}{comparison && <><p>{comparison.caveat}</p><div className="commercial-table-wrap"><table><thead><tr><th>Indicador</th><th>Actual</th><th>Anterior</th><th>Diferencia</th><th>Variación</th></tr></thead><tbody>{comparison.changes.map(c => <tr key={c.metric}><td>{labels[c.metric]}</td><td>{n(c.current)}</td><td>{n(c.previous)}</td><td>{n(c.difference)}</td><td>{n(c.variation)}{c.variation != null && "%"}</td></tr>)}</tbody></table></div><h3>Crecimiento y caída por producto</h3><div className="commercial-table-wrap"><table><thead><tr><th>Reporte</th><th>Cadena / producto</th><th>Actual</th><th>Anterior</th><th>Variación</th></tr></thead><tbody>{comparison.sales_changes.map((c, i) => <tr key={i}><td>{labels[c.kind]}</td><td>{c.chain}<small>{c.product_name}</small></td><td>{n(c.current)}</td><td>{n(c.previous)}</td><td>{n(c.variation)}{c.variation != null && "%"}</td></tr>)}</tbody></table></div></>}</section></>;
}
function Master({ products, onSaved }: {
    products: CommercialProduct[];
    onSaved: () => Promise<void>;
}) {
    const [selected, setSelected] = useState<CommercialProduct | null>(null);
    const [form, setForm] = useState({ ean14: "", presentation: "", content: "", line: "", aliases: "", reason: "" });
    const [error, setError] = useState("");
    const [saving, setSaving] = useState(false);
    return <><h2>Tabla maestra de productos</h2><p>Nombre oficial, EAN 13 y unidades por caja vienen del catálogo central. Las equivalencias nuevas requieren confirmación del administrador. Crecimiento → Romero, Hidratación → Coco y Fortalecimiento → Cebolla solo se aceptan si el resto de la identidad coincide. Registra cada equivalencia exacta de packs para evitar confundir contenidos.</p><div className="commercial-table-wrap"><table><thead><tr><th>Producto</th><th>EAN 13 / 14</th><th>Línea / presentación</th><th>Unidades por caja</th><th>Equivalencias</th><th>Acción</th></tr></thead><tbody>{products.map(p => <tr key={p.id}><td>{p.name}<small>{p.sku} · {p.description}</small></td><td>{p.ean13 || "Sin dato"}<small>{p.ean14 || "Sin EAN 14"}</small></td><td>{p.line || p.category}<small>{p.presentation} {p.content}</small></td><td>{p.units_per_box}</td><td>{p.aliases?.join("; ")}{p.chain_aliases.map((a, i) => <small key={i}>{a.chain}: {a.name}</small>)}</td><td><button onClick={() => { setSelected(p); setError(""); setForm({ ean14: p.ean14 || "", presentation: p.presentation || "", content: p.content || "", line: p.line || p.category, aliases: (p.aliases || []).join("\n"), reason: "" }); }}>Completar maestro</button></td></tr>)}</tbody></table></div>{selected && <form className="commercial-panel" onSubmit={async (e) => { e.preventDefault(); setSaving(true); setError(""); try {
        await apiRequest(`/commercial/products/${selected.id}`, { method: "PUT", body: JSON.stringify({ ...form, ean14: form.ean14 || null, aliases: form.aliases.split("\n").map(s => s.trim()).filter(Boolean) }) });
        setSelected(null);
        await onSaved();
    }
    catch (e) {
        setError(e instanceof Error ? e.message : "No se pudo guardar");
    }
    finally {
        setSaving(false);
    } }}><h3>{selected.name}</h3><div className="commercial-edit-grid">{([['ean14', 'EAN 14'], ['presentation', 'Presentación'], ['content', 'Contenido'], ['line', 'Línea']] as const).map(([key, label]) => <label key={key}>{label}<input value={form[key]} onChange={e => setForm({ ...form, [key]: e.target.value })}/></label>)}</div><label>Equivalencias exactas, una por línea<textarea value={form.aliases} onChange={e => setForm({ ...form, aliases: e.target.value })}/></label><label>Motivo / evidencia<textarea required minLength={5} value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })}/></label>{error && <p role="alert">{error}</p>}<button disabled={saving}>Guardar maestro</button><button type="button" onClick={() => setSelected(null)}>Cancelar</button></form>}</>;
}
function Assistant({ filters, records, onEvidence }: {
    filters: Filters;
    records: Evidence[];
    onEvidence: (r: Evidence) => void;
}) {
    const [question, setQuestion] = useState("");
    const [answer, setAnswer] = useState<{
        answer: string[];
        mode: string;
        limitations: string;
        sources: {
            id: string;
            filename: string;
        }[];
        filters: Record<string, unknown>;
    } | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    async function ask(text: string) { setQuestion(text); setBusy(true); setError(""); try {
        setAnswer(await apiRequest("/commercial/assistant", { method: "POST", body: JSON.stringify({ ...bodyFilters(filters), question: text }) }));
    }
    catch (e) {
        setError(e instanceof Error ? e.message : "No se pudo consultar");
    }
    finally {
        setBusy(false);
    } }
    return <section className="commercial-panel"><h2>Asistente comercial</h2><p>Consulta los datos guardados y sus fuentes. Las respuestas se calculan con datos verificables. La interpretación con IA se activa al configurar el proveedor; sin esa conexión, funcionan las consultas locales.</p><div className="commercial-suggestions">{["Analiza esta semana", "¿Qué cadena tiene problemas?", "¿Qué productos no se facturaron?", "¿Cuánto dinero dejamos de facturar?", "Compárame esta semana con la anterior", "Analiza Sell In", "Analiza Sell Out", "Compara Sell In y Sell Out", "Dime qué debería revisar", "Hazme un resumen para gerencia"].map(q => <button disabled={busy} key={q} onClick={() => void ask(q)}>{q}</button>)}</div><form onSubmit={e => { e.preventDefault(); void ask(question); }}><label>Tu pregunta<textarea required minLength={3} maxLength={1500} value={question} onChange={e => setQuestion(e.target.value)} placeholder="¿Qué debería revisar?"/></label><button className="commercial-primary" disabled={busy}>{busy ? "Consultando evidencia…" : "Consultar datos"}</button></form>{error && <p role="alert">{error}</p>}{answer && <article className="commercial-answer" aria-live="polite"><small>{answer.mode} · {String(answer.filters.date_from || "Histórico")} → {String(answer.filters.date_to || "Último registro")}</small>{answer.answer.map((t, i) => <p key={i}>{t}</p>)}<details><summary>Fuentes consultadas ({answer.sources.length})</summary>{answer.sources.map(s => <button key={s.id} onClick={() => { const r = records.find(r => r.id === s.id); if (r)
        onEvidence(r); }}>{s.filename}</button>)}</details><small>{answer.limitations}</small></article>}</section>;
}
