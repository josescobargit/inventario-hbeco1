import { navigationGroups, type ModuleId } from "./navigation";

const collapsedModules = new Set<ModuleId>(["dashboard", "inventory", "movements", "adjustments", "orders", "invoices", "deliveries"]);

interface SidebarProps {
  activeModule: ModuleId;
  open: boolean;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  onNavigate: (module: ModuleId) => void;
  onClose: () => void;
}

export function Sidebar({ activeModule, open, collapsed = false, onToggleCollapsed, onNavigate, onClose }: SidebarProps) {
  return <>
    {open && <button className="sidebar-backdrop" type="button" aria-label="Cerrar navegación" onClick={onClose} />}
    <aside className={`app-sidebar ${open ? "open" : ""} ${collapsed ? "collapsed" : ""}`} aria-label="Navegación principal">
      <div className="sidebar-brand"><div className="brand-mark small" aria-hidden="true">IO</div><div className="sidebar-brand-copy"><strong>Inventario</strong><span>Operativo</span></div>{onToggleCollapsed && <button className="sidebar-collapse" type="button" aria-label={collapsed ? "Expandir barra lateral" : "Colapsar barra lateral"} aria-expanded={!collapsed} onClick={onToggleCollapsed}>{collapsed ? "›" : "‹"}</button>}</div>
      <nav className="sidebar-nav">
        {navigationGroups.map((group, index) => <section className="nav-group" key={group.label ?? `main-${index}`}>
          {group.label && <h2>{group.label}</h2>}
          {group.items.map((item) => <button type="button" key={item.id} className={`${activeModule === item.id ? "active " : ""}${collapsedModules.has(item.id) ? "collapsed-essential" : ""}`} aria-label={item.label} aria-current={activeModule === item.id ? "page" : undefined} title={`${item.label} — ${item.status === "pending" ? "Módulo preparado" : item.description}`} onClick={() => onNavigate(item.id)}><i aria-hidden="true">{item.icon}</i><span>{item.label}</span>{item.status === "pending" && <small aria-hidden="true">•</small>}<b className="sidebar-tooltip" aria-hidden="true">{item.label}</b></button>)}
        </section>)}
      </nav>
    </aside>
  </>;
}
