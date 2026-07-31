# Registro de variables de entorno (Nordik)

**Ventas / provisión USB al cliente:** solo el panel web `auto-venta1` (puerto **8001**); ver `docs/usb-provision-entrega.md`.

**Producción:** un `.env` por proceso desplegable en el servidor. **No commitear** secretos ni plantillas `.env.example` en el repo del producto.

| Prefijo | Consumidor |
|---------|------------|
| `VITE_*` | Solo Vite/React (`frontend`) — expuesto en el bundle |
| `DATABASE_URL`, `JWT_*`, `TOKEN_*`, `FIREBASE_*`, `GEMINI_*`, `GOOGLE_CLOUD_*` | `apps/dot/backend` (FastAPI DOT; alias histórico `frontend/backend`) |
| `OPENCLAW_*`, `NORDIK_NODE` | Electron / scripts Node |
| Variables sin prefijo en cada app | `auto-venta1`, `Chatbot-Cobro`, `infra/billing` |

---

## `frontend/.env`

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `VITE_API_BASE_URL` | Sí | URL del backend, ej. `http://127.0.0.1:8000` |
| `VITE_PANEL_ONLY_USB` | No | `1` oculta `#/provisioner` en dev del cliente (ventas = panel `auto-venta1`) |
| `VITE_NORDIK_PROVISIONER` | No | `1` en build de la app **Provisioner** (soporte interno, `#/provisioner` standalone). **No** es el flujo del vendedor |
| `VITE_ADMIN_API_KEY` | Sí (Provisioner) | Mismo valor que `ADMIN_API_KEY` del backend; lista clientes admin en app soporte |
| `VITE_OPENCLAW_AUTOMATION_PLUGINS` | No | CSV de paquetes npm OpenClaw (Gmail/Calendar) |

Login Nordik usa **solo JWT** (`POST /v1/auth/login`). No se requiere SDK Firebase en el cliente.

---

## `apps/dot/backend/.env` (DOT producto)

> Ruta canónica del backend DOT. En documentación antigua aparece como `frontend/backend/.env`; el código vive en `apps/dot/backend/`.

| Variable | Obligatoria | Descripción | Settings / origen |
|----------|-------------|-------------|-------------------|
| `NORDIK_ENV` | Recomendada | `production` desactiva bypass OAuth dev | `settings.py` |
| `DATABASE_URL` | Sí (prod) | Postgres/SQLite — tablas billing (`clientes_suscripcion`, `subscription_reminder_outbox`) y, si `ENABLE_CHAT`, `chat_conversations` / `chat_messages` | `settings.py` |
| `JWT_PRIVATE_KEY_PEM` | Sí (RS256) | Clave privada RSA en formato PEM para JWT RS256 (recomendado producción). Pasar en una línea con `\n` o multilínea entre comillas | `settings.py` |
| `JWT_PUBLIC_KEY_PEM` | Sí (RS256) | Clave pública RSA en formato PEM para JWT RS256 | `settings.py` |
| `JWT_SECRET` | Sí (HS256) | Secreto HS256 legacy para tokens de sesión (solo desarrollo / migración) | `settings.py` |
| `JWT_ACCESS_EXPIRES_MINUTES` | No | TTL JWT access token (default 30) | `settings.py` |
| `JWT_REFRESH_EXPIRES_DAYS` | No | TTL JWT refresh token (default 30) | `settings.py` |
| `TOKEN_ENCRYPTION_KEY` | Sí | Fernet (32 bytes base64) para cifrar tokens OAuth de terceros (Google, etc.) en Firestore | `settings.py` |
| `CHAT_ENCRYPTION_KEY` | Recomendada | Fernet SEPARADO para cifrar `chat_messages` en BD. **Debe** ser diferente de `TOKEN_ENCRYPTION_KEY`. Si vacía, usa `TOKEN_ENCRYPTION_KEY` como fallback (no recomendado en prod) | `settings.py` |
| `ADMIN_API_KEY` | Sí (prod) | Habilita endpoints admin internos (`X-Admin-Key`); usado tambien por `auto-venta1` para recovery key | `settings.py` |
| `HARDWARE_TOKEN_PEPPER` | Sí (prod) | SHA-256(serial + pepper) para pendrive USB | `settings.py` |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Sí | Ruta al JSON de cuenta de servicio Admin de Firebase | `settings.py` |
| `GOOGLE_CLIENT_SECRETS_PATH` | Sí | Ruta a `client_secret.json` (`infra/credentials/client_secret.json`) | `settings.py` |
| `OAUTH_REDIRECT_URI` | Sí | URI autorizada en Google Cloud Console | `settings.py` |
| `CORS_ALLOW_ORIGINS` | No | CSV de orígenes permitidos (default en dev: `http://127.0.0.1:5173,http://localhost:5173`) | `settings.py` |
| `TRUSTED_HOSTS` | No | CSV de hosts permitidos para validación Host header (producción; default `127.0.0.1,localhost`) | `settings.py` |
| `ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH` | Solo dev | `1` permite `dev_user_id` sin JWT — **prohibido en producción** | `settings.py` |
| `REFRESH_USE_FIRESTORE_ONLY` | No | `1` fuerza refresh/revocación solo en Firestore (sin memoria de proceso). Automático con `NORDIK_ENV=production` | `settings.py` |
| `TESTING` | No | `1` permite fallback en memoria sin Firestore (tests) | `settings.py` |

### Feature flags

| Variable | Obligatoria | Descripción | Settings / origen |
|----------|-------------|-------------|-------------------|
| `ENABLE_CHAT` | No | `true` activa el módulo de chat → flag `enable_chat_core` en catálogo de capacidades | `settings.py` |
| `ENABLE_NEW_INTEGRATION` | No | Alias legacy de `ENABLE_IMAGE_GENERATION` → flag `enable_image_gen` | `settings.py` |
| `ENABLE_WEB_SEARCH` | No | `true` (default) habilita búsqueda web → flag `enable_web_search` (**no** usar `enable_websearch`) | `settings.py` |
| `ENABLE_WEB_SEARCH_IN_CHAT` | No | `true` (default) detección automática de búsqueda en chat | `settings.py` |
| `DEFAULT_CHAT_PROVIDER` | No | Proveedor IA por defecto (`default`) | `settings.py` |

### API keys para proveedores IA

| Variable | Obligatoria | Descripción | Settings / origen |
|----------|-------------|-------------|-------------------|
| `DEEPSEEK_API_KEY` | Sí (chat) | API key de Deepseek (modelo por defecto para chat) | `settings.py` |
| `OPENAI_API_KEY` | No | API key de OpenAI (ChatGPT) | `settings.py` |
| `GOOGLE_TRANSLATE_API_KEY` | No | API key de Google Translate | `settings.py` |

### Visión — Gemini / Vertex AI (Sprint 2)

Endpoint: `POST /v1/vision/analyze`. Arquitectura: `docs/ARCHITECTURE.md` §3.5. Contrato HTTP: `docs/public-api.md`.

| Variable | Obligatoria | Descripción | Settings / origen |
|----------|-------------|-------------|-------------------|
| `GEMINI_PROVIDER` | No | `vertex` (recomendado prod) o `api_key` (default en código). Valores desconocidos se normalizan a `api_key`. | `settings.normalized_gemini_provider` |
| `GOOGLE_CLOUD_PROJECT` | Condicional | ID del proyecto GCP para Vertex. **Obligatorio** si `GEMINI_PROVIDER=vertex`. | `settings.google_cloud_project` |
| `GCP_PROJECT` | — | Alias de `GOOGLE_CLOUD_PROJECT` (misma variable en `settings.py`). | `settings.google_cloud_project` |
| `GOOGLE_CLOUD_LOCATION` | No | Región Vertex AI (default `us-central1`). | `settings.google_cloud_location` |
| `GEMINI_VERTEX_MODEL` | No | Modelo Vertex Vision cuando `GEMINI_PROVIDER=vertex` (default `gemini-2.5-flash`). | `settings.gemini_vertex_model` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Condicional | Ruta al JSON de cuenta de servicio para ADC de Vertex. **Obligatoria** en servidor si no hay ADC de `gcloud`. Puede apuntar al mismo archivo que `FIREBASE_SERVICE_ACCOUNT_PATH` si la SA tiene rol Vertex AI User. No commitear el JSON. | ADC / `vision_vertex_service` |
| `GEMINI_API_KEY` | Condicional | API key de Gemini REST. **Obligatoria** si `GEMINI_PROVIDER=api_key`. No exponer al cliente. | `settings.gemini_api_key` |
| `GEMINI_MODEL` | No | Modelo Gemini REST cuando `GEMINI_PROVIDER=api_key` (default `gemini-1.5-flash`). | `settings.gemini_model` |

### Generación de imágenes — Vertex Imagen (Sprint 2.5)

Endpoint: `POST /v1/images/generate`. Arquitectura y contrato: `docs/SPRINT-2.5-DESIGN.md`. Reutiliza `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` y `GOOGLE_APPLICATION_CREDENTIALS` de la sección Visión.

| Variable | Obligatoria | Descripción | Dev default | Prod |
|----------|-------------|-------------|-------------|------|
| `ENABLE_IMAGE_GENERATION` | No | Activa generación de imágenes → flag `enable_image_gen`. Alias legacy: `ENABLE_NEW_INTEGRATION`. | `true` | `true` |
| `IMAGEN_VERTEX_MODEL` | No | Modelo Vertex Imagen (ej. `imagen-3.0-generate-002`). | `imagen-3.0-generate-002` | igual |
| `IMAGE_GEN_DEFAULT_RESOLUTION` | No | Resolución por defecto fase 1. | `1024x1024` | `1024x1024` |
| `IMAGE_GEN_ENABLE_1080P` | No | Fase post-lanzamiento: habilita mínimo 1080p. | `false` | `false` |
| `IMAGE_GEN_MAX_IMAGES_PER_REQUEST` | No | Tope de seguridad de imágenes por request. | `4` | `4` |

### Límite de consumo IA unificado (Sprint 2.5)

Endpoint: `GET /v1/usage/summary`. Cuenta chat DeepSeek + visión Vertex + generación Imagen contra el mismo tope mensual.

| Variable | Obligatoria | Descripción | Dev default | Prod |
|----------|-------------|-------------|-------------|------|
| `AI_USAGE_LIMIT_ENABLED` | No | `true` aplica tope; `false` desactiva bloqueo (dev/testing). El código del límite debe existir siempre. | `false` | `true` |
| `AI_USAGE_MONTHLY_LIMIT_USD` | No | Tope mensual en USD por `cliente_id`/pendrive. | `7.5` | `7.5` |
| `AI_USAGE_BILLING_TIMEZONE` | No | Zona IANA para el mes de facturación. | `America/Bogota` | `America/Bogota` |
| `AI_COST_DEEPSEEK_INPUT_PER_1M` | No | Precio USD por 1M tokens input (cálculo de costo). | `0.14` | actualizar según tarifa |
| `AI_COST_DEEPSEEK_OUTPUT_PER_1M` | No | Precio USD por 1M tokens output. | `0.28` | actualizar según tarifa |
| `AI_COST_GEMINI_VISION_PER_REQUEST` | No | Costo fijo estimado por análisis de imagen (visión). | `0.001` | calibrar |
| `AI_COST_IMAGEN_PER_IMAGE` | No | Costo USD por imagen generada. | `0.04` | calibrar |

**Deploy producción:** en el `.env` del servidor `apps/dot/backend`, establecer `AI_USAGE_LIMIT_ENABLED=true` y revisar precios antes de activar bloqueo en clientes reales.

### APM / Logging

| Variable | Obligatoria | Descripción | Settings / origen |
|----------|-------------|-------------|-------------------|
| `SENTRY_DSN` | No | DSN de Sentry para APM | `settings.py` → `sentry_sdk.init()` |
| `LOGTAIL_SOURCE_TOKEN` | No | Token de Logtail (Better Stack) | `settings.py` → `logging_config.py` |
| `LOGTAIL_HOST` | No | Host de Logtail (default `https://logs.betterstack.com`) | `settings.py` → `logging_config.py` |
| `LOG_LEVEL` | No | Nivel de logging (`DEBUG`, `INFO`, `WARNING`, `ERROR`; default `INFO`) | `settings.py` → `logging_config.py` |
| `SECURITY_WEBHOOK_URL` | No | URL de webhook Discord/Slack para alertas de seguridad (refresh reuse, login fallido repetido) | `nordik_billing.webhook_alert` → `os.environ` |

### Configuración avanzada (solo en `settings.py`, defaults seguros)

| Variable | Descripción | Default |
|----------|-------------|---------|
| `OAUTH_STATE_TTL_MINUTES` | TTL del state OAuth en minutos | `15` |
| `API_TLS_PIN_SHA256` | SHA-256 del certificado TLS del servidor para SSL pinning | `""` (vacío) |
| `OPENCLAW_API_URL` | URL base de la API de OpenClaw (WhatsApp/automation) | `""` (vacío) |
| `ALLOWED_REMOTE_COMMANDS_JSON` | JSON string con whitelist de comandos remotos permitidos | `['download-file','system-info']` |
| `WHATSAPP_WEBHOOK_URL` | URL donde OpenClaw envía mensajes entrantes de WhatsApp | `http://localhost:8000/v1/whatsapp/inbound` |
| `WHATSAPP_WEBHOOK_SECRET` | Secreto para validar webhooks entrantes de WhatsApp | `""` (vacío) |

**Catálogo de capacidades (`openclaw_adapter.CAPABILITY_FLAG_KEYS`):** cada `capability_id` del registro mapea a una clave explícita en `FEATURE_FLAGS` (no derivar con `enable_{id}` ni quitar guiones bajos). El desktop **no** consume aún `GET /v1/capabilities`; el gating efectivo está en backend (plan + flags). Ver comentario en `apps/dot/backend/app/routers/capabilities.py`.

| capability_id | FEATURE_FLAGS key | Settings / notas |
|---------------|-------------------|-------------------|
| `chat_completion` | `enable_chat_core` | `ENABLE_CHAT` |
| `whatsapp_channel_login` | `enable_whatsapp_qr` | siempre `true` en v1 |
| `automation_plugins` | `enable_automation_plugins` | siempre `true` en v1 |
| `image_generation` | `enable_image_gen` | `ENABLE_NEW_INTEGRATION` |
| `web_search` | `enable_web_search` | `ENABLE_WEB_SEARCH` |
| `file_tools` | `enable_file_tools` | Fase 3+ (default `false`) |
| `remote_execution` | `enable_remote_execution` | default `false` |

**Documentos (`POST /v1/documents/generate`):** tipos válidos `docx`, `xlsx`, `txt`, `pdf`. Plantillas (`POST /v1/templates`): `docx`, `xlsx`, `txt` (sin `pdf`). El frontend no expone `csv` ni `md`.

Generar `TOKEN_ENCRYPTION_KEY` / `CHAT_ENCRYPTION_KEY`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## `infra/billing/.env` (Docker Postgres local)

| Variable | Descripción |
|----------|-------------|
| `NORDIK_PG_USER` | Usuario (default `nordik`) |
| `NORDIK_PG_PASSWORD` | Contraseña |
| `NORDIK_PG_DATABASE` | Base (default `nordik_billing`) |
| `NORDIK_PG_PORT` | Puerto host (default `5432`) |

`DATABASE_URL` equivalente para backend:

`postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/DATABASE`

---

## `auto-venta1/.env`

**Ventas:** provisión USB al cliente solo desde el panel web (puerto **8001**); ver `docs/usb-provision-entrega.md`.

| Variable | Obligatoria | Descripción | Settings / origen |
|----------|-------------|-------------|-------------------|
| `PORT` | No | HTTP del panel (default **8001**, no usar 8000 — reservado a Nordik API) | `config.py` |
| `HOST` | No | IP de escucha del panel (default `127.0.0.1`) | `config.py` |
| `DATABASE_URL` | Sí (prod) | Misma Postgres que billing | `config.py` |
| `REPOSITORY_BACKEND` | No | `sql` o `memory` (solo pruebas locales) | `config.py` |
| `SESSION_SECRET` | Sí | Secreto para cookies del panel | `config.py` |
| `BASIC_AUTH_ENABLED` | No | `true` activa HTTP Basic Auth (popup del navegador) en `/app`; en local `false` | `config.py` |
| `BASIC_AUTH_USER` | Condicional | Usuario para Basic Auth (requerido si `BASIC_AUTH_ENABLED=true`) | `config.py` |
| `BASIC_AUTH_PASSWORD` | Condicional | Contraseña para Basic Auth | `config.py` |
| `PANEL_SKIP_USB_REQUIREMENT` | No | `true` permite alta en panel sin pendrive USB (no guarda `hardware_token_hash`); Fase 1 / dev | `config.py` |
| `PANEL_AUTH_ENABLED` | No | `true` activa login por roles del panel (JWT en cookie HttpOnly) | `config.py` |
| `PANEL_JWT_SECRET` | No | Secreto HS256 para cookie JWT del panel (si no está, usa `SESSION_SECRET`) | `config.py` |
| `PANEL_JWT_EXP_HOURS` | No | Duración del token de panel en horas (default 12) | `config.py` |
| `PANEL_JWT_COOKIE_NAME` | No | Nombre de la cookie JWT (default `nordik_panel_token`) | `config.py` |
| `PANEL_COOKIE_SECURE` | No | `true` activa Secure flag en la cookie JWT (requiere HTTPS; default `false` en local) | `config.py` |
| `PANEL_ADMIN_USERNAME` | No | Usuario bootstrap administrador (default `admin`; todo permitido) | `config.py` |
| `PANEL_ADMIN_PASSWORD` | Condicional | Contraseña plana administrador (requerido en prod si no se usa hash) | `config.py` |
| `PANEL_ADMIN_PASSWORD_HASH` | Condicional | Hash bcrypt alternativo para administrador (más seguro que clave plana) | `config.py` |
| `PANEL_EMPLEADO_USERNAME` | No | Usuario bootstrap empleado (default `empleado`; solo ver/registrar) | `config.py` |
| `PANEL_EMPLEADO_PASSWORD` | Condicional | Contraseña plana empleado | `config.py` |
| `PANEL_EMPLEADO_PASSWORD_HASH` | Condicional | Hash bcrypt alternativo para empleado | `config.py` |
| `ADMIN_API_KEY` | Sí (sql) | Clave para `X-Admin-Api-Key` en `/api/clientes` (obligatoria si `REPOSITORY_BACKEND=sql`) | `config.py` |

### Recordatorios

| Variable | Obligatoria | Descripción | Default |
|----------|-------------|-------------|---------|
| `REMINDER_OWNER` | No | `auto-venta1` o `chatbot-cobro` | `auto-venta1` |
| `REMINDER_ENABLED` | No | `false` si Chatbot-Cobro es dueño de recordatorios | `true` |
| `REMINDER_DAYS_BEFORE` | No | Días antes del vencimiento | `7` |
| `REMINDER_TIMEZONE` | No | IANA, ej. `America/Bogota` | `America/Bogota` |
| `REMINDER_CRON_HOUR` | No | Hora del job de recordatorios | `9` |
| `REMINDER_CRON_MINUTE` | No | Minuto del job de recordatorios | `0` |

### Correo

| Variable | Obligatoria | Descripción | Default |
|----------|-------------|-------------|---------|
| `WELCOME_EMAIL_ENABLED` | No | Activa/desactiva correo de bienvenida al crear clientes | `true` |
| `SMTP_HOST` | Condicional | Host SMTP (requerido si hay correo habilitado) | `None` |
| `SMTP_PORT` | No | Puerto SMTP | `587` |
| `SMTP_USER` | Condicional | Usuario SMTP | `None` |
| `SMTP_PASSWORD` | Condicional | Contraseña SMTP | `None` |
| `SMTP_FROM` | Condicional | Dirección from SMTP | `None` |
| `SMTP_USE_TLS` | No | `true` usa TLS para SMTP | `true` |

### WhatsApp / API externa (legacy)

| Variable | Obligatoria | Descripción | Default |
|----------|-------------|-------------|---------|
| `WHATSAPP_API_URL` | No | URL de API WhatsApp HTTP genérica (legacy; preferir Chatbot-Cobro + Meta) | `None` |
| `WHATSAPP_API_TOKEN` | No | Token de API WhatsApp | `None` |
| `WHATSAPP_FROM_NUMBER` | No | Número remitente WhatsApp | `None` |

### Integración con Nordik API

| Variable | Obligatoria | Descripción | Default |
|----------|-------------|-------------|---------|
| `NORDIK_API_BASE_URL` | Sí (prod) | Base URL de `apps/dot/backend` para recovery key y revocación de sesiones | `http://127.0.0.1:8000` |
| `NORDIK_API_KEY` | Sí (prod) | API key admin usada como `X-Admin-Key` hacia Nordik API | `None` |

### Feature flags (auto-venta1)

| Variable | Obligatoria | Descripción | Default |
|----------|-------------|-------------|---------|
| `ENABLE_WEB_SEARCH` | No | `true` habilita búsqueda web | `true` |
| `ENABLE_CHAT` | No | `true` activa el módulo de chat | `true` |
| `GEMINI_API_KEY` | Condicional | API key Gemini (necesaria si `ENABLE_CHAT=true`) | `""` |
| `OPENAI_API_KEY` | Condicional | API key OpenAI (necesaria si `ENABLE_CHAT=true`) | `""` |

### APM / Logging

| Variable | Obligatoria | Descripción | Settings / origen |
|----------|-------------|-------------|-------------------|
| `SENTRY_DSN` | No | DSN de Sentry para APM | `config.py` → `sentry_sdk.init()` |
| `LOGTAIL_SOURCE_TOKEN` | No | Token de Logtail (Better Stack) | `config.py` → `logging_config.py` |
| `LOGTAIL_HOST` | No | Host de Logtail (default `https://logs.betterstack.com`) | `config.py` → `logging_config.py` |
| `LOG_LEVEL` | No | Nivel de logging (`DEBUG`, `INFO`, `WARNING`, `ERROR`; default `INFO`) | `config.py` → `logging_config.py` |
| `SECURITY_WEBHOOK_URL` | No | URL de webhook Discord/Slack para alertas de seguridad | `nordik_billing.webhook_alert` → `os.environ` |

### Provisión USB (configuración avanzada)

| Variable | Obligatoria | Descripción | Default |
|----------|-------------|-------------|---------|
| `NORDIK_NODE_PATH` / `NORDIK_NODE` | No | Ruta a `node.exe` para provisión USB (si no está en PATH); ver `docs/usb-provision-entrega.md` | `""` |
| `HARDWARE_TOKEN_PEPPER` | Sí (prod) | SHA-256(serial + pepper) para validación de pendrive USB | `None` |
| `USB_REGISTER_API_KEY` | No | API key para registro de USBs | `None` |
| `USB_AUTH_RATE_LIMIT_PER_MINUTE` | No | Límite de intentos de autenticación USB por minuto | `10` |
| `PROVISIONER_EXE_DIR` | No | Directorio del provisioner en NAS compartido | `""` |
| `PROVISIONER_VERSION` | No | Versión del provisioner | `1.0.0` |
| `PROVISIONER_EXE_FILENAME` | No | Nombre del ejecutable (template con `{version}`) | `NordikProvisioner-{version}-x64.exe` |

### Seguridad HTTP

| Variable | Obligatoria | Descripción | Default |
|----------|-------------|-------------|---------|
| `TRUSTED_HOSTS` | No | CSV de hosts permitidos para validación Host header (producción) | `127.0.0.1,localhost` |
| `DEBUG` | No | Modo debug de la aplicación | `false` |

---

## `Chatbot-Cobro/.env`

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `DATABASE_URL` | Prod | Misma Postgres — activa repos reales |
| `NODE_ENV` | Prod | `production` exige `META_APP_SECRET` |
| `PORT` | No | HTTP (default 8080) |
| `META_ACCESS_TOKEN` | Sí | Graph API |
| `META_PHONE_NUMBER_ID` | Sí | Número WhatsApp Business |
| `META_GRAPH_API_VERSION` | No | default `v22.0` |
| `META_WEBHOOK_VERIFY_TOKEN` | Sí | Verificación webhook GET |
| `META_APP_SECRET` | Sí (prod) | HMAC POST webhook |
| `BUSINESS_TIMEZONE` | No | IANA calendario de vencimiento |
| `REMIND_DAYS_BEFORE_EXPIRY` | No | default 7 |
| `REMINDER_TEMPLATE_NAME` | Sí | Plantilla aprobada en Meta |
| `REMINDER_TEMPLATE_LANGUAGE` | No | default `es` |
| `REMINDERS_CRON` | No | Cron interno |
| `ENABLE_INTERNAL_SCHEDULER` | No | default `true` |

---

## Electron (sistema / lanzador)

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `NORDIK_PROVISIONER` | No | `1` arranca la app **Nordik Provisioner** standalone (soporte/dev). Vendedores usan panel :8001 |
| `NORDIK_SKIP_USB_GATE` | No | `1` omite gate pendrive en dev |
| `OPENCLAW_AUTOMATION_PLUGINS` | No | CSV de paquetes npm para Gmail/Calendar vía OpenClaw |
| `NORDIK_API_TLS_PIN_SHA256` | No | SHA-256 del certificado TLS del servidor para SSL pinning en Electron |

### Auto-updater

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `NORDIK_AUTO_UPDATE_ENABLED` | No | Habilita/deshabilita auto-update (default: `true`) |
| `NORDIK_UPDATER_URL` | No | URL del feed genérico, ej. `https://releases.nordik-ia.com/updates/` |
| `NORDIK_UPDATER_CHANNEL` | No | Canal del feed (default: `latest`) |
| `NORDIK_UPDATER_GH_OWNER` | No* | GitHub owner para releases (requerido si no se usa `UPDATER_URL`) |
| `NORDIK_UPDATER_GH_REPO` | No* | GitHub repo para releases (requerido si no se usa `UPDATER_URL`) |
| `NORDIK_UPDATER_GH_PRIVATE` | No | `true` si el repo es privado (default: `false`) |
| `NORDIK_UPDATER_GH_TOKEN` | No | GitHub token con acceso a releases |
| `GH_TOKEN` | No | Fallback si no está `NORDIK_UPDATER_GH_TOKEN` |
| `NORDIK_UPDATER_ALLOW_PRERELEASE` | No | Permite prereleases (default: `false`) |

\* `NORDIK_UPDATER_GH_OWNER` y `NORDIK_UPDATER_GH_REPO` son requeridos si no se configura `NORDIK_UPDATER_URL`.

Si ambas fuentes están configuradas, tiene prioridad `NORDIK_UPDATER_URL` (feed genérico). Ver `buildUpdaterFeedConfig()` en `electron/main.cjs`.

---

## Preflight backend (dev)

`cd apps/dot/backend && python scripts/preflight_config.py` compara `DATABASE_URL` entre los `.env` de `apps/dot/backend`, `auto-venta1` y `Chatbot-Cobro` cuando existen: **no impone una sola BD**, pero emite *warning* si difieren. Verifica también que la BD del backend tenga las tablas del checklist (`app/services/db_schema_checklist.py`).

---

## Reglas

- OAuth Google (Gmail/Calendar) ≠ API keys de modelos LLM.
- **Un dueño de recordatorios:** `REMINDER_OWNER=chatbot-cobro` en auto-venta1 o `REMINDER_ENABLED=false`.
