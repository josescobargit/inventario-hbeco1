import { KeyboardEvent, useEffect, useId, useRef, useState } from "react";

import { apiRequest } from "../../api/client";

export interface SearchableProduct {
  id?: string;
  sku: string;
  product_name: string;
  barcode?: string | null;
  contifico_aux_code?: string | null;
  available_to_invoice?: number;
  units_per_box?: number;
}

export function ProductCombobox({
  label, value, products, onSelect,
}: {
  label: string;
  value: string;
  products: SearchableProduct[];
  onSelect: (sku: string, product?: SearchableProduct) => void;
}) {
  const listId = useId();
  const selected = products.find((product) => product.sku === value);
  const [query, setQuery] = useState(selected ? `${selected.product_name} · SKU: ${selected.sku}` : "");
  const [results, setResults] = useState<SearchableProduct[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const request = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(async () => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller; setLoading(true);
      try {
        const params = new URLSearchParams({ limit: "25" });
        if (query.trim() && !value) params.set("search", query.trim());
        const found = await apiRequest<SearchableProduct[]>(`/inventory/availability?${params}`, { signal: controller.signal });
        setResults(found); setActive(0);
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) setResults([]);
      } finally {
        if (request.current === controller) setLoading(false);
      }
    }, 180);
    return () => { window.clearTimeout(timer); request.current?.abort(); };
  }, [open, query, value]);

  const choose = (product: SearchableProduct) => {
    setQuery(`${product.product_name} · SKU: ${product.sku}`);
    setOpen(false); onSelect(product.sku, product);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") { event.preventDefault(); setOpen(true); setActive((current) => Math.min(current + 1, Math.max(results.length - 1, 0))); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive((current) => Math.max(current - 1, 0)); }
    else if (event.key === "Enter" && open && results[active]) { event.preventDefault(); choose(results[active]); }
    else if (event.key === "Escape") setOpen(false);
    else if (event.key === "Backspace" && !query) onSelect("");
  };

  return <div className="combobox product-combobox">
    <input role="combobox" aria-label={label} aria-expanded={open} aria-controls={listId}
      aria-autocomplete="list" autoComplete="off" value={value && selected ? `${selected.product_name} · SKU: ${selected.sku}` : query}
      placeholder="Busca por nombre, SKU, variante o tamaño"
      onFocus={() => { if (value && selected) setQuery(`${selected.product_name} · SKU: ${selected.sku}`); setOpen(true); }} onBlur={() => window.setTimeout(() => setOpen(false), 120)}
      onKeyDown={onKeyDown} onChange={(event) => { setQuery(event.target.value); onSelect(""); setOpen(true); }} />
    {value && <button className="combobox-clear" type="button" aria-label={`Limpiar ${label}`}
      onMouseDown={(event) => event.preventDefault()} onClick={() => { setQuery(""); onSelect(""); setOpen(true); }}>×</button>}
    {open && <div id={listId} className="combobox-options product-options" role="listbox">
      {loading && <span>Buscando…</span>}
      {!loading && results.map((product, index) => <button type="button" role="option"
        key={product.id ?? product.sku} aria-selected={index === active}
        onMouseDown={(event) => event.preventDefault()} onMouseEnter={() => setActive(index)}
        onClick={() => choose(product)}><strong>{product.product_name}</strong><span>SKU: {product.sku}</span></button>)}
      {!loading && !results.length && <span>Sin resultados</span>}
    </div>}
  </div>;
}
