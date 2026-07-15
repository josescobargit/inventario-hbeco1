# Vista previa de conteo masivo

El flujo permite descargar una plantilla CSV UTF-8 con los 29 productos y cargarla como CSV o XLSX para revisión sin modificar inventario.

La vista previa valida encabezados, tamaño máximo de 5 MB, SKU vacíos, desconocidos, duplicados o faltantes y cantidades que no sean enteros mayores o iguales a cero. Cada error informa fila, columna, SKU y corrección esperada.

Cuando el archivo es válido devuelve stock actual, conteo, diferencia y versión de cada posición. Al confirmar, el principal lo aplica directamente; otro usuario crea una solicitud pendiente. Aprobar bloquea y valida las 29 posiciones y aplica todo o nada. Rechazar no modifica inventario.
