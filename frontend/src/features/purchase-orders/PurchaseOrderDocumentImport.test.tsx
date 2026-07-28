import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PurchaseOrderDocumentImport } from "./PurchaseOrderDocumentImport";

vi.mock("./DocumentViewer", () => ({
  DocumentViewer: () => <div data-testid="document-viewer" />,
}));

afterEach(cleanup);

const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "Content-Type": "application/json" },
});
const previewResponse = {
  drafts: [{
    document_token: "token-preview",
    filename: "orden.pdf",
    content_type: "application/pdf",
    extraction_method: "pdf_text",
    page_count: 1,
    text: "ORDEN DE COMPRA OC-10\nTOTAL DE ITEMS 1",
    warnings: [],
    separation_needs_review: false,
    header: {
      order_number: "OC-10", chain_name: null, order_date: null,
      chain_candidates: [], order_number_source: "document_label", secondary_reference: null,
    },
    classification: {
      type: "purchase_order", label: "Orden de compra",
      allowed_for_purchase_order: true, message: "",
    },
    signals: {
      order: true, chain: false, product_structure: true,
      quantity_structure: true, candidate_rows: 1,
    },
    expected_product_count: 1,
    table_rows: [{
      page: 1, raw: "10 PRODUCTO 12", item_number: "10",
      chain_code: "ABC", description: "PRODUCTO DE PRUEBA",
      supplier_reference: null, size: null, units_per_box: null,
      quantity: 12, original_unit_type: "units",
    }],
  }],
};

describe("PurchaseOrderDocumentImport", () => {
  it("abre la pantalla sin realizar una solicitud de procesamiento", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<PurchaseOrderDocumentImport products={[]} orders={[]} onCreated={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Crear OC desde PDF, imagen o pedido" })).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByText("Not Found")).not.toBeInTheDocument();
  });

  it("selecciona un PDF y envía multipart al endpoint que existe", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(previewResponse));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<PurchaseOrderDocumentImport products={[]} orders={[]} onCreated={vi.fn()} onCancel={vi.fn()} />);
    const file = new File(["%PDF-1.7"], "orden.pdf", { type: "application/pdf" });
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;

    fireEvent.change(input, { target: { files: [file] } });
    expect(screen.getByText("orden.pdf")).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Procesar y crear borradores" }));

    expect(await screen.findByLabelText("Resumen del reconocimiento")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/v1/purchase-orders/imports/preview");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.headers).not.toHaveProperty("Content-Type");
  });

  it("acepta un PDF arrastrado sin procesarlo antes de la confirmación", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<PurchaseOrderDocumentImport products={[]} orders={[]} onCreated={vi.fn()} onCancel={vi.fn()} />);
    const file = new File(["%PDF"], "arrastrada.pdf", { type: "application/pdf" });
    fireEvent.drop(container.querySelector(".document-dropzone")!, { dataTransfer: { files: [file] } });
    expect(screen.getByText("arrastrada.pdf")).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["imagen.png", "image/png"],
    ["foto.jpg", "image/jpeg"],
  ])("acepta %s para el servicio OCR", (filename, type) => {
    const { container } = render(<PurchaseOrderDocumentImport products={[]} orders={[]} onCreated={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(container.querySelector<HTMLInputElement>('input[type="file"]')!, {
      target: { files: [new File(["image"], filename, { type })] },
    });
    expect(screen.getByText(filename)).toBeVisible();
  });

  it("rechaza formato inválido antes de llamar al endpoint", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<PurchaseOrderDocumentImport products={[]} orders={[]} onCreated={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(container.querySelector<HTMLInputElement>('input[type="file"]')!, {
      target: { files: [new File(["data"], "orden.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" })] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("usa PDF, JPG, JPEG, PNG o WEBP");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rechaza un archivo superior a 15 MB antes de llamar al endpoint", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<PurchaseOrderDocumentImport products={[]} orders={[]} onCreated={vi.fn()} onCancel={vi.fn()} />);
    const file = new File(["small"], "grande.pdf", { type: "application/pdf" });
    Object.defineProperty(file, "size", { value: 15 * 1024 * 1024 + 1 });
    fireEvent.change(container.querySelector<HTMLInputElement>('input[type="file"]')!, { target: { files: [file] } });
    expect(screen.getByRole("alert")).toHaveTextContent("supera el límite de 15 MB");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [400, "documento dañado", "documento dañado"],
    [401, "Not authenticated", "tu sesión expiró"],
    [500, "Internal Server Error", "error interno"],
  ])("explica la respuesta %i sin dejar la pantalla en blanco", async (status, detail, expected) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail }, status)));
    render(<PurchaseOrderDocumentImport products={[]} orders={[]} onCreated={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText("Pega aquí el contenido completo de la orden…"), { target: { value: "OC-10" } });
    fireEvent.click(screen.getByRole("button", { name: "Procesar y crear borradores" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(expected);
    expect(screen.getByRole("heading", { name: "Crear OC desde PDF, imagen o pedido" })).toBeVisible();
  });

  it("convierte el 404 en un diagnóstico útil y permite reintentar", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "Not Found" }, 404))
      .mockResolvedValueOnce(jsonResponse(previewResponse));
    vi.stubGlobal("fetch", fetchMock);
    render(<PurchaseOrderDocumentImport products={[]} orders={[]} onCreated={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText("Pega aquí el contenido completo de la orden…"), { target: { value: "OC-10" } });
    fireEvent.click(screen.getByRole("button", { name: "Procesar y crear borradores" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("servicio de lectura no está disponible");
    expect(screen.queryByText(/^Not Found$/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByLabelText("Resumen del reconocimiento")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

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
