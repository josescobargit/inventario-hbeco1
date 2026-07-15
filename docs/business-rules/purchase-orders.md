# Órdenes de compra

La OC registra el pedido original de una cadena, pero no reemplaza al Centro de Facturas como vista operativa principal. Su número es único dentro de cada cadena.

Cada línea guarda SKU y unidades pedidas. La consulta compara en tiempo real lo pedido con la disponibilidad operativa y muestra cantidad sugerida para facturar, faltante y condición completa o incompleta. Esta sugerencia no emite una factura ni modifica inventario.

## API

- `GET /api/v1/purchase-orders`
- `GET /api/v1/purchase-orders/{id}`
- `POST /api/v1/purchase-orders`
