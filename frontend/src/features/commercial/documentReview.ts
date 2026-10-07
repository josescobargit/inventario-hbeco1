import type { Evidence } from "./types";
export const chains = ["CORPORACIÓN FAVORITA", "CORPORACIÓN EL ROSADO", "FARCOMED", "INDUSTRIAL DANEC", "GERARDO ORTIZ", "TIA", "TUTI", "LIRIS DEL PORTAL"];
export const kindNames: Record<string, string> = { order: "Orden de compra", invoice: "Factura", sell_in: "Sell In", sell_out: "Sell Out" };
export type StoredDocument = { id: string; filename: string; warnings: string[]; needs_reprocessing?: boolean };
export type ImportResult = { document_id?: string; filename: string; status: string; message: string };
export type DocumentGroup = { id: string; filename: string; records: Evidence[]; issues: string[]; status: "OK" | "REVISAR" | "ERROR"; failure?: string; needsReprocessing?: boolean };
export function headerField(issue: string, row?: Evidence): string | undefined {
    if (/cadena/i.test(issue) && /identific|ausente|inválid/i.test(issue)) return "chain";
    if (/campos pendientes de la cabecera|cabecera extraída por OCR/i.test(issue)) return "extraction_confirmed";
    if (/fecha/i.test(issue)) return "date";
    if (/tipo de documento/i.test(issue)) return "kind";
    if (/número de documento/i.test(issue)) return row?.kind === "invoice" ? "invoice_number" : "order_number";
    if (/moneda/i.test(issue)) return "currency";
    if (/duplicado.*documento|documento duplicado/i.test(issue)) return "status";
}
export function groupDocuments(records: Evidence[], stored: StoredDocument[], imports: ImportResult[] = []): DocumentGroup[] {
    const groups = new Map<string, DocumentGroup>();
    for (const d of stored) groups.set(d.id, { id: d.id, filename: d.filename, records: [], issues: [], status: "OK", needsReprocessing: d.needs_reprocessing });
    for (const r of records) {
        const key = r.document_id || r.id;
        const group = groups.get(key) ?? { id: key, filename: r.filename, records: [], issues: [], status: "OK" as const };
        group.records.push(r);
        group.issues.push(...r.issues, ...r.monetary_issues);
        groups.set(key, group);
    }
    for (const group of groups.values()) {
        group.issues = [...new Set(group.issues)];
        if (!group.records.length) group.issues.push("No se encontraron productos. Revisa el documento original.");
        if (group.needsReprocessing) group.issues.push("Extracción anterior: vuelve a procesar el original.");
        group.status = group.issues.length ? "REVISAR" : "OK";
    }
    imports.filter(r => r.status === "error").forEach((r, i) => groups.set(`error:${i}`, { id: `error:${i}`, filename: r.filename, records: [], issues: [r.message], failure: r.message, status: "ERROR" }));
    return [...groups.values()];
}
export function documentValue(rows: Evidence[], key: "chain" | "kind" | "date" | "order_number" | "invoice_number") {
    const values = [...new Set(rows.map(r => r[key]).filter(Boolean))];
    return values.length > 1 ? `${values.length} ${key === "order_number" ? "OC" : key === "invoice_number" ? "facturas" : "valores"} · ver detalle` : values[0] || "Pendiente";
}
