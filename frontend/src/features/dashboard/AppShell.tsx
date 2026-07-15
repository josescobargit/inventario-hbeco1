import { useState, type ReactNode } from "react";

import type { AuthenticatedUser } from "../auth/types";
import { Sidebar } from "./Sidebar";
import { moduleById, type ModuleId } from "./navigation";

interface AppShellProps {
  user: AuthenticatedUser;
  activeModule: ModuleId;
  onNavigate: (module: ModuleId) => void;
  onLogout: () => Promise<void>;
  children: ReactNode;
}

const roleLabel = (role: string) => role === "principal" ? "Administrador" : role.replaceAll("_", " ");

export function AppShell({ user, activeModule, onNavigate, onLogout, children }: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const navigate = (module: ModuleId) => { onNavigate(module); setSidebarOpen(false); };
  const dateModules: ModuleId[] = ["dashboard", "movements", "comparisons", "reports", "history"];
  const showDates = dateModules.includes(activeModule);

  return <div className={`authenticated-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
    <Sidebar activeModule={activeModule} open={sidebarOpen} collapsed={sidebarCollapsed} onToggleCollapsed={() => setSidebarCollapsed((value) => !value)} onNavigate={navigate} onClose={() => setSidebarOpen(false)} />
    <div className="shell-body">
      <header className="shell-header">
        <div className="header-context"><button className="menu-button" type="button" aria-label="Abrir navegación" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(true)}>☰</button><div><span>Inventario / {moduleById[activeModule].label}</span><strong>{moduleById[activeModule].label}</strong></div></div>
        <div className="header-tools">
          <label className="global-search" title="La búsqueda global se habilitará al conectar el servicio"><span aria-hidden="true">⌕</span><input aria-label="Buscar en el sistema" type="search" placeholder="Buscar en inventario" disabled /></label>
          {showDates && <div className="header-date-range" title="El filtro se habilitará al conectar datos por fecha"><label><span>Desde</span><input type="date" disabled /></label><label><span>Hasta</span><input type="date" disabled /></label></div>}
          <div className="quick-actions" aria-label="Acciones rápidas"><button type="button" onClick={() => navigate("entries")}>Entrada</button><button type="button" onClick={() => navigate("exits")}>Salida</button><button type="button" onClick={() => navigate("invoices")}>Factura</button><button type="button" onClick={() => navigate("orders")}>OC</button><button type="button" onClick={() => navigate("reports")}>Exportar</button></div>
        </div>
        <div className="user-actions"><div><strong>{user.full_name}</strong><span>{roleLabel(user.role)}</span></div><button className="secondary-button" type="button" onClick={onLogout}>Salir</button></div>
      </header>
      <div className="shell-content">{children}</div>
    </div>
  </div>;
}
