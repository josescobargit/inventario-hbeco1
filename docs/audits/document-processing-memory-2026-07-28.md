# Auditoría de memoria del procesamiento de documentos

Fecha: 2026-07-28
Servicio: `inventario-operativo-api`

## Diagnóstico

El agotamiento no era causado por el tamaño almacenado de los archivos. La ruta
anterior acumulaba varias copias del documento y, para OCR, creaba una imagen PNG,
una imagen PIL, arreglos RGB y tres modelos ONNX de RapidOCR dentro del proceso web.
Cada solicitud podía hacerlo sin un límite global de concurrencia.

Mediciones locales del mismo flujo con los documentos reales:

| Documento | Método anterior | Pico RSS (proceso + hijos) |
|---|---|---:|
| OC Favorita JPG | RapidOCR/ONNX | 848,248,832 bytes |
| OC Rosado JPG | RapidOCR/ONNX | 742,768,640 bytes |
| OC Favorita JPG, segunda medición | RapidOCR/ONNX | 1,252,179,968 bytes |

El plan gratuito de Render dispone de 512 MB. Por tanto, una sola ejecución OCR
podía superar el límite, aun sin solicitudes simultáneas. RapidOCR además conservaba
memoria nativa fuera del heap de Python; por eso el heap no explicaba el RSS.

No se dispone desde este entorno de una sesión autenticada al panel de Render para
recuperar el RSS exacto y el timestamp del reinicio histórico. No se inventó ese
dato. La nueva instrumentación registra RSS, heap opcional, etapa, duración,
trabajos activos y pendientes para correlacionar futuros eventos sin incluir el
nombre completo del archivo en los logs.

Referencias de plataforma:

- [Planes y memoria de Render](https://render.com/docs/compute-plans)
- [Métricas de servicio](https://render.com/docs/service-metrics)
- [RSS en streams de métricas](https://render.com/docs/metrics-streams)
- [Sistema de archivos efímero en servicios gratuitos](https://render.com/docs/free)
- [Herramientas del sistema y uso de Docker](https://render.com/docs/native-runtimes)

## Corrección aplicada

- Los uploads se copian al disco temporal en bloques de 1 MB mientras se calcula
  SHA-256; ya no se cargan completos en RAM.
- Se valida tipo, 15 MB máximo, PDF de 1 a 50 páginas e imágenes de hasta 30
  millones de píxeles antes de encolar.
- Los PDF digitales usan texto embebido y no inicializan OCR.
- Los PDF mixtos se procesan página por página y solo se rasteriza la página que
  no tiene texto útil.
- Cuando un PDF escaneado contiene una imagen principal, se procesa esa imagen
  directamente para no rasterizar una página completa y perder resolución.
- Las imágenes se normalizan a un máximo de 1.800 píxeles, en escala de grises.
- Las líneas largas de tablas se eliminan antes del OCR; UxC se recupera con una
  segunda pasada numérica acotada cuando el OCR general confunde `12` con letras.
- Render usa una imagen Docker con Tesseract (`spa+eng`). Se eliminó
  `rapidocr-onnxruntime` de producción.
- El OCR se ejecuta en un subproceso con timeout de 120 segundos. El subproceso se
  termina al finalizar o cancelar, devolviendo inmediatamente su memoria al SO.
- Existe una sola ranura global de OCR y dos para documentos digitales.
- Los trabajos son persistentes: `pending`, `processing`, `review`, `error` o
  `cancelled`, con progreso consultable por solicitudes cortas.
- Los temporales siempre se eliminan en éxito, error, timeout o cancelación. Los
  resultados antiguos se purgan a las 24 horas.
- Reintentar el mismo hash por usuario y tipo reutiliza el trabajo existente y no
  crea procesamiento duplicado.

## Verificación bajo 512 MB

La imagen Docker final se ejecutó con `--memory=512m`.

| Documento | Método | Pico RSS | RSS después | Filas |
|---|---|---:|---:|---:|
| Factura 57409 | texto PDF | 87,298,048 | 87,851,008 | 7 |
| Factura 57453 | texto PDF | 87,867,392 | 87,863,296 | 5 |
| Factura 57458 | texto PDF | 87,867,392 | 87,863,296 | 1 |
| OC Favorita JPG | Tesseract | 204,140,544 | 79,265,792 | 1 |
| OC Rosado JPG | Tesseract | 205,422,592 | 79,278,080 | 5 |
| OC Rosado PDF escaneado | Tesseract | 207,532,032 | 82,677,760 | 4 |

Los seis PDF históricos produjeron respectivamente `4, 4, 6, 4, 9, 16`
líneas: 43 en total. El pico permanece por debajo de 512 MB y el RSS vuelve al
nivel base después de cada subproceso OCR.

## Operación y alertas

El endpoint autenticado `GET /api/v1/document-jobs/metrics/current` expone cola,
trabajos activos y una instantánea de memoria. Los logs JSON usan el evento
`document_memory` y etapas como `uploads_queued`, `ocr_start`, `ocr_end`,
`pdf_page_ocr_complete` y `job_processing_error`.

Alertas recomendadas:

- advertencia sostenida al 70 % de RAM;
- crítica al 85 %;
- cola OCR pendiente durante más de 5 minutos;
- cualquier timeout o reinicio mientras un trabajo está `processing`.

Subir el plan solo sería justificable por volumen sostenido o tiempos de espera,
no para ocultar una ejecución individual que exceda el límite.
