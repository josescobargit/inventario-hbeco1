# Catálogo inicial

## Fuente

El catálogo se extrajo de `PRODUCTOS HOME .xlsx`, exportado desde Contífico.

Se incluyen únicamente registros cuyo tipo sea `Producto` y que estén marcados como inventariables. Esto produce 29 productos. Los registros de servicio o no inventariables quedan fuera.

## Campos conservados

- SKU.
- Código auxiliar de Contífico.
- Categoría.
- Nombre y descripción.
- Código de catálogo o barras.
- Costo.
- Unidades por caja.
- Estado activo.

## Stock

La columna `Stock` del archivo fuente se ignora deliberadamente. Al cargar la semilla, el stock físico, reservado, facturado pendiente y bloqueado comienzan en cero.

## Unidades por caja

- Nombre con `RISTRA` o `SACHET`: 288.
- Nombre con `PACK`: 6.
- Cualquier otro producto: 12.

Resultado validado: 21 productos con UXC 12, 6 con UXC 6 y 2 con UXC 288.
