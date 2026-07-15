# ADR 0003: Separar despacho y entrega

Estado: aceptada.

## Decisión

`Despachado` significa que el producto salió de la bodega. `Entregado` significa que llegó al centro de distribución del cliente.

Como no siempre existe confirmación formal, se distinguirán:

- pendiente de entrega;
- entrega sin novedad;
- entrega confirmada;
- entrega con novedad.

La ausencia de noticias no se convertirá automáticamente en una confirmación documental.
