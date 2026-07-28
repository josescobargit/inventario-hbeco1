# Diagnóstico de rendimiento de Órdenes de compra

## Medición anterior

La implementación anterior hacía una consulta para obtener las OC y llamaba
`detail()` una vez por cada resultado. Con una OC real disponible en el entorno
de medición se observaron:

- 13 consultas SQL.
- 46,1 ms de backend.
- 1.034 bytes de respuesta.
- 1 línea de producto.

Doce consultas adicionales por OC producen aproximadamente 481 consultas para
40 OC, antes de sumar consultas variables de facturas, despachos y entregas.
La causa exacta era el N+1 `list_orders -> detail(order)`.

El frontend añadía tres solicitudes iniciales y descargaba todas las OC, todos
sus detalles y todo el inventario antes de mostrar el módulo.

## Diseño corregido

- Una consulta agrupada devuelve solo resúmenes.
- Paginación por cursor con 25 o 50 OC.
- Búsqueda y filtros se ejecutan en el servidor.
- El detalle se solicita únicamente al seleccionar una OC.
- El catálogo se consulta bajo demanda con resultados limitados y cancelación
  de búsquedas anteriores.

## Pruebas reproducibles

`test_purchase_order_listing_performance.py` valida:

- 40 OC: una consulta, 25 resúmenes y respuesta menor de 10 KB.
- 1.000 OC: cursor sin duplicados.
- 10.000 OC: búsqueda habitual menor de 300 ms y respuesta acotada.

La medición de navegador se cubre con pruebas de interfaz: el primer render no
selecciona ni descarga detalles, y los combobox consultan después de una espera
de 180 ms. Las cifras reales de red pueden variar por el arranque del plan
gratuito de Render y deben distinguirse del tiempo de consulta.
