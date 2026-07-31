# Billing — Postgres (canónico)

Capa **transaccional** del negocio: clientes dados de alta desde **`auto-venta1`**, consumidos por **`frontend/backend`** para JWT (`cedula`, `clave_acceso`, `plan`, `fecha_vencimiento`).

## Arranque local (Docker)

```powershell
cd infra\billing
Copy-Item .env.example .env
# Editá .env y cambiá NORDIK_PG_PASSWORD

docker compose --env-file .env up -d
```

Primera vez, Postgres crea la DB y ejecuta **`schema.sql`**. Si el volumen ya existía vacío pero sin las tablas, o cambiás el DDL: bajá con volúmenes y subí de nuevo (**borra datos**):

```powershell
docker compose --env-file .env down -v
docker compose --env-file .env up -d
```

## Variables en `frontend/backend/.env`

```env
DATABASE_URL=postgresql+psycopg://nordik:TU_PASSWORD@127.0.0.1:5432/nordik_billing
JWT_SECRET=<generada>
```

Aplicá tablas también con ORM si preferís reproduccionar código (útiles SQLite/local):

Desde **`frontend`**:

```bash
npm run backend:db-init
```

SQLite de prueba (`sqlite+pysqlite:///./venta-local.sqlite`): el script usa **`create_all`**; no ejecuta Extension `pgcrypto` innecesaria.

## Alta de datos

Usá **`auto-venta1`** contra esta misma **`DATABASE_URL`**. Sin filas → login del producto responde 401 hasta que exista cliente.

Opcionalmente copiá y adaptá **`seed.development.example.sql`** en psql/pgAdmin sólo para pruebas locales (no usar en prod).

---

# Firebase — Firestore (canónico de perfil / integraciones)

**No guarda cobros ni estado de suscripción origen.** Eso permanece en **Postgres**. Firestore lleva:

| Colección / doc | Rol |
|-----------------|-----|
| `users/{cliente_uuid}` | Perfil onboarding: nombre preferido, canal, proveedor IA, integraciones declaradas (`merge`). `cliente_uuid` = `sub` del JWT = `clientes_suscripcion.id`. |
| `user_google_tokens/{cliente_uuid}` | Blob cifrado con refresh/consentimiento Google (solo backend Admin SDK). |
| `oauth_google_pending/{state}` | Estado efímero del flujo OAuth (léase y se borra al callback). |

Reglas cliente: **`frontend/backend/firestore.rules`** (denegar lectura/escritura públicas; sólo servidor). Despliegue:

```bash
cd frontend/backend
firebase login
firebase deploy --only firestore:rules --project TU_PROJECT_ID
```

Índices compuestos (cuando filtres por campo + orden): declaralos en **`firestore.indexes.json`** mismo directorio que `firebase.json`, luego:

```bash
firebase deploy --only firestore:indexes --project TU_PROJECT_ID
```

Servicio de cuenta: **`firebase-service-account.json`** en backend (referencia `FIREBASE_SERVICE_ACCOUNT_PATH`); nunca commit.
