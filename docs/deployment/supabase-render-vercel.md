# Despliegue con Supabase + Render + Vercel

Este despliegue separa responsabilidades:

- **Supabase**: PostgreSQL administrado.
- **Render**: API FastAPI.
- **Vercel**: frontend React/Vite.

La aplicación no factura. El despliegue mantiene el objetivo operativo: controlar inventario, trazabilidad, OC, facturas externas registradas, despachos, entregas, devoluciones y reportes.

## 1. Supabase

1. Crear un proyecto en Supabase.
2. Copiar la URL de conexión PostgreSQL.
3. Usar una URL compatible con SQLAlchemy/psycopg:

```text
postgresql+psycopg://USUARIO:CLAVE@HOST:PUERTO/BASE?sslmode=require
```

Usar esa URL en Render como:

- `DATABASE_URL`
- `MIGRATION_DATABASE_URL`

## 2. Render backend

El repo incluye `render.yaml` para crear el servicio web del backend.

Variables necesarias:

```text
ENVIRONMENT=production
PYTHON_VERSION=3.12.13
API_PREFIX=/api/v1
DATABASE_URL=postgresql+psycopg://...
MIGRATION_DATABASE_URL=postgresql+psycopg://...
COOKIE_SECURE=true
COOKIE_SAMESITE=none
SESSION_COOKIE_NAME=inventario_session
SESSION_TTL_HOURS=12
CORS_ORIGINS=["https://TU-FRONTEND.vercel.app"]
CORS_ORIGIN_REGEX=
```

Notas:

- `COOKIE_SAMESITE=none` es necesario porque Vercel y Render usan dominios distintos.
- `COOKIE_SECURE=true` es obligatorio en producción.
- `CORS_ORIGINS` debe contener la URL exacta del frontend en Vercel.
- El comando de inicio ejecuta migraciones Alembic antes de levantar FastAPI.

Comando configurado:

```bash
PYTHONPATH=backend alembic -c database/alembic.ini upgrade head && PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Después del primer deploy, verificar:

```text
https://TU-BACKEND.onrender.com/health
```

Debe responder:

```json
{"status":"ok","service":"inventario-operativo-api"}
```

## 3. Vercel frontend

Configurar Vercel apuntando al directorio `frontend`.

El repo incluye `frontend/vercel.json` con:

- `npm ci`
- `npm run build`
- salida `dist`

Variable necesaria en Vercel:

```text
VITE_API_BASE_URL=https://TU-BACKEND.onrender.com
```

No incluir `/api/v1` en esa variable. El frontend ya agrega ese prefijo automáticamente.

## 4. Primer arranque

1. Abrir el frontend en Vercel.
2. Crear el usuario principal desde la pantalla inicial si el sistema lo solicita.
3. Verificar:
   - Login/logout.
   - Catálogo.
   - Inventario.
   - Registro de OC.
   - Reservas.
   - Facturas externas.
   - Despachos/entregas.
   - Configuración.

## 5. Semilla de productos

Si la base arranca vacía, ejecutar el seed desde Render Shell o localmente apuntando a Supabase:

```bash
PYTHONPATH=backend python backend/scripts/seed_products.py
```

Antes de correrlo, confirmar que `DATABASE_URL` apunte a Supabase.

## 6. Checklist antes de producción real

- Confirmar dominio final de Vercel.
- Confirmar dominio final de Render.
- Actualizar `CORS_ORIGINS`.
- Confirmar que las cookies se guardan al hacer login.
- Crear backup/export inicial de Supabase.
- Crear usuario principal.
- Cargar catálogo/stock inicial.
- Probar un flujo completo: OC → reserva → factura externa → despacho → entrega.
