# Reservas

Una reserva compromete disponibilidad sin reducir el stock físico. Puede relacionarse con cliente, referencia de OC, vendedor, pedido pendiente o motivo operativo y puede incluir varios productos.

La creación bloquea las posiciones, valida disponibilidad y aumenta `reserved` dentro de una sola transacción. No existe vencimiento automático.

La liberación exige motivo, devuelve únicamente la cantidad pendiente al disponible y registra movimientos y auditoría. Las líneas conservan cantidad original y cantidad restante para permitir su consumo parcial cuando se implemente el registro de facturas.

## API

- `GET /api/v1/reservations`
- `POST /api/v1/reservations`
- `POST /api/v1/reservations/{id}/release`
