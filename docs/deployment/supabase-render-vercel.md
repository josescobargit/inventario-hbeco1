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

- `COOKIE_SAMESITE=none` permite clientes que acceden directamente entre dominios. El frontend publicado usa el proxy del mismo dominio de Vercel.
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

La API publicada se accede mediante `/api/v1` en el dominio del frontend. `frontend/vercel.json` reenvía esas solicitudes a Render, conservando las cookies de sesión en el dominio de Vercel. Si se cambia el backend, actualizar el destino del rewrite.

Variable opcional para desarrollo local:

```text
VITE_API_BASE_URL=https://TU-BACKEND.onrender.com
```

No incluir `/api/v1` en esa variable. El frontend ya agrega ese prefijo automáticamente. En la web publicada se usa el proxy del mismo dominio, incluso si esa variable existe.

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

## 7. Diagnóstico y recuperación del administrador

Localhost y producción son bases independientes. Crear o cambiar una cuenta local no modifica la cuenta publicada. No copiar la base local sobre producción para resolver un acceso.

1. Consultar `/api/v1/auth/bootstrap-status` desde el dominio publicado. `required: false` confirma que la base responde y contiene al menos un usuario; no demuestra que una contraseña sea correcta.
2. Probar el acceso con las credenciales de producción. Un 401 indica usuario, contraseña o estado de cuenta inválido; un error de conexión no debe interpretarse como base vacía ni mostrar creación de administrador.
3. Un acceso correcto debe emitir la cookie y permitir `/api/v1/auth/me` usando esa misma sesión.
4. Si se necesita recuperar la cuenta, hacerlo desde un entorno privado con acceso autorizado a la base. El script siguiente solo lista usuarios cuando no se indica `--username`:

```bash
PYTHONPATH=backend python backend/scripts/recover_admin_access.py --expected-host HOST_REAL_DE_LA_BASE
```

Para cambiar la contraseña de un administrador existente y activo:

```bash
PYTHONPATH=backend python backend/scripts/recover_admin_access.py --expected-host HOST_REAL_DE_LA_BASE --username USUARIO_REAL --reason "Recuperación autorizada del acceso"
```

La clave se pide dos veces en una terminal interactiva, sin imprimirse ni pasarse por argumentos. La operación revoca sesiones previas y deja auditoría. No crea cuentas, reactiva usuarios, cambia roles ni ofrece un endpoint público de recuperación. El host esperado evita ejecutar por error contra localhost. El plan gratuito de Render no proporciona Shell; se requiere un entorno privado con la conexión autorizada a Supabase.

Tras cualquier deploy, confirmar el commit activo en ambos servicios: un push a GitHub no demuestra por sí solo que Render y Vercel estén ejecutando esa versión.
