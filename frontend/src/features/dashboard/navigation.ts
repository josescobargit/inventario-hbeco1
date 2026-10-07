export type ModuleId =
  | "dashboard"
  | "sales"
  | "processing"
  | "operational"
  | "catalog"
  | "inventory"
  | "movements"
  | "entries"
  | "exits"
  | "adjustments"
  | "reservations"
  | "orders"
  | "invoices"
  | "dispatches"
  | "deliveries"
  | "returns"
  | "comparisons"
  | "reports"
  | "history"
  | "users"
  | "settings";

export type ModuleStatus = "existing" | "pending";
export type ComponentKey = "commercial" | "sales" | "processing" | "overview" | "catalog" | "inventory" | "movements" | "operations" | "adjustments" | "orders" | "reservations" | "invoices" | "dispatches" | "deliveries" | "returns" | "comparisons" | "reports" | "history" | "users" | "settings" | "empty";

export interface NavigationItem {
  id: ModuleId;
  label: string;
  icon: string;
  description: string;
  status: ModuleStatus;
  component: ComponentKey;
}

export interface NavigationGroup {
  label: string | null;
  items: NavigationItem[];
}

export const navigationGroups: NavigationGroup[] = [
  { label: "Principal", items: [
    { id: "dashboard", label: "Dashboard", icon: "⌂", description: "Control comercial, cruces y gerencia", status: "existing", component: "commercial" },
    { id: "orders", label: "Órdenes de compra", icon: "□", description: "Pedidos originales", status: "existing", component: "orders" },
    { id: "invoices", label: "Facturación", icon: "▤", description: "Facturas externas y trazabilidad", status: "existing", component: "invoices" },
    { id: "comparisons", label: "Comparativo", icon: "≋", description: "OC vs Facturado con documentos guardados", status: "existing", component: "comparisons" },
    { id: "sales", label: "Sell In / Sell Out", icon: "⌁", description: "Ventas por cadena y producto", status: "existing", component: "sales" },
    { id: "history", label: "Historial", icon: "◷", description: "Auditoría de acciones y responsables", status: "existing", component: "history" }
  ] },
  { label: "Documentos", items: [
    { id: "processing", label: "Procesar documentos", icon: "⇧", description: "Importar OC y facturas, revisar solo excepciones de extracción", status: "existing", component: "processing" }
  ] },
  { label: "Operación", items: [
    { id: "catalog", label: "Catálogo", icon: "◫", description: "Productos inventariables", status: "existing", component: "catalog" },
    { id: "inventory", label: "Inventario", icon: "▦", description: "Existencias y disponibilidad", status: "existing", component: "inventory" },
    { id: "movements", label: "Movimientos", icon: "↔", description: "Vista consolidada de movimientos", status: "existing", component: "movements" },
    { id: "entries", label: "Entradas", icon: "↓", description: "Ingresos de producto", status: "existing", component: "operations" },
    { id: "exits", label: "Salidas", icon: "↑", description: "Egresos no asociados a despacho", status: "existing", component: "operations" },
    { id: "adjustments", label: "Ajustes", icon: "±", description: "Correcciones físicas justificadas", status: "existing", component: "adjustments" },
    { id: "reservations", label: "Reservas", icon: "◇", description: "Stock comprometido", status: "existing", component: "reservations" }
  ] },
  { label: "Ventas y pedidos", items: [
    { id: "dispatches", label: "Despachos", icon: "↗", description: "Salidas vinculadas a facturas", status: "existing", component: "dispatches" },
    { id: "deliveries", label: "Entregas", icon: "✓", description: "Recepción por el cliente", status: "existing", component: "deliveries" },
    { id: "returns", label: "Devoluciones", icon: "↶", description: "Retornos y notas relacionadas", status: "existing", component: "returns" }
  ] },
  { label: "Análisis", items: [
    { id: "operational", label: "Panel operativo", icon: "◈", description: "Indicadores de inventario y pendientes operativos", status: "existing", component: "overview" },
    { id: "reports", label: "Reportes", icon: "⌁", description: "Consultas filtradas y exportación", status: "existing", component: "reports" }
  ] },
  { label: "Administración", items: [
    { id: "users", label: "Usuarios / Responsables", icon: "○", description: "Accesos y responsables operativos", status: "existing", component: "users" },
    { id: "settings", label: "Configuración", icon: "⚙", description: "Parámetros operativos", status: "existing", component: "settings" }
  ] }
];

export const navigationItems = navigationGroups.flatMap((group) => group.items);
export const moduleById = Object.fromEntries(navigationItems.map((item) => [item.id, item])) as Record<ModuleId, NavigationItem>;
