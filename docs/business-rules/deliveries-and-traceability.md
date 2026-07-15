# Entregas y trazabilidad

La entrega al centro de distribución se registra separada del despacho. Puede quedar como entrega sin novedad, confirmada o con novedad; esta última abre una incidencia.

Un faltante puede resolverse como producto encontrado y disponible, reintento de despacho o faltante físico confirmado. Cada decisión transforma los saldos bloqueado, físico y pendiente de despacho de manera explícita.

`GET /api/v1/invoices/{id}/traceability` reúne factura, OC, cantidades facturadas, despachadas, faltantes, pendientes, entregas, alertas e incidencias manteniendo estados separados.
