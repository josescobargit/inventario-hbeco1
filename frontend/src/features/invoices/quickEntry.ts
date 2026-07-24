export interface MatchableProduct {
  id?: string;
  sku: string;
  product_name: string;
  barcode?: string | null;
  contifico_aux_code?: string | null;
  units_per_box?: number;
}

export interface QuickLine {
  id: string;
  raw: string;
  quantity: number | null;
  sku: string;
  error: string | null;
  suggestions: string[];
}

export interface QuickBlock {
  id: string;
  invoice_number: string;
  is_void: boolean;
  lines: QuickLine[];
}

export interface ProductIndex {
  products: MatchableProduct[];
  byIdentifier: Map<string, MatchableProduct[]>;
  byName: Map<string, MatchableProduct[]>;
  aliases: Map<string, string>;
}

const invoiceHeader = /^\s*FAC(?:TURA)?\s*[:#-]?\s*(\d{3}-\d{3}-\d{9})\s*$/i;
const separator = /^\s*[-–—]+\s*$/;
const quantityLine = /^\s*(\d+(?:[.,]\d+)?)\s+(.+?)\s*$/;
const ALIAS_STORAGE_KEY = "inventario.confirmed-product-aliases.v1";
let memoryAliases: Record<string, string> = {};
let sequence = 0;
const id = (prefix: string) => `${prefix}-${Date.now()}-${sequence++}`;

export function normalizeProductText(value: string): string {
  const withoutInvisible = [...value].filter((character) => {
    const code = character.codePointAt(0) ?? 0;
    return !(
      code <= 31 || (code >= 127 && code <= 159) ||
      (code >= 0x200B && code <= 0x200F) ||
      (code >= 0x202A && code <= 0x202E) ||
      code === 0x2060 || (code >= 0x2066 && code <= 0x2069) || code === 0xFEFF
    );
  }).join("");
  return withoutInvisible
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleUpperCase("es-EC")
    .replace(/[–—−]/g, "-")
    .replace(/\s*\+\s*/g, "+")
    .replace(/\s*[/|]\s*/g, "/")
    .replace(/\s*-\s*/g, "-")
    .replace(/[.,;:!?'"`´()[\]{}]/g, " ")
    .replace(/(?:[-/|]\s*)+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function loadAliases(): Map<string, string> {
  try {
    const raw = globalThis.localStorage?.getItem(ALIAS_STORAGE_KEY);
    if (raw) memoryAliases = JSON.parse(raw) as Record<string, string>;
  } catch {
    // Memory fallback keeps recognition functional in restricted/private contexts.
  }
  return new Map(Object.entries(memoryAliases));
}

export function clearConfirmedAliases(): void {
  memoryAliases = {};
  try {
    globalThis.localStorage?.removeItem(ALIAS_STORAGE_KEY);
  } catch {
    // The in-memory copy is already cleared.
  }
}

export function confirmProductAlias(rawName: string, sku: string): void {
  const normalized = normalizeProductText(rawName);
  if (!normalized || !sku) return;
  memoryAliases[normalized] = sku;
  try {
    globalThis.localStorage?.setItem(ALIAS_STORAGE_KEY, JSON.stringify(memoryAliases));
  } catch {
    // Keep the confirmed alias for the current session if storage is unavailable.
  }
}

export function applyConfirmedAlias(lines: QuickLine[], rawName: string, sku: string): QuickLine[] {
  confirmProductAlias(rawName, sku);
  const normalized = normalizeProductText(rawName);
  return lines.map((line) => normalizeProductText(line.raw) === normalized
    ? { ...line, sku, error: null, suggestions: [] } : line);
}

function addToIndex(map: Map<string, MatchableProduct[]>, key: string, product: MatchableProduct): void {
  if (!key) return;
  map.set(key, [...(map.get(key) ?? []), product]);
}

export function buildProductIndex(products: MatchableProduct[]): ProductIndex {
  const byIdentifier = new Map<string, MatchableProduct[]>();
  const byName = new Map<string, MatchableProduct[]>();
  for (const product of products) {
    addToIndex(byName, normalizeProductText(product.product_name), product);
    for (const value of [product.sku, product.barcode, product.contifico_aux_code]) {
      if (value) addToIndex(byIdentifier, normalizeProductText(value), product);
    }
  }
  const validSkus = new Set(products.map((product) => product.sku));
  const aliases = new Map(
    [...loadAliases()].filter(([, sku]) => validSkus.has(sku)),
  );
  return { products, byIdentifier, byName, aliases };
}

function identifierAtEnd(description: string, index: ProductIndex): MatchableProduct[] {
  const normalized = normalizeProductText(description);
  const matches = new Map<string, MatchableProduct>();
  for (const [identifier, products] of index.byIdentifier) {
    if (normalized === identifier || normalized.endsWith(`-${identifier}`) || normalized.endsWith(` ${identifier}`)) {
      for (const product of products) matches.set(product.sku, product);
    }
  }
  return [...matches.values()];
}

function editDistance(left: string, right: string): number {
  const previous = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
    const current = [leftIndex];
    for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
      current[rightIndex] = Math.min(
        current[rightIndex - 1]! + 1,
        previous[rightIndex]! + 1,
        previous[rightIndex - 1]! + (left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1),
      );
    }
    previous.splice(0, previous.length, ...current);
  }
  return previous[right.length]!;
}

function numericTokens(value: string): string {
  return (value.match(/\d+/g) ?? []).join("|");
}

function approximateCandidates(normalized: string, index: ProductIndex): MatchableProduct[] {
  const scored = index.products.map((product) => {
    const name = normalizeProductText(product.product_name);
    const longest = Math.max(normalized.length, name.length);
    return { product, score: longest ? 1 - editDistance(normalized, name) / longest : 0 };
  }).filter(({ product, score }) =>
    score >= 0.96 && numericTokens(normalized) === numericTokens(normalizeProductText(product.product_name)),
  ).sort((left, right) => right.score - left.score);
  if (scored.length === 1) return [scored[0]!.product];
  if (scored.length > 1 && scored[0]!.score - scored[1]!.score >= 0.05) return [scored[0]!.product];
  return scored.slice(0, 3).map(({ product }) => product);
}

export interface ProductMatch {
  sku: string;
  suggestions: string[];
  matchType: "identifier" | "name" | "alias" | "approximate" | "ambiguous" | "none";
}

export function findProduct(description: string, index: ProductIndex): ProductMatch {
  const normalized = normalizeProductText(description);
  const identifierMatches = identifierAtEnd(description, index);
  if (identifierMatches.length === 1) return { sku: identifierMatches[0]!.sku, suggestions: [], matchType: "identifier" };
  if (identifierMatches.length > 1) return { sku: "", suggestions: identifierMatches.map((item) => item.sku), matchType: "ambiguous" };

  const exact = index.byName.get(normalized) ?? [];
  if (exact.length === 1) return { sku: exact[0]!.sku, suggestions: [], matchType: "name" };
  if (exact.length > 1) return { sku: "", suggestions: exact.map((item) => item.sku), matchType: "ambiguous" };

  const alias = index.aliases.get(normalized);
  if (alias) return { sku: alias, suggestions: [], matchType: "alias" };

  const approximate = approximateCandidates(normalized, index);
  return approximate.length === 1
    ? { sku: approximate[0]!.sku, suggestions: [], matchType: "approximate" }
    : { sku: "", suggestions: approximate.map((item) => item.sku), matchType: approximate.length ? "ambiguous" : "none" };
}

export function matchProduct(description: string, products: MatchableProduct[]): string {
  return findProduct(description, buildProductIndex(products)).sku;
}

function parseQuickLineWithIndex(raw: string, index: ProductIndex): QuickLine {
  const match = raw.match(quantityLine);
  if (!match) return { id: id("line"), raw: raw.trim(), quantity: null, sku: "", error: "La línea debe iniciar con una cantidad.", suggestions: [] };
  const description = match[2]!;
  const numeric = Number(match[1]!.replace(",", "."));
  if (!Number.isInteger(numeric) || numeric <= 0) {
    return { id: id("line"), raw: description.trim(), quantity: null, sku: "", error: "La cantidad debe ser un entero positivo de unidades.", suggestions: [] };
  }
  const result = findProduct(description, index);
  const error = result.sku ? null : result.suggestions.length
    ? "Coincidencia ambigua. Revisa las sugerencias."
    : "Producto no reconocido. Selecciónalo del catálogo.";
  return { id: id("line"), raw: description.trim(), quantity: numeric, sku: result.sku, error, suggestions: result.suggestions };
}

export function parseQuickLine(raw: string, products: MatchableProduct[]): QuickLine {
  return parseQuickLineWithIndex(raw, buildProductIndex(products));
}

export function parseProductLines(value: string, products: MatchableProduct[]): QuickLine[] {
  const index = buildProductIndex(products);
  return value.split(/\r?\n/).filter((line) => line.trim() && !separator.test(line))
    .map((line) => parseQuickLineWithIndex(line, index));
}

export function retryProductRecognition(lines: QuickLine[], products: MatchableProduct[]): QuickLine[] {
  const index = buildProductIndex(products);
  return lines.map((line) => {
    if (line.sku || line.quantity == null) return line;
    const result = findProduct(line.raw, index);
    return {
      ...line,
      sku: result.sku,
      suggestions: result.suggestions,
      error: result.sku ? null : result.suggestions.length
        ? "Coincidencia ambigua. Revisa las sugerencias."
        : "Producto no reconocido. Selecciónalo del catálogo.",
    };
  });
}

export function parseInvoiceBlocks(value: string, products: MatchableProduct[]): QuickBlock[] {
  const index = buildProductIndex(products);
  const rawBlocks: Array<{ invoice_number: string; lines: string[] }> = [];
  let current: { invoice_number: string; lines: string[] } | null = null;
  for (const raw of value.split(/\r?\n/)) {
    const header = raw.match(invoiceHeader);
    if (header) {
      if (current) rawBlocks.push(current);
      current = { invoice_number: header[1]!, lines: [] };
    } else if (current && raw.trim() && !separator.test(raw)) {
      current.lines.push(raw.trim());
    }
  }
  if (current) rawBlocks.push(current);
  return rawBlocks.map((block) => {
    const explicitlyVoid = block.lines.some((line) => normalizeProductText(line) === "ANULADA");
    const productLines = block.lines.filter((line) => normalizeProductText(line) !== "ANULADA");
    return {
      id: id("block"),
      invoice_number: block.invoice_number,
      is_void: explicitlyVoid || productLines.length === 0,
      lines: productLines.map((line) => parseQuickLineWithIndex(line, index)),
    };
  });
}

export interface CustomerAlias {
  source_text: string;
  source_text_normalized?: string;
  detected_code?: string | null;
  sku: string;
}

export interface DocumentProductLine extends QuickLine {
  page: number;
  detected_code: string;
  description: string;
  unit: string;
  confidence: "high" | "medium" | "low";
  reviewed: boolean;
  original_quantity: number | null;
  original_unit_type: "boxes" | "units" | "ambiguous";
  units_per_box: number | null;
  calculated_units: number | null;
  calculation_method: "direct_units" | "document_uxc" | "catalog_uxc" | "manual";
  conversion_confirmed: boolean;
  item_number?: string | null;
  chain_code?: string | null;
  supplier_reference?: string | null;
  bounds?: { x: number; y: number; width: number; height: number } | null;
}

export interface PositionalTableRow {
  page: number;
  raw: string;
  item_number: string | null;
  chain_code: string | null;
  description: string;
  supplier_reference: string | null;
  size: string | null;
  units_per_box: number | null;
  quantity: number;
  original_unit_type: "boxes" | "units" | "ambiguous";
  bounds: { x: number; y: number; width: number; height: number };
}

const pageMarker = /^\[\[PAGE:(\d+)]]$/;
const productHeaderTerm = /\b(?:PRODUCTO|PRODUCT|ARTICULO|ARTICLE|ITEM|DESCRIPCION|DESCRIPTION|DETALLE|MERCADERIA|CODIGO|CODE|SKU|EAN|BARRAS|PROVEEDOR)\b/;
const quantityHeaderTerm = /\b(?:CANTIDAD|CANT|QTY|UNIDADES?|UDS?|SOLICITADO|PEDIDO)\b/;
const headerOrMetadata = /^(?:ORDEN(?:\s+DE\s+COMPRA)?|O\s*C|PURCHASE\s+ORDER|P\s*O|NRO?\s+(?:DE\s+)?(?:OC|PEDIDO|DOCUMENTO)|CLIENTE|CADENA|COMPRADOR|CUSTOMER|BUYER|RAZON\s+SOCIAL|FECHA|EMISION|DATE|RUC|DIRECCION|TELEFONO|CORREO|EMAIL)\b/;
const financialOrFooter = /^(?:SUBTOTAL|TOTAL(?:\s+(?:A\s+PAGAR|NETO|BRUTO|SIN\s+IVA|DE\s+ITEMS?|DE\s+PRODUCTOS?))?|IVA|IMPUESTO|DESCUENTO|PRECIO|VALOR|COSTO|PAGINA|PAGE|OBSERVACIONES?|CONDICIONES?\s+COMERCIALES?|FIRMAS?)\b/;
const units = /^(?:UN|UND|UNIDAD(?:ES)?|U|UDS?|EA|PCS?|PZA(?:S)?|CAJAS?|CJ|PACKS?|PAQ(?:UETE)?S?)$/i;

interface ParsedDocumentRow {
  raw: string;
  code: string;
  description: string;
  quantity: number | null;
  unit: string;
  unitType: "boxes" | "units" | "ambiguous";
  unitsPerBox: number | null;
  itemNumber?: string;
  chainCode?: string;
  supplierReference?: string;
}

function validQuantity(value: string): number | null {
  if (!/^\d+(?:[.,]00)?$/.test(value.trim())) return null;
  const numeric = Number(value.replace(",", "."));
  return Number.isSafeInteger(numeric) && numeric > 0 ? numeric : null;
}

function likelyCode(value: string): boolean {
  const cleaned = value.replace(/[()[\],;:]$/g, "");
  return /^(?=.{2,50}$)(?=.*\d)[A-Z0-9][A-Z0-9._/-]*$/i.test(cleaned);
}

function splitColumns(raw: string): string[] {
  return raw.split(/\t|\s{2,}|\s*\|\s*|\s*;\s*/).map((value) => value.trim()).filter(Boolean);
}

function parseColumnRow(raw: string, header: string[]): ParsedDocumentRow | null {
  const hasExplicitDescription = header.some((cell) =>
    /^(?:PRODUCTO|PRODUCT|DESCRIPCION|DESCRIPTION|DETALLE|MERCADERIA|NAME)$/.test(normalizeProductText(cell)),
  );
  const kind = (cell: string) => {
    const normalized = normalizeProductText(cell);
    if (/^(?:ITEM|ITEN)$/.test(normalized)) return hasExplicitDescription ? "item" : "description";
    if (/^(?:NRO|NO|#)$/.test(normalized)) return "item";
    if (/^(?:UC|UXC|U X C)$|UNID(?:ADES)? (?:X|POR) CAJA|UNITS PER (?:BOX|CASE)/.test(normalized)) return "units_per_box";
    if (quantityHeaderTerm.test(normalized)) return "quantity";
    if (/\b(?:UNIDAD|UOM|MEDIDA|UNIT)\b/.test(normalized)) return "unit";
    if (/^(?:REFERENCIA|REFERENCE|REF|EAN|BARRAS|CODIGO PROVEEDOR)$/.test(normalized)) return "supplier_reference";
    if (/^(?:ARTICULO|ARTICLE|CODIGO|CODE|SKU)$/.test(normalized)) return "code";
    if (/\b(?:PRODUCTO|PRODUCT|DESCRIPCION|DESCRIPTION|DETALLE|MERCADERIA|NAME)\b/.test(normalized)) return "description";
    return "other";
  };
  const kinds = header.map(kind);
  let cells = splitColumns(raw);
  const descriptionPosition = kinds.indexOf("description");
  if (cells.length < header.length && descriptionPosition >= 0 && header.length >= 3) {
    const tokens = raw.split(/\s+/).filter(Boolean);
    const leftCount = descriptionPosition;
    const rightCount = header.length - descriptionPosition - 1;
    if (tokens.length >= leftCount + rightCount + 1) {
      cells = [
        ...tokens.slice(0, leftCount),
        tokens.slice(leftCount, tokens.length - rightCount).join(" "),
        ...tokens.slice(tokens.length - rightCount),
      ];
    }
  }
  if (header.length < 2 || cells.length < 2) return null;
  const quantityIndex = kinds.indexOf("quantity");
  const descriptionIndex = kinds.indexOf("description");
  if (quantityIndex < 0 || descriptionIndex < 0 || quantityIndex >= cells.length || descriptionIndex >= cells.length) return null;
  const quantity = validQuantity(cells[quantityIndex]!);
  if (!quantity) return null;
  const codeIndex = kinds.indexOf("code");
  const referenceIndex = kinds.indexOf("supplier_reference");
  const itemIndex = kinds.indexOf("item");
  const unitIndex = kinds.indexOf("unit");
  const unitsPerBoxIndex = kinds.indexOf("units_per_box");
  const quantityHeader = normalizeProductText(header[quantityIndex]!);
  const explicitUnit = unitIndex >= 0 && unitIndex < cells.length ? cells[unitIndex]!.toUpperCase() : "";
  const unitType = /\b(?:CAJA|CAJAS|CJ|BOX|BOXES|CASE|CASES)\b/.test(quantityHeader)
    || /^(?:CAJA|CAJAS|CJ|BOX|BOXES|CASE|CASES)$/i.test(explicitUnit)
    ? "boxes"
    : /\b(?:UNID|UNIDADES|UNITS|PIEZAS)\b/.test(quantityHeader)
      || /^(?:UN|UND|UNIDAD(?:ES)?|U|UDS?|EA|PCS?|PZAS?)$/i.test(explicitUnit)
      ? "units"
      : unitsPerBoxIndex >= 0 ? "boxes" : "ambiguous";
  return {
    raw,
    code: referenceIndex >= 0 && referenceIndex < cells.length
      ? cells[referenceIndex]!
      : codeIndex >= 0 && codeIndex < cells.length ? cells[codeIndex]! : "",
    description: cells[descriptionIndex]!,
    quantity,
    unit: explicitUnit || (unitType === "boxes" ? "CAJAS" : unitType === "units" ? "UN" : ""),
    unitType,
    unitsPerBox: unitsPerBoxIndex >= 0 && unitsPerBoxIndex < cells.length
      ? validQuantity(cells[unitsPerBoxIndex]!) : null,
    itemNumber: itemIndex >= 0 && itemIndex < cells.length ? cells[itemIndex]! : "",
    chainCode: codeIndex >= 0 && codeIndex < cells.length ? cells[codeIndex]! : "",
    supplierReference: referenceIndex >= 0 && referenceIndex < cells.length ? cells[referenceIndex]! : "",
  };
}

function parseFlexibleRow(raw: string, header: string[]): ParsedDocumentRow | null {
  const columnRow = parseColumnRow(raw, header);
  if (columnRow) return columnRow;

  const tokens = raw.split(/\s+/).filter(Boolean);
  if (tokens.length < 2) return null;
  let quantityIndex = -1;
  let unit = "";
  for (let index = 0; index < tokens.length; index += 1) {
    if (validQuantity(tokens[index]!) && units.test(tokens[index + 1] ?? "")) {
      quantityIndex = index;
      unit = tokens[index + 1]!.toUpperCase();
      break;
    }
  }
  if (quantityIndex < 0 && validQuantity(tokens[0]!)) quantityIndex = 0;
  if (quantityIndex < 0 && validQuantity(tokens.at(-1)!)) quantityIndex = tokens.length - 1;
  if (quantityIndex < 0 && tokens.length > 2 && validQuantity(tokens.at(-2)!) && units.test(tokens.at(-1)!)) {
    quantityIndex = tokens.length - 2;
    unit = tokens.at(-1)!.toUpperCase();
  }
  const quantity = quantityIndex >= 0 ? validQuantity(tokens[quantityIndex]!) : null;
  if (!quantity) return null;

  const remaining = tokens.filter((_, index) =>
    index !== quantityIndex && !(index === quantityIndex + 1 && units.test(tokens[index]!)),
  );
  let code = "";
  const codeIndex = remaining.findIndex((token, index) => likelyCode(token) && (index === 0 || token.replace(/\D/g, "").length >= 8));
  if (codeIndex >= 0) code = remaining.splice(codeIndex, 1)[0]!.replace(/[()[\],;:]$/g, "");
  const description = remaining.join(" ").trim();
  if (!/[A-Za-zÁÉÍÓÚÑáéíóúñ]{2,}/.test(description)) return null;
  const unitType = /^(?:CAJA|CAJAS|CJ|BOX|BOXES|CASE|CASES)$/i.test(unit)
    ? "boxes"
    : /^(?:UN|UND|UNIDAD(?:ES)?|U|UDS?|EA|PCS?|PZA(?:S)?)$/i.test(unit)
      ? "units" : "ambiguous";
  return {
    raw, code, description, quantity, unit, unitType, unitsPerBox: null,
    itemNumber: "", chainCode: code, supplierReference: "",
  };
}

export function parseDocumentProductLines(
  text: string,
  products: MatchableProduct[],
  customerAliases: CustomerAlias[] = [],
): DocumentProductLine[] {
  const index = buildProductIndex(products);
  for (const alias of customerAliases) {
    index.aliases.set(normalizeProductText(alias.source_text), alias.sku);
    if (alias.detected_code) index.aliases.set(normalizeProductText(alias.detected_code), alias.sku);
  }
  const result: DocumentProductLine[] = [];
  let page = 1;
  let tableHeader: string[] = [];
  let inProductTable = false;
  let continuation: string[] = [];
  const documentHasHeader = text.split(/\r?\n/).some((source) => {
    const normalized = normalizeProductText(splitColumns(source).join(" "));
    return productHeaderTerm.test(normalized) && quantityHeaderTerm.test(normalized);
  });

  const append = (row: ParsedDocumentRow, originPage: number) => {
    let combinedDescription = [...continuation, row.description].join(" ").trim();
    const combinedRaw = [...continuation, row.raw].join(" ").trim();
    let detectedCode = row.supplierReference || row.chainCode || row.code;
    const leadingToken = combinedDescription.split(/\s+/)[0] ?? "";
    if (!detectedCode && likelyCode(leadingToken)) {
      detectedCode = leadingToken;
      combinedDescription = combinedDescription.slice(leadingToken.length).trim();
    }
    continuation = [];
    const chainAlias = index.aliases.get(normalizeProductText(combinedRaw))
      ?? index.aliases.get(normalizeProductText(detectedCode))
      ?? index.aliases.get(normalizeProductText(combinedDescription));
    const match = chainAlias
      ? { sku: chainAlias, suggestions: [], matchType: "alias" as const }
      : findProduct(detectedCode ? `${combinedDescription} - ${detectedCode}` : combinedDescription, index);
    const matchedConfidence = match.matchType === "identifier" || match.matchType === "name" || match.matchType === "alias"
      ? "high" : match.matchType === "approximate" ? "medium" : "low";
    const confidence = row.quantity === null ? "low" : matchedConfidence;
    const matchedProduct = products.find((product) => product.sku === match.sku);
    const unitsPerBox = row.unitsPerBox ?? matchedProduct?.units_per_box ?? null;
    const calculatedUnits = row.quantity === null
      ? null
      : row.unitType === "boxes"
        ? unitsPerBox ? row.quantity * unitsPerBox : null
        : row.quantity;
    const calculationMethod = row.unitType === "boxes"
      ? row.unitsPerBox ? "document_uxc" : unitsPerBox ? "catalog_uxc" : "manual"
      : row.unitType === "units" ? "direct_units" : "manual";
    result.push({
      id: id("document-line"),
      page: originPage,
      raw: combinedRaw,
      description: combinedDescription,
      quantity: calculatedUnits,
      sku: match.sku,
      error: row.quantity === null
        ? "Cantidad pendiente; completa la fila extraída."
        : match.sku ? null : match.suggestions.length ? "Coincidencia ambigua." : "Producto no reconocido.",
      suggestions: match.suggestions,
      detected_code: detectedCode,
      unit: row.unit,
      confidence,
      reviewed: confidence === "high" && row.quantity !== null,
      original_quantity: row.quantity,
      original_unit_type: row.unitType,
      units_per_box: unitsPerBox,
      calculated_units: calculatedUnits,
      calculation_method: calculationMethod,
      conversion_confirmed: row.unitType === "units",
      item_number: row.itemNumber || null,
      chain_code: row.chainCode || (!row.supplierReference ? detectedCode : null),
      supplier_reference: row.supplierReference || null,
      bounds: null,
    });
  };
  const flushContinuation = (originPage: number) => {
    if (!continuation.length) return;
    const raw = continuation.join(" ");
    continuation = [];
    const codeToken = raw.split(/\s+/).find(likelyCode) ?? "";
    const description = codeToken ? raw.replace(codeToken, "").trim() : raw;
    append({
      raw, code: codeToken, description, quantity: null, unit: "",
      unitType: "ambiguous", unitsPerBox: null,
      itemNumber: "", chainCode: codeToken, supplierReference: "",
    }, originPage);
  };

  for (const source of text.split(/\r?\n/)) {
    const raw = source.trim();
    const marker = raw.match(pageMarker);
    if (marker) {
      flushContinuation(page);
      page = Number(marker[1]);
      tableHeader = [];
      inProductTable = false;
      continue;
    }
    if (!raw || separator.test(raw)) continue;
    const normalized = normalizeProductText(splitColumns(raw).join(" "));
    const firstToken = raw.split(/\s+/)[0] ?? "";
    if (productHeaderTerm.test(normalized) && quantityHeaderTerm.test(normalized) && !likelyCode(firstToken) && !/\bSIN\b/.test(normalized)) {
      flushContinuation(page);
      tableHeader = splitColumns(raw);
      if (tableHeader.length === 1) tableHeader = raw.split(/\s+/).filter(Boolean);
      inProductTable = true;
      continuation = [];
      continue;
    }
    if (financialOrFooter.test(normalized)) {
      flushContinuation(page);
      inProductTable = false;
      tableHeader = [];
      continue;
    }
    if (headerOrMetadata.test(normalized)) continue;
    const parsed = inProductTable || !documentHasHeader
      ? parseFlexibleRow(raw, tableHeader)
      : null;
    if (parsed) {
      append(parsed, page);
      inProductTable = true;
      continue;
    }
    if (/\b\d+[.,]\d{1,2}\s*$/.test(raw) && !/\b(?:UN|UND|UNIDADES?|UDS?|EA|PCS?|PZAS?|CAJAS?|CJ|PACKS?|PAQUETES?)\s*$/i.test(raw)) continue;
    if (inProductTable && /[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}/.test(raw) && raw.length <= 300) {
      continuation.push(raw);
    }
  }
  flushContinuation(page);
  return result;
}

export function parsePositionalTableRows(
  rows: PositionalTableRow[],
  products: MatchableProduct[],
  customerAliases: CustomerAlias[] = [],
): DocumentProductLine[] {
  const index = buildProductIndex(products);
  for (const alias of customerAliases) {
    index.aliases.set(normalizeProductText(alias.source_text), alias.sku);
    if (alias.detected_code) index.aliases.set(normalizeProductText(alias.detected_code), alias.sku);
  }
  return rows.map((row) => {
    const aliasSku = index.aliases.get(normalizeProductText(row.chain_code ?? ""))
      ?? index.aliases.get(normalizeProductText(row.supplier_reference ?? ""))
      ?? index.aliases.get(normalizeProductText(row.description));
    const referenceMatch = row.supplier_reference
      ? findProduct(`${row.description} - ${row.supplier_reference}`, index)
      : { sku: "", suggestions: [], matchType: "none" as const };
    const chainCodeMatch = !referenceMatch.sku && row.chain_code
      ? findProduct(`${row.description} - ${row.chain_code}`, index)
      : referenceMatch;
    const match = aliasSku
      ? { sku: aliasSku, suggestions: [], matchType: "alias" as const }
      : referenceMatch.sku ? referenceMatch
      : chainCodeMatch.sku ? chainCodeMatch
      : findProduct(row.description, index);
    const product = products.find((item) => item.sku === match.sku);
    const unitsPerBox = row.units_per_box ?? product?.units_per_box ?? null;
    const calculatedUnits = row.original_unit_type === "boxes"
      ? unitsPerBox ? row.quantity * unitsPerBox : null
      : row.quantity;
    const confidence = match.matchType === "identifier" || match.matchType === "name" || match.matchType === "alias"
      ? "high" : match.matchType === "approximate" ? "medium" : "low";
    return {
      id: id("positioned-line"),
      page: row.page,
      raw: row.raw,
      detected_code: row.supplier_reference ?? row.chain_code ?? "",
      description: row.description,
      unit: row.original_unit_type === "boxes" ? "CAJAS" : row.original_unit_type === "units" ? "UN" : "",
      quantity: calculatedUnits,
      sku: match.sku,
      error: match.sku ? null : match.suggestions.length ? "Coincidencia ambigua." : "Producto no reconocido.",
      suggestions: match.suggestions,
      confidence,
      reviewed: confidence === "high",
      original_quantity: row.quantity,
      original_unit_type: row.original_unit_type,
      units_per_box: unitsPerBox,
      calculated_units: calculatedUnits,
      calculation_method: row.original_unit_type === "boxes"
        ? row.units_per_box ? "document_uxc" : unitsPerBox ? "catalog_uxc" : "manual"
        : row.original_unit_type === "units" ? "direct_units" : "manual",
      conversion_confirmed: row.original_unit_type === "units",
      item_number: row.item_number,
      chain_code: row.chain_code,
      supplier_reference: row.supplier_reference,
      bounds: row.bounds,
    };
  });
}

export function extractVisibleUnitTotal(text: string): number | null {
  const match = text.match(
    /(?:TOTAL\s+(?:DE\s+)?(?:UNIDADES|CANTIDAD)|CANTIDAD\s+TOTAL)\s*[:#-]?\s*(\d+)/i,
  );
  return match ? Number(match[1]) : null;
}
