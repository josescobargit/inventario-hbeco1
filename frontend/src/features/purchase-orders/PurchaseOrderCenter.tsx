import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import { apiRequest, apiUpload, apiUrl } from "../../api/client";
import {
  applyConfirmedAlias, parseProductLines, retryProductRecognition,
} from "../invoices/quickEntry";
import { ProductIdentity } from "../inventory/ProductIdentity";
import { PurchaseOrderDocumentImport } from "./PurchaseOrderDocumentImport";
import { PurchaseOrderCombobox } from "./PurchaseOrderCombobox";
import { DocumentViewer, ViewableDocument } from "./DocumentViewer";

interface ProductOption {
  id: string;
  sku: string;
  product_name: string;
  barcode: string | null;
  contifico_aux_code: string | null;
  available_to_invoice: number;
  units_per_box: number;
}

interface OrderLine {
  sku: string;
  product_name: string;
  ordered_quantity: number;
  invoiced_quantity: number;
  dispatched_quantity: number;
  delivered_quantity: number;
  returned_quantity: number;
  net_delivered_quantity: number;
  pending_delivery: number;
  difference: number;
  fulfillment_status: string;
  has_incident: boolean;
  available: number;
  suggested_to_invoice: number;
  shortage: number;
  complete: boolean;
  billing_result?: string;
  pending_invoice_quantity: number;
  excess_invoice_quantity: number;
  billing_comparison_result: string;
  invoice_breakdown: Array<{
    id: string; invoice_number: string; invoice_date: string; quantity: number;
    administrative_status: string;
  }>;
  original_quantity?: number | null;
  original_unit?: string | null;
  units_per_box?: number | null;
}

interface PurchaseOrder {
  id: string;
  chain_name: string;
  customer_name: string | null;
  order_number: string;
  order_date: string | null;
  destination: string | null;
  status: string;
  notes: string | null;
  lines: OrderLine[];
  source_documents: Array<ViewableDocument & { extraction_method: string; available?: boolean }>;
  related_invoices: Array<{
    id: string; invoice_number: string; administrative_status: string;
    invoice_date: string; inventory_status: string; inventory_status_label: string;
    dispatch_status: string; delivery_status: string;
    dispatches: Array<{ id: string; dispatched_at: string }>;
    deliveries: Array<{ id: string; delivered_at: string }>;
  }>;
  related_reservations: Array<{ id: string; status: string; reason: string }>;
  has_related_operations: boolean;
  manually_modified: boolean;
  product_count: number;
  billing_summary: {
    ordered_units: number; invoiced_units: number; pending_units: number; excess_units: number;
    complete_products: number; partial_products: number; not_invoiced_products: number;
    result: string;
  };
}
interface PurchaseOrderPage { items: Array<Pick<PurchaseOrder, "id" | "chain_name" | "order_number" | "order_date" | "destination" | "status" | "product_count">>; next_cursor: string | null }

interface DraftLine {
  id: number; sku: string; quantity: string; units_per_box?: number | null;
  original_quantity?: string; original_unit?: "boxes" | "units";
  original_sku?: string;
  raw?: string; error?: string | null; suggestions?: string[];
}
interface OrderHistory {
  id: string; occurred_at: string; actor: string; field: string;
  previous_value: unknown; new_value: unknown; reason: string | null;
}
interface OperationalSettings { suggested_chains: string[] }

let nextDraftLineId = 1;
const emptyLine = (): DraftLine => ({ id: nextDraftLineId++, sku: "", quantity: "1" });
const DEFAULT_CHAINS = ["Favorita", "Rosado", "Danec", "Tía", "TUTI", "Mega Santa María", "Gerardo Ortiz"];
const normalize = (value: string) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es-EC");
const chainIdentity = (value: string) => ["tuti", "tiendas tuti"].includes(normalize(value).trim()) ? "tuti" : normalize(value).trim();
const historyValue = (value: unknown) => value === null || value === undefined
  ? "—"
  : typeof value === "object" ? JSON.stringify(value) : String(value);
const fulfillmentLabels: Record<string, string> = {
  not_processed: "No procesado", pending: "Pendiente",
  invoicing_partial: "Facturación parcial", dispatch_partial: "Despacho parcial",
  delivery_partial: "Entrega parcial", delivered_complete: "Entregado completo",
  delivered_excess: "Entregado con exceso", with_return: "Con devolución",
  with_incident: "Con incidencia",
};
const summaryOrder = (order: PurchaseOrderPage["items"][number]): PurchaseOrder => ({
  ...order, customer_name: order.chain_name, notes: null, lines: [], source_documents: [],
  related_invoices: [], related_reservations: [], has_related_operations: false,
  manually_modified: false, billing_summary: {
    ordered_units: 0, invoiced_units: 0, pending_units: 0, excess_units: 0,
    complete_products: 0, partial_products: 0, not_invoiced_products: 0, result: "Se puede facturar",
  },
});

function ProductSearch({ products, value, disabledSkus, onChange, onProductLoaded, label }: {
  products: ProductOption[]; value: string; disabledSkus: Set<string>;
  onChange: (sku: string) => boolean | void; onProductLoaded: (product: ProductOption) => void; label: string;
}) {
  const selected = products.find((item) => item.sku === value);
  const [query, setQuery] = useState(selected ? `${selected.product_name} · SKU: ${selected.sku}` : "");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [matches, setMatches] = useState<ProductOption[]>([]);
  const [searching, setSearching] = useState(false);
  const productRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(async () => {
      productRequest.current?.abort();
      const controller = new AbortController();
      productRequest.current = controller; setSearching(true);
      try {
        const params = new URLSearchParams({ limit: "25" });
        if (query.trim() && !selected) params.set("search", query.trim());
        const found = await apiRequest<ProductOption[]>(`/inventory/availability?${params}`, { signal: controller.signal });
        setMatches(found.filter((item) => !disabledSkus.has(item.sku) || item.sku === value));
        setActive(0);
      } catch (caught) {
        if (!(caught instanceof DOMException && caught.name === "AbortError")) setMatches([]);
      } finally {
        if (productRequest.current === controller) setSearching(false);
      }
    }, 180);
    return () => { window.clearTimeout(timer); productRequest.current?.abort(); };
  }, [disabledSkus, open, query, selected, value]);
  const choose = (sku: string) => {
    const product = matches.find((item) => item.sku === sku) ?? products.find((item) => item.sku === sku);
    if (onChange(sku) === false) { setOpen(false); return; }
    if (product) onProductLoaded(product);
    setQuery(product ? `${product.product_name} · SKU: ${product.sku}` : "");
    setOpen(false); setActive(0);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") { event.preventDefault(); setOpen(true); setActive((current) => Math.min(current + 1, Math.max(matches.length - 1, 0))); }
    if (event.key === "ArrowUp") { event.preventDefault(); setActive((current) => Math.max(current - 1, 0)); }
    if (event.key === "Enter" && open && matches[active]) { event.preventDefault(); choose(matches[active].sku); }
    if (event.key === "Escape") setOpen(false);
  };
  return <label className="product-combobox"><span>{label}</span><div className="combobox">
    <input required role="combobox" aria-label={label} aria-autocomplete="list" aria-expanded={open} aria-controls="product-options"
      autoComplete="off" value={value && selected ? `${selected.product_name} · SKU: ${selected.sku}` : query} placeholder="Busca por nombre, SKU, variante o tamaño"
      onFocus={() => { if (value && selected) setQuery(`${selected.product_name} · SKU: ${selected.sku}`); setOpen(true); setActive(0); }}
      onBlur={() => window.setTimeout(() => setOpen(false), 120)}
      onKeyDown={onKeyDown}
      onChange={(event) => {
        const nextQuery = event.target.value;
        setQuery(nextQuery); onChange(""); setOpen(true); setActive(0);
        const terms = normalize(nextQuery).trim().split(/\s+/).filter(Boolean);
        setMatches(products.filter((item) => {
          if (disabledSkus.has(item.sku)) return false;
          const text = normalize(`${item.product_name} ${item.sku} ${item.barcode ?? ""} ${item.contifico_aux_code ?? ""}`);
          return terms.every((term) => text.includes(term));
        }).slice(0, 25));
      }} />
    {value && <button className="combobox-clear" type="button" aria-label="Limpiar producto"
      onMouseDown={(event) => event.preventDefault()} onClick={() => { if (onChange("") === false) return; setQuery(""); setOpen(true); }}>×</button>}
    {open && <div className="combobox-options product-options" id="product-options" role="listbox">
      {searching && <span>Buscando…</span>}
      {matches.map((item, index) => <button key={item.id} type="button" role="option" aria-selected={index === active}
        onMouseDown={(event) => event.preventDefault()} onMouseEnter={() => setActive(index)} onClick={() => choose(item.sku)}>
        <strong>{item.product_name}</strong><span>SKU: {item.sku}</span>
      </button>)}
      {!searching && !matches.length && <span>No hay coincidencias en el catálogo.</span>}
    </div>}
  </div></label>;
}

export function PurchaseOrderCenter() {
  const [initialOpenOrderId] = useState(() => {
    const value = sessionStorage.getItem("inventario.openPurchaseOrderId");
    sessionStorage.removeItem("inventario.openPurchaseOrderId");
    return value;
  });
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [products, setProducts] = useState<ProductOption[]>([]);
  const [suggestedChains, setSuggestedChains] = useState(DEFAULT_CHAINS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [showDocumentImport, setShowDocumentImport] = useState(false);
  const [quickMode, setQuickMode] = useState(false);
  const [quickText, setQuickText] = useState("");
  const [quickProcessed, setQuickProcessed] = useState(false);
  const [confirmedPreview, setConfirmedPreview] = useState(false);
  const [differenceOnly, setDifferenceOnly] = useState(false);
  const [billingFilter, setBillingFilter] = useState<"all" | "billable" | "shortage" | "no_stock" | "review">("all");
  const [detailPane, setDetailPane] = useState<"document" | "data" | "comparison">("comparison");
  const [selectedDocumentToken, setSelectedDocumentToken] = useState<string | null>(null);
  const [chainName, setChainName] = useState("");
  const [selectedChain, setSelectedChain] = useState("");
  const [chainMenuOpen, setChainMenuOpen] = useState(false);
  const [orderNumber, setOrderNumber] = useState("");
  const [orderDate, setOrderDate] = useState("");
  const [destination, setDestination] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([emptyLine()]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [orderSearch, setOrderSearch] = useState("");
  const [orderStatus, setOrderStatus] = useState("");
  const [pageSize, setPageSize] = useState(25);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [keepChainDestination, setKeepChainDestination] = useState(false);
  const [templateConfirmed, setTemplateConfirmed] = useState(false);
  const [copyOrderId, setCopyOrderId] = useState("");
  const [editingOrderId, setEditingOrderId] = useState<string | null>(null);
  const [editReview, setEditReview] = useState(false);
  const [editReason, setEditReason] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<OrderHistory[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [attachingDocument, setAttachingDocument] = useState(false);
  const orderNumberRef = useRef<HTMLInputElement>(null);
  const submitLock = useRef(false);
  const successTimerRef = useRef<number | null>(null);
  const initialOpenHandled = useRef(false);

  const normalizeDetail = (order: PurchaseOrder): PurchaseOrder => ({
    ...order, product_count: order.lines.length,
    billing_summary: order.billing_summary ?? {
      ordered_units: order.lines.reduce((total, line) => total + line.ordered_quantity, 0),
      invoiced_units: order.lines.reduce((total, line) => total + (line.invoiced_quantity ?? 0), 0),
      pending_units: order.lines.reduce((total, line) => total + Math.max(line.ordered_quantity - (line.invoiced_quantity ?? 0), 0), 0),
      excess_units: order.lines.reduce((total, line) => total + Math.max((line.invoiced_quantity ?? 0) - line.ordered_quantity, 0), 0),
      complete_products: order.lines.filter((line) => line.ordered_quantity > 0 && line.invoiced_quantity === line.ordered_quantity).length,
      partial_products: order.lines.filter((line) => (line.invoiced_quantity ?? 0) > 0 && (line.invoiced_quantity ?? 0) < line.ordered_quantity).length,
      not_invoiced_products: order.lines.filter((line) => !(line.invoiced_quantity ?? 0)).length,
      result: "Se puede facturar",
    },
    source_documents: order.source_documents ?? [], related_invoices: order.related_invoices ?? [],
    related_reservations: order.related_reservations ?? [],
    has_related_operations: order.has_related_operations ?? Boolean(order.related_invoices?.length),
    manually_modified: order.manually_modified ?? false,
    lines: order.lines.map((line) => ({
      ...line, invoiced_quantity: line.invoiced_quantity ?? 0,
      dispatched_quantity: line.dispatched_quantity ?? 0, delivered_quantity: line.delivered_quantity ?? 0,
      returned_quantity: line.returned_quantity ?? 0, net_delivered_quantity: line.net_delivered_quantity ?? 0,
      pending_delivery: line.pending_delivery ?? line.ordered_quantity,
      difference: line.difference ?? -line.ordered_quantity,
      fulfillment_status: line.fulfillment_status ?? "not_processed", has_incident: line.has_incident ?? false,
      pending_invoice_quantity: line.pending_invoice_quantity ?? Math.max(line.ordered_quantity - (line.invoiced_quantity ?? 0), 0),
      excess_invoice_quantity: line.excess_invoice_quantity ?? Math.max((line.invoiced_quantity ?? 0) - line.ordered_quantity, 0),
      billing_comparison_result: line.billing_comparison_result ?? (!(line.invoiced_quantity ?? 0) ? "No facturado" : (line.invoiced_quantity ?? 0) < line.ordered_quantity ? "Facturación parcial" : (line.invoiced_quantity ?? 0) === line.ordered_quantity ? "Facturado completo" : "Facturado en exceso"),
      invoice_breakdown: line.invoice_breakdown ?? [],
    })),
  });
  const loadOrderPage = async (append = false, cursor: string | null = null) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (pageSize !== 25) params.set("limit", String(pageSize));
      if (orderSearch.trim()) params.set("search", orderSearch.trim());
      if (orderStatus) params.set("status", orderStatus);
      if (cursor) params.set("cursor", cursor);
      const suffix = params.size ? `?${params}` : "";
      const response = await apiRequest<PurchaseOrderPage | PurchaseOrder[]>(`/purchase-orders${suffix}`);
      const page: PurchaseOrderPage = Array.isArray(response)
        ? { items: response.map((order) => ({ ...order, product_count: order.lines.length })), next_cursor: null }
        : response;
      const summaries = page.items.map((item) => {
        const full = Array.isArray(response) ? response.find((order) => order.id === item.id) : null;
        return full ? normalizeDetail(full) : summaryOrder(item);
      });
      if (!append && initialOpenOrderId && !initialOpenHandled.current) {
        initialOpenHandled.current = true;
        const detail = normalizeDetail(
          await apiRequest<PurchaseOrder>(`/purchase-orders/${initialOpenOrderId}`),
        );
        setOrders([detail, ...summaries.filter((order) => order.id !== detail.id)]);
        setSelectedId(detail.id);
        setSelectedDocumentToken(detail.source_documents[0]?.token ?? null);
      } else {
        setOrders((current) => append ? [...current, ...summaries] : summaries);
        if (!append) setSelectedId(null);
      }
      setNextCursor(page.next_cursor);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos cargar las órdenes de compra.");
    } finally { setLoading(false); }
  };
  const loadOrderDetail = async (id: string): Promise<PurchaseOrder | null> => {
    const existing = orders.find((order) => order.id === id);
    if (existing?.lines.length) return existing;
    setDetailLoading(true);
    try {
      const detail = normalizeDetail(await apiRequest<PurchaseOrder>(`/purchase-orders/${id}`));
      setOrders((current) => current.map((order) => order.id === id ? detail : order));
      return detail;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos cargar el detalle de la OC.");
      return null;
    } finally { setDetailLoading(false); }
  };
  const ensureProducts = async () => {
    if (products.length) return;
    setProducts(await apiRequest<ProductOption[]>("/inventory/availability?limit=100"));
  };
  const cacheOrderProducts = (order: PurchaseOrder) => setProducts((current) => {
    const bySku = new Map(current.map((product) => [product.sku, product]));
    for (const line of order.lines) {
      if (!bySku.has(line.sku)) bySku.set(line.sku, {
        id: line.sku, sku: line.sku, product_name: line.product_name,
        barcode: null, contifico_aux_code: null,
        available_to_invoice: line.available, units_per_box: line.units_per_box ?? 1,
      });
    }
    return [...bySku.values()];
  });

  useEffect(() => {
    apiRequest<OperationalSettings>("/settings/operational")
      .then((loadedSettings) => setSuggestedChains(loadedSettings.suggested_chains))
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No pudimos cargar las órdenes de compra."))
      .finally(() => undefined);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadOrderPage(); }, 220);
    return () => window.clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderSearch, orderStatus, pageSize]);

  useEffect(() => {
    if (successTimerRef.current !== null) window.clearTimeout(successTimerRef.current);
    if (!success) return;
    successTimerRef.current = window.setTimeout(() => {
      setSuccess(null);
      successTimerRef.current = null;
    }, 3000);
    return () => {
      if (successTimerRef.current !== null) window.clearTimeout(successTimerRef.current);
    };
  }, [success]);

  const selected = useMemo(() => {
    const order = orders.find((item) => item.id === selectedId);
    return order?.lines.length ? order : null;
  }, [orders, selectedId]);
  const editingOrder = useMemo(
    () => orders.find((order) => order.id === editingOrderId) ?? null,
    [editingOrderId, orders],
  );
  const editSummary = useMemo(() => {
    if (!editingOrder) return null;
    const original = new Map(editingOrder.lines.map((line) => [line.sku, line]));
    const current = new Map(lines.filter((line) => line.sku).map((line) => [line.sku, line]));
    return {
      numberChanged: orderNumber.trim() !== editingOrder.order_number,
      chainChanged: chainIdentity(chainName) !== chainIdentity(editingOrder.chain_name),
      destinationChanged: destination !== (editingOrder.destination ?? ""),
      dateChanged: orderDate !== (editingOrder.order_date ?? ""),
      notesChanged: notes !== (editingOrder.notes ?? ""),
      productsAdded: [...current.keys()].filter((sku) => !original.has(sku)).length,
      productsRemoved: [...original.keys()].filter((sku) => !current.has(sku)).length,
      quantitiesChanged: [...current].filter(([sku, line]) => original.has(sku)
        && Number(line.quantity) !== original.get(sku)!.ordered_quantity).length,
    };
  }, [chainName, destination, editingOrder, lines, notes, orderDate, orderNumber]);
  const billingLines = selected?.lines.filter((line) => {
    const pending = Math.max(line.ordered_quantity - line.invoiced_quantity, 0);
    if (billingFilter === "billable") return line.suggested_to_invoice > 0;
    if (billingFilter === "shortage") return line.shortage > 0;
    if (billingFilter === "no_stock") return pending > 0 && line.suggested_to_invoice === 0;
    if (billingFilter === "review") return !line.sku || !Number.isFinite(line.ordered_quantity) || line.ordered_quantity <= 0;
    return true;
  }) ?? [];
  const comparisonLines = selected?.lines.filter((line) => !differenceOnly || line.difference !== 0 || line.returned_quantity > 0 || line.has_incident) ?? [];
  const comparisonSummary = selected ? {
    products: selected.lines.length,
    ordered: selected.lines.reduce((sum, line) => sum + line.ordered_quantity, 0),
    invoiced: selected.lines.reduce((sum, line) => sum + line.invoiced_quantity, 0),
    dispatched: selected.lines.reduce((sum, line) => sum + line.dispatched_quantity, 0),
    delivered: selected.lines.reduce((sum, line) => sum + line.delivered_quantity, 0),
    pending: selected.lines.reduce((sum, line) => sum + Math.max(0, line.pending_delivery), 0),
    differences: selected.lines.filter((line) => line.difference !== 0 || line.returned_quantity > 0 || line.has_incident).length,
  } : null;
  const selectedDocument = selected?.source_documents.find((document) => document.token === selectedDocumentToken)
    ?? selected?.source_documents[0] ?? null;
  const selectedSkus = new Set(lines.map((line) => line.sku).filter(Boolean));
  const chainOptions = useMemo(() => {
    const unique = new Map<string, string>();
    for (const chain of [...DEFAULT_CHAINS, ...suggestedChains, ...orders.map((order) => order.chain_name)]) {
      const identity = chainIdentity(chain);
      if (!unique.has(identity)) unique.set(identity, identity === "tuti" ? "TUTI" : chain);
    }
    return [...unique.values()].sort((a, b) => a.localeCompare(b, "es-EC"));
  }, [orders, suggestedChains]);
  const visibleChains = chainOptions.filter((chain) => normalize(chain).includes(normalize(chainName)));

  const updateLine = (index: number, patch: Partial<DraftLine>) => {
    setLines((current) => current.map((line, lineIndex) => lineIndex === index ? { ...line, ...patch } : line));
    if (editingOrderId) setEditReview(false);
  };
  const confirmQuickProduct = (index: number, sku: string) => {
    const selected = lines[index];
    if (!selected?.raw || !sku) { updateLine(index, { sku, error: null }); return; }
    setLines((current) => applyConfirmedAlias(current.map((line, lineIndex) => ({
      id: `order-alias-${lineIndex}`, raw: line.raw ?? "", quantity: Number(line.quantity) || null, sku: line.sku,
      error: line.error ?? null, suggestions: line.suggestions ?? [],
    })), selected.raw!, sku).map((line, lineIndex) => ({
      id: current[lineIndex]!.id, sku: line.sku, quantity: String(line.quantity ?? ""), raw: line.raw,
      error: line.error, suggestions: line.suggestions,
    })));
  };
  const retryRecognition = () => {
    setLines((current) => retryProductRecognition(current.map((line, index) => ({
      id: `order-line-${index}`, raw: line.raw ?? "", quantity: Number(line.quantity) || null, sku: line.sku,
      error: line.error ?? null, suggestions: line.suggestions ?? [],
    })), products).map((line, index) => ({ id: current[index]!.id, sku: line.sku, quantity: String(line.quantity ?? ""), raw: line.raw, error: line.error, suggestions: line.suggestions })));
  };

  const resetForm = (preserveContext = false) => {
    if (!preserveContext) { setChainName(""); setSelectedChain(""); setDestination(""); }
    setOrderNumber(""); setOrderDate(""); setNotes(""); setLines([emptyLine()]); setQuickText(""); setQuickProcessed(false);
    setConfirmedPreview(false); setTemplateConfirmed(false); setCopyOrderId(""); setQuickMode(false); setError(null);
    setEditingOrderId(null); setEditReview(false); setEditReason("");
  };
  const applyOrderTemplate = async (order: PurchaseOrder) => {
    const fullOrder = order.lines.length ? order : await loadOrderDetail(order.id);
    if (!fullOrder) return;
    cacheOrderProducts(fullOrder);
    void ensureProducts();
    setShowDocumentImport(false); setShowForm(true); setQuickMode(false); setSuccess(null);
    setEditingOrderId(null); setEditReview(false); setEditReason("");
    setChainName(fullOrder.chain_name); setSelectedChain(fullOrder.chain_name); setDestination(fullOrder.destination ?? "");
    setOrderNumber(""); setOrderDate(""); setNotes("");
    setLines(fullOrder.lines.map((line) => ({ id: nextDraftLineId++, sku: line.sku, quantity: String(line.ordered_quantity), units_per_box: line.units_per_box })));
    setCopyOrderId(fullOrder.id); setTemplateConfirmed(false);
    window.setTimeout(() => orderNumberRef.current?.focus(), 0);
  };
  const startEdit = async (order: PurchaseOrder) => {
    const fullOrder = order.lines.length ? order : await loadOrderDetail(order.id);
    if (!fullOrder) return;
    cacheOrderProducts(fullOrder);
    void ensureProducts();
    setSelectedId(fullOrder.id);
    setShowDocumentImport(false); setShowForm(true); setQuickMode(false);
    setEditingOrderId(fullOrder.id); setEditReview(false); setEditReason("");
    setError(null); setSuccess(null);
    setChainName(fullOrder.chain_name); setSelectedChain(fullOrder.chain_name);
    setOrderNumber(fullOrder.order_number); setOrderDate(fullOrder.order_date ?? "");
    setDestination(fullOrder.destination ?? ""); setNotes(fullOrder.notes ?? "");
    setLines(fullOrder.lines.map((line) => ({
      id: nextDraftLineId++,
      sku: line.sku,
      original_sku: line.sku,
      quantity: String(line.ordered_quantity),
      original_quantity: String(line.original_quantity ?? line.ordered_quantity),
      original_unit: line.original_unit === "boxes" ? "boxes" : "units",
      units_per_box: line.units_per_box ?? products.find((item) => item.sku === line.sku)?.units_per_box ?? null,
    })));
    window.setTimeout(() => orderNumberRef.current?.focus(), 0);
  };
  const cancelEdit = () => {
    setShowForm(false); setEditingOrderId(null); setEditReview(false);
    setEditReason(""); setError(null);
  };
  const moveLine = (index: number, direction: -1 | 1) => {
    setLines((current) => {
      const target = index + direction;
      if (target < 0 || target >= current.length) return current;
      const reordered = [...current];
      [reordered[index], reordered[target]] = [reordered[target]!, reordered[index]!];
      return reordered;
    });
    setEditReview(false);
  };
  const updateEditConversion = (
    index: number,
    patch: Partial<Pick<DraftLine, "original_quantity" | "original_unit" | "units_per_box">>,
  ) => {
    const current = lines[index];
    if (!current) return;
    const originalQuantity = patch.original_quantity ?? current.original_quantity ?? "";
    const unitType = patch.original_unit ?? current.original_unit ?? "units";
    const unitsPerBox = patch.units_per_box === undefined ? current.units_per_box : patch.units_per_box;
    const parsedOriginal = /^[1-9]\d*$/.test(originalQuantity) ? Number(originalQuantity) : null;
    const calculated = parsedOriginal === null ? "" : unitType === "boxes"
      ? unitsPerBox ? String(parsedOriginal * unitsPerBox) : ""
      : String(parsedOriginal);
    updateLine(index, { ...patch, quantity: calculated, error: null });
    setEditReview(false);
  };
  const loadHistory = async (order: PurchaseOrder) => {
    setShowHistory(true); setHistoryLoading(true); setError(null);
    try {
      setHistory(await apiRequest<OrderHistory[]>(`/purchase-orders/${order.id}/history`));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos cargar el historial.");
    } finally {
      setHistoryLoading(false);
    }
  };
  const attachCorrectedDocument = async (order: PurchaseOrder, file: File | undefined) => {
    if (!file) return;
    setAttachingDocument(true); setError(null);
    const data = new FormData(); data.append("file", file);
    try {
      const updated = await apiUpload<PurchaseOrder>(`/purchase-orders/${order.id}/documents`, data);
      const normalized = normalizeDetail(updated);
      setOrders((current) => current.map((item) => item.id === normalized.id ? normalized : item));
      setSelectedDocumentToken(updated.source_documents.at(-1)?.token ?? null);
      setSuccess("Documento corregido adjuntado");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos adjuntar el documento.");
    } finally {
      setAttachingDocument(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitLock.current) return;
    if (lines.some((line) => !line.sku || !/^[1-9]\d*$/.test(line.quantity.trim()))) {
      setError("Cada producto necesita una cantidad entera mayor que cero.");
      return;
    }
    if (copyOrderId && !templateConfirmed) {
      setError("Revisa y confirma la vista previa copiada antes de guardar.");
      return;
    }
    if (quickMode && (!quickProcessed || !confirmedPreview)) {
      setError("Procesa el texto, corrige todas las líneas y confirma la vista previa.");
      return;
    }
    if (editingOrder) {
      setError(null);
      setEditReview(true);
      return;
    }
    setError(null);
    setSuccess(null);
    submitLock.current = true;
    setSaving(true);
    try {
      const created = await apiRequest<PurchaseOrder>("/purchase-orders", {
        method: "POST",
        body: JSON.stringify({
          chain_name: chainName,
          customer_name: chainName,
          order_number: orderNumber,
          order_date: orderDate || null,
          destination: destination || null,
          notes: notes || null,
          lines: lines.map(({ sku, quantity, units_per_box }) => ({ sku, quantity: Number(quantity), units_per_box })),
        }),
      });
      const normalized = normalizeDetail(created);
      setOrders((current) => [normalized, ...current]);
      setSuccess("OC registrada correctamente");
      resetForm(keepChainDestination);
      window.setTimeout(() => orderNumberRef.current?.focus(), 0);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos registrar la OC.");
    } finally {
      submitLock.current = false;
      setSaving(false);
    }
  };
  const saveEdit = async () => {
    if (!editingOrder || submitLock.current) return;
    if (editingOrder.has_related_operations && editReason.trim().length < 5) {
      setError("Indica el motivo de la edición porque esta OC ya tiene operaciones relacionadas.");
      return;
    }
    submitLock.current = true; setSaving(true); setError(null);
    try {
      const updated = await apiRequest<PurchaseOrder>(`/purchase-orders/${editingOrder.id}`, {
        method: "PUT",
        body: JSON.stringify({
          chain_name: chainName,
          customer_name: chainName,
          order_number: orderNumber,
          order_date: orderDate || null,
          destination: destination || null,
          notes: notes || null,
          reason: editReason.trim() || null,
          lines: lines.map((line) => ({
            sku: line.sku,
            quantity: Number(line.quantity),
            original_quantity: Number(line.original_quantity || line.quantity),
            original_unit: line.original_unit ?? "units",
            units_per_box: line.original_unit === "boxes" ? line.units_per_box : null,
            conversion_method: line.original_unit === "boxes" ? "manual_boxes" : "direct_units",
            conversion_confirmed: true,
          })),
        }),
      });
      const normalized = normalizeDetail(updated);
      setOrders((current) => current.map((item) => item.id === normalized.id ? normalized : item));
      setSelectedId(normalized.id); setShowForm(false); setEditingOrderId(null);
      setEditReview(false); setEditReason(""); setSuccess("OC actualizada correctamente");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos actualizar la OC.");
    } finally {
      submitLock.current = false; setSaving(false);
    }
  };
  const prepareInvoice = (order: PurchaseOrder) => {
    sessionStorage.setItem("inventario.invoiceTemplate", JSON.stringify({
      id: "", number: "", date: "", customer: order.chain_name, chain: order.chain_name,
      source_type: "purchase_order", authorization_number: null, remittance_guide: null,
      total_value: null, notes: order.source_documents[0] ? `Documento original: ${order.source_documents[0].filename}` : null,
      purchase_order_id: order.id,
      lines: order.lines.filter((line) => line.suggested_to_invoice > 0).map((line) => ({ sku: line.sku, invoiced: line.suggested_to_invoice })),
    }));
    window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "invoices" }));
  };

  return (
    <main className="dashboard order-center">
      <section className="module-heading">
        <div className="welcome-block"><p className="eyebrow">Documento de origen</p><h1>Órdenes de Compra</h1><p>Registra el pedido original de cada cadena y contrástalo con el inventario realmente disponible.</p></div>
        <div className="heading-actions">{!showDocumentImport && !editingOrderId && <button className="secondary-button" type="button" onClick={() => { void ensureProducts(); setShowDocumentImport(true); setShowForm(false); setError(null); setSuccess(null); }}>Leer PDF o imagen</button>}{!showDocumentImport && <button className="primary-button" type="button" onClick={() => { if (editingOrderId) cancelEdit(); else { if (!showForm) void ensureProducts(); setShowForm((value) => !value); setError(null); setSuccess(null); } }}>{showForm ? editingOrderId ? "Cancelar edición" : "Cancelar" : "Nueva OC"}</button>}</div>
      </section>

      {error && <div className="message error" role="alert">{error}</div>}
      {success && <div className="message success po-toast" role="status"><span>{success}</span><button type="button" aria-label="Cerrar notificación" onClick={() => setSuccess(null)}>×</button></div>}

      {showDocumentImport && <PurchaseOrderDocumentImport products={products} orders={orders} onCreated={(created) => {
        setOrders((current) => [normalizeDetail(created as PurchaseOrder), ...current]);
        setShowDocumentImport(false); setShowForm(true); setSuccess("OC registrada correctamente");
        resetForm(keepChainDestination);
        window.setTimeout(() => orderNumberRef.current?.focus(), 0);
      }} onCancel={() => { setShowDocumentImport(false); setShowForm(true); }} />}

      {!showDocumentImport && showForm && <form className="order-form" onSubmit={submit}>
        <div className="form-section-title"><div><h2>{editingOrder ? `Editar OC ${editingOrder.order_number}` : "Nueva orden de compra"}</h2><p>La numeración puede repetirse entre cadenas, pero no dentro de la misma cadena.</p></div>
          {!editingOrder && <div className="mode-switch" role="group" aria-label="Modo de registro"><button type="button" className={!quickMode ? "active" : ""} onClick={() => { setQuickMode(false); setLines([emptyLine()]); }}>Ingreso manual</button><button type="button" onClick={() => { setShowDocumentImport(true); setShowForm(false); }}>Leer PDF o imagen</button><button type="button" className={quickMode ? "active" : ""} onClick={() => { setQuickMode(true); setLines([]); }}>Pegar líneas</button></div>}
        </div>
        {editingOrder?.has_related_operations && <div className="message warning">Esta OC ya tiene operaciones relacionadas. Algunos cambios pueden producir diferencias.</div>}
        {editingOrder?.source_documents.length ? <div className="message warning subtle">El PDF original se conservará sin modificaciones.</div> : null}
        <div className="form-grid">
          <label className="combobox-field"><span>Cadena *</span><div className="combobox"><input required disabled={Boolean(editingOrder?.related_reservations.length)} minLength={2} role="combobox" aria-label="Cadena" aria-autocomplete="list" aria-expanded={chainMenuOpen} aria-controls="chain-options" autoComplete="off" value={chainName} onFocus={() => setChainMenuOpen(true)} onBlur={() => window.setTimeout(() => setChainMenuOpen(false), 120)} onChange={(event) => { setChainName(event.target.value); setSelectedChain(""); setChainMenuOpen(true); setEditReview(false); }} placeholder="Escribe para filtrar o agregar otra" />{chainName && selectedChain === chainName ? <span className="selected-check" aria-label="Cadena seleccionada">✓</span> : null}{chainMenuOpen && !editingOrder?.related_reservations.length && <div className="combobox-options" id="chain-options" role="listbox">{visibleChains.map((chain) => <button key={chain} type="button" role="option" aria-selected={selectedChain === chain} onMouseDown={(event) => event.preventDefault()} onClick={() => { setChainName(chain); setSelectedChain(chain); setChainMenuOpen(false); setEditReview(false); }}>{chain}</button>)}{visibleChains.length === 0 && <span>“{chainName}” se guardará como una cadena nueva.</span>}</div>}</div><small>{editingOrder?.related_reservations.length ? "No puede cambiarse mientras existan reservas relacionadas." : "Elige una sugerencia o escribe una cadena nueva."}</small></label>
           <label><span>Número de OC *</span><input ref={orderNumberRef} required disabled={Boolean(editingOrder?.related_reservations.length)} value={orderNumber} onChange={(event) => { setOrderNumber(event.target.value); setEditReview(false); }} placeholder="Número del documento" />{editingOrder?.related_reservations.length ? <small>No puede cambiarse mientras existan reservas relacionadas.</small> : null}</label>
          <label><span>Fecha de OC</span><input type="date" value={orderDate} onChange={(event) => { setOrderDate(event.target.value); setEditReview(false); }} /></label>
          <label className="wide"><span>Destino</span><input value={destination} onChange={(event) => { setDestination(event.target.value); setEditReview(false); }} placeholder="CD o lugar de entrega" /></label>
        </div>
        {!quickMode && !editingOrder && <div className="copy-order-field"><PurchaseOrderCombobox label="Copiar productos de otra OC" value={orders.find((item) => item.id === copyOrderId) ?? null} onSelect={async (summary) => { if (!summary) { setCopyOrderId(""); setTemplateConfirmed(false); return; } const order = await loadOrderDetail(summary.id); if (order) await applyOrderTemplate(order); }} /></div>}
        {quickMode && <section className="quick-paste-panel"><label><span>Pega productos y cantidades</span><textarea rows={7} value={quickText} onChange={(event) => { setQuickText(event.target.value); setQuickProcessed(false); setConfirmedPreview(false); }} placeholder={"372 | AR004\n300 | SHAMPOO REGENEXT ARGAN 400 ML"} /><small>Formato admitido: cantidad | código o nombre del producto. Una línea por producto.</small></label><button className="secondary-button" type="button" onClick={() => { const parsed = parseProductLines(quickText, products); setLines(parsed.map((line) => ({ id: nextDraftLineId++, sku: line.sku, quantity: String(line.quantity ?? ""), raw: line.raw, error: line.error, suggestions: line.suggestions }))); setQuickProcessed(true); setConfirmedPreview(false); }}>Pegar y procesar</button></section>}
        <div className="order-lines"><div className="line-heading"><div><h3>{quickMode ? "Vista previa de productos" : "Productos solicitados"}</h3>{quickMode && <p>Corrige en la tabla cualquier coincidencia no reconocida.</p>}</div>{quickMode ? <button className="text-button" type="button" onClick={retryRecognition}>Reintentar reconocimiento</button> : <button className="text-button" type="button" onClick={() => setLines((current) => [...current, emptyLine()])}>+ Agregar producto</button>}</div>
          {quickMode && !quickProcessed && <div className="table-message">Pega la lista y pulsa “Pegar y procesar” para generar la vista previa.</div>}
          {lines.map((line, index) => {
            const product = products.find((item) => item.sku === line.sku);
            const originalLine = editingOrder?.lines.find((item) => item.sku === line.original_sku);
            const lineHasOperations = Boolean(originalLine && (
              originalLine.invoiced_quantity > 0
              || originalLine.dispatched_quantity > 0
              || originalLine.delivered_quantity > 0
            ));
            return <div className={`draft-line ${editingOrder ? "editing-line" : ""} ${quickMode && !line.sku ? "unrecognized-line" : ""}`} key={line.id}>
              <ProductSearch products={products} value={line.sku} disabledSkus={selectedSkus} label={quickMode ? line.raw || "Producto" : "Producto"} onProductLoaded={(loaded) => setProducts((current) => current.some((item) => item.sku === loaded.sku) ? current : [...current, loaded])} onChange={(sku) => {
                if (editingOrder && lineHasOperations && sku !== line.original_sku) {
                  updateLine(index, { error: `No puedes cambiar ${line.original_sku} porque ya tiene operaciones relacionadas.` });
                  return false;
                }
                if (quickMode) confirmQuickProduct(index, sku);
                else updateLine(index, { sku, error: null });
                return true;
              }} />
              {editingOrder ? <>
                <label><span>Tipo</span><select value={line.original_unit ?? "units"} onChange={(event) => updateEditConversion(index, { original_unit: event.target.value as "boxes" | "units" })}><option value="units">Unidades</option><option value="boxes">Cajas</option></select></label>
                <label><span>{line.original_unit === "boxes" ? "Cajas" : "Cantidad"}</span><input inputMode="numeric" value={line.original_quantity ?? ""} onChange={(event) => updateEditConversion(index, { original_quantity: event.target.value })} /></label>
                <label><span>UxC</span><input inputMode="numeric" disabled={line.original_unit !== "boxes"} value={line.units_per_box ?? ""} onChange={(event) => updateEditConversion(index, { units_per_box: Number(event.target.value) || null })} /></label>
                <div className="calculated-units"><span>Unidades calculadas</span><strong>{line.quantity || "—"}</strong></div>
              </> : <label><span>Cantidad</span><input required inputMode="numeric" value={line.quantity} aria-invalid={line.quantity !== "" && !/^[1-9]\d*$/.test(line.quantity)} onFocus={(event) => event.currentTarget.select()} onChange={(event) => updateLine(index, { quantity: event.target.value })} onBlur={() => { if (!/^[1-9]\d*$/.test(line.quantity)) updateLine(index, { error: "Ingresa una cantidad mayor que cero." }); }} /></label>}
              <div className="availability-hint"><span>Disponible ahora</span><strong>{product?.available_to_invoice ?? "—"}</strong></div>
              {editingOrder && <div className="line-order-actions"><button type="button" aria-label={`Subir producto ${index + 1}`} disabled={index === 0} onClick={() => moveLine(index, -1)}>↑</button><button type="button" aria-label={`Bajar producto ${index + 1}`} disabled={index === lines.length - 1} onClick={() => moveLine(index, 1)}>↓</button></div>}
              {(lines.length > 1 || editingOrder) && <button className="remove-line" aria-label={`Eliminar producto ${index + 1}`} title={lineHasOperations ? "Este producto ya tiene operaciones relacionadas." : lines.length === 1 ? "La OC debe conservar al menos un producto." : undefined} disabled={lineHasOperations || lines.length === 1} type="button" onClick={() => { setLines((current) => current.filter((_, lineIndex) => lineIndex !== index)); setEditReview(false); }}>×</button>}
              {line.error && <small className="field-error line-wide-error">{line.error}</small>}
            </div>;
          })}
        </div>
        {quickMode && quickProcessed && lines.length > 0 && <label className="preview-confirm"><input type="checkbox" checked={confirmedPreview} onChange={(event) => setConfirmedPreview(event.target.checked)} /><span>Revisé la vista previa y confirmo esta orden de compra.</span></label>}
        {copyOrderId && <label className="preview-confirm"><input type="checkbox" checked={templateConfirmed} onChange={(event) => setTemplateConfirmed(event.target.checked)} /><span>Revisé los productos y cantidades copiados y confirmo esta nueva OC.</span></label>}
        <label className="notes-field"><span>Observaciones</span><textarea value={notes} onChange={(event) => { setNotes(event.target.value); setEditReview(false); }} rows={3} /></label>
        {editingOrder?.has_related_operations && <label className="notes-field"><span>Motivo de la edición *</span><textarea value={editReason} onChange={(event) => setEditReason(event.target.value)} rows={2} placeholder="Explica por qué se modifica una OC con operaciones relacionadas" /></label>}
        {!editingOrder && <label className="keep-context"><input type="checkbox" checked={keepChainDestination} onChange={(event) => setKeepChainDestination(event.target.checked)} /><span>Conservar cadena y destino para la siguiente OC</span></label>}
        {editingOrder && editReview && editSummary && <section className="edit-change-review" aria-label="Resumen de cambios"><h3>Revisa los cambios antes de guardar</h3><dl><div><dt>Número de OC</dt><dd>{editSummary.numberChanged ? "cambiado" : "sin cambios"}</dd></div><div><dt>Cadena</dt><dd>{editSummary.chainChanged ? "cambiada" : "sin cambios"}</dd></div><div><dt>Fecha</dt><dd>{editSummary.dateChanged ? "cambiada" : "sin cambios"}</dd></div><div><dt>Destino</dt><dd>{editSummary.destinationChanged ? "cambiado" : "sin cambios"}</dd></div><div><dt>Observaciones</dt><dd>{editSummary.notesChanged ? "cambiadas" : "sin cambios"}</dd></div><div><dt>Productos agregados</dt><dd>{editSummary.productsAdded}</dd></div><div><dt>Productos eliminados</dt><dd>{editSummary.productsRemoved}</dd></div><div><dt>Cantidades modificadas</dt><dd>{editSummary.quantitiesChanged}</dd></div></dl></section>}
        <div className="form-actions">{editingOrder ? <><button className="secondary-button" type="button" onClick={cancelEdit}>Cancelar</button>{editReview ? <><button className="secondary-button" type="button" onClick={() => setEditReview(false)}>Volver a editar</button><button className="primary-button" type="button" disabled={saving} onClick={saveEdit}>{saving ? "Guardando…" : "Confirmar y guardar"}</button></> : <button className="primary-button" disabled={saving} type="submit">Revisar cambios</button>}</> : <button className="primary-button" disabled={saving || (quickMode && (!quickProcessed || !confirmedPreview || lines.length === 0)) || (copyOrderId !== "" && !templateConfirmed)} type="submit">{saving ? "Registrando…" : quickMode ? "Confirmar y registrar OC" : "Registrar OC"}</button>}</div>
      </form>}

      {!showDocumentImport && !showForm && <section className="order-workspace">
        <aside className="order-list">
          <div className="list-title"><strong>Órdenes registradas</strong><span>{orders.length}</span></div>
          <div className="order-list-filters">
            <input aria-label="Buscar órdenes" value={orderSearch} onChange={(event) => setOrderSearch(event.target.value)} placeholder="Buscar número, cadena, estado o destino" />
            <select aria-label="Filtrar por estado" value={orderStatus} onChange={(event) => setOrderStatus(event.target.value)}><option value="">Todos los estados</option><option value="open">Abiertas</option><option value="partially_invoiced">Facturadas parcialmente</option><option value="completed">Completadas</option><option value="cancelled">Canceladas</option></select>
            <select aria-label="Órdenes por página" value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}><option value={25}>25 por página</option><option value={50}>50 por página</option></select>
          </div>
          {loading && <div className="table-message">Cargando órdenes…</div>}
          {!loading && orders.map((order) => <div className="order-list-entry" key={order.id}><button type="button" className={`order-list-item ${selectedId === order.id ? "selected" : ""}`} onClick={async () => { setSelectedId(order.id); setDetailPane("comparison"); setShowHistory(false); const detail = await loadOrderDetail(order.id); setSelectedDocumentToken(detail?.source_documents[0]?.token ?? null); }}><strong>{order.order_number}</strong><span>{order.chain_name}</span><small>{order.product_count} producto{order.product_count === 1 ? "" : "s"}</small></button><div className="order-list-actions"><button className="template-link" type="button" onClick={() => void startEdit(order)}>Editar OC</button><button className="template-link" type="button" onClick={() => void applyOrderTemplate(order)}>Usar como plantilla</button></div></div>)}
          {!loading && nextCursor && <button className="secondary-button load-more-orders" type="button" onClick={() => void loadOrderPage(true, nextCursor)}>Cargar más</button>}
          {!loading && orders.length === 0 && <div className="table-message">Todavía no hay órdenes. Registra la primera para comenzar el flujo.</div>}
        </aside>
        <div className="order-detail">
          {detailLoading && <div className="table-message">Cargando detalle de la OC…</div>}
          {!selected && !loading && <div className="empty-detail"><strong>La OC inicia la trazabilidad</strong><span>Luego podrás reservar stock y vincular la factura correcta.</span></div>}
          {selected && <><header className="detail-header"><div><p className="eyebrow">{selected.chain_name}</p><h2>OC {selected.order_number}</h2><p>{selected.destination ?? "Sin destino especificado"}</p></div><div className="detail-actions"><span className="status-pill available">{selected.status === "open" ? "Abierta" : selected.status === "partially_invoiced" ? "Facturada parcialmente" : selected.status === "completed" ? "Completamente facturada" : "Cancelada"}</span><button className="secondary-button" type="button" onClick={() => startEdit(selected)}>Editar OC</button><button className="secondary-button" type="button" onClick={() => loadHistory(selected)}>Historial de cambios</button><button className="secondary-button" type="button" onClick={() => applyOrderTemplate(selected)}>Usar como plantilla</button><button className="primary-button" type="button" disabled={!selected.lines.some((line) => line.suggested_to_invoice > 0)} onClick={() => prepareInvoice(selected)}>Preparar factura</button></div></header>
            {selected.manually_modified && <div className="message warning">Esta OC contiene modificaciones manuales posteriores al documento original.</div>}
            <div className="mobile-detail-tabs" role="group" aria-label="Vista de la orden"><button type="button" className={detailPane === "document" ? "active" : ""} onClick={() => setDetailPane("document")}>Documento original</button><button type="button" className={detailPane === "data" ? "active" : ""} onClick={() => setDetailPane("data")}>Datos reconocidos</button><button type="button" className={detailPane === "comparison" ? "active" : ""} onClick={() => setDetailPane("comparison")}>Comparación</button></div>
            <section className={`trace-section detail-data-pane mobile-pane-${detailPane}`}><div className="line-heading"><h3>Disponibilidad y facturación</h3><div className="billing-filters" role="group" aria-label="Filtrar disponibilidad">{([["all", "Todos"], ["billable", "Facturables"], ["shortage", "Con faltantes"], ["no_stock", "Sin inventario"], ["review", "Pendientes de revisión"]] as const).map(([value, label]) => <button type="button" className={billingFilter === value ? "active" : ""} key={value} onClick={() => setBillingFilter(value)}>{label}</button>)}</div></div><div className="table-scroll"><table><thead><tr><th>Producto</th><th>Pedido</th><th>Ya facturado</th><th>Pendiente</th><th>Disponible</th><th>Sugerido a facturar</th><th>Faltante</th><th>Resultado</th></tr></thead><tbody>{billingLines.map((line) => <tr key={line.sku} className={line.complete ? "" : "row-warning"}><td><ProductIdentity name={line.product_name} sku={line.sku} /></td><td>{line.ordered_quantity}</td><td>{line.invoiced_quantity}</td><td>{Math.max(line.ordered_quantity - line.invoiced_quantity, 0)}</td><td>{line.available}</td><td><strong>{line.suggested_to_invoice}</strong></td><td>{line.shortage}</td><td><span className={`status-pill ${line.complete ? "available" : "low_stock"}`}>{line.billing_result ?? (line.complete ? "Lista para facturar completa" : "Con faltante")}</span></td></tr>)}</tbody></table>{billingLines.length === 0 && <div className="table-message">No hay productos en este filtro.</div>}</div></section>
            <section className="trace-section po-billing-comparison">
              <div className="line-heading"><div><h3>Pedido vs. facturado</h3><p>Todas las cantidades se comparan en unidades. Las facturas anuladas están excluidas.</p></div><span className={`status-pill ${selected.billing_summary.excess_units ? "low_stock" : "available"}`}>{selected.billing_summary.result}</span></div>
              <div className="fulfillment-summary"><div><span>Unidades pedidas</span><strong>{selected.billing_summary.ordered_units}</strong></div><div><span>Unidades facturadas</span><strong>{selected.billing_summary.invoiced_units}</strong></div><div><span>Unidades pendientes</span><strong>{selected.billing_summary.pending_units}</strong></div><div><span>Unidades en exceso</span><strong>{selected.billing_summary.excess_units}</strong></div><div><span>Productos completos</span><strong>{selected.billing_summary.complete_products}</strong></div><div><span>Productos parciales</span><strong>{selected.billing_summary.partial_products}</strong></div><div><span>Productos sin facturar</span><strong>{selected.billing_summary.not_invoiced_products}</strong></div></div>
              <div className="table-scroll"><table><thead><tr><th>Producto</th><th>Pedido</th><th>Facturado acumulado</th><th>Pendiente</th><th>Exceso</th><th>Resultado</th><th>Facturas</th></tr></thead><tbody>{selected.lines.map((line) => <tr key={`billing-${line.sku}`} className={line.excess_invoice_quantity > 0 || line.ordered_quantity === 0 ? "row-warning" : ""}><td><ProductIdentity name={line.product_name} sku={line.sku} /></td><td>{line.original_unit === "boxes" && line.original_quantity && line.units_per_box ? <span>{line.original_quantity} cajas × {line.units_per_box} = <strong>{line.ordered_quantity} unidades</strong></span> : `${line.ordered_quantity} unidades`}</td><td>{line.invoiced_quantity}</td><td>{line.pending_invoice_quantity}</td><td>{line.excess_invoice_quantity}</td><td><span className={`status-pill ${line.excess_invoice_quantity || line.ordered_quantity === 0 ? "low_stock" : "available"}`}>{line.billing_comparison_result}</span></td><td>{line.invoice_breakdown.length ? <details className="invoice-breakdown"><summary>{line.invoice_breakdown.length} factura{line.invoice_breakdown.length === 1 ? "" : "s"}</summary><div>{line.invoice_breakdown.map((invoice) => <button key={invoice.id} type="button" onClick={() => { sessionStorage.setItem("inventario.openInvoiceId", invoice.id); window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "invoices" })); }}><strong>{invoice.invoice_number}</strong><span>{invoice.invoice_date} · {invoice.quantity} unidades · {invoice.administrative_status}</span></button>)}</div></details> : "—"}</td></tr>)}</tbody></table></div>
              <details className="related-invoices-disclosure"><summary>Ver facturas vinculadas</summary><div>{selected.related_invoices.length ? selected.related_invoices.map((invoice) => <button key={invoice.id} type="button" onClick={() => { sessionStorage.setItem("inventario.openInvoiceId", invoice.id); window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "invoices" })); }}><strong>{invoice.invoice_number}</strong><span>{invoice.invoice_date} · {invoice.administrative_status} · {invoice.inventory_status_label}</span></button>) : <p>No hay facturas vinculadas.</p>}</div></details>
            </section>
            <section className="po-document-comparison">
              <aside className={`po-original-panel mobile-pane-${detailPane}`}><h3>Documento de origen</h3>{selected.source_documents.length > 1 && <div className="document-selector">{selected.source_documents.map((document) => <button type="button" className={selectedDocument?.token === document.token ? "active" : ""} key={document.token} onClick={() => setSelectedDocumentToken(document.token)}>{document.filename}</button>)}</div>}{selectedDocument?.available ? <DocumentViewer document={selectedDocument} url={apiUrl(`/purchase-orders/imports/${selectedDocument.token}/content`)} /> : selectedDocument ? <div className="table-message">Por privacidad y rendimiento, el archivo se eliminó después de extraer y confirmar la información. Se conserva únicamente su nombre y huella de auditoría.</div> : <div className="table-message">Esta OC no fue creada desde un documento.</div>}<label className="secondary-button corrected-document-button">{attachingDocument ? "Procesando…" : "Procesar documento corregido"}<input hidden disabled={attachingDocument} type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" onChange={(event) => attachCorrectedDocument(selected, event.target.files?.[0])} /></label></aside>
              <div className={`po-comparison-panel mobile-pane-${detailPane}`}><div className="line-heading"><div><h3>Comparación: pedido vs. cumplimiento</h3><p>Las entregas se muestran en bruto; las devoluciones permanecen separadas según la regla actual.</p></div><label className="difference-filter"><input type="checkbox" checked={differenceOnly} onChange={(event) => setDifferenceOnly(event.target.checked)} /> Solo con diferencias</label></div>
                {comparisonSummary && <div className="fulfillment-summary"><div><span>Productos</span><strong>{comparisonSummary.products}</strong></div><div><span>Unidades pedidas</span><strong>{comparisonSummary.ordered}</strong></div><div><span>Facturadas</span><strong>{comparisonSummary.invoiced}</strong></div><div><span>Despachadas</span><strong>{comparisonSummary.dispatched}</strong></div><div><span>Entregadas</span><strong>{comparisonSummary.delivered}</strong></div><div><span>Pendiente</span><strong>{comparisonSummary.pending}</strong></div><div><span>Con diferencias</span><strong>{comparisonSummary.differences}</strong></div></div>}
                <div className="table-scroll"><table className="fulfillment-table"><thead><tr><th>Producto</th><th>Pedido</th><th>Facturado</th><th>Despachado</th><th>Entregado</th><th>Devuelto</th><th>Neto</th><th>Pendiente</th><th>Diferencia</th><th>Estado</th></tr></thead><tbody>{comparisonLines.map((line) => <tr key={line.sku} className={line.difference !== 0 || line.returned_quantity || line.has_incident ? "row-warning" : ""}><td><ProductIdentity name={line.product_name} sku={line.sku} /></td><td>{line.ordered_quantity}</td><td>{line.invoiced_quantity}</td><td>{line.dispatched_quantity}</td><td>{line.delivered_quantity}</td><td>{line.returned_quantity}</td><td>{line.net_delivered_quantity}</td><td>{line.pending_delivery}</td><td>{line.difference > 0 ? `+${line.difference}` : line.difference}</td><td><span className={`fulfillment-status ${line.fulfillment_status}`}>{fulfillmentLabels[line.fulfillment_status] ?? line.fulfillment_status}</span></td></tr>)}</tbody></table>{!comparisonLines.length && <div className="table-message">No hay productos con diferencias.</div>}</div>
                {selected.related_invoices.length > 0 && <section className="related-operations"><h4>Documentos y operaciones relacionadas</h4>{selected.related_invoices.map((invoice) => <article key={invoice.id}><div><strong>Factura {invoice.invoice_number}</strong><span>{invoice.dispatch_status} · {invoice.delivery_status}</span></div><div className="operation-links"><button type="button" onClick={() => { sessionStorage.setItem("inventario.openInvoiceId", invoice.id); window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "invoices" })); }}>Abrir factura</button>{invoice.dispatches.length > 0 && <button type="button" onClick={() => window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "dispatches" }))}>Ver despachos</button>}{invoice.deliveries.length > 0 && <button type="button" onClick={() => window.dispatchEvent(new CustomEvent("inventario:navigate", { detail: "deliveries" }))}>Ver entregas</button>}</div><small>{invoice.dispatches.length} despachos · {invoice.deliveries.length} entregas</small></article>)}</section>}
              </div>
            </section>
            {selected.notes && <section className="trace-section order-notes"><h3>Observaciones</h3><p>{selected.notes}</p></section>}
            {showHistory && <section className="trace-section order-history"><div className="line-heading"><h3>Historial de cambios</h3><button className="text-button" type="button" onClick={() => setShowHistory(false)}>Cerrar</button></div>{historyLoading ? <div className="table-message">Cargando historial…</div> : history.length === 0 ? <div className="table-message">Esta OC todavía no tiene modificaciones.</div> : <div className="history-list">{history.map((item) => <article key={item.id}><header><strong>{item.field}</strong><span>{new Intl.DateTimeFormat("es-EC", { dateStyle: "medium", timeStyle: "short" }).format(new Date(item.occurred_at))}</span></header><p><span>{historyValue(item.previous_value)}</span><b>→</b><span>{historyValue(item.new_value)}</span></p><small>{item.actor}{item.reason ? ` · Motivo: ${item.reason}` : ""}</small></article>)}</div>}</section>}
          </>}
        </div>
      </section>}
    </main>
  );
}
