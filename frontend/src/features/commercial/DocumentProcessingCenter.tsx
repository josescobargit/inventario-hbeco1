import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../../api/client";
import { DocumentWorkspace } from "./DocumentWorkspace";
import type { Evidence } from "./types";
import "./commercial.css";

export function DocumentProcessingCenter() {
    const [data, setData] = useState<{ records: Evidence[] } | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const generation = useRef(0);
    const refresh = useCallback(async (signal?: AbortSignal) => {
        const request = ++generation.current;
        setLoading(true); setError("");
        try {
            const result = await apiRequest<{ records: Evidence[] }>("/commercial/processing", { signal });
            if (request === generation.current && !signal?.aborted) setData(result);
        } catch (e) {
            if (request === generation.current && !signal?.aborted) { setData(null); setError(e instanceof Error ? e.message : "No se pudieron consultar los documentos"); }
        } finally { if (request === generation.current && !signal?.aborted) setLoading(false); }
    }, []);
    useEffect(() => { const controller = new AbortController(); const timer = window.setTimeout(() => void refresh(controller.signal), 0); return () => { window.clearTimeout(timer); controller.abort(); }; }, [refresh]);
    return <section className="commercial-center"><header className="commercial-header"><div><span className="commercial-eyebrow">IMPORTAR OC / FACTURAS</span><h1>Procesar documentos</h1><p>Carga archivos, procesa y revisa solo los datos dudosos.</p></div></header><DocumentWorkspace data={data} products={[]} loading={loading} onRefresh={refresh} />{error && <p className="commercial-error" role="alert">{error} <button onClick={() => void refresh()}>Reintentar</button></p>}</section>;
}
