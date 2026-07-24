import { useEffect, useState } from "react";

import type { AuthenticatedUser } from "../auth/types";
import { CatalogCenter } from "../catalog/CatalogCenter";
import { ComparisonCenter } from "../comparisons/ComparisonCenter";
import { DeliveryIncidentCenter } from "../deliveries/DeliveryIncidentCenter";
import { DispatchCenter } from "../dispatches/DispatchCenter";
import { HistoryCenter } from "../history/HistoryCenter";
import { InventoryCenter } from "../inventory/InventoryCenter";
import { AdjustmentsCenter } from "../inventory/AdjustmentsCenter";
import { InventoryOperationCenter } from "../inventory/InventoryOperationCenter";
import { MovementCenter } from "../inventory/MovementCenter";
import { InvoiceCenter } from "../invoices/InvoiceCenter";
import { OperationalOverview } from "../overview/OperationalOverview";
import { PostSaleCenter } from "../post-sale/PostSaleCenter";
import { PurchaseOrderCenter } from "../purchase-orders/PurchaseOrderCenter";
import { ReportCenter } from "../reports/ReportCenter";
import { ReservationCenter } from "../reservations/ReservationCenter";
import { SettingsCenter } from "../settings/SettingsCenter";
import { UserCenter } from "../users/UserCenter";
import { AppShell } from "./AppShell";
import { EmptyModule } from "./EmptyModule";
import { moduleById, type ModuleId } from "./navigation";

interface DashboardProps { user: AuthenticatedUser; onLogout: () => Promise<void> }

export function Dashboard({ user, onLogout }: DashboardProps) {
  const [activeModule, setActiveModule] = useState<ModuleId>("dashboard");
  useEffect(() => {
    const navigate = (event: Event) => {
      const module = (event as CustomEvent<ModuleId>).detail;
      if (module && moduleById[module]) setActiveModule(module);
    };
    window.addEventListener("inventario:navigate", navigate);
    return () => window.removeEventListener("inventario:navigate", navigate);
  }, []);
  const component = moduleById[activeModule].component;

  const content = component === "overview" ? <OperationalOverview onNavigate={setActiveModule} />
    : component === "catalog" ? <CatalogCenter />
    : component === "inventory" ? <InventoryCenter />
    : component === "movements" ? <MovementCenter />
    : component === "operations" ? <InventoryOperationCenter operationType={activeModule === "entries" ? "entry" : "exit"} user={user} />
    : component === "adjustments" ? <AdjustmentsCenter user={user} />
    : component === "orders" ? <PurchaseOrderCenter />
    : component === "reservations" ? <ReservationCenter />
    : component === "invoices" ? <InvoiceCenter />
    : component === "dispatches" ? <DispatchCenter />
    : component === "deliveries" ? <DeliveryIncidentCenter />
    : component === "returns" ? <PostSaleCenter />
    : component === "comparisons" ? <ComparisonCenter />
    : component === "reports" ? <ReportCenter />
    : component === "history" ? <HistoryCenter />
    : component === "users" ? <UserCenter />
    : component === "settings" ? <SettingsCenter userRole={user.role} />
    : <EmptyModule module={activeModule} />;

  return <AppShell user={user} activeModule={activeModule} onNavigate={setActiveModule} onLogout={onLogout}>{content}</AppShell>;
}
