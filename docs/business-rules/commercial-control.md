# Centro de control comercial

El dashboard inicial reúne las OC y facturas operativas y los documentos comerciales cargados. El panel anterior se encuentra en **Panel operativo**. Las importaciones comerciales sirven para analizar documentos; no emiten facturas ni alteran stock, reservas o despachos.

## Flujo disponible

1. **Archivos y revisión**: cargar PDF, XLSX, CSV, PNG/JPG/WEBP/TIFF o ZIP. Se conserva el archivo, su SHA-256, texto extraído y celdas/fila/página de origen. Las copias idénticas no se importan otra vez.
2. La extracción reconoce encabezados y cabeceras explícitas, incluidas hojas Sell In/Out. Los PDF reutilizan el extractor digital/OCR existente. Los formatos dudosos requieren cotejo con el original.
3. **Abrir evidencia** muestra la conversión, datos originales y motivos de revisión. Una corrección conserva el original, aumenta la revisión y registra usuario, motivo, antes y después. Conflictos de edición devuelven 409. Una cabecera puede completarse para todo el documento, únicamente en campos vacíos.
4. **OC vs facturas** conserva cada factura que aporta unidades al pedido. **Por cadena** consolida cadena/producto. Los filtros se aplican a tablas, asistente y exportaciones.
5. **Sell In / Sell Out**, **Histórico**, **Maestro**, **Asistente** y **Reporte** comparten el mismo motor de cálculo.

## Criterios de identidad y cálculo

- Una OC se identifica por cadena y número. Las facturas se identifican por su número dentro de la empresa operativa. No se relaciona por similitud de importes.
- Los nombres se normalizan en mayúsculas/minúsculas y acentos. Crecimiento/Romero, Hidratación/Coco y Fortalecimiento/Cebolla son equivalencias de familia; se conserva el resto de la identidad (marca, tipo y contenido).
- Para packs identificados, `PACK SH + AC … 500 ML` corresponde a dos componentes de 500 ml; se admite la misma identidad como pack de 1000 ml o shampoo 500 + acondicionador 500. Deben coincidir marca/línea/variante y existir un único candidato. `pack 1000 ml` sin identidad adicional no se acepta.
- EAN/códigos/nombres contradictorios, múltiples candidatos o unidades ausentes se marcan REVISAR. Las equivalencias confirmadas por cadena existentes también se consultan. El administrador puede añadir equivalencias exactas, línea, presentación, contenido y EAN 14 al maestro.
- Cajas se convierten con el factor explícito del documento o con el del SKU identificado. Las unidades declaradas y calculadas deben coincidir. Un pack inventariable cuenta como una unidad del SKU pack; no se descompone en componentes.
- Los precios se interpretan sobre la unidad original declarada; para precio por caja se divide por unidades/caja. Se verifica subtotal contra cantidad × precio (tolerancia USD 0,02). No se adivinan descuentos, impuestos ni moneda.
- Importes netos USD. Falta de precio/moneda o conflicto monetario deja el importe sin dato; **nunca se usa costo de catálogo como precio de venta**. Excel deja la celda desconocida vacía y escribe los importes conocidos como valores numéricos.
- Diferencia = pedido − facturado. Faltante = máximo(diferencia, 0). Dinero no facturado = faltante valorado al precio neto de la OC. Las diferencias de precio de factura generan otra alerta; no se confunden con falta de unidades.
- El porcentaje individual puede exceder 100%. El cumplimiento consolidado limita lo cubierto a lo pedido en cada OC/producto: un exceso no compensa faltantes de otros productos.
- Estados de cruces confirmados: COMPLETO, PARCIAL, NO FACTURADO y EXCESO. Una factura pendiente de validar deja su cruce en REVISAR. Documentos sin identidad suficiente quedan en revisión, sin inventar una vinculación o una fecha pendiente.
- Anuladas/reemplazadas explícitas no se suman. Una referencia a reemplazo sin estado verificable de la original bloquea ambas para revisión. No se interpreta un cambio de número como prueba de reemplazo.
- Posibles duplicados entre documentos se detectan antes de filtrar fechas. Las copias importadas quedan fuera del cálculo; prevalece el registro operativo si existe. Entre varias copias importadas no se elige una arbitrariamente. Para confirmar una copia válida hay que excluir las otras con motivo y evidencia. No se suman reportes de ventas con la misma identidad, fecha, cantidad e importe en archivos distintos sin revisión.

## Períodos y alertas

La comparación toma **OC fechadas en el período y todas sus facturas hasta la fecha final**. Sin fecha final usa todo el histórico. Facturas sin OC/producto comparable se muestran como alertas y evidencia; no se incorporan silenciosamente a la cohorte de pedidos.

Sell In/Out usa las fechas de los reportes explícitos; no se deriva automáticamente Sell In de las facturas para evitar duplicar reportes cargados. Se ofrecen unidades, dólares, participación, línea, rankings y evolución semanal/mensual. La comparación de períodos arbitrarios informa diferencia y variación; si falta un período no se inventa cero. La consulta de esta semana frente a la anterior desplaza siete días ambos límites.

La comparación Sell In/Out requiere las mismas fechas disponibles para calcular una diferencia comparable. Sus conclusiones son hipótesis: no hay inventario inicial, cobertura de tiendas ni devoluciones suficientes para demostrar acumulación o falta de stock. Las caídas mensuales de Sell Out de 20% o más se alertan como variación de los registros y requieren verificar cobertura.

Objetivos iniciales visibles y ajustables en filtros: cumplimiento 95%, faltante económico USD 1.000. Alertas priorizadas: duplicados, faltantes, cumplimiento, impacto económico, diferencias de precio, caída de Sell Out y revisión de identidad, unidad, moneda, estado o relación documental.

## Asistente

Sin configuración externa, funciona un asistente analítico local para las consultas sugeridas: resumen, faltantes, anomalías, dinero, Sell In/Out y comparación semanal. No se presenta como generación libre.

Para habilitar interpretación de preguntas con IA en el backend:

```dotenv
COMMERCIAL_AI_ENABLED=true
COMMERCIAL_AI_MODEL=<modelo disponible en tu cuenta con Responses y function calling>
OPENAI_API_KEY=<credencial configurada en el entorno del servidor>
```

La integración utiliza [Responses con function calling estricto](https://developers.openai.com/api/docs/guides/function-calling). Envía pregunta, filtros y fecha actual; no envía documentos originales ni tablas de importes. El modelo elige una consulta limitada, sin SQL ni escrituras. El backend valida los argumentos y construye las respuestas con datos reales. `store=false`, timeout de 20 segundos; ante error vuelve a consultas locales e informa el modo. Las credenciales nunca se exponen al navegador. La conexión real requiere configuración; las pruebas cubren el contrato con proveedor simulado.

## Límites y validación pendiente con documentos reales

- Hasta 60 archivos, 20 MB por archivo y 60 MB descomprimidos por carga; 20.000 filas, 40 páginas por PDF. ZIP cifrado/anidado y rutas inseguras se rechazan. XLS antiguo debe convertirse a XLSX.
- La importación se procesa secuencialmente dentro de la petición, con transacción por archivo. Lotes con OCR pueden tardar; reintentar es seguro por SHA-256. No hay procesamiento comercial distribuido ni análisis ilimitado en segundo plano.
- Excel con fórmulas requiere valores exportados o revisión explícita; no se ejecutan fórmulas. Descripciones nuevas o PDF sin tablas suficientes necesitan confirmar extracción. No se promete reconocimiento universal de formatos no probados.
- Las OC operativas históricas no almacenaban precio. Su importe permanece desconocido; importar otra copia de la misma OC no sustituye automáticamente su valoración. Esa ampliación de valores históricos requiere un flujo específico de vinculación de evidencia.
- La normalización compara contra el catálogo vigente. Las correcciones y originales quedan auditados, pero no hay un cierre contable inmutable por período ni versiones de catálogo congeladas.
- Se validaron individualmente las OC reales de las ocho cadenas del ZIP. La extracción de facturas se verifica con ejemplos sintéticos aislados; falta contrastarla con facturas reales del usuario, especialmente descuentos, impuestos y formatos sin tabla. Los ejemplos sintéticos no se cargan en la base operativa.

## Verificación

`make db-validate`, `make db-schema`, `make db-check`, tests de backend/frontend, build y lint. La migración `c01a10e577f5` añade tablas comerciales con RLS y revocación de acceso web directo. `c01a10e577f6` completa esa regla en cuatro tablas de documentos/proveedores creadas por migraciones anteriores. El backend mantiene acceso usando su rol de servidor.


## Revisión por documento

La pantalla inicial permite cargar archivos, procesarlos, consultar resultados y revisar excepciones. Los filtros, cruces, histórico, maestro, asistente y reportes se conservan en Más opciones.

Los resultados se agrupan por identidad del documento, nunca por cantidades o nombre del archivo. Cada documento muestra productos encontrados y un estado: OK, REVISAR o ERROR. Las alertas iguales de una cabecera cuentan una sola vez. Los productos se consultan dentro del detalle. Después de una carga, el resumen corresponde a esa carga; los documentos anteriores siguen disponibles.

La revisión ofrece solo los campos dudosos. Las correcciones de cabecera se aplican en una única transacción a todas las líneas, comprueban sus revisiones y conservan los originales y la auditoría. Una copia duplicada puede excluirse como documento completo sin borrarla. Los documentos identificados correctamente no requieren confirmación manual. Los problemas específicos de producto se resuelven dentro del detalle.


## Arquitectura de procesamiento de OC y facturas

Procesar documentos es un módulo independiente del Dashboard gerencial. El Dashboard conserva indicadores, cumplimiento, faltantes, gráficos y Sell In/Out. Los filtros secundarios y el maestro permanecen en Más opciones.

El lector reúne el texto completo (digital u OCR), identifica la empresa, el tipo, el número y la fecha, y después analiza la tabla. INDUSTRIAL DANEC se normaliza desde su razón social/RUC; la fecha prioritaria es Fecha de Orden, nunca Fecha de Entrega. Las líneas de detalle terminan antes del subtotal.

GET /commercial/processing valida reconocimiento y datos originales. La falta de una equivalencia en el catálogo o un posible duplicado financiero no convierte una extracción correcta en incorrecta. Esas dudas siguen visibles y bloquean los totales que corresponda en el análisis comercial: el estado OK del documento no significa que su cruce o valoración estén confirmados.

Cada documento guarda la versión del lector. Volver a cargar un original con una extracción antigua ejecuta el lector vigente. Se archivan sus filas anteriores sin borrarlas y se conservan los originales y la auditoría. Las correcciones revisadas se trasladan únicamente cuando la identidad de la línea permite hacerlo de forma inequívoca.

La batería de formatos reales se ejecuta con REAL_OC_ZIP=/ruta/Archivo.zip PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/modules/commercial/test_real_order_formats.py -q. Prueba cada OC de forma independiente, incluidos los dos números de El Rosado dentro del mismo PDF, con nombres de entrada neutros.

## Flujo principal por cadena (octubre 2026)

El menú principal muestra Dashboard, Órdenes de compra, Facturación, Comparativo, Sell In / Sell Out e Historial. Procesar documentos, inventario, despachos, entregas y administración permanecen en Más opciones. Las pantallas operativas anteriores siguen disponibles dentro de Más opciones de cada módulo.

`GET /commercial/workflow` consulta la evidencia persistida y los registros operativos. No pide documentos adicionales, no emite facturas y no mueve stock. Los vínculos se calculan de forma reproducible al consultar y se mantienen al volver a abrir; una corrección cambia su resultado sin conservar enlaces obsoletos. Las revisiones explícitas de cabecera y elección de versiones quedan auditadas.

- Cada cadena contiene sus OC; el detalle muestra cantidades, valores explícitos, facturas relacionadas y cumplimiento. Desde allí se abre su factura o comparativo directamente.
- Facturación acepta varios PDF, imágenes y ZIP mediante el mismo importador existente. Una referencia explícita de OC solo se busca dentro de su cadena; si no existe, queda pendiente y no se sustituye por otra de productos/importe parecido.
- Sin referencia, exige cadena, todos los productos exactos y una única OC con fecha anterior o igual a la factura, hasta 90 días. Si dos OC cumplen, se requiere revisión. Un código exacto de la misma cadena o identidad del catálogo sirve para comparar; en ausencia de códigos solo se utiliza descripción exacta. No se usan similitudes de importes.
- Una identidad comercial (cadena, tipo, número) ocupa un solo lugar. Las copias con detalles idénticos se consolidan, sin eliminar los originales. Las copias con fecha, referencias, productos, unidades o importes diferentes bloquean el vínculo. El usuario puede consultar cada versión y elegir una; las demás se excluyen mediante correcciones auditadas, manteniendo todo el historial y control de revisión 409.
- Se acumulan todas las facturas vinculadas por OC/producto. Se conserva la base de cantidad. Cajas sin factor verificable no se comparan con unidades; las diferencias se muestran pendientes. No se rellenan valores faltantes con el costo del catálogo. El total documental, si aparece, puede incluir impuestos; los valores por producto y dinero pendiente utilizan los importes netos de detalle.
- Las importaciones comerciales se registran como evidencia para el cruce. El registro operativo de inventario continúa en las herramientas existentes; cargar documentos no realiza un descuento adicional de inventario.
- El parser `documents-v5` preserva fecha propia, número, referencia OC y destinatario de factura antes de extraer detalle; conserva precios identificados y omite subtotales como productos. Las extracciones anteriores se archivan al reprocesar, sin sobrescribir el original ni descartar correcciones que puedan trasladarse con certeza.
