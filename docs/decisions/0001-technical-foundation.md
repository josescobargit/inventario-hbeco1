# ADR 0001: Base técnica

Estado: aceptada.

## Decisión

Usar FastAPI, Python 3.12, SQLAlchemy 2, Alembic, PostgreSQL, React y TypeScript en un monolito modular.

## Motivos

- Las operaciones de inventario necesitan transacciones fuertes.
- PostgreSQL permite bloqueo y validación de concurrencia.
- FastAPI conserva las reglas y credenciales fuera del navegador.
- React y TypeScript permiten dividir una interfaz operativa creciente por funcionalidades.

## Consecuencias

- Python 3.9 no está soportado por la versión actual de FastAPI.
- El entorno local requiere Python 3.12 y PostgreSQL.
- No se incorporarán microservicios salvo que exista una necesidad operativa demostrable.

