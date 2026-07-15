# Entradas y salidas generales

Una entrada representa producto que ingresa físicamente a la bodega. Una salida general representa un egreso que no está asociado a una factura ni a un cliente; los despachos continúan en su flujo independiente.

Ambas operaciones exigen fecha, responsable, documento de respaldo, motivo y al menos un producto. Pueden incluir varios SKU, se aplican dentro de una sola transacción y generan movimiento y auditoría por producto.

Las entradas aumentan únicamente el stock físico confirmado. Las salidas sólo pueden consumir disponibilidad libre y reducen únicamente el stock físico. Ninguna de las dos elimina reservas, facturas pendientes ni bloqueos por incidencias.
