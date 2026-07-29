# Diagnóstico HTTP 405 del Centro de Facturas

Fecha de reproducción: 2026-07-29, zona `America/Guayaquil`.

## Solicitud que fallaba

- URL: `https://inventario-hbeco1.vercel.app/api/v1/invoices/listing?page=1&page_size=25&sort=sequence`
- Método: `GET`
- Parámetros:
  - `page=1`
  - `page_size=25`
  - `sort=sequence`
- Cuerpo enviado: ninguno.
- Código recibido: `405 Method Not Allowed`.
- Encabezado `Allow`: `PUT`.
- Respuesta: `{"detail":"Method Not Allowed"}`.

## Preflight

La solicitud `OPTIONS` al backend para el mismo endpoint respondió `200`.
Permitió `GET, POST, PATCH, PUT, DELETE`, las credenciales y el origen de
Vercel. El problema no era CORS ni el preflight.

## Versiones desplegadas observadas

- Frontend: paquete público `/assets/index-CulRNGwM.js`, que contiene llamadas
  de solo lectura a `/invoices/listing` y `/invoices/inventory-audit`.
- Backend Render: `27476cd9265a`, informado por `/health`.

El backend `27476cd9265a` no incluía todavía la ruta estática
`GET /api/v1/invoices/listing`. FastAPI interpretó `listing` como el parámetro
`invoice_id` de la ruta dinámica `PUT /api/v1/invoices/{invoice_id}`. Por eso
respondió `405` y anunció únicamente `Allow: PUT`.

## Corrección

- El listado usa explícitamente `GET /api/v1/invoices/listing`.
- Pendientes usa explícitamente `GET /api/v1/invoices/inventory-pending`.
- La auditoría usa explícitamente `GET /api/v1/invoices/inventory-audit`.
- Los filtros viajan exclusivamente en la cadena de consulta.
- Se agregaron pruebas que comparan las rutas utilizadas por el frontend con
  el OpenAPI real y fallan si `GET` deja de estar permitido.
- La interfaz convierte errores HTTP del listado en un estado recuperable con
  el mensaje `No se pudieron cargar las facturas.` y una acción `Reintentar`.
- Frontend y backend deben desplegar el mismo commit. En este repositorio,
  Vercel sigue `main`, mientras el servicio Render observado estaba siguiendo
  una revisión anterior de la rama de trabajo.
