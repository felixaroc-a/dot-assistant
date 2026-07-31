# Contratos API/UI v1 — Nordik

## Proposito del documento

Congelar los contratos actuales entre servicios para poder evolucionar `frontend` como producto cliente (frontend principal) sin romper `auto-venta1` (backoffice interno) ni `Chatbot-Cobro` (cobranzas/recordatorios).

## Perimetro oficial de cada servicio

| Servicio | Carpeta | Puerto | Rol | Audiencia |
|----------|---------|--------|-----|-----------|
| Nordik API (producto) | `frontend/backend` | 8000 | Login JWT, perfil Firestore, OAuth Google, chat IA, tools | **Cliente final** via frontend |
| Nordik App (Electron) | `frontend` | 5173 (dev) | Interfaz de escritorio del producto | **Cliente final** |
| Panel admin suscripciones | `auto-venta1` | 8001 | Alta/edicion de `clientes_suscripcion` | **Solo operacion interna** |
| Chatbot cobranza | `Chatbot-Cobro` | 8080 | Recordatorios WhatsApp + outbox | **Solo operacion interna** |
| Paquete compartido | `packages/nordik-billing` | - | Modelos SQLAlchemy, utilidades comunes | **Interno** |

## Contratos API estables (NO modificar sin versionar)

### Nordik API (`frontend/backend`)

#### Autenticacion

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/v1/auth/login` | `{ cedula, password, hardware_serial? }` | `{ access_token, token_type, expires_in, cliente }` | Rate: 10/min. Errores: 401, 403, 503 |
| POST | `/v1/auth/refresh` | `{ refresh_token }` | `{ access_token, refresh_token, expires_in }` | Rate: 30/min. Rotacion con deteccion de reuso |
| POST | `/v1/auth/logout` | `{ refresh_token }` | 204 | Requiere Bearer. Revoca JTI + familia |
| GET | `/me` | - | `{ cliente_id, cedula, plan, fecha_vencimiento, correo }` | Requiere Bearer. Rate: 120/min |
| POST | `/v1/admin/revoke-user-tokens` | `{ uid }` | 204 | Interno/backoffice. Requiere `X-Admin-Key` |

#### Perfil

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| GET | `/users/me/profile` | - | `UserProfileResponse` | Firestore. Requiere Bearer |
| PATCH | `/users/me/profile` | `UserProfilePatch` | `UserProfileResponse` | Merge en Firestore |

Campos del perfil (`snake_case` en Firestore):
- `display_name` (string)
- `channel_id` (string)
- `ai_provider_id` (string)
- `integrations` (string[])
- `automation_summary` (string)
- `onboarding_completed` (boolean)
- `saved_automations` (AutomationDTO[]: `id`, `name`, `integration_id`, `instruction`, `active?`, `output_type?`, `schedule?` — snake_case en JSON de API)
- `updated_at` (timestamp)

#### OAuth Google

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/oauth/google/start` | `GoogleOAuthStartBody` | `{ authorization_url, state }` | Requiere Bearer en prod |
| GET | `/oauth/google/callback` | Query: `code, state, error?` | HTML success page | Redirect URI debe coincidir con Google Console |
| GET | `/oauth/google/status` | Bearer JWT | `{ configured, integrations, expires_at, scopes_ok }` | Estado vinculacion OAuth |

#### WhatsApp Channel

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| GET | `/v1/whatsapp/channel/status` | - | `WhatsAppChannelStatus` | Requiere Bearer |
| POST | `/v1/whatsapp/channel/status` | `{ linked, phone_number?, channel_name?, error? }` | `WhatsAppChannelStatus` | Actualiza estado |
| POST | `/v1/whatsapp/channel/events` | `{ event, phone_number?, channel_name?, error? }` | `WhatsAppChannelStatus` | Evento operacional |
| POST | `/v1/whatsapp/channel/reconnect` | - | `WhatsAppChannelStatus` | Reinicia estado a disconnected |

#### WhatsApp Messaging (v1.4)

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/v1/whatsapp/message` | `WhatsAppMessageRequest` | `SendMessageOutput` | Envia mensaje WhatsApp via bridge Electron. Requiere Bearer |
| POST | `/v1/whatsapp/outbound` | `WhatsAppOutboundRequest` | `SendMessageOutput` | Envio outbound desde backend (interno). Requiere bridge secret |
| GET | `/v1/whatsapp/messages` | Query: `limit, before, after` | `ListMessagesOutput` | Lista mensajes del usuario. Requiere Bearer |
| POST | `/v1/whatsapp/messages/list` | `ListMessagesRequest` | `ListMessagesOutput` | Lista mensajes con filtros. Requiere Bearer |

#### WhatsApp Automation (v1.4)

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/v1/whatsapp/automation` | `WhatsAppAutomationRequest` | `AutomationOutput` | Ejecuta automatización via WhatsApp. Requiere Bearer |

#### WhatsApp Remote (v1.4 → deprecado M2 FASE 5)

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/v1/whatsapp/remote` | `RemoteExecutionRequest` | `RemoteExecutionOutput` | **410 Gone.** Path feliz: Agent Runtime `download_url_to_desktop` → bridge `/v1/tools/execute`. OpenClaw `:3000` ya no. |

#### WebSocket (v1.4)

| Metodo | Ruta | Description | Notas |
|--------|------|-------------|-------|
| WS | `/ws/notifications` | Notificaciones en tiempo real (automatizaciones, mensajes) | Conexión WebSocket. Requiere token de autenticación |

**Modelo `WhatsAppChannelStatus`:**
```json
{
  "status": "disconnected|connecting|linked",
  "linked": false,
  "phone_number": null,
  "channel_name": null,
  "last_linked_at": null,
  "last_disconnected_at": null,
  "last_qr_at": null,
  "last_heartbeat_at": null,
  "last_error_at": null,
  "reconnect_required": false,
  "reconnect_attempts": 0,
  "error": null
}
```

#### OAuth Google (v1.1 — propuesto)

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/oauth/google/start` | `GoogleOAuthStartBody` | `{ authorization_url, state }` | Requiere Bearer en prod |
| GET | `/oauth/google/callback` | Query: `code, state, error?` | HTML success page | Redirect URI debe coincidir con Google Console |
| GET | `/oauth/google/status` | - | `{ configured, integrations, expires_at, scopes_ok }` | **(NUEVO v1.1)** Verifica tokens OAuth desde Firestore |

#### Health

| Metodo | Ruta | Response |
|--------|------|----------|
| GET | `/health` | `{ status: "ok", ... }` |
| GET | `/health/db` | `{ status, billing, chat }` — verifica tablas Postgres. 503 si falta `clientes_suscripcion` o tablas chat |

#### Chat

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/v1/chat/send` | `{ conversation_id?, text, provider? }` | `{ message, conversation_id, history_saved }` | Requiere Bearer. Envia mensaje y recibe respuesta. Errores: 402 `ai_usage_limit_exceeded` |
| POST | `/v1/chat/send/stream` | `{ conversation_id?, text, provider? }` | `text/event-stream` (SSE) | Streaming token por token. Errores: 402 `ai_usage_limit_exceeded` |
| GET | `/v1/chat` | - | `{ conversations: [...] }` | Lista conversaciones del usuario |
| GET | `/v1/chat/{conversation_id}/history` | - | `{ conversation_id, messages: [...] }` | Historial de una conversacion |
| GET | `/v1/chat/agenda/today` | - | `{ linked, events, message }` | Eventos del dia desde Google Calendar |
| POST | `/v1/chat/translate` | `{ text, target_lang, provider? }` | `{ translated_text, provider, target_lang }` | Traduccion de texto |
| POST | `/v1/chat/summarize` | `{ content, provider? }` | `{ summary, source_type, chunks }` | Resumen de contenido |
| POST | `/v1/chat/reminders` | `{ text, due_at }` | `{ ok, id, due_at, message }` | Crear recordatorio |
| GET | `/v1/chat/reminders/pending` | - | `{ reminders: [...] }` | Recordatorios pendientes |
| POST | `/v1/chat/reminders/ack` | `{ ids }` | `{ ok, acked }` | Confirmar recordatorios como leidos |

#### Documentos

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/v1/documents/generate` | `{ document_type, title, content, folder? }` | `{ ok, filename, path, document_type, size_bytes }` | Genera docx/xlsx/txt/pdf |

#### Plantillas

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| GET | `/v1/templates` | - | `{ templates: [...] }` | Lista plantillas del usuario |
| POST | `/v1/templates` | `{ name, document_type, structure }` | `DocumentTemplateItem` | Crea plantilla reutilizable |
| DELETE | `/v1/templates/{template_id}` | - | `{ ok }` | Elimina plantilla |
| POST | `/v1/templates/{template_id}/render` | `{ user_input, provider? }` | `{ template_id, template_name, document_type, title, content }` | Renderiza plantilla con IA |

#### Automatizaciones

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/v1/automations/{auto_id}/execute` | - | `{ success, result, executed_at }` | Ejecuta automatizacion inmediatamente |
| GET | `/v1/automations/{auto_id}/history` | - | `{ executions: [...] }` | Historial de ejecuciones |
| GET | `/v1/automations/results/pending` | - | `{ has_new, last_auto_id, last_auto_name, last_executed_at, last_result_preview }` | Resultados pendientes para notificacion desktop |
| POST | `/v1/automations/results/ack` | - | `{ ok }` | Marca resultados pendientes como leidos |

#### Capacidades

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| GET | `/v1/capabilities/` | - | `{ capabilities: [...] }` | Catalogo de funcionalidades segun plan del usuario |
| GET | `/v1/capabilities/{capability_id}` | - | `{ id, label, description, enabled_by_default, available_in_plan }` | Detalle de capacidad especifica |

#### Consumo IA

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| GET | `/v1/usage/summary` | - | `UsageSummaryResponse` | Requiere Bearer. Resumen del mes en curso (tope $7.50 USD). Errores: 401, 403 `subscription_expired` |

**Modelo `UsageSummaryResponse`:**
```json
{
  "cliente_id": "uuid",
  "period": { "start": "2026-07-01", "end": "2026-07-31" },
  "limit_usd": 7.5,
  "consumed_usd": 2.55,
  "consumed_percent": 34,
  "remaining_usd": 4.95,
  "limit_enabled": true,
  "blocked": false
}
```

Cuenta consumo de chat DeepSeek, vision Vertex y generacion de imagenes Vertex Imagen contra el mismo tope mensual por `cliente_id` + serial USB.

#### Generacion de imagenes

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/v1/images/generate` | `ImageGenerateRequest` | `ImageGenerateResponse` | Requiere Bearer + suscripcion vigente + validacion de limite. Vertex Imagen. Disponible en todos los planes. Errores: 400 `invalid_prompt`, 402 `ai_usage_limit_exceeded`, 403 `subscription_expired`, 503 `image_generation_unavailable` |

**Request `ImageGenerateRequest`:**
```json
{
  "prompt": "Un gato astronauta en la luna, estilo acuarela",
  "count": null,
  "aspect_ratio": "1:1",
  "resolution": "1024x1024"
}
```

**Response `ImageGenerateResponse`:**
```json
{
  "images": [
    {
      "mime_type": "image/png",
      "data_base64": "...",
      "width": 1024,
      "height": 1024
    }
  ],
  "prompt_used": "Un gato astronauta en la luna, estilo acuarela",
  "count": 1,
  "usage": { "cost_usd": 0.04, "model": "imagen-3.0-generate-002" }
}
```

#### Errores IA (codigos estables)

| HTTP | Codigo | Condicion | `detail` |
|------|--------|-----------|----------|
| 402 | `ai_usage_limit_exceeded` | Tope mensual de consumo IA agotado ($7.50 USD) | `{ "code": "ai_usage_limit_exceeded", "message": "Ha alcanzado su limite de consumo de IA este mes..." }` |

Aplica a endpoints de IA: `POST /v1/chat/send`, `POST /v1/chat/send/stream`, `POST /v1/vision/analyze`, `POST /v1/images/generate`. En desarrollo, `AI_USAGE_LIMIT_ENABLED=false` desactiva el bloqueo.

#### Telemetria

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/v1/telemetry/event` | `{ type, timestamp, meta }` | 204 | Evento anonimo (`session_error`, `api_latency`, `provider_failure`, `login_failure`) |

#### Pendrive / Recovery

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/v1/pendrive/verify` | `{ serial, drive_path? }` | `{ ok, serial_hash, uid, cedula, nombre }` | Verifica serial del pendrive en servidor |
| POST | `/v1/pendrive/recovery-backup` | `{ recovery_key }` | `{ ok }` | Guarda recovery key en Firestore (requiere Bearer) |
| GET | `/v1/pendrive/recovery/{cliente_id}` | - | `{ ok, recovery_key }` | Recupera recovery key (propio usuario) |
| DELETE | `/v1/pendrive/recovery/{cliente_id}` | - | `{ ok }` | Elimina backup de recovery key |
| POST | `/v1/pendrive/challenge/request` | - | `{ nonce }` | Solicita nonce para handshake criptografico |
| POST | `/v1/pendrive/challenge/verify` | `{ nonce, signature }` | `{ ok }` | Verifica firma HMAC-SHA256 del nonce |
| POST | `/v1/pendrive/recovery-login` | `{ cedula, password, recovery_key }` | `{ access_token, refresh_token, ... }` | Login alternativo sin pendrive (JWT 24h) |
| POST | `/v1/pendrive/link` | `{ serial }` | `{ ok }` | Vincula nuevo pendrive (requiere JWT valido) |
| GET | `/v1/admin/pendrive/provisioning/clients` | Query: `limit, q` | `{ ok, count, clients: [...] }` | Admin: lista clientes aptos para provision. Requiere `X-Admin-Key` |
| POST | `/v1/admin/pendrive/provisioning/validate` | `{ uid, serial, mark_completed }` | `{ ok, uid, cedula, nombre, serial_matches, ... }` | Admin: valida serial y opcionalmente confirma provision |
| GET | `/v1/admin/pendrive/recovery/{cliente_id}` | - | `{ ok, recovery_key }` | Admin: recupera recovery key. Requiere `X-Admin-Key` |

#### USB Provisioning (admin local)

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| GET | `/v1/usb/devices` | - | `{ ok, count, devices: [...] }` | Lista USB conectados en equipo local. Requiere `X-Admin-Key` |
| POST | `/v1/usb/provision` | `{ serial, drive?, force?, copy_installer? }` | `{ ok, message, code, steps }` | Ejecuta provision de entrega (vault + instalador). Requiere `X-Admin-Key` |
| GET | `/v1/usb/client-by-serial/{serial}` | - | `{ ok, serial, cedula, nombre, uid }` | Busca cliente por serial USB. Requiere `X-Admin-Key` |

### auto-venta1 API (solo backoffice interno)

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/api/clientes` | `ClienteCreate` | `ClienteResponse` | Requiere `X-Admin-Api-Key` |
| GET | `/api/clientes` | Query params | `ClienteResponse[]` | Filtros: cedula, nombre |
| PATCH | `/api/clientes/{cedula}/vencimiento` | `{ fecha_vencimiento }` | `ClienteResponse` | - |
| POST | `/api/auth/usb` | `{ cedula, clave, hardware_serial? }` | `{ ok }` | Login con pendrive |
| POST | `/api/auth/usb/register` | `{ cedula, hardware_serial }` | `{ ok }` | Vincular pendrive. Requiere `X-USB-Register-Key` |
| GET | `/api/usb/devices` | - | `USBDevice[]` | Solo equipo local |

### Chatbot-Cobro API (solo backoffice interno)

| Metodo | Ruta | Request | Response | Notas |
|--------|------|---------|----------|-------|
| POST | `/api/meta/webhook` | Meta payload | `200 OK` | Verificacion HMAC |
| GET | `/api/meta/webhook` | Query: `hub.mode, hub.challenge, hub.verify_token` | `hub.challenge` | Verificacion webhook |
| GET | `/health` | - | `{ status: "ok" }` | - |

## Contratos de base de datos

### Postgres compartido

Tabla **`clientes_suscripcion`** — fuente de verdad para auth y suscripciones.

| Columna | Tipo | Uso |
|---------|------|-----|
| `id` | UUID | PK |
| `cedula` | VARCHAR(32) UNIQUE | Identificador de login del cliente |
| `clave_acceso` | VARCHAR(128) | Hash bcrypt. Consumido por frontend/backend |
| `hardware_token_hash` | VARCHAR(128) UNIQUE | SHA-256(serial + pepper). Consumido por auth |
| `fecha_vencimiento` | DATE | Control de suscripcion activa |
| `plan` | VARCHAR(20) | `mensual`, `trimestral`, `anual` |
| `telefono` | VARCHAR(32) | Usado por Chatbot-Cobro para recordatorios |

Tabla **`subscription_reminder_outbox`** — ledger idempotente de recordatorios.

### Firestore

Coleccion **`users/{uid}`** — perfiles y tokens OAuth.
Coleccion **`user_google_tokens/{id}`** — tokens Google cifrados.

## Contratos Electron IPC (no romper)

| Channel | Direccion | Estado | Uso |
|---------|-----------|--------|-----|
| `nordik:secure-session-save` | Renderer -> Main | ✅ OK | Guardar sesion JWT |
| `nordik:secure-session-load` | Renderer -> Main | ✅ OK | Cargar sesion |
| `nordik:secure-session-clear` | Renderer -> Main | ✅ OK | Limpiar sesion |
| `nordik:usb-serial` | Renderer -> Main | ✅ OK | Leer serial de pendrive |
| `nordik:whatsapp-qr-data-url` | Renderer -> Main | ✅ OK | Generar data URL de QR |
| `nordik:open-url` | Renderer -> Main | ✅ OK | Abrir URL externa |
| `openclaw:install-automation-plugins` | Renderer -> Main | ✅ OK | Instalar plugins OpenClaw |
| `openclaw:start-whatsapp-login` | Renderer -> Main | ✅ OK | Iniciar login WhatsApp |
| `openclaw:stop` | Renderer -> Main | ✅ OK | Detener proceso OpenClaw |
| `openclaw:data` | Main -> Renderer | ✅ OK | Datos stdout/stderr de OpenClaw |
| `openclaw:exit` | Main -> Renderer | ✅ OK | Notificacion de salida de OpenClaw |

## Notas de versión

### v1 — Estrategia DeepSeek-only

A partir de Sprint 4, el campo `provider` en requests de chat es **ignorado**. El backend siempre enruta a DeepSeek independientemente del valor enviado. El frontend ya no envía `provider` en las requests de chat (v1.1).

### v2 (propuesto, backlog)

- Eliminar `ai_provider_id` del perfil (`UserProfilePatch` / `UserProfileDto`)
- Eliminar `ai_credentials` del perfil
- Eliminar `get_available_providers` del backend

## Capacidades OpenClaw integradas (v1)

Las siguientes capacidades de OpenClaw se consideran integradas en Nordik:

1. **WhatsApp channel login** — a traves de `openclaw:start-whatsapp-login` IPC
2. **Automation plugins** — a traves de `openclaw:install-automation-plugins` IPC con allowlist
3. **Gmail/Google Calendar** — OAuth Google via backend Nordik

## Notas de version

### v1.4 (2026-07-15)
- **WhatsApp Messaging**: Nuevos endpoints `/v1/whatsapp/message`, `/v1/whatsapp/outbound`, `/v1/whatsapp/messages`, `/v1/whatsapp/messages/list`. Comunicación bidireccional WhatsApp via bridge Electron.
- **WhatsApp Automation**: Nuevo endpoint `/v1/whatsapp/automation` para ejecutar automatizaciones desde WhatsApp.
- **WhatsApp Remote**: Nuevo endpoint `/v1/whatsapp/remote` para comandos remotos con whitelist.
- **WebSocket**: Nuevo endpoint `/ws/notifications` para notificaciones en tiempo real.
- **Fase 5–7 completada**: Deuda técnica P1-P2, pulido fino, jobs retención D5, build + updater + regression.

### v1.3 (2026-07-07)
- **Sprint 2.5 — Consumo IA y generacion de imagenes**: Nuevos endpoints `GET /v1/usage/summary` y `POST /v1/images/generate`. Codigo de error estable `ai_usage_limit_exceeded` (402) para tope mensual unificado de IA.

### v1.2 (2026-06-11)
- **Documentacion de endpoints completa**: Se agregaron todos los endpoints faltantes a este documento: Chat (`/v1/chat/*`), Documentos (`/v1/documents/generate`), Plantillas (`/v1/templates/*`), Automatizaciones (`/v1/automations/*`), Capacidades (`/v1/capabilities/*`), Telemetria (`/v1/telemetry/event`), Pendrive/Recovery (`/v1/pendrive/*`), USB Provisioning (`/v1/usb/*`), y Health DB (`/health/db`).
- **Sin cambios de implementacion**: Solo actualizacion de documentacion operativa (Fase 9).

### v1.1 (2026-06-08)
- **DeepSeek-only**: El backend ignora el campo `provider` en requests de chat. Siempre usa DeepSeek. El campo `ai_provider_id` en perfil se fija como `deepseek` desde el frontend.
- **WhatsApp Channel API**: Nuevos endpoints `/v1/whatsapp/channel/*` documentados arriba. Implementados en `whatsapp_channel.py`.
- **Electron IPC completado**: Todos los canales `openclaw:*` y `nordik:whatsapp-qr-data-url` ahora estan cableados en `main.cjs` + `preload.cjs`.
- **OAuth `/status`**: Endpoint `GET /oauth/google/status` propuesto para verificar tokens OAuth desde Firestore (no implementado aun).

### v1.0 (original)
- Contratos iniciales congelados de auto-venta1, Chatbot-Cobro, y Nordik API.

Capacidades NO integradas (pendientes para fases futuras):
- Tools locales de filesystem
- Creacion/edicion de documentos Office
- Chat engine con historial persistente
- Automatizaciones sin terminal (guiadas por UI)
