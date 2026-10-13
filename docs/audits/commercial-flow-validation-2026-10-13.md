# Validación del flujo comercial en localhost

Alcance: OC → factura → comparativo → Dashboard → reporte semanal. No se añadieron módulos del menú ni se publicó esta versión en producción.

## Un solo cálculo

`saved_evidence` conserva originales, normalización y dudas del catálogo. `build_workflow` identifica documentos comerciales, consolida copias equivalentes, relaciona facturas y acumula sus productos. `build_commercial_summary` consume ese mismo comparativo para Dashboard, reporte semanal, análisis por períodos y exportaciones.

El reporte usa el período aplicado. Sin fechas utiliza la semana actual hasta hoy en America/Guayaquil. Las OC forman la cohorte por su fecha; se consideran sus facturas hasta la fecha final. Una factura posterior no se incorpora antes del corte.

Los excesos se muestran por producto. El cumplimiento consolidado limita la cobertura a lo pedido en cada producto. Las facturas distintas de una misma OC se acumulan; la pertenencia a la OC no constituye duplicidad.

## Documentos reales

El ZIP original se probó OC por OC, incluyendo las dos OC dentro de un PDF de El Rosado y su imagen de referencia. Las 11 verificaciones de reconocimiento cubren las ocho cadenas. Los archivos se mantienen fuera del repositorio.

Se procesaron individualmente las 211 facturas `FAC*.pdf` autorizadas en Descargas, con nombres de entrada neutros. Se verifican encabezado del comprador, fecha de emisión, número, productos, cantidades, precios, descuentos, subtotal, IVA y total contra el texto del documento y su coherencia aritmética. Estas pruebas no certifican la vigencia administrativa externa de una factura; el estado depende de evidencia explícita o revisión auditada.

También se probaron estos pares reales a través de la API de importación y consulta, en bases aisladas de pruebas:

| Cadena | OC | Facturas | Productos de la OC | Resultado observado |
|---|---|---|---:|---|
| INDUSTRIAL DANEC | 26003023 | 001-001-000001016 | 4 | 1.248 unidades pedidas y facturadas; COMPLETO |
| CORPORACIÓN FAVORITA | 100625388996 | 001-001-000001009 | 13 | 5.460 de 7.680 unidades facturadas; tres productos no facturados |
| CORPORACIÓN EL ROSADO | 4617985918 | 001-001-000000707 | 12 | Completo, parcial y no facturado por producto; el mismo PDF conserva separadamente la OC 4617985914 |
| TUTI | 4500360076 | 001-001-000000915 y 001-001-000000916 | 3 | Ambas facturas acumuladas; excesos y un producto adicional explícitos, sin decidir que una es duplicada |
| TIA | 3000949552 | 001-001-000000820 | 4 | 804 unidades pedidas y facturadas; COMPLETO |
| LIRIS DEL PORTAL | OC_005884445 | 001-001-000000913 | 3 | 48 unidades pedidas y facturadas; COMPLETO |
| FARCOMED | 6974083 | 001-001-000000978 | 2 | 96 unidades pedidas y facturadas; COMPLETO |
| GERARDO ORTIZ | 5601886574 / referencia CP143221 | 001-001-000001107 | 6 | 60 de 66 unidades facturadas; pack Coco pendiente de 6 unidades |

Las equivalencias exactas de códigos DANEC y TUTI quedan documentadas por cadena en `customer_profiles.json`. Se cotejaron tipo, marca y contenido de los productos; no se decidió una equivalencia mediante cantidades ni importes similares. El alias numérico de LIRIS conserva los ceros y solo elimina la etiqueta `OC_` para buscar dentro de esa cadena. GERARDO conserva el número Ped. Compra y su referencia alfanumérica secundaria.

## Correcciones encontradas con la prueba real

- Comprador identificado desde Razón Social / RUC del destinatario, separado del emisor.
- Fecha de emisión separada de fecha de autorización y fecha de OC.
- Productos de factura envueltos en varias líneas conservados individualmente.
- Descuentos y valores netos separados de IVA y total documental.
- EAN de El Rosado completados desde su continuación impresa; líneas 100, 110 y 120 incluidas.
- Pie de página de TIA excluido del detalle; cuatro productos reales conservados.
- Precio unitario de TIA reconocido sobre unidades aunque la cantidad se presente en cajas.
- Importe de LIRIS separado de la fecha de vencimiento impresa en la siguiente columna.
- Páginas finales realmente vacías omitidas sin intentar OCR.
- Totales de factura válidos conservados aunque falte moneda o precio en la OC.
- Copias antiguas de DANEC releídas con el parser vigente y consolidadas al comprobar su equivalencia; originales y auditoría conservados.

## Prueba visible en localhost

Se cargó únicamente la factura DANEC 001-001-000001016 y se actualizó su OC de prueba. La pantalla confirma una OC, una factura vinculada por número explícito, cuatro productos, cero excepciones y cumplimiento 100%.

El reporte del 14/09/2026 al 20/09/2026 muestra 1.248 unidades pedidas, 1.248 facturadas, cero faltantes, valor neto pedido/facturado USD 5.218,08 y dinero no facturado USD 0. El total de factura con IVA es USD 6.000,79; no se usa ese total tributario como valor neto del comparativo.

## Límites que permanecen explícitos

La moneda de algunas OC no está indicada de forma verificable. Su valoración permanece pendiente, conservando cantidades, productos y valores de sus facturas. No se completa con costos del catálogo ni por asumir USD.

Las pruebas de anulaciones, reemplazos contradictorios, descuentos y versiones conflictivas incluyen casos de regresión controlados. No se decide entre facturas reales contradictorias sin evidencia de estado. Los reportes no representan pérdidas contables definitivas: muestran dinero pendiente al precio neto de la OC.

## Repetir las pruebas

```bash
REAL_OC_ZIP=/ruta/Archivo.zip REAL_INVOICE_DIR=/ruta/Descargas PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/modules/commercial -q
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
cd frontend
npm test -- --run
npm run build
npm run lint
```

Las pruebas usan bases aisladas; no cargan las 211 facturas ni datos sintéticos en el inventario local o de producción.
