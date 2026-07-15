import { FormEvent, useEffect, useState } from "react";

import { apiRequest } from "../../api/client";

interface OperationalSettings {
  warehouse_name: string;
  low_stock_threshold_mode: "boxes" | "units";
  low_stock_threshold_boxes: number;
  low_stock_threshold_units: number;
  report_default_days: number;
  allow_exception_invoices: boolean;
  suggested_chains: string[];
  invoice_exception_note: string;
  updated_at: string | null;
  updated_by: string | null;
}

const emptySettings: OperationalSettings = {
  warehouse_name: "Bodega principal",
  low_stock_threshold_mode: "boxes",
  low_stock_threshold_boxes: 1,
  low_stock_threshold_units: 0,
  report_default_days: 30,
  allow_exception_invoices: true,
  suggested_chains: ["Gerardo Ortiz", "Favorita", "Rosado", "Danec", "Tía"],
  invoice_exception_note: "Usar excepción cuando la factura no corresponde a una OC normal o tiene otro fin operativo.",
  updated_at: null,
  updated_by: null,
};

const dateLabel = (value: string | null) => value ? new Intl.DateTimeFormat("es-EC", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "Sin cambios registrados";
const normalizeSettings = (value: OperationalSettings): OperationalSettings => ({ ...emptySettings, ...value, low_stock_threshold_mode: value.low_stock_threshold_mode ?? "boxes", low_stock_threshold_units: value.low_stock_threshold_units ?? 0 });

export function SettingsCenter({ userRole = "principal" }: { userRole?: string }) {
  const [settings, setSettings] = useState<OperationalSettings>(emptySettings);
  const [chainText, setChainText] = useState(emptySettings.suggested_chains.join("\n"));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canEdit = userRole === "principal";

  useEffect(() => {
    let ignore = false;
    apiRequest<OperationalSettings>("/settings/operational")
      .then((loaded) => {
        if (ignore) return;
        setSettings(normalizeSettings(loaded));
        setChainText(loaded.suggested_chains.join("\n"));
      })
      .catch((caught) => { if (!ignore) setError(caught instanceof Error ? caught.message : "No se pudo cargar la configuración."); })
      .finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!canEdit) {
      setError("Solo el usuario principal puede guardar cambios de configuración.");
      return;
    }
    setSaving(true);
    setMessage(null);
    setError(null);
    const suggestedChains = chainText.split("\n").map((line) => line.trim()).filter(Boolean);
    apiRequest<OperationalSettings>("/settings/operational", {
      method: "PUT",
      body: JSON.stringify({ ...settings, suggested_chains: suggestedChains }),
    })
      .then((saved) => {
        setSettings(normalizeSettings(saved));
        setChainText(saved.suggested_chains.join("\n"));
        setMessage("Configuración operativa guardada correctamente.");
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No se pudo guardar la configuración."))
      .finally(() => setSaving(false));
  };

  return <main className="dashboard settings-center">
    <section className="module-heading">
      <div className="welcome-block">
        <p className="eyebrow">Administración</p>
        <h1>Configuración</h1>
        <p>Parámetros operativos simples que ayudan a mantener consistente el uso diario del sistema.</p>
      </div>
      <div className="settings-heading-actions">
        <span className="settings-updated">Último cambio: {dateLabel(settings.updated_at)}</span>
        <button className="primary-button" type="submit" form="operational-settings-form" disabled={loading || saving || !canEdit}>{saving ? "Guardando…" : "Guardar cambios"}</button>
      </div>
    </section>

    {!canEdit && <div className="message error" role="alert">Estás viendo la configuración en modo lectura. Para cambiar el umbral de stock bajo debes ingresar con el usuario principal.</div>}
    {message && <div className="message success" role="status">{message}</div>}
    {error && <div className="message error" role="alert">{error}</div>}

    <form id="operational-settings-form" className="settings-workspace" onSubmit={submit}>
      <section className="settings-panel">
        <div className="panel-title"><div><h2>Operación general</h2><p>Valores base para inventario, reportes y documentos excepcionales.</p></div></div>
        {loading ? <div className="table-message">Cargando configuración…</div> : <div className="settings-grid">
          <label><span>Bodega operativa</span><input disabled={!canEdit} required minLength={2} maxLength={120} value={settings.warehouse_name} onChange={(event) => setSettings({ ...settings, warehouse_name: event.target.value })} /></label>
          <label><span>Medir stock bajo por</span><select disabled={!canEdit} value={settings.low_stock_threshold_mode} onChange={(event) => setSettings({ ...settings, low_stock_threshold_mode: event.target.value as "boxes" | "units" })}><option value="boxes">Cajas</option><option value="units">Unidades</option></select><small>Elige una sola forma de medición para evitar confusiones.</small></label>
          <label><span>Umbral stock bajo (cajas)</span><input disabled={!canEdit || settings.low_stock_threshold_mode !== "boxes"} required min={0} max={20} type="number" value={settings.low_stock_threshold_boxes} onChange={(event) => setSettings({ ...settings, low_stock_threshold_boxes: Number(event.target.value) })} /><small>Ej: 2 marca stock bajo cuando el disponible sea menor o igual a 2 cajas según UxC.</small></label>
          <label><span>Umbral stock bajo (unidades)</span><input disabled={!canEdit || settings.low_stock_threshold_mode !== "units"} required min={0} max={10000} type="number" value={settings.low_stock_threshold_units} onChange={(event) => setSettings({ ...settings, low_stock_threshold_units: Number(event.target.value) })} /><small>Ej: 24 marca stock bajo cuando el disponible sea menor o igual a 24 unidades.</small></label>
          <label><span>Días por defecto en reportes</span><input disabled={!canEdit} required min={1} max={365} type="number" value={settings.report_default_days} onChange={(event) => setSettings({ ...settings, report_default_days: Number(event.target.value) })} /></label>
          <label className="toggle-row"><input disabled={!canEdit} type="checkbox" checked={settings.allow_exception_invoices} onChange={(event) => setSettings({ ...settings, allow_exception_invoices: event.target.checked })} /><span>Permitir facturas de excepción</span></label>
          <label className="wide"><span>Nota para facturas de excepción</span><textarea disabled={!canEdit} required minLength={2} maxLength={500} rows={4} value={settings.invoice_exception_note} onChange={(event) => setSettings({ ...settings, invoice_exception_note: event.target.value })} /></label>
        </div>}
      </section>

      <section className="settings-panel">
        <div className="panel-title"><div><h2>Cadenas sugeridas</h2><p>Una por línea. Se usan como sugerencias al registrar órdenes de compra.</p></div><span>{chainText.split("\n").filter((line) => line.trim()).length}</span></div>
        <label className="chain-editor">
          <span>Listado</span>
          <textarea disabled={loading || !canEdit} rows={9} value={chainText} onChange={(event) => setChainText(event.target.value)} />
        </label>
        <div className="settings-note">
          <strong>Importante</strong>
          <p>Esto no bloquea cadenas nuevas: en OC podrás seguir escribiendo otra cadena manualmente si aparece un cliente diferente.</p>
        </div>
      </section>

      <section className="settings-panel settings-summary">
        <div className="panel-title"><div><h2>Resumen</h2><p>Lectura rápida de cómo queda el sistema.</p></div></div>
        <dl>
          <div><dt>Bodega</dt><dd>{settings.warehouse_name}</dd></div>
          <div><dt>Stock bajo</dt><dd>{settings.low_stock_threshold_mode === "boxes" ? `≤ ${settings.low_stock_threshold_boxes} caja${settings.low_stock_threshold_boxes === 1 ? "" : "s"}` : `≤ ${settings.low_stock_threshold_units} unidad${settings.low_stock_threshold_units === 1 ? "" : "es"}`}</dd></div>
          <div><dt>Reportes</dt><dd>{settings.report_default_days} días por defecto</dd></div>
          <div><dt>Facturas excepción</dt><dd>{settings.allow_exception_invoices ? "Permitidas" : "No permitidas"}</dd></div>
          <div><dt>Actualizado por</dt><dd>{settings.updated_by ?? "Sistema"}</dd></div>
        </dl>
      </section>
    </form>
  </main>;
}
