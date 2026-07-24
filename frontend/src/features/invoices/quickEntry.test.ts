import { beforeEach, describe, expect, it } from "vitest";

import {
  applyConfirmedAlias, buildProductIndex, clearConfirmedAliases, matchProduct,
  extractVisibleUnitTotal, normalizeProductText, parseDocumentProductLines,
  parseInvoiceBlocks, parsePositionalTableRows, parseProductLines, retryProductRecognition,
} from "./quickEntry";

const products = [
  { sku: "ACP001", product_name: "TOALLITAS HÚMEDAS ANA X 100", barcode: "7862133169244", units_per_box: 20 },
  { sku: "SHA400", product_name: "SHAMPOO ANA REGENEXT 400 ML.", barcode: "7860000000001", units_per_box: 20 },
  { sku: "ACO400", product_name: "ACONDICIONADOR ANA REGENEXT 400 ML.", units_per_box: 12 },
  { sku: "SHA190", product_name: "SHAMPOO ANA REGENEXT 190 ML.", units_per_box: 12 },
  { sku: "PACK-COCO", product_name: "PACK SH+AC ANA ELIXIR COCO 500 ML", units_per_box: 6 },
];

describe("registro rápido", () => {
  beforeEach(() => clearConfirmedAliases());

  it("reconoce primero por código y luego por nombre sin tildes", () => {
    expect(matchProduct("texto externo - ACP001", products)).toBe("ACP001");
    expect(matchProduct("SHAMPOO ANA REGENEXT 400 ML", products)).toBe("SHA400");
  });

  it.each([
    ["PACK SH+AC ANA ELIXIR COCO 500 ML -", "PACK SH+AC ANA ELIXIR COCO 500 ML"],
    ["SHAMPOO ANA REGENEXT 400 ML. -", "shampoo ana regenext 400 ml"],
    ["TOALLITAS HÚMEDAS  ANA X 100", "toallitas humedas ana x 100"],
    ["PACK SH + AC ANA ELIXIR COCO 500 ML", "PACK SH+AC ANA ELIXIR COCO 500 ML"],
    ["\u200BTOALLITAS HÚMEDAS ANA X 100\uFEFF", "TOALLITAS HUMEDAS ANA X 100"],
  ])("normaliza signos, espacios, mayúsculas e invisibles", (imported, catalog) => {
    expect(normalizeProductText(imported)).toBe(normalizeProductText(catalog));
  });

  it("reconoce por SKU y código de barras", () => {
    expect(matchProduct("ACP001", products)).toBe("ACP001");
    expect(matchProduct("TOALLITAS - 7862133169244", products)).toBe("ACP001");
  });

  it("no confunde productos similares, variantes ni tamaños", () => {
    expect(matchProduct("SHAMPOO ANA REGENEXT 370 ML", products)).toBe("");
    expect(matchProduct("ACONDICIONADOR ANA REGENEXT 400 ML", products)).toBe("ACO400");
    expect(matchProduct("SHAMPOO ANA REGENEXT 190 ML", products)).toBe("SHA190");
  });

  it("marca productos desconocidos sin perder líneas correctas", () => {
    const lines = parseProductLines("2 DESCONOCIDO\n3.00 TOALLITAS HÚMEDAS ANA X 100 - ACP001", products);
    expect(lines[0]!.error).toContain("no reconocido");
    expect(lines[1]!).toMatchObject({ sku: "ACP001", quantity: 3, error: null });
  });

  it("separa múltiples facturas y propone las vacías como anuladas", () => {
    const blocks = parseInvoiceBlocks(
      "FAC 001-001-000000758\n2 ACP001\n---\nFAC 001-001-000000759\nANULADA\nFAC 001-001-000000760",
      products,
    );
    expect(blocks).toHaveLength(3);
    expect(blocks[0]!.lines[0]!.sku).toBe("ACP001");
    expect(blocks[1]!.is_void).toBe(true);
    expect(blocks[2]!.is_void).toBe(true);
  });

  it("indexa el catálogo completo aunque llegue dividido en páginas", () => {
    const pages = [products.slice(0, 2), products.slice(2)];
    const index = buildProductIndex(pages.flat());
    expect(index.products).toHaveLength(products.length);
    expect(index.byName.get(normalizeProductText("PACK SH+AC ANA ELIXIR COCO 500 ML"))?.[0]?.sku).toBe("PACK-COCO");
  });

  it("reintenta después de que el catálogo termine de cargar", () => {
    const pending = parseProductLines("2 SHAMPOO ANA REGENEXT 400 ML. -", []);
    expect(pending[0]!.sku).toBe("");
    expect(retryProductRecognition(pending, products)[0]!.sku).toBe("SHA400");
  });

  it("aplica una selección manual a líneas repetidas y reutiliza el alias persistido", () => {
    const pending = parseProductLines("2 SHAMPOO REGEN TOTAL\n3 shampoo  regen total -", products);
    const confirmed = applyConfirmedAlias(pending, pending[0]!.raw, "SHA400");
    expect(confirmed.map((line) => line.sku)).toEqual(["SHA400", "SHA400"]);
    expect(parseProductLines("1 SHAMPOO REGEN TOTAL", products)[0]!.sku).toBe("SHA400");
  });

  it("interpreta una tabla con código, descripción, cantidad y unidad", () => {
    const lines = parseDocumentProductLines(
      "CÓDIGO DESCRIPCIÓN CANTIDAD\nSHA400 SHAMPOO ANA REGENEXT 400 ML. 12 UN",
      products,
    );
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatchObject({
      detected_code: "SHA400", sku: "SHA400", quantity: 12, unit: "UN",
      confidence: "high", reviewed: true,
    });
  });

  it("ignora encabezados repetidos, precios y totales", () => {
    const lines = parseDocumentProductLines(
      [
        "CÓDIGO DESCRIPCIÓN CANTIDAD",
        "SHA400 SHAMPOO ANA REGENEXT 400 ML. 2 UN",
        "TOTAL 25.50",
        "PÁGINA 2",
        "CÓDIGO DESCRIPCIÓN CANTIDAD",
      ].join("\n"),
      products,
    );
    expect(lines).toHaveLength(1);
    expect(lines[0]!.quantity).toBe(2);
  });

  it("mantiene desconocidos y no confunde cantidad con precio decimal", () => {
    const lines = parseDocumentProductLines(
      "ZZ999 PRODUCTO QUE NO EXISTE 4 UN\nPRODUCTO EXTRAÑO 19.95",
      products,
    );
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatchObject({ sku: "", quantity: 4, confidence: "low", reviewed: false });
  });

  it("aplica códigos específicos solamente con los alias de esa cadena", () => {
    const text = "CLI-77 SHAMPOO ESPECIAL 6 UN";
    expect(parseDocumentProductLines(text, products)).toMatchObject([{ sku: "" }]);
    expect(parseDocumentProductLines(text, products, [{
      source_text: text, detected_code: "CLI-77", sku: "SHA400",
    }])).toMatchObject([{ sku: "SHA400", confidence: "high" }]);
  });

  it("extrae totales de unidades pero no confunde totales monetarios", () => {
    expect(extractVisibleUnitTotal("TOTAL UNIDADES: 24")).toBe(24);
    expect(extractVisibleUnitTotal("SUBTOTAL $24.00\nTOTAL $28.50")).toBeNull();
  });

  it.each([
    ["TIA", "[[PAGE:1]]\nSKU DESCRIPCIÓN CANTIDAD\nSHA400 SHAMPOO ANA REGENEXT 400 ML. 3 UN"],
    ["Cadena Norte", "[[PAGE:1]]\nQTY | ITEM | EAN\n4 | SHAMPOO ANA REGENEXT 400 ML. | SHA400"],
    ["Mercado Sur", "[[PAGE:1]]\nARTÍCULO  UNIDADES  DETALLE\nSHA400  5  SHAMPOO ANA REGENEXT 400 ML."],
    ["Retail Centro", "[[PAGE:1]]\nDESCRIPCIÓN;CÓDIGO PROVEEDOR;SOLICITADO\nSHAMPOO ANA REGENEXT 400 ML.;SHA400;6"],
    ["Comprador Internacional", "[[PAGE:1]]\nDESCRIPTION\tQTY\tSKU\nSHAMPOO ANA REGENEXT 400 ML.\t7\tSHA400"],
  ])("usa el mismo parser general para %s y columnas en distinto orden", (_chain, text) => {
    expect(parseDocumentProductLines(text, products)).toMatchObject([
      { page: 1, sku: "SHA400", confidence: "high" },
    ]);
  });

  it("procesa varias páginas, encabezados repetidos y descripciones divididas", () => {
    const text = [
      "[[PAGE:1]]",
      "SKU DESCRIPCIÓN CANTIDAD",
      "SHA400 SHAMPOO ANA",
      "REGENEXT 400 ML. 8 UN",
      "PÁGINA 1",
      "[[PAGE:2]]",
      "SKU DESCRIPCIÓN CANTIDAD",
      "ZZ-55 PRODUCTO DESCONOCIDO 9 UN",
    ].join("\n");
    const lines = parseDocumentProductLines(text, products);
    expect(lines).toHaveLength(2);
    expect(lines[0]).toMatchObject({ page: 1, sku: "SHA400", quantity: 8 });
    expect(lines[1]).toMatchObject({ page: 2, sku: "", quantity: 9, reviewed: false });
  });

  it("conserva una fila candidata incompleta para revisión manual", () => {
    const lines = parseDocumentProductLines(
      "[[PAGE:3]]\nCÓDIGO DESCRIPCIÓN CANTIDAD\nZZ-88 PRODUCTO SIN CANTIDAD",
      products,
    );
    expect(lines).toMatchObject([{
      page: 3, detected_code: "ZZ-88", description: "PRODUCTO SIN CANTIDAD",
      quantity: null, sku: "", confidence: "low", reviewed: false,
    }]);
  });

  it("convierte las cantidades de TUTI usando Cajas × UC y exige confirmación", () => {
    const text = [
      "CODIGO  DESCRIPCION  CANT CAJAS  UC",
      "ACP001  TOALLITAS HÚMEDAS ANA X 100  15  20",
      "SHA400  SHAMPOO ANA REGENEXT 400 ML.  15  20",
      "ACO400  ACONDICIONADOR ANA REGENEXT 400 ML.  20  12",
      "SHA190  SHAMPOO ANA REGENEXT 190 ML.  20  12",
    ].join("\n");
    const lines = parseDocumentProductLines(text, products);
    expect(lines.map((line) => line.original_quantity)).toEqual([15, 15, 20, 20]);
    expect(lines.map((line) => line.units_per_box)).toEqual([20, 20, 12, 12]);
    expect(lines.map((line) => line.calculated_units)).toEqual([300, 300, 240, 240]);
    expect(lines.reduce((sum, line) => sum + (line.calculated_units ?? 0), 0)).toBe(1080);
    expect(lines.every((line) => line.original_unit_type === "boxes" && !line.conversion_confirmed)).toBe(true);
  });

  it("usa CANT (UNID) directamente y no multiplica de nuevo", () => {
    const text = [
      "CODIGO  DESCRIPCION  CANT (UNID)",
      "163818000  PRODUCTO HOMOLOGADO UNO  96",
      "166451000  PRODUCTO HOMOLOGADO DOS  180",
      "168929000  PRODUCTO HOMOLOGADO TRES  60",
      "168933000  PRODUCTO HOMOLOGADO CUATRO  108",
    ].join("\n");
    const lines = parseDocumentProductLines(text, [], [
      { source_text: "PRODUCTO HOMOLOGADO UNO", detected_code: "163818000", sku: "AR004" },
      { source_text: "PRODUCTO HOMOLOGADO DOS", detected_code: "166451000", sku: "ACP001" },
      { source_text: "PRODUCTO HOMOLOGADO TRES", detected_code: "168929000", sku: "AR003" },
      { source_text: "PRODUCTO HOMOLOGADO CUATRO", detected_code: "168933000", sku: "AR001" },
    ]);
    expect(lines.map((line) => line.calculated_units)).toEqual([96, 180, 60, 108]);
    expect(lines.reduce((sum, line) => sum + (line.calculated_units ?? 0), 0)).toBe(444);
    expect(lines.every((line) => line.original_unit_type === "units")).toBe(true);
  });

  it("reproduce una OC escaneada de cajas con UxC uniforme", () => {
    const text = [
      "ARTICULO  DETALLE  CANT CAJAS  UXC",
      "R001  PRODUCTO ROSADO UNO  2  12",
      "R002  PRODUCTO ROSADO DOS  10  12",
      "R003  PRODUCTO ROSADO TRES  22  12",
      "R004  PRODUCTO ROSADO CUATRO  5  12",
    ].join("\n");
    const lines = parseDocumentProductLines(text, []);
    expect(lines).toHaveLength(4);
    expect(lines.map((line) => line.calculated_units)).toEqual([24, 120, 264, 60]);
    expect(lines.reduce((sum, line) => sum + (line.calculated_units ?? 0), 0)).toBe(468);
  });

  it("mantiene cantidades unitarias de un local sin aplicar la UxC del catálogo", () => {
    const text = [
      "CODIGO  DESCRIPCION  CANT UNIDADES",
      ...Array.from({ length: 16 }, (_, index) => `L${index + 100}  PRODUCTO LOCAL ${index + 1}  12`),
    ].join("\n");
    const lines = parseDocumentProductLines(text, []);
    expect(lines).toHaveLength(16);
    expect(lines.reduce((sum, line) => sum + (line.calculated_units ?? 0), 0)).toBe(192);
    expect(lines.every((line) => line.calculation_method === "direct_units")).toBe(true);
  });

  it("reporta seis productos y 1.620 unidades en una tabla de cajas con UC", () => {
    const uxc = [20, 20, 20, 20, 20, 8];
    const text = [
      "SKU  DESCRIPCION  CANT CAJAS  UC",
      ...uxc.map((units, index) => `F${index + 100}  PRODUCTO FAVORITA ${index + 1}  15  ${units}`),
    ].join("\n");
    const lines = parseDocumentProductLines(text, []);
    expect(lines).toHaveLength(6);
    expect(lines.reduce((sum, line) => sum + (line.calculated_units ?? 0), 0)).toBe(1620);
  });

  it("reporta nueve productos y 3.582 unidades con Cantidad × UXC", () => {
    const text = [
      "CODIGO  DETALLE  CANT CAJAS  UXC",
      ...Array.from({ length: 8 }, (_, index) => `E${index + 100}  PRODUCTO ROSADO ${index + 1}  30  12`),
      "E999  PRODUCTO ROSADO NUEVE  39  18",
    ].join("\n");
    const lines = parseDocumentProductLines(text, []);
    expect(lines).toHaveLength(9);
    expect(lines.reduce((sum, line) => sum + (line.calculated_units ?? 0), 0)).toBe(3582);
  });

  it("delimita la tabla y no convierte proveedor, destino ni observaciones en productos", () => {
    const text = [
      "PROVEEDOR HOME BEAUTY S.A.",
      "COMISARIATO DESTINO",
      "ORDEN 4618111953",
      "ITEN  ARTICULO  DESCRIPCION  REFERENCIA  TAMAÑO  UXC  CANTIDAD  COSTO",
      "10  000000000040622962  CREMA DE PEINAR ANA REGENEXT 200ML  7862133169220  200ML  12  31  1.25",
      "TOTAL DE ITEMS 1",
      "OBSERVACIONES COMERCIALES",
      "FECHA 23/07/2026",
    ].join("\n");
    const lines = parseDocumentProductLines(text, products);
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatchObject({
      item_number: "10",
      chain_code: "000000000040622962",
      supplier_reference: "7862133169220",
      original_quantity: 31,
      units_per_box: 12,
      calculated_units: 372,
    });
    expect(lines[0]!.raw).not.toContain("PROVEEDOR");
    expect(lines[0]!.raw).not.toContain("COMISARIATO");
  });

  it("prioriza la referencia del proveedor en una fila reconstruida por coordenadas", () => {
    const lines = parsePositionalTableRows([{
      page: 1,
      raw: "10 000000000040622962 CREMA DE PEINAR 7862133169220 12 31",
      item_number: "10",
      chain_code: "000000000040622962",
      description: "CREMA DE PEINAR ANA REGENEXT 200ML",
      supplier_reference: "7862133169220",
      size: "200ML",
      units_per_box: 12,
      quantity: 31,
      original_unit_type: "boxes",
      bounds: { x: 20, y: 130, width: 820, height: 12 },
    }], [{ sku: "AR004", product_name: "CREMA DE PEINAR ANA REGENEXT 200 ML.", barcode: "7862133169220", units_per_box: 12 }]);
    expect(lines).toMatchObject([{
      sku: "AR004",
      detected_code: "7862133169220",
      original_quantity: 31,
      units_per_box: 12,
      calculated_units: 372,
      bounds: { x: 20, y: 130 },
    }]);
  });

  it("reconstruye por el esquema de columnas cuando OCR colapsa los espacios", () => {
    const lines = parseDocumentProductLines([
      "ITEN ARTICULO DESCRIPCION REFERENCIA TAMAÑO UXC CANTIDAD COSTO",
      "10 000000000040622962 CREMA DE PEINAR ANA REGENEXT 200ML 7862133169220 200ML 12 31 1.25",
      "TOTAL DE ITEMS 1",
    ].join("\n"), products);
    expect(lines).toMatchObject([{
      item_number: "10",
      chain_code: "000000000040622962",
      supplier_reference: "7862133169220",
      original_quantity: 31,
      units_per_box: 12,
      calculated_units: 372,
    }]);
  });
});
