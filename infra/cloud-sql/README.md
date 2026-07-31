# Cloud SQL Migration Guide

Guía para migrar la base de datos PostgreSQL de Nordik-IA a Google Cloud SQL.

## Prerequisites

- **gcloud SDK** instalado y autenticado (`gcloud auth login`)
- **Cloud SQL Proxy** para acceso local a la instancia Cloud SQL
- **PostgreSQL client tools** (`pg_dump`, `pg_restore`, `psql`) v14+
- Permisos IAM: `cloudsql.client`, `cloudsql.instanceUser` sobre la instancia destino

### Verificar prerrequisitos

```bash
gcloud --version                                   # ≥ 400.0.0
pg_dump --version                                  # ≥ 14.0
```

## Step-by-Step Migration Procedure

### 1. Iniciar Cloud SQL Proxy

El proxy crea un túnel seguro desde tu máquina local a Cloud SQL sin necesidad de IP pública.

```bash
# Descargar Cloud SQL Proxy (primera vez)
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.15.2/cloud-sql-proxy.darwin.amd64

chmod +x cloud-sql-proxy

# Iniciar el proxy (reemplaza con tu connection name real)
./cloud-sql-proxy nordik-prod:us-central1:nordik-db --port 5433 &
```

El proxy escucha en `127.0.0.1:5433`. Úsalo como `TARGET_DB_HOST`.

### 2. Preparar variables de entorno

Crea un archivo `.env.migration` (NO comitear):

```bash
# Source (PostgreSQL actual)
export SOURCE_DB_HOST="192.168.1.100"
export SOURCE_DB_USER="nordik_admin"
export SOURCE_DB_PASS="..."
export SOURCE_DB_NAME="nordikdb"

# Target (Cloud SQL via proxy)
export TARGET_DB_HOST="127.0.0.1"
export TARGET_DB_PORT="5433"
export TARGET_DB_USER="postgres"
export TARGET_DB_PASS="..."
export TARGET_DB_NAME="nordikdb"
```

Cárgalas en tu shell:

```bash
source .env.migration
```

### 3. Ejecutar migración

```bash
# Modo estándar (4 jobs paralelos)
bash migrate.sh

# Modo conservador (1 job, útil si hay constraints complejas)
PGRESTORE_JOBS=1 bash migrate.sh

# Con directorio de dumps personalizado
DUMP_DIR=/tmp/nordik-dumps bash migrate.sh
```

### 4. Verificar resultado

El script valida automáticamente los row counts de las tablas clave. Revisa la salida final.

Adicionalmente, ejecuta el verification checklist manual.

## Rollback Procedure

Si la migración falla o se detectan inconsistencias:

### Opción A — Restaurar desde dump (el source sigue intacto)

1. Detén el tráfico hacia Cloud SQL
2. Vuelve a apuntar la app a la base de datos source original
3. No se requiere acción adicional — el source no fue modificado

### Opción B — Si Cloud SQL ya está recibiendo tráfico y hay que migrar de vuelta

Invierte las variables y ejecuta de nuevo:

```bash
# Intercambia source y target
export SOURCE_DB_HOST="127.0.0.1"       # Cloud SQL (era target)
export SOURCE_DB_USER="postgres"
export SOURCE_DB_PASS="..."
export SOURCE_DB_NAME="nordikdb"

export TARGET_DB_HOST="192.168.1.100"   # PostgreSQL original (era source)
export TARGET_DB_USER="nordik_admin"
export TARGET_DB_PASS="..."
export TARGET_DB_NAME="nordikdb"

bash migrate.sh
```

## Verification Checklist

Después de migrar, verifica manualmente:

- [ ] **Conectividad**: la app se conecta a Cloud SQL sin errores
- [ ] **Auth**: login funciona con credenciales existentes (bcrypt hashes intactos)
- [ ] **Tokens**: JWT refresh tokens se validan correctamente
- [ ] **Suscripciones**: `clientes_suscripcion` tiene todas las filas
- [ ] **Outbox**: `subscription_reminder_outbox` contiene los recordatorios pendientes
- [ ] **Secuencias**: los valores `nextval` de todas las secuencias son correctos:

  ```sql
  SELECT schemaname, sequencename, last_value
  FROM pg_sequences
  WHERE schemaname = 'public'
  ORDER BY sequencename;
  ```

- [ ] **Índices**: todos los índices se recrearon:

  ```sql
  SELECT schemaname, tablename, indexname
  FROM pg_indexes
  WHERE schemaname = 'public'
  ORDER BY tablename, indexname;
  ```

- [ ] **Extensiones**: las extensiones requeridas están instaladas:

  ```sql
  SELECT * FROM pg_extension;
  ```

  Extensiones esperadas: `pgcrypto` (para bcrypt)

- [ ] **Permisos**: los grants de tablas son correctos

## Troubleshooting

| Error | Causa probable | Solución |
|-------|---------------|----------|
| `FATAL: password authentication failed` | Credenciales incorrectas en TARGET | Verifica la contraseña Cloud SQL en GCP Console |
| `could not connect to server` | Proxy no iniciado o puerto incorrecto | Verifica `TARGET_DB_HOST` y que el proxy esté corriendo |
| `role "X" does not exist` | Usuario no existe en Cloud SQL | Crea el usuario en Cloud SQL con `gcloud sql users create` |
| Mismatch en row counts | Secuencias o triggers no migrados | Revisa `--no-owner` y `--no-acl`, verifica secuencias |
| `pg_restore: error: could not execute query` | Dependencia circular o constraint | Usa `PGRESTORE_JOBS=1` para restauración secuencial |
