import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PurchaseOrderDocumentImport } from "./PurchaseOrderDocumentImport";

vi.mock("./DocumentViewer", () => ({
  DocumentViewer: () => <div data-testid="document-viewer" />,
}));

afterEach(cleanup);

const jsonResponse = (body: unknown) => new Response(JSON.stringify(body), {
  status: 200,
  headers: { "Content-Type": "application/json" },
});

describe("PurchaseOrderDocumentImport", () => {
  it("separa detectados, no encontrados y líneas faltantes sin mostrar encabezados como productos", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      if (String(input).includes("/customer-aliases")) return jsonResponse([]);
      return jsonResponse({
        drafts: [{
          document_token: "token-1",
          filename: "orden.pdf",
          content_type: "application/pdf",
          extraction_method: "pdf_text",
          page_count: 1,
          text: "TOTAL DE ITEMS 3",
          warnings: [],
          separation_needs_review: false,
          header: {
            order_number: "OC-10",
            chain_name: "Rosado",
            order_date: "2026-07-23",
            chain_candidates: ["Rosado"],
            order_number_source: "document_label",
            secondary_reference: null,
          },
          classification: {
            type: "purchase_order",
            label: "Orden de compra",
            allowed_for_purchase_order: true,
            message: "",
          },
          signals: {
            order: true,
            chain: true,
            product_structure: true,
            quantity_structure: true,
            candidate_rows: 2,
          },
          expected_product_count: 3,
          table_rows: [
            {
              page: 1,
              raw: "10 CREMA ANA 7862133169220 12 2",
              item_number: "10",
              chain_code: "40622962",
              description: "CREMA DE PEINAR ANA REGENEXT 200 ML",
              supplier_reference: "7862133169220",
              size: "200 ML",
              units_per_box: 12,
              quantity: 2,
              original_unit_type: "boxes",
            },
            {
              page: 1,
              raw: "20 PRODUCTO NUEVO ZZ99 6 5",
              item_number: "20",
              chain_code: "ZZ99",
              description: "PRODUCTO NUEVO SIN CATALOGO",
              supplier_reference: "9999999999999",
              size: null,
              units_per_box: 6,
              quantity: 5,
              original_unit_type: "boxes",
            },
          ],
        }],
      });
    }));

    render(<PurchaseOrderDocumentImport
      products={[{
        id: "p1",
        sku: "AR004",
        product_name: "CREMA DE PEINAR ANA REGENEXT 200 ML",
        barcode: "7862133169220",
        units_per_box: 12,
      }]}
      orders={[]}
      onCreated={vi.fn()}
      onCancel={vi.fn()}
    />);

    fireEvent.change(screen.getByPlaceholderText("Pega aquí el contenido completo de la orden…"), {
      target: { value: "ORDEN DE COMPRA OC-10" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Procesar y crear borradores" }));

    const summary = await screen.findByLabelText("Resumen del reconocimiento");
    expect(within(summary).getByText("Productos esperados").parentElement).toHaveTextContent("3");
    expect(within(summary).getByText("Productos detectados").parentElement).toHaveTextContent("2");
    expect(within(summary).getByText("Relacionados con el catálogo").parentElement).toHaveTextContent("1");
    expect(within(summary).getByText("No encontrados en el catálogo").parentElement).toHaveTextContent("1");
    expect(within(summary).getByText("Líneas que no se pudieron extraer").parentElement).toHaveTextContent("1");
    expect(screen.getAllByText(/Falta revisar 1 línea/)).toHaveLength(2);
    expect(screen.queryByText("PROVEEDOR")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "No encontrados" }));
    expect(screen.getByText("PRODUCTO NUEVO SIN CATALOGO")).toBeVisible();
    expect(screen.getByText("No encontrado en el catálogo")).toBeVisible();
    expect(screen.getAllByRole("row")).toHaveLength(2);
  });
});
