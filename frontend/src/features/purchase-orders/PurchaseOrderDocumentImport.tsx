import { ChangeEvent, DragEvent, useState } from "react";

import { ApiError, apiRequest, apiUpload, apiUrl } from "../../api/client";
import {
  CustomerAlias, DocumentProductLine, MatchableProduct, normalizeProductText,
  parseDocumentProductLines, extractVisibleUnitTotal, parsePositionalTableRows,
  PositionalTableRow,
} from "../invoices/quickEntry";
import { DocumentViewer } from "./DocumentViewer";

interface OrderSummary { id: string; chain_name: string; order_number: string }
interface CreatedOrder extends OrderSummary { lines: unknown[] }
interface PreviewDraft {
  document_token: string; filename: string; content_type: string; extraction_method: string;
  page_count: number; text: string; warnings: string[]; separation_needs_review: boolean;
  header: {
    order_number: string | null; chain_name: string | null; order_date: string | null;
    chain_candidates: string[];
    order_number_source: string | null;
    secondary_reference: string | null;
  };
  classification: {
    type: string; label: string; allowed_for_purchase_order: boolean; message: string;
  };
  signals: {
    order: boolean; chain: boolean; product_structure: boolean;
    quantity_structure: boolean; candidate_rows: number;
  };
  table_rows: PositionalTableRow[];
  expected_product_count: number | null;
}
interface DraftState extends PreviewDraft {
  id: string; order_number: string; chain_name: string; order_date: string;
  destination: string; notes: string; secondaryReference: string; localName: string;
  headerConfirmed: boolean; lines: DocumentProductLine[];
  aliases: CustomerAlias[]; confirmedAliases: Map<string, { source_text: string; detected_code: string | null; sku: string }>;
  visibleUnitTotal: number | null; separationConfirmed: boolean;
  chainCandidates: string[];
  status: "review" | "saving" | "created"; createdOrderId?: string;
}

const accepted = ".pdf,.jpg,.jpeg,.png,.webp";
const maxDocumentBytes = 15 * 1024 * 1024;
export const purchaseOrderPreviewPath = "/purchase-orders/imports/preview";

function documentProcessingError(caught: unknown): string {
  if (caught instanceof ApiError) {
    if (caught.status === 401) return "No se pudo procesar el documento. Detalle: tu sesión expiró; inicia sesión nuevamente.";
    if (caught.status === 404) return "No se pudo procesar el documento. Detalle: el servicio de lectura no está disponible (la ruta de importación respondió 404).";
    if (caught.status >= 500) return "No se pudo procesar el documento. Detalle: el servicio de lectura tuvo un error interno.";
    return `No se pudo procesar el documento. Detalle: ${caught.message}`;
  }
  return "No se pudo procesar el documento. Detalle: no fue posible conectar con el servicio de lectura.";
}

export function PurchaseOrderDocumentImport({
  products, orders, onCreated, onCancel,
}: {
  products: MatchableProduct[];
  orders: OrderSummary[];
  onCreated: (order: CreatedOrder) => void;
  onCancel: () => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [pastedText, setPastedText] = useState("");
  const [drafts, setDrafts] = useState<DraftState[]>([]);
  const [processing, setProcessing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [mobileView, setMobileView] = useState<"document" | "data">("data");
  const [selectedLineId, setSelectedLineId] = useState<string | null>(null);
  const [lineFilter, setLineFilter] = useState<"all" | "recognized" | "not_found" | "missing" | "quantity">("all");
  const [error, setError] = useState<string | null>(null);

  const addFiles = (incoming: File[]) => {
    const supported = ["application/pdf", "image/jpeg", "image/png", "image/webp"];
    const allowed = incoming.filter((file) => supported.includes(file.type) && file.size <= maxDocumentBytes);
    setFiles((current) => [...current, ...allowed].slice(0, 10));
    const oversized = incoming.filter((file) => file.size > maxDocumentBytes);
    const invalid = incoming.filter((file) => !supported.includes(file.type));
    if (oversized.length) setError(`${oversized[0]!.name}: supera el límite de 15 MB.`);
    else if (invalid.length) setError(`${invalid[0]!.name}: usa PDF, JPG, JPEG, PNG o WEBP.`);
    else setError(null);
  };
  const chooseFiles = (event: ChangeEvent<HTMLInputElement>) => addFiles([...event.target.files ?? []]);
  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault(); setDragging(false); addFiles([...event.dataTransfer.files]);
  };
  const process = async () => {
    setProcessing(true); setError(null);
    const data = new FormData();
    files.forEach((file) => data.append("files", file));
    if (pastedText.trim()) data.append("pasted_text", pastedText);
    try {
      const response = await apiUpload<{ drafts: PreviewDraft[] }>(purchaseOrderPreviewPath, data);
      const recognized = await Promise.all(response.drafts.map(async (draft, index) => {
        const chainName = draft.header.chain_name ?? "";
        let aliases: CustomerAlias[] = [];
        if (chainName.length >= 2) {
          try {
            aliases = await apiRequest<CustomerAlias[]>(`/purchase-orders/customer-aliases?chain_name=${encodeURIComponent(chainName)}`);
          } catch {
            // The general parser remains usable if the optional learned profile fails.
          }
        }
        return {
          ...draft, id: `${draft.document_token}-${index}`,
          order_number: draft.header.order_number ?? "", chain_name: chainName,
          chainCandidates: draft.header.chain_candidates ?? [],
          order_date: draft.header.order_date ?? "", destination: "", notes: "",
          secondaryReference: draft.header.secondary_reference ?? "", localName: "",
          headerConfirmed: false,
          lines: draft.table_rows?.length
            ? parsePositionalTableRows(draft.table_rows, products, aliases)
            : parseDocumentProductLines(draft.text, products, aliases),
          aliases,
          visibleUnitTotal: extractVisibleUnitTotal(draft.text),
          separationConfirmed: !draft.separation_needs_review,
          confirmedAliases: new Map(), status: "review" as const,
        };
      }));
      setDrafts(recognized);
    } catch (caught) {
      setError(documentProcessingError(caught));
    } finally {
      setProcessing(false);
    }
  };
  const patchDraft = (id: string, patch: Partial<DraftState>) =>
    setDrafts((current) => current.map((draft) => draft.id === id ? { ...draft, ...patch } : draft));
  const updateLine = (draftId: string, lineId: string, patch: Partial<DocumentProductLine>) =>
    setDrafts((current) => current.map((draft) => draft.id === draftId ? {
      ...draft, lines: draft.lines.map((line) => line.id === lineId ? { ...line, ...patch } : line),
    } : draft));
  const conversionPatch = (
    line: DocumentProductLine,
    patch: Partial<Pick<DocumentProductLine, "original_quantity" | "original_unit_type" | "units_per_box">>,
  ): Partial<DocumentProductLine> => {
    const original = patch.original_quantity ?? line.original_quantity;
    const type = patch.original_unit_type ?? line.original_unit_type;
    const uxc = patch.units_per_box === undefined ? line.units_per_box : patch.units_per_box;
    const calculated = original === null ? null : type === "boxes" ? (uxc ? original * uxc : null) : original;
    return {
      ...patch,
      unit: type === "boxes" ? "CAJAS" : type === "units" ? "UN" : line.unit,
      calculated_units: calculated,
      quantity: calculated,
      calculation_method: type === "units" ? "direct_units" : type === "boxes" && uxc ? line.calculation_method === "document_uxc" ? "document_uxc" : "catalog_uxc" : "manual",
      conversion_confirmed: false,
    };
  };
  const loadCustomerAliases = async (draft: DraftState) => {
    if (draft.chain_name.trim().length < 2) {
      setError("Escribe Cliente/Cadena antes de buscar equivalencias.");
      return;
    }
    try {
      const aliases = await apiRequest<CustomerAlias[]>(`/purchase-orders/customer-aliases?chain_name=${encodeURIComponent(draft.chain_name)}`);
      const retried = draft.table_rows?.length
        ? parsePositionalTableRows(draft.table_rows, products, aliases)
        : parseDocumentProductLines(draft.text, products, aliases);
      const manualByRaw = new Map(draft.lines.filter((line) => line.reviewed && line.sku).map((line) => [normalizeProductText(line.raw), line]));
      patchDraft(draft.id, {
        aliases,
        lines: retried.map((line) => manualByRaw.get(normalizeProductText(line.raw)) ?? line),
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos cargar equivalencias.");
    }
  };
  const confirmLineProduct = (draft: DraftState, line: DocumentProductLine, sku: string) => {
    if (!sku) { updateLine(draft.id, line.id, { sku: "", reviewed: false }); return; }
    const normalized = normalizeProductText(line.raw);
    const catalogUnitsPerBox = products.find((product) => product.sku === sku)?.units_per_box ?? null;
    const confirmedAliases = new Map(draft.confirmedAliases);
    confirmedAliases.set(normalized, { source_text: line.raw, detected_code: line.detected_code || null, sku });
    patchDraft(draft.id, {
      confirmedAliases,
      lines: draft.lines.map((item) => normalizeProductText(item.raw) === normalized
        ? {
          ...item, sku, reviewed: true, confidence: "high", error: null, suggestions: [],
          units_per_box: item.units_per_box ?? catalogUnitsPerBox,
          calculated_units: item.original_unit_type === "boxes"
            ? item.original_quantity !== null && (item.units_per_box ?? catalogUnitsPerBox)
              ? item.original_quantity * (item.units_per_box ?? catalogUnitsPerBox)! : null
            : item.original_quantity,
          quantity: item.original_unit_type === "boxes"
            ? item.original_quantity !== null && (item.units_per_box ?? catalogUnitsPerBox)
              ? item.original_quantity * (item.units_per_box ?? catalogUnitsPerBox)! : null
            : item.original_quantity,
          conversion_confirmed: item.original_unit_type === "units",
        } : item),
    });
  };
  const reprocessDraft = (draft: DraftState) => patchDraft(draft.id, {
    lines: draft.table_rows?.length
      ? parsePositionalTableRows(draft.table_rows, products, draft.aliases)
      : parseDocumentProductLines(draft.text, products, draft.aliases),
  });
  const addLine = (draft: DraftState) => patchDraft(draft.id, { lines: [...draft.lines, {
    id: `document-manual-${Date.now()}`, page: 1, raw: "", detected_code: "", description: "",
    sku: "", quantity: 1,
    unit: "UN", confidence: "low", reviewed: false, error: "Completa y revisa la línea.", suggestions: [],
    original_quantity: 1, original_unit_type: "units", units_per_box: null,
    calculated_units: 1, calculation_method: "direct_units", conversion_confirmed: true,
  }] });
  const confirmAllRecognized = (draft: DraftState) => patchDraft(draft.id, {
    lines: draft.lines.map((line) => ({
      ...line,
      conversion_confirmed: Boolean(
        line.sku && line.original_quantity && line.calculated_units
        && (line.original_unit_type !== "boxes" || line.units_per_box),
      ),
      reviewed: Boolean(line.sku && line.calculated_units),
    })),
  });

  const problems = (draft: DraftState) => {
    const errors: string[] = [];
    if (!draft.order_number.trim()) errors.push("Número de OC obligatorio.");
    if (!draft.chain_name.trim()) errors.push("Cliente/Cadena obligatorio.");
    if (orders.some((order) => normalizeProductText(order.chain_name) === normalizeProductText(draft.chain_name) && order.order_number.trim() === draft.order_number.trim())) errors.push("Esta OC ya existe para la cadena.");
    if (!draft.lines.length) errors.push("Agrega por lo menos un producto.");
    const missingLines = Math.max(0, (draft.expected_product_count ?? draft.lines.length) - draft.lines.length);
    if (missingLines) errors.push(`Falta revisar ${missingLines} línea${missingLines === 1 ? "" : "s"} del documento.`);
    if (draft.lines.some((line) => !line.sku || !line.quantity || line.quantity <= 0)) errors.push("Hay productos no reconocidos o cantidades pendientes.");
    if (draft.lines.some((line) => !line.reviewed)) errors.push("Revisa las líneas de confianza media o baja.");
    if (!draft.classification.allowed_for_purchase_order) errors.push(draft.classification.message);
    if (!draft.headerConfirmed) errors.push("Confirma el número de OC y la cadena.");
    if (draft.lines.some((line) => !line.conversion_confirmed)) errors.push("Confirma todas las cantidades y conversiones.");
    if (!draft.separationConfirmed) errors.push("Confirma la separación detectada entre órdenes.");
    const detectedUnits = draft.lines.reduce((sum, line) => sum + (line.calculated_units ?? 0), 0);
    if (draft.visibleUnitTotal !== null && detectedUnits !== draft.visibleUnitTotal) errors.push(`El documento muestra ${draft.visibleUnitTotal} unidades y el borrador suma ${detectedUnits}.`);
    const skus = draft.lines.map((line) => line.sku).filter(Boolean);
    if (new Set(skus).size !== skus.length) errors.push("Hay productos duplicados.");
    return errors;
  };
  const createOrder = async (draft: DraftState) => {
    const errors = problems(draft);
    if (errors.length) { setError(errors.join(" ")); return; }
    patchDraft(draft.id, { status: "saving" });
    try {
      const created = await apiRequest<CreatedOrder>("/purchase-orders", {
        method: "POST",
        body: JSON.stringify({
          chain_name: draft.chain_name, customer_name: null, order_number: draft.order_number,
          order_date: draft.order_date || null, destination: draft.destination || null,
          notes: draft.notes || null, secondary_reference: draft.secondaryReference || null,
          local_name: draft.localName || null, source_document_tokens: [draft.document_token],
          confirmed_aliases: [...draft.confirmedAliases.values()],
          lines: draft.lines.map((line) => ({
            sku: line.sku, quantity: line.calculated_units,
            original_quantity: line.original_quantity, original_unit: line.original_unit_type,
            units_per_box: line.units_per_box, conversion_method: line.calculation_method,
            conversion_confirmed: line.conversion_confirmed, source_page: line.page,
            source_text: line.raw, source_code: line.detected_code,
            source_description: line.description,
          })),
        }),
      });
      patchDraft(draft.id, { status: "created", createdOrderId: created.id });
      onCreated(created);
    } catch (caught) {
      patchDraft(draft.id, { status: "review" });
      setError(caught instanceof Error ? caught.message : "No pudimos crear la OC.");
    }
  };
  const discardUnlinkedDocuments = async () => {
    await Promise.allSettled([...new Set(drafts.map((draft) => draft.document_token))]
      .map((token) => apiRequest<void>(`/purchase-orders/imports/${token}`, { method: "DELETE" })));
  };
  const resetDocuments = async () => {
    await discardUnlinkedDocuments();
    setDrafts([]);
  };
  const cancelImport = async () => {
    await discardUnlinkedDocuments();
    onCancel();
  };

  const totals = {
    drafts: drafts.length,
    ready: drafts.filter((draft) => !problems(draft).length).length,
    errors: drafts.filter((draft) => problems(draft).length).length,
  };
  const missingLineCount = (draft: DraftState) =>
    Math.max(0, (draft.expected_product_count ?? draft.lines.length) - draft.lines.length);
  const visibleLines = (draft: DraftState) => draft.lines.filter((line) => {
    if (lineFilter === "recognized") return Boolean(line.sku);
    if (lineFilter === "not_found") return !line.sku;
    if (lineFilter === "quantity") return !line.original_quantity || !line.calculated_units;
    if (lineFilter === "missing") return false;
    return true;
  });

  if (!drafts.length) return <section className="order-form document-import">
    <div className="form-section-title"><div><h2>Crear OC desde PDF, imagen o pedido</h2><p>El documento se procesa localmente y siempre genera un borrador para revisión.</p></div></div>
    {error && <div className="message error document-reader-error" role="alert"><span>{error}</span>{(files.length > 0 || pastedText.trim()) && <button type="button" disabled={processing} onClick={process}>Reintentar</button>}</div>}
    <div className={`document-dropzone ${dragging ? "dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
      <strong>Arrastra PDF, JPG, PNG o WEBP</strong><span>Hasta 10 archivos de 15 MB cada uno</span>
      <label className="secondary-button">Seleccionar archivos<input hidden multiple type="file" accept={accepted} onChange={chooseFiles} /></label>
    </div>
    {files.length > 0 && <div className="selected-documents">{files.map((file, index) => <span key={`${file.name}-${index}`}>{file.name}<button type="button" onClick={() => setFiles((current) => current.filter((_, itemIndex) => itemIndex !== index))}>×</button></span>)}</div>}
    <label className="notes-field"><span>O pega el texto del pedido</span><textarea rows={10} value={pastedText} onChange={(event) => setPastedText(event.target.value)} placeholder="Pega aquí el contenido completo de la orden…" /></label>
    <div className="form-actions"><button className="secondary-button" type="button" onClick={onCancel}>Cancelar</button><button className="primary-button" type="button" disabled={processing || (!files.length && !pastedText.trim())} onClick={process}>{processing ? "Procesando documento…" : "Procesar y crear borradores"}</button></div>
  </section>;

  return <section className="order-form document-review">
    <div className="form-section-title"><div><h2>Revisión de órdenes reconocidas</h2><p>{totals.drafts} borradores · {totals.ready} listos · {totals.errors} con pendientes</p></div><button className="secondary-button" type="button" onClick={resetDocuments}>Cargar otros documentos</button></div>
    <div className="mobile-document-toggle" role="group" aria-label="Vista de revisión"><button type="button" className={mobileView === "document" ? "active" : ""} onClick={() => setMobileView("document")}>Documento original</button><button type="button" className={mobileView === "data" ? "active" : ""} onClick={() => setMobileView("data")}>Datos reconocidos</button></div>
    {error && <div className="message error" role="alert">{error}</div>}
    {drafts.map((draft) => <article className={`document-draft mobile-${mobileView}`} key={draft.id}>
      <div className="document-original">
        <DocumentViewer
          document={{ token: draft.document_token, filename: draft.filename, content_type: draft.content_type, page_count: draft.page_count }}
          url={apiUrl(`/purchase-orders/imports/${draft.document_token}/content`)}
          highlight={(() => {
            const selectedLine = draft.lines.find((line) => line.id === selectedLineId);
            return selectedLine?.bounds ? { page: selectedLine.page, ...selectedLine.bounds } : null;
          })()}
        />
        <small className="extraction-method">Extracción: {draft.extraction_method}</small>
      </div>
      <div className="recognized-order">
        <header><span className={`status-pill ${draft.classification.allowed_for_purchase_order ? "available" : "blocked"}`}>{draft.classification.label}</span><span className={`status-pill ${problems(draft).length ? "low_stock" : "available"}`}>{draft.status === "created" ? "OC creada" : problems(draft).length ? "Requiere revisión" : "Lista para crear"}</span>{draft.visibleUnitTotal !== null && <small>Total visible: {draft.visibleUnitTotal} unidades</small>}</header>
        {!draft.classification.allowed_for_purchase_order && <div className="message error" role="alert">{draft.classification.message}</div>}
        <div className="recognition-summary product-recognition-summary" aria-label="Resumen del reconocimiento">
          <span><strong>{draft.expected_product_count ?? draft.lines.length}</strong>Productos esperados</span>
          <span><strong>{draft.lines.length}</strong>Productos detectados</span>
          <span><strong>{draft.lines.filter((line) => line.sku).length}</strong>Relacionados con el catálogo</span>
          <span><strong>{draft.lines.filter((line) => !line.sku).length}</strong>No encontrados en el catálogo</span>
          <span><strong>{missingLineCount(draft)}</strong>Líneas que no se pudieron extraer</span>
        </div>
        {missingLineCount(draft) > 0 && <div className="message warning">El documento indica {draft.expected_product_count} productos, pero sólo se detectaron {draft.lines.length}. Falta revisar {missingLineCount(draft)} línea{missingLineCount(draft) === 1 ? "" : "s"}.</div>}
        {draft.warnings.map((warning) => <div className="message warning" key={warning}>{warning}</div>)}
        {draft.chainCandidates.length > 1 && !draft.chain_name && <div className="chain-candidates"><span>Se encontraron varias posibles cadenas. Confirma una:</span>{draft.chainCandidates.map((candidate) => <button type="button" key={candidate} onClick={() => patchDraft(draft.id, { chain_name: candidate, headerConfirmed: false })}>{candidate}</button>)}</div>}
        {draft.separation_needs_review && <label className="preview-confirm"><input type="checkbox" checked={draft.separationConfirmed} onChange={(event) => patchDraft(draft.id, { separationConfirmed: event.target.checked })} /><span>Confirmo que este bloque corresponde a una OC separada del mismo documento.</span></label>}
        <div className="form-grid compact">
          <label><span>Número de OC *</span><input value={draft.order_number} onChange={(event) => patchDraft(draft.id, { order_number: event.target.value, headerConfirmed: false })} /><small>Fuente: {draft.header.order_number_source?.replaceAll("_", " ") ?? "pendiente"}</small></label>
          <label><span>Cadena *</span><input value={draft.chain_name} onChange={(event) => patchDraft(draft.id, { chain_name: event.target.value, headerConfirmed: false })} /></label>
          <label><span>Fecha</span><input type="date" value={draft.order_date} onChange={(event) => patchDraft(draft.id, { order_date: event.target.value })} /></label>
          <label><span>Destino</span><input value={draft.destination} onChange={(event) => patchDraft(draft.id, { destination: event.target.value })} /></label>
          <label><span>Referencia secundaria</span><input value={draft.secondaryReference} onChange={(event) => patchDraft(draft.id, { secondaryReference: event.target.value, headerConfirmed: false })} /></label>
          <label><span>Local</span><input value={draft.localName} onChange={(event) => patchDraft(draft.id, { localName: event.target.value })} /></label>
        </div>
        <label className="preview-confirm"><input type="checkbox" checked={draft.headerConfirmed} disabled={!draft.classification.allowed_for_purchase_order || !draft.order_number.trim() || !draft.chain_name.trim()} onChange={(event) => patchDraft(draft.id, { headerConfirmed: event.target.checked })} /><span>Confirmo el número de OC y la cadena propuestos.</span></label>
        <div className="review-tools"><button type="button" className="text-button" onClick={() => loadCustomerAliases(draft)}>Aplicar perfil de la cadena</button><button type="button" className="text-button" onClick={() => reprocessDraft(draft)}>Reintentar reconocimiento</button><button type="button" className="text-button" onClick={() => confirmAllRecognized(draft)}>Confirmar todos los reconocidos</button><button type="button" className="text-button" onClick={() => addLine(draft)}>+ Agregar producto faltante</button></div>
        <div className="line-review-filters" role="group" aria-label="Filtrar líneas">{([["all", "Todos"], ["recognized", "Reconocidos"], ["not_found", "No encontrados"], ["missing", "Líneas faltantes"], ["quantity", "Cantidades pendientes"]] as const).map(([value, label]) => <button type="button" className={lineFilter === value ? "active" : ""} key={value} onClick={() => setLineFilter(value)}>{label}</button>)}</div>
        {lineFilter === "missing" && <div className="missing-lines-panel">{missingLineCount(draft) ? <>Falta revisar {missingLineCount(draft)} línea{missingLineCount(draft) === 1 ? "" : "s"}. <button type="button" onClick={() => addLine(draft)}>Agregar producto faltante</button></> : "No faltan líneas por extraer."}</div>}
        <div className="table-scroll detected-products-table compact-product-review"><table><thead><tr><th>Producto del documento</th><th>Producto del catálogo</th><th>Cantidad</th><th>UxC</th><th>Unidades</th><th>Estado</th></tr></thead><tbody>{visibleLines(draft).map((line, index) => <tr className={`${selectedLineId === line.id ? "selected-source-row" : ""} confidence-${line.confidence}`} key={line.id} onClick={() => setSelectedLineId(line.id)}>
          <td><strong>{line.description || "Producto agregado manualmente"}</strong><small>{line.chain_code ? `Código: ${line.chain_code}` : ""}{line.supplier_reference ? ` · Referencia: ${line.supplier_reference}` : ""}</small>{line.bounds && <button className="text-button row-action" type="button" onClick={(event) => { event.stopPropagation(); setSelectedLineId(line.id); }}>Ver línea en el PDF</button>}</td>
          <td><select aria-label={`Producto fila ${index + 1}`} value={line.sku} onClick={(event) => event.stopPropagation()} onChange={(event) => confirmLineProduct(draft, line, event.target.value)}><option value="">Corregir producto…</option>{products.map((product) => <option key={product.id ?? product.sku} value={product.sku}>{product.product_name} · SKU: {product.sku}</option>)}</select>{line.suggestions.length > 0 && <small>Posibles coincidencias: {line.suggestions.join(", ")}</small>}</td>
          <td><input aria-label={`Cantidad fila ${index + 1}`} type="number" min={1} value={line.original_quantity ?? ""} onClick={(event) => event.stopPropagation()} onChange={(event) => updateLine(draft.id, line.id, conversionPatch(line, { original_quantity: Number(event.target.value) || null }))} /><select aria-label={`Tipo fila ${index + 1}`} value={line.original_unit_type} onClick={(event) => event.stopPropagation()} onChange={(event) => updateLine(draft.id, line.id, conversionPatch(line, { original_unit_type: event.target.value as DocumentProductLine["original_unit_type"] }))}><option value="ambiguous">¿Tipo?</option><option value="boxes">Cajas</option><option value="units">Unidades</option></select></td>
          <td><input aria-label={`UxC fila ${index + 1}`} type="number" min={1} disabled={line.original_unit_type === "units"} value={line.units_per_box ?? ""} onClick={(event) => event.stopPropagation()} onChange={(event) => updateLine(draft.id, line.id, conversionPatch(line, { units_per_box: Number(event.target.value) || null }))} /></td>
          <td><strong>{line.calculated_units ?? "—"}</strong></td>
          <td><span className={`fulfillment-status ${line.sku && line.reviewed && line.conversion_confirmed ? "delivered_complete" : "invoicing_partial"}`}>{!line.calculated_units ? "Cantidad pendiente" : !line.sku ? "No encontrado en el catálogo" : !line.reviewed ? "Producto reconocido · confirmar" : !line.conversion_confirmed ? "Cantidad pendiente de confirmar" : "Producto reconocido"}</span><label className="inline-confirm"><input aria-label={`Confirmar fila ${index + 1}`} type="checkbox" checked={line.reviewed && line.conversion_confirmed} disabled={!line.sku || !line.original_quantity || !line.calculated_units || (line.original_unit_type === "boxes" && !line.units_per_box)} onClick={(event) => event.stopPropagation()} onChange={(event) => updateLine(draft.id, line.id, { reviewed: event.target.checked, conversion_confirmed: event.target.checked })} /> Confirmar</label><button className="danger-link" type="button" onClick={(event) => { event.stopPropagation(); patchDraft(draft.id, { lines: draft.lines.filter((item) => item.id !== line.id) }); }}>Eliminar</button></td>
        </tr>)}</tbody></table>{visibleLines(draft).length === 0 && lineFilter !== "missing" && <div className="table-message">No hay productos en este filtro.</div>}</div>
        {problems(draft).length > 0 && <ul className="block-errors">{problems(draft).map((problem) => <li key={problem}>{problem}</li>)}</ul>}
        <label className="notes-field"><span>Observaciones</span><textarea rows={2} value={draft.notes} onChange={(event) => patchDraft(draft.id, { notes: event.target.value })} /></label>
        <div className="form-actions">{draft.status === "created" ? <a className="primary-button" href={`#purchase-orders/${draft.createdOrderId}`}>OC creada correctamente</a> : <button className="primary-button" type="button" disabled={draft.status === "saving" || problems(draft).length > 0} onClick={() => createOrder(draft)}>{draft.status === "saving" ? "Creando OC…" : "Confirmar y crear OC"}</button>}</div>
      </div>
    </article>)}
    <div className="form-actions"><button className="secondary-button" type="button" onClick={cancelImport}>Volver a Órdenes de Compra</button></div>
  </section>;
}
