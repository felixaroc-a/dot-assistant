# Esquema SQLite Local — DOT v2

> **Versión:** 1.0 · Julio 2026  
> **Ubicación:** `%APPDATA%/DOT/dot-local.db` (Electron `userData`)  
> **Motor:** `better-sqlite3` (Node.js, compilado nativo contra Electron)  
> **Modo:** WAL (`PRAGMA journal_mode=WAL`) + Foreign Keys ON

---

## Diagrama de relaciones

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│   profile   │     │ automations  │     │ oauth_tokens │
│  (key-value)│     │ (crud jobs)  │     │ (google etc) │
└─────────────┘     └──────────────┘     └──────────────┘

┌─────────────┐     ┌──────────────┐
│   memory    │     │ conversations│──┬──┐
│ (embeddings)│     │   (chats)    │  │  │
└─────────────┘     └──────────────┘  │  │
                                      │  │ 1:N
┌─────────────┐     ┌──────────────┐  │  │
│    jobs     │     │   messages   │◄─┘  │
│ (cron tasks)│     │  (por conv)  │     │
└─────────────┘     └──────────────┘     │
                                         │
┌─────────────┐                          │
│  kv_store   │ (genérico key-value)     │
│ (namespaces)│                          │
└─────────────┘                          │
                                         │
┌─────────────┐                          │
│   _meta     │ (versión schema, etc) ◄──┘
└─────────────┘
```

---

## Tablas (10)

### 1. `_meta` — Metadatos de la BD
```sql
CREATE TABLE IF NOT EXISTS _meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
```
- `schema_version`: versión del schema para migraciones
- `created_at`: fecha de creación de la BD
- `last_backup`: timestamp del último backup

### 2. `profile` — Perfil del usuario (key-value)
```sql
CREATE TABLE IF NOT EXISTS profile (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT DEFAULT (datetime('now'))
);
```
Keys comunes: `display_name`, `onboarding_completed`, `ai_provider_id`, `theme`, `language`

### 3. `automations` — Automatizaciones del usuario
```sql
CREATE TABLE IF NOT EXISTS automations (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  instruction TEXT NOT NULL,
  schedule TEXT,                    -- cron expression
  integration_id TEXT DEFAULT 'third-option',
  output_type TEXT DEFAULT 'notification',
  active INTEGER DEFAULT 1,
  source TEXT DEFAULT 'interactive',
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
```

### 4. `oauth_tokens` — Tokens OAuth (Google, etc.)
```sql
CREATE TABLE IF NOT EXISTS oauth_tokens (
  provider TEXT PRIMARY KEY,        -- 'google', 'twitter', etc.
  access_token TEXT,
  refresh_token TEXT,
  expiry TEXT,                      -- ISO 8601 timestamp
  encrypted INTEGER DEFAULT 1       -- 1 = cifrado con Fernet
);
```

### 5. `memory` — Memoria del usuario con embeddings
```sql
CREATE TABLE IF NOT EXISTS memory (
  id TEXT PRIMARY KEY,
  content TEXT NOT NULL,
  embedding BLOB,                   -- Float32Array de 384 dimensiones (ONNX)
  category TEXT,                    -- 'daily_summary', 'file', 'user_preference'
  importance REAL DEFAULT 0.5,      -- 0.0 a 1.0. >= 0.9 = nunca decae
  created_at TEXT DEFAULT (datetime('now')),
  decayed_at TEXT                   -- NULL = activa, timestamp = archivada
);
```

### 6. `conversations` — Historial de conversaciones
```sql
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  title TEXT,
  channel TEXT DEFAULT 'desktop',   -- 'desktop', 'whatsapp'
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  archived_at TEXT                  -- NULL = activa
);
```

### 7. `messages` — Mensajes dentro de conversaciones
```sql
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,    -- FK → conversations.id
  role TEXT NOT NULL CHECK(role IN ('user','assistant','system','tool')),
  content TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  tool_trace TEXT                   -- JSON: trace de herramientas usadas
);
```

### 8. `jobs` — Tareas programadas (node-cron)
```sql
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  cron_expr TEXT NOT NULL,          -- '0 9 * * 1' = lunes 9AM
  instruction TEXT,                 -- qué ejecutar
  last_run TEXT,                    -- última ejecución
  next_run TEXT,                    -- próxima ejecución calculada
  status TEXT DEFAULT 'pending',    -- 'pending', 'running', 'done', 'failed'
  error_log TEXT                    -- último error si falló
);
```

### 9. `kv_store` — Almacén genérico clave-valor
```sql
CREATE TABLE IF NOT EXISTS kv_store (
  key TEXT PRIMARY KEY,
  value TEXT,
  namespace TEXT DEFAULT 'default'  -- 'file_index', 'personality', 'settings'
);
```

### 10. `memory_archive` — Memorias archivadas (creada por memory-decay)
```sql
CREATE TABLE IF NOT EXISTS memory_archive (
  id TEXT PRIMARY KEY,
  original_id TEXT,
  content TEXT,
  category TEXT,
  importance REAL,
  created_at TEXT,
  archived_at TEXT DEFAULT (datetime('now'))
);
```

---

## Configuración

| PRAGMA | Valor | Motivo |
|--------|-------|--------|
| `journal_mode` | WAL | Mejor concurrencia, lecturas sin bloquear escrituras |
| `foreign_keys` | ON | Integridad referencial |
| `synchronous` | NORMAL | Balance seguridad/rendimiento (WAL ya protege) |
| `cache_size` | -64000 | 64MB de caché en RAM |

---

## Backups

SQLite es un solo archivo. Backup = copiar `dot-local.db`:

```powershell
copy $env:APPDATA\DOT\dot-local.db $env:APPDATA\DOT\dot-local-backup.db
```

**Recomendado:** backup automático cada 24h (job `db_backup_daily` en job-scheduler).

---

## Migraciones

El sistema de migraciones usa la tabla `_meta`:

```javascript
const currentVersion = localDb.kvGet('schema_version', '_meta') || '0';
if (currentVersion === '0') {
  // Ejecutar migración v0 → v1
  localDb.kvSet('schema_version', '1', '_meta');
}
```

---

## Firestore como backup opcional

Cuando `FIRESTORE_AVAILABLE = True`:
- Al escribir en SQLite, también se escribe en Firestore
- Al leer, SQLite es fuente primaria; Firestore es fallback
- Sincronización: último-gana (last-write-wins)

Modo offline (`FIRESTORE_AVAILABLE = False`):
- Todo se lee/escribe solo en SQLite local
- Backend no crashea, endpoints retornan 200 con defaults
