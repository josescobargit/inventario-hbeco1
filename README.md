# InventarioApp

Sistema de control y visualización del inventario operativo, con trazabilidad desde la orden de compra hasta el despacho, la entrega y las devoluciones.

El sistema **no emite facturas**. Ayuda a determinar qué puede facturarse y registra posteriormente las facturas emitidas en Contífico.

## Arquitectura

- Backend: FastAPI y Python 3.12.
- Frontend: React 19, TypeScript y Vite.
- Base de datos: PostgreSQL 17.
- Migraciones: Alembic.
- Acceso a datos: SQLAlchemy 2.

La aplicación se construye como un monolito modular. Las reglas de cada área viven en `backend/app/modules` y el frontend se organiza por funcionalidades en `frontend/src/features`.

## Desarrollo local

Requisitos:

- Python 3.12 o superior.
- Node.js 22.12 o superior.
- Docker con Compose, o una instancia PostgreSQL equivalente.

Preparación:

```bash
cp .env.example .env
make setup
make db-up
make db-schema
make db-seed
make test
```

Ejecución, en dos terminales:

```bash
make backend
make frontend
```

- Interfaz: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8000`
- Documentación API: `http://127.0.0.1:8000/docs`

## Validaciones obligatorias

Antes de cerrar un cambio de base de datos:

```bash
make db-validate
make test
make db-schema
make db-check
```

`db-check` verifica, entre otras cosas, que todas las tablas de `public` tengan RLS y que los roles web de Supabase no posean acceso directo.

## Catálogo inicial

La semilla contiene 29 productos inventariables tomados del catálogo de Contífico:

- 21 productos con 12 unidades por caja.
- 6 packs con 6 unidades por caja.
- 2 ristras con 288 unidades por caja.

`make db-seed` crea o actualiza el catálogo y garantiza una posición de inventario por producto. Nunca copia la columna de stock de Contífico: todas las posiciones empiezan en cero hasta aprobar un conteo físico.

## Regla central

```text
Disponible para facturar =
Stock físico confirmado
- Reservado
- Facturado no despachado
- Bloqueado por incidencia
```

La disponibilidad es un valor calculado. Nunca se introduce ni modifica manualmente.

## Ajustes de stock físico

El principal aplica ajustes individuales directamente, siempre con motivo, movimiento y auditoría. Los demás usuarios generan solicitudes aprobables. La aprobación actualiza únicamente el stock físico y conserva reservas, facturas pendientes y bloqueos. Si la posición cambió durante la espera, la solicitud queda obsoleta.

## Entradas y salidas generales

Las entradas y salidas generales registran movimientos físicos con fecha, responsable, documento y motivo. Una salida sólo puede consumir disponibilidad libre; nunca toma unidades reservadas, facturadas pendientes o bloqueadas. Los despachos a clientes permanecen separados y vinculados a sus facturas.
