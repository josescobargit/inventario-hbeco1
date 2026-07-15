import fs from "node:fs/promises";

import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = process.argv[2];
const outputPath = process.argv[3];

if (!inputPath || !outputPath) {
  throw new Error(
    "Uso: node build_product_seed.mjs catalogo.xlsx products_seed.csv",
  );
}

const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItemAt(0);
const rows = sheet.getRange("A4:AC200").values;
const headers = rows[0];

if (!headers) throw new Error("No se encontró la fila de encabezados.");

const index = Object.fromEntries(
  headers.map((header, column) => [String(header ?? "").trim(), column]),
);
const requiredHeaders = [
  "Código",
  "Código Auxiliar",
  "Categoría",
  "Nombre",
  "Descripción",
  "Código Catálogo",
  "Tipo",
  "Inventariable",
  "Costo",
];

for (const header of requiredHeaders) {
  if (index[header] === undefined) {
    throw new Error(`Falta la columna requerida: ${header}`);
  }
}

function value(row, header) {
  return row[index[header]];
}

function text(row, header) {
  return String(value(row, header) ?? "").trim();
}

function unitsPerBox(name) {
  const normalized = name.toLocaleUpperCase("es-EC");
  if (normalized.includes("RISTRA") || normalized.includes("SACHET")) return 288;
  if (normalized.includes("PACK")) return 6;
  return 12;
}

const products = rows
  .slice(1)
  .filter(
    (row) => text(row, "Tipo") === "Producto" && text(row, "Inventariable") === "Sí",
  )
  .map((row, position) => {
    const sku = text(row, "Código");
    const name = text(row, "Nombre");
    const rawCost = value(row, "Costo");
    const cost = Number(rawCost ?? 0);

    if (!sku) throw new Error(`Producto sin SKU en la fila ${position + 5}.`);
    if (!name) throw new Error(`Producto ${sku} sin nombre.`);
    if (!Number.isFinite(cost) || cost < 0) {
      throw new Error(`Costo inválido para ${sku}: ${rawCost}`);
    }

    return {
      sku,
      name,
      description: text(row, "Descripción"),
      category: text(row, "Categoría"),
      barcode: text(row, "Código Catálogo"),
      contifico_aux_code: text(row, "Código Auxiliar"),
      cost: cost.toFixed(4),
      units_per_box: unitsPerBox(name),
      is_active: "true",
    };
  });

const duplicateSkus = products
  .map((product) => product.sku)
  .filter((sku, position, values) => values.indexOf(sku) !== position);

if (duplicateSkus.length > 0) {
  throw new Error(`SKU duplicados: ${[...new Set(duplicateSkus)].join(", ")}`);
}
if (products.length !== 29) {
  throw new Error(`Se esperaban 29 productos inventariables y se encontraron ${products.length}.`);
}

const columns = [
  "sku",
  "name",
  "description",
  "category",
  "barcode",
  "contifico_aux_code",
  "cost",
  "units_per_box",
  "is_active",
];
const escapeCsv = (inputValue) => {
  const stringValue = String(inputValue ?? "");
  return /[",\n\r]/.test(stringValue)
    ? `"${stringValue.replaceAll('"', '""')}"`
    : stringValue;
};
const csv = [
  columns.join(","),
  ...products.map((product) =>
    columns.map((column) => escapeCsv(product[column])).join(","),
  ),
].join("\n");

await fs.mkdir(new URL(".", `file://${outputPath}`).pathname, { recursive: true });
await fs.writeFile(outputPath, `${csv}\n`, "utf8");

const counts = Object.groupBy(products, (product) => product.units_per_box);
console.log(
  JSON.stringify({
    products: products.length,
    unitsPerBox: Object.fromEntries(
      Object.entries(counts).map(([key, values]) => [key, values.length]),
    ),
    ignoredOperationalStock: true,
    outputPath,
  }),
);
