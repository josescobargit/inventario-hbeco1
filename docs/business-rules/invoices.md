# Registro de facturas emitidas

InventarioApp no emite facturas. Registra documentos ya creados en Contífico con formato `001-001-000000686`.

Una factura puede relacionarse con una OC o clasificarse como venta sin OC, consumo interno, muestra, reposición u otro. Una cantidad acumulada superior a la OC o un producto ajeno se permiten para reflejar el documento real, pero generan una alerta abierta y dejan visible la diferencia.

Las reservas vinculadas a la OC se eligen manualmente. Su consumo y el aumento de `invoiced_not_dispatched` ocurren en la misma transacción. El stock físico no cambia hasta el despacho.
