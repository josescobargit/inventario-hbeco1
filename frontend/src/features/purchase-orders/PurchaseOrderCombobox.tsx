import { KeyboardEvent, useEffect, useId, useRef, useState } from "react";

import { apiRequest } from "../../api/client";

export interface PurchaseOrderSummary {
  id: string;
  order_number: string;
  chain_name: string;
  status: string;
  destination: string | null;
  product_count: number;
}

interface PurchaseOrderPage {
  items: PurchaseOrderSummary[];
  next_cursor: string | null;
}

const statusLabel: Record<string, string> = {
  open: "Abierta",
  partially_invoiced: "Facturada parcialmente",
  completed: "Completada",
  cancelled: "Cancelada",
};

export function PurchaseOrderCombobox({
  label, value, onSelect, placeholder = "Busca por número, cadena, estado o destino",
}: {
  label: string;
  value: PurchaseOrderSummary | null;
  onSelect: (order: PurchaseOrderSummary | null) => void;
  placeholder?: string;
}) {
  const listId = useId();
  const [query, setQuery] = useState(value?.order_number ?? "");
  const [results, setResults] = useState<PurchaseOrderSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const request = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(async () => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      setLoading(true);
      try {
        const params = new URLSearchParams({ limit: "25" });
        if (query.trim()) params.set("search", query.trim());
        const page = await apiRequest<PurchaseOrderPage>(`/purchase-orders?${params}`, { signal: controller.signal });
        setResults(page.items);
        setActive(0);
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) setResults([]);
      } finally {
        if (request.current === controller) setLoading(false);
      }
    }, 180);
    return () => {
      window.clearTimeout(timer);
      request.current?.abort();
    };
  }, [open, query]);

  const choose = (order: PurchaseOrderSummary) => {
    setQuery(order.order_number);
    setOpen(false);
    onSelect(order);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") { event.preventDefault(); setOpen(true); setActive((current) => Math.min(current + 1, Math.max(results.length - 1, 0))); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive((current) => Math.max(current - 1, 0)); }
    else if (event.key === "Enter" && open && results[active]) { event.preventDefault(); choose(results[active]); }
    else if (event.key === "Escape") setOpen(false);
    else if (event.key === "Backspace" && !query) onSelect(null);
  };

  return <label className="combobox-field"><span>{label}</span><div className="combobox">
    <input role="combobox" aria-label={label} aria-expanded={open} aria-controls={listId}
      aria-autocomplete="list" autoComplete="off" value={value ? value.order_number : query} placeholder={placeholder}
      onFocus={() => { if (value) setQuery(value.order_number); setOpen(true); }} onBlur={() => window.setTimeout(() => setOpen(false), 120)}
      onKeyDown={onKeyDown} onChange={(event) => { setQuery(event.target.value); onSelect(null); setOpen(true); }} />
    {query && <button className="combobox-clear" type="button" aria-label={`Limpiar ${label}`} onMouseDown={(event) => event.preventDefault()} onClick={() => { setQuery(""); onSelect(null); setOpen(true); }}>×</button>}
    {open && <div id={listId} className="combobox-options" role="listbox">
      {loading && <span>Buscando…</span>}
      {!loading && results.map((order, index) => <button type="button" role="option" key={order.id}
        aria-selected={index === active} onMouseDown={(event) => event.preventDefault()}
        onMouseEnter={() => setActive(index)} onClick={() => choose(order)}>
        <strong>{order.order_number}</strong><span>{order.chain_name} · {statusLabel[order.status] ?? order.status}</span>
      </button>)}
      {!loading && !results.length && <span>Sin resultados</span>}
    </div>}
  </div></label>;
}
