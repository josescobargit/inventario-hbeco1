import { useEffect, useState } from "react";

import { apiRequest } from "../../api/client";
import type { AuthenticatedUser } from "../auth/types";
import { StockAdjustmentPanel } from "./StockAdjustmentPanel";
import { StockImportPanel } from "./StockImportPanel";

interface Availability { sku: string; product_name: string; physical_confirmed: number; reserved: number; invoiced_not_dispatched: number; blocked_by_incident: number }

export function AdjustmentsCenter({ user }: { user: AuthenticatedUser }) {
  const [products, setProducts] = useState<Availability[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { let active = true; apiRequest<Availability[]>("/inventory/availability").then((data) => { if (active) { setProducts(data); setError(null); } }).catch(() => { if (active) setError("No se pudo cargar la información. Intenta nuevamente."); }); return () => { active = false; }; }, [reloadKey]);

  return <main className="dashboard adjustments-center"><section className="welcome-block"><p className="eyebrow">Corrección física</p><h1>Ajustes de inventario</h1><p>Correcciones físicas, conteos y cargas masivas.</p></section>
    <div className="operation-definition"><span><strong>Entrada</strong> Ingreso real de producto</span><span><strong>Salida</strong> Egreso real de producto</span><span><strong>Ajuste</strong> Corrección del conteo</span><span><strong>Despacho</strong> Salida vinculada a una factura</span></div>
    {error && <div className="message error" role="alert">{error}</div>}
    <StockImportPanel onApplied={() => setReloadKey((value) => value + 1)} />
    <StockAdjustmentPanel products={products} userRole={user.role} onApplied={() => setReloadKey((value) => value + 1)} />
  </main>;
}
