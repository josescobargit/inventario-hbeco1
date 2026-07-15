import { type FormEvent, useState } from "react";
import { apiRequest } from "../../api/client";

interface PreviewRow { sku: string; product_name: string; current_physical: number; counted_physical: number; difference: number; position_version: number }
interface Preview { valid: boolean; rows: PreviewRow[]; errors: Array<{ row: number | null; sku: string | null; message: string }> }

export function StockImportPanel({ onApplied }: { onApplied: () => void }) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage(null);
    const body = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/v1/stock-imports/preview", { method: "POST", credentials: "include", body });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? "No pudimos revisar el archivo.");
      setPreview(result);
    } catch (error) { setMessage(error instanceof Error ? error.message : "No pudimos revisar el archivo."); }
    finally { setBusy(false); }
  }

  async function confirm() {
    if (!preview?.valid || reason.trim().length < 5) { setMessage("Escribe un motivo de al menos 5 caracteres."); return; }
    setBusy(true); setMessage(null);
    try {
      const result = await apiRequest<{ status: string }>("/stock-imports", { method: "POST", body: JSON.stringify({ reason, lines: preview.rows.map((row) => ({ sku: row.sku, counted_physical: row.counted_physical, position_version: row.position_version })) }) });
      setMessage(result.status === "approved" ? "Conteo aplicado correctamente." : "Conteo enviado para aprobación.");
      setPreview(null); setReason(""); onApplied();
    } catch (error) { setMessage(error instanceof Error ? error.message : "No pudimos confirmar el conteo."); }
    finally { setBusy(false); }
  }

  return <section className="import-panel">
    <div><p className="eyebrow">Conteo físico</p><h2>Carga masiva</h2><p>Descarga la plantilla, completa unidades y revisa las diferencias antes de confirmar.</p></div>
    <div className="import-actions"><a className="secondary-button" href="/api/v1/stock-imports/template">Descargar plantilla CSV</a><form onSubmit={upload}><input name="file" type="file" accept=".csv,.xlsx" required /><button disabled={busy}>{busy ? "Revisando…" : "Vista previa"}</button></form></div>
    {message && <div className="message">{message}</div>}
    {preview && !preview.valid && <div className="import-errors">{preview.errors.map((error, index) => <p key={`${error.sku}-${index}`}>Fila {error.row ?? "—"} · {error.sku ?? "sin SKU"}: {error.message}</p>)}</div>}
    {preview?.valid && <div className="preview-box"><strong>{preview.rows.length} productos revisados</strong><p>{preview.rows.filter((row) => row.difference !== 0).length} diferencias frente al stock actual.</p><label>Motivo del conteo<input value={reason} onChange={(event) => setReason(event.target.value)} /></label><button onClick={confirm} disabled={busy}>Confirmar conteo completo</button></div>}
  </section>;
}
