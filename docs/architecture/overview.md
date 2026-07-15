# Arquitectura del sistema

## Propósito

InventarioApp controla la realidad operativa de una bodega y conserva trazabilidad. Contífico continúa emitiendo las facturas; esta aplicación compara la OC, el inventario disponible y la factura externa registrada.

## Estilo

Se utiliza un monolito modular para conservar transacciones consistentes sin introducir la complejidad de microservicios. Cada módulo contiene sus reglas, casos de uso, persistencia y API.

## Dependencias permitidas

```text
api -> application -> domain
infrastructure -> domain
```

El dominio no depende de FastAPI, SQLAlchemy ni React. Las rutas no modifican saldos directamente: llaman a un caso de uso que controla la transacción completa.

## Módulos previstos

- Identidad y sesiones.
- Catálogo.
- Inventario y movimientos.
- Conteos y ajustes.
- Órdenes de compra.
- Reservas.
- Registro de facturas externas.
- Despachos.
- Entregas.
- Incidencias.
- Devoluciones.
- Documentos relacionados.
- Auditoría y trazabilidad.

## Seguridad

El navegador solo se comunica con FastAPI. PostgreSQL no se expone al frontend. Todas las tablas de `public` tienen RLS activado y no se crean políticas para `anon` ni `authenticated`.

