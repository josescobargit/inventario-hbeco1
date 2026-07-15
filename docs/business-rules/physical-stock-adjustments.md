# Ajustes individuales de stock físico

## Flujo

1. Un usuario registra un nuevo conteo físico para un SKU y explica el motivo.
2. Si es el principal, el ajuste se aplica directamente con movimiento y auditoría.
3. Si es otro usuario, se guarda el stock y la versión observados sin cambiar inventario; el principal aprueba o rechaza.
4. La aprobación bloquea la posición y comprueba que su versión no haya cambiado.
5. Si sigue vigente, actualiza únicamente el stock físico, incrementa la versión y crea movimiento y auditoría dentro de la misma transacción.
6. Si el inventario cambió, la solicitud queda obsoleta y debe repetirse el conteo.

El principal no necesita aprobarse a sí mismo. Un rechazo no modifica ningún saldo. Reservas, facturas pendientes y bloqueos no se eliminan al ajustar el stock físico.

## API

- `GET /api/v1/stock-adjustments`
- `POST /api/v1/stock-adjustments`
- `POST /api/v1/stock-adjustments/{id}/approve`
- `POST /api/v1/stock-adjustments/{id}/reject`
