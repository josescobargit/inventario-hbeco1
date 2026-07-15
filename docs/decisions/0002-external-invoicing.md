# ADR 0002: La aplicación no factura

Estado: aceptada.

## Decisión

Las facturas se emiten en Contífico. InventarioApp recomienda cantidades facturables y registra una factura externa después de emitirla.

La interfaz utilizará expresiones como `Registrar factura emitida` y evitará acciones llamadas `Crear factura` o `Facturar`.

## Excepciones

Se podrán registrar operaciones sin OC con una categoría y motivo explícitos. Los productos ajenos a una OC se permitirán únicamente con confirmación e incidencia. Un acumulado superior a lo pedido quedará bloqueado con una explicación detallada.

