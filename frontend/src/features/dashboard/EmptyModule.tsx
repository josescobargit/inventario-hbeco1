import { moduleById, type ModuleId } from "./navigation";

const preparations: Partial<Record<ModuleId, { columns: string[]; note: string }>> = {
  movements: { columns: ["Fecha", "Tipo", "Producto", "Cantidad", "Origen", "Destino", "Responsable", "Documento", "Observación", "Estado"], note: "No hay una vista consolidada de movimientos disponible todavía." },
  entries: { columns: ["Fecha", "Responsable", "Producto", "Cantidad", "Documento", "Motivo"], note: "Las entradas se conectarán a movimientos de ingreso reales." },
  exits: { columns: ["Fecha", "Responsable", "Producto", "Cantidad", "Documento", "Motivo"], note: "Las salidas generales permanecerán separadas de los despachos a clientes." },
  comparisons: { columns: ["OC", "Fecha", "Cliente / Cadena", "Producto", "Pedido", "Facturado", "Despachado", "Entregado", "Diferencias", "Estado"], note: "Para calcular entregas por producto se requiere registrar cantidades entregadas por SKU." },
  reports: { columns: ["Rango", "Cadena", "Ciudad", "Producto", "Responsable", "Tipo"], note: "Los filtros y exportaciones se habilitarán cuando exista el servicio de reportes." },
  history: { columns: ["Fecha y hora", "Usuario", "Acción", "Módulo", "Producto", "Cantidad", "Documento relacionado", "Observación", "Estado"], note: "El historial consolidado todavía no está disponible." },
  users: { columns: ["Usuario", "Nombre", "Rol", "Estado", "Último acceso"], note: "La administración de accesos se habilitará en una etapa posterior." },
  settings: { columns: ["Parámetro", "Valor", "Responsable", "Última modificación"], note: "No hay parámetros editables disponibles en esta sección." },
};

const filterFields: Partial<Record<ModuleId, string[]>> = {
  movements: ["Fecha inicial", "Fecha final", "Tipo", "Producto", "Responsable"],
  comparisons: ["Fecha inicial", "Fecha final", "Cadena", "Producto", "Estado"],
  reports: ["Fecha inicial", "Fecha final", "Cadena", "Producto", "Ciudad", "Responsable", "Tipo de movimiento"],
  history: ["Fecha inicial", "Fecha final", "Usuario", "Módulo", "Acción"],
};

const plannedViews: Partial<Record<ModuleId, string[]>> = {
  comparisons: ["OC vs Facturado", "Facturado vs Despachado", "Despachado vs Entregado", "Pedido vs Entregado"],
  reports: ["Ventas por cadena", "Ventas por ciudad", "Ventas por producto", "Ventas por línea", "Más vendidos en unidades", "Más vendidos en dólares", "Productos con faltantes", "Cadenas con diferencias", "Cumplimiento por cadena", "Cumplimiento por OC", "Movimientos por responsable", "Reporte diario", "Reporte mensual"],
  settings: ["Stock mínimo", "Equivalencias", "Categorías", "Marcas", "Líneas", "Ciudades", "Ubicaciones", "Responsables", "Preferencias de reportes"],
};

export function EmptyModule({ module }: { module: ModuleId }) {
  const item = moduleById[module];
  const preparation = preparations[module];
  const filters = filterFields[module];
  const views = plannedViews[module];
  return <main className="dashboard prepared-module"><section className="module-heading"><div><p className="eyebrow">Módulo preparado</p><h1>{item.label}</h1><p>{item.description}</p></div></section>
    {filters && <section className="prepared-filters" aria-label="Filtros preparados">{filters.map((field) => <label key={field}><span>{field}</span><input type={field.includes("Fecha") ? "date" : "text"} disabled placeholder="Pendiente de conexión" /></label>)}<button type="button" className="secondary-button" disabled>Aplicar filtros</button></section>}
    {views && <section className="planned-views" aria-label="Consultas preparadas">{views.map((view) => <span key={view}>{view}</span>)}</section>}
    <section className="prepared-panel"><div className="prepared-toolbar"><div><h2>No hay información disponible</h2><p>{preparation?.note ?? "La estructura está preparada para conectar datos reales."}</p></div><button className="secondary-button" type="button" disabled>{module === "reports" ? "Exportación no disponible" : "Sin acciones disponibles"}</button></div>
      <div className="table-scroll"><table><thead><tr>{preparation?.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody /></table><div className="table-message">Cuando existan registros, aparecerán aquí.</div></div>
    </section>
  </main>;
}
