export type CommercialProduct = {
    id: string;
    sku: string;
    name: string;
    ean13: string | null;
    ean14?: string | null;
    description?: string;
    units_per_box: number;
    category: string;
    line?: string;
    presentation?: string;
    content?: string;
    aliases?: string[];
    chain_aliases: {
        chain: string;
        name: string;
        code: string;
    }[];
};
export type Evidence = {
    id: string;
    document_id: string;
    filename: string;
    source_location: string;
    source_url: string;
    origin: string;
    kind: string;
    chain: string;
    date: string | null;
    product_id: string | null;
    product_name: string;
    sku: string;
    units: number | null;
    amount: string | null;
    conversion: string;
    match_method: string;
    order_number: string;
    invoice_number: string;
    issues: string[];
    monetary_issues: string[];
    excluded: boolean;
    source: Record<string, unknown>;
    original_source?: Record<string, unknown>;
    revision: number;
};
export type Totals = {
    ordered: number | null;
    invoiced: number | null;
    missing: number | null;
    difference: number | null;
    known_ordered?: number;
    known_invoiced?: number;
    known_missing?: number;
    fulfillment: number | null;
    ordered_amount: number | null;
    invoiced_amount: number | null;
    unbilled_amount: number | null;
    currency?: string | null;
    invoiced_currency?: string | null;
};
export type ComparisonRow = Totals & {
    chain: string;
    product_name: string;
    sku: string;
    order_number: string;
    product_id: string;
    status: string;
    order_records: Evidence[];
    invoices: Evidence[];
    pending_records: Evidence[];
};
export type Alert = {
    level: string;
    code: string;
    message: string;
    record_ids: string[];
    chain: string;
};
export type Sale = {
    kind: string;
    chain: string;
    product_name: string;
    product_id: string;
    line: string;
    units: number;
    amount: number | null;
    share: number | null;
};
export type CommercialData = {
    summary: Totals & {
        review_records: number;
        review_documents?: number;
        excluded_records: number;
        sell_in_units: number | null;
        sell_out_units: number | null;
    };
    rows: ComparisonRow[];
    chains: (Totals & {
        chain: string;
    })[];
    products: (Totals & {
        product_name: string;
    })[];
    by_chain_product: ComparisonRow[];
    records: Evidence[];
    alerts: Alert[];
    sales: Sale[];
    sales_by_line: {
        kind: string;
        line: string;
        units: number;
        amount: number | null;
    }[];
    sales_movements: {
        kind: string;
        chain: string;
        product_name: string;
        period: string;
        previous_period: string;
        variation: number | null;
        current: number;
        previous: number;
    }[];
    sell_comparison: {
        chain: string;
        product_name: string;
        sell_in: number | null;
        sell_out: number | null;
        difference: number | null;
        hypothesis: string;
    }[];
    evolution: {
        grain: string;
        period: string;
        kind: string;
        units: number;
        amount: number | null;
    }[];
    rankings: Record<string, (Totals & {
        chain?: string;
        product_name?: string;
    })[]>;
    basis: string;
    executive_report: string[];
};
export type WeeklyReport = {
    period: { date_from: string | null; date_to: string | null; basis?: string };
    summary: Totals;
    chains: (Totals & { chain: string })[];
    critical_products: { missing: ComparisonRow[]; not_invoiced: ComparisonRow[]; economic: ComparisonRow[] };
    alerts: Alert[];
    counts: { orders: number; invoices: number; linked: number; pending: number; review_documents: number; excluded_invoices: number };
    basis?: string;
};
export type Filters = {
    date_from: string;
    date_to: string;
    chain: string;
    product_id: string;
    line: string;
    target: string;
    economic_threshold: string;
};
