# Checklist de Regresión — Nordik-IA Pre-Demo

**Versión:** v3.0 (QA-Integration, Jul 2026)
**Propósito:** Verificación exhaustiva pre-demo y pre-release. Cubre todos los flujos críticos del producto DOT.
**Uso:** Marcar `[PASS]` o `[FAIL]` antes de cada demo, release o merge mayor. Si algo falla, detener y corregir.

---

## 1. LOGIN JWT (Cédula + Clave + Serial)

### 1.1 Login Básico

- [ ] `POST /v1/auth/login` con cédula + clave válidas devuelve `200` + `access_token` + `refresh_token`
- [ ] `POST /v1/auth/login` con cédula incorrecta devuelve `401` con mensaje en español
- [ ] `POST /v1/auth/login` con clave incorrecta devuelve `401` con mensaje en español
- [ ] `POST /v1/auth/login` con cédula vacía devuelve `400` o `422`
- [ ] `POST /v1/auth/login` con clave vacía devuelve `400` o `422`

### 1.2 Login con Pendrive (Hardware Token)

- [ ] `POST /v1/auth/login` con `hardware_serial` correcto pasa validación y devuelve `200`
- [ ] `POST /v1/auth/login` con `hardware_serial` incorrecto devuelve `401`
- [ ] `POST /v1/auth/login` sin `hardware_serial` cuando el cliente tiene `hardware_token_hash` devuelve `400` con `pendrive_required`
- [ ] `hardware_token_pepper` idéntico en frontend/backend y auto-venta1
- [ ] Hash en BD (`hardware_token_hash`) coincide al hacer login desde frontend

### 1.3 Refresh Token y Rotación

- [ ] `POST /v1/auth/refresh` con refresh token válido devuelve `200` + nuevo `access_token` + `refresh_token`
- [ ] `POST /v1/auth/refresh` con refresh token reusado (robo detectado) devuelve `401` y revoca toda la familia
- [ ] `POST /v1/auth/refresh` con refresh token expirado devuelve `401`

### 1.4 Logout

- [ ] `POST /v1/auth/logout` con access token válido revoca tokens y devuelve `204`
- [ ] `POST /v1/auth/logout` sin token devuelve `401`
- [ ] Después de logout, el access token anterior ya no es válido (`401`)

### 1.5 Información del Usuario

- [ ] `GET /users/me` con token válido devuelve datos del cliente (nombre, cédula, plan, vencimiento)
- [ ] `GET /users/me` sin token o token expirado devuelve `401`
- [ ] `GET /users/me` con token de cliente con suscripción vencida devuelve datos (no bloquea `/me`)

### 1.6 Suscripción

- [ ] Login con suscripción vencida devuelve `403` con `subscription_expired`
- [ ] Login con suscripción activa devuelve `200`
- [ ] Planes `mensual`, `trimestral`, `anual` se calculan correctamente

### 1.7 Mensajes de Error (UX)

- [ ] LoginScreen muestra error amigable en español para cada caso: `401`, `403`, `400`
- [ ] Error de red muestra mensaje claro ("Sin conexión al servidor")
- [ ] Error de servidor caído (503) muestra mensaje apropiado

---

## 2. CHAT IA (DeepSeek)

### 2.1 Envío de Mensajes

- [ ] `POST /v1/chat/send` con JWT válido y mensaje de texto devuelve `200` + respuesta del modelo
- [ ] `POST /v1/chat/send` sin JWT devuelve `401`
- [ ] `POST /v1/chat/send` con JWT expirado devuelve `401`
- [ ] `POST /v1/chat/send` con mensaje vacío devuelve `400` o `422`

### 2.2 Streaming (SSE)

- [ ] `POST /v1/chat/send/stream` emite eventos SSE válidos (`data: ...`)
- [ ] Streaming termina con evento `data: {"done": true}`
- [ ] Streaming no pierde conexión a mitad del mensaje
- [ ] Timeout de streaming maneja desconexión gracefully

### 2.3 Provider Routing

- [ ] DeepSeek es el provider por defecto (`default_chat_model=deepseek-chat`)
- [ ] Respuesta de DeepSeek contiene texto coherente (no error 500 del provider)
- [ ] Si DeepSeek falla, el error se traduce al español

### 2.4 Respuesta del Modelo

- [ ] Respuesta incluye `message_id` único
- [ ] Respuesta incluye `conversation_id` válido
- [ ] Tiempo de respuesta < 30s para mensajes cortos

### 2.5 Comandos del Chat

- [ ] `/doc` genera documento Word en Escritorio
- [ ] `/recordar` crea recordatorio
- [ ] `/buscar` realiza búsqueda web
- [ ] `/traducir` traduce texto
- [ ] `/resumir` resume contenido
- [ ] `/agenda` muestra eventos del día

---

## 3. CONVERSACIONES

### 3.1 CRUD de Conversaciones

- [ ] `POST /v1/chat/conversations` crea nueva conversación y devuelve `conversation_id`
- [ ] `GET /v1/chat/conversations` lista conversaciones del usuario (ordenadas por más reciente)
- [ ] `PATCH /v1/chat/conversations/{id}` renombra conversación
- [ ] `DELETE /v1/chat/conversations/{id}` soft-deletea conversación

### 3.2 Archivar

- [ ] `POST /v1/chat/conversations/{id}/archive` archiva conversación
- [ ] `POST /v1/chat/conversations/{id}/unarchive` desarchiva conversación
- [ ] `GET /v1/chat/conversations/archived` lista conversaciones archivadas

### 3.3 Búsqueda

- [ ] `GET /v1/chat/conversations/search?q=texto` busca mensajes en todas las conversaciones
- [ ] Búsqueda funciona con texto parcial
- [ ] Búsqueda sin resultados devuelve lista vacía

### 3.4 Historial de Mensajes

- [ ] `GET /v1/chat/conversations/{id}/messages` devuelve mensajes paginados
- [ ] Paginación funciona con `before` y `limit`
- [ ] Historial incluye tanto mensajes del usuario como respuestas del modelo

### 3.5 Aislamiento entre Usuarios

- [ ] Usuario A no puede ver conversaciones del Usuario B (403 o lista vacía)
- [ ] Usuario A no puede enviar mensajes a conversación del Usuario B (403)
- [ ] Usuario A no puede archivar/renombrar conversación del Usuario B (403)

### 3.6 Cifrado de Mensajes

- [ ] Mensajes se almacenan cifrados en BD (si `CHAT_ENCRYPTION_KEY` configurada)
- [ ] Mensajes se descifran correctamente al recuperarlos

---

## 4. WHATSAPP

### 4.1 Escaneo QR

- [ ] `GET /v1/whatsapp/channel/status` devuelve `connected: true/false`
- [ ] QR de WhatsApp se genera correctamente (spinner de pelotitas)
- [ ] QR tiene cuenta regresiva y se puede regenerar
- [ ] Escaneo de QR con WhatsApp mobile vincula correctamente

### 4.2 Envío/Recepción de Mensajes

- [ ] `POST /v1/whatsapp/messaging/send` envía mensaje a número WhatsApp
- [ ] Mensajes entrantes de WhatsApp se procesan y notifican vía WebSocket
- [ ] Auto-reply funciona cuando DOT es mencionado en grupo (`dot_group_mention`)
- [ ] Mensajes sin mención no generan auto-reply (si `require_mention=true`)

### 4.3 Automatizaciones WhatsApp

- [ ] `POST /v1/whatsapp/automation/execute` dispara automatización vía WhatsApp
- [ ] Pipeline de WhatsApp ejecuta comandos de archivo (crear txt, descargar PDF)

### 4.4 Deprecación

- [ ] `/v1/whatsapp/remote` responde `410 Gone` (endpoint deprecado)

---

## 5. GOOGLE (Gmail + Calendar)

### 5.1 OAuth Google

- [ ] `POST /oauth/google/start` con Bearer token devuelve `authorization_url`
- [ ] `POST /oauth/google/start` sin token devuelve `401`
- [ ] `GET /oauth/google/callback` completa flujo y guarda tokens en Firestore
- [ ] `GET /oauth/google/status` muestra estado de vinculación

### 5.2 Gmail

- [ ] Envío de correo funciona con OAuth activo
- [ ] Error de credenciales muestra mensaje claro en español
- [ ] Gmail envía correo con contenido correcto

### 5.3 Google Calendar

- [ ] `GET /v1/chat/agenda/today` devuelve eventos del día si OAuth activo
- [ ] Sin OAuth, devuelve `linked: false` con mensaje informativo
- [ ] Calendario muestra eventos con fecha, hora y título correctos

---

## 6. MEMORIA (DOT recuerda entre sesiones)

### 6.1 Persistencia

- [ ] `GET /users/me/memory` devuelve datos de memoria del usuario
- [ ] `PATCH /users/me/memory` actualiza y persiste memoria
- [ ] Memoria sobrevive a logout + relogin (persiste en Firestore)
- [ ] Memoria sobrevive a reinicio del backend

### 6.2 Embeddings

- [ ] Memoria usa embeddings para búsqueda semántica (si feature flag activo)
- [ ] Memoria no pierde datos en merge/compact

### 6.3 Seguridad

- [ ] Memoria no tiene inyección de prompt (sanitización)
- [ ] Usuario A no puede leer memoria del Usuario B

---

## 7. FRONTEND (Electron + React)

### 7.1 Arranque de la App

- [ ] App arranca en desarrollo (`npm run desktop`)
- [ ] App empaquetada arranca sin errores (si build existe)
- [ ] Sin pendrive conectado, muestra pantalla "Conecta tu llave Nordik"
- [ ] Con pendrive válido, app abre y permite login

### 7.2 Router (HashRouter)

- [ ] HashRouter funciona — URLs usan `#` (ej: `/#/login`, `/#/dashboard`)
- [ ] Navegación entre pantallas funciona sin recargar página completa
- [ ] Refresh en cualquier ruta no produce pantalla blanca
- [ ] Deep linking funciona (abrir app en ruta específica)

### 7.3 Sin Pantalla Negra

- [ ] LoginScreen renderiza correctamente (no pantalla negra)
- [ ] Dashboard renderiza correctamente tras login
- [ ] LoadingScreen se muestra durante carga (no pantalla negra)
- [ ] ErrorBoundary captura errores y muestra UI de fallback (no pantalla negra)

### 7.4 Sin "Failed to Fetch"

- [ ] Conexión al backend funciona (sin errores CORS)
- [ ] `api-client.ts` usa URL base correcta (`http://localhost:8000` en dev)
- [ ] Errores de red muestran mensaje amigable en UI
- [ ] Timeout de API muestra mensaje de reintento

### 7.5 Flujo Completo

- [ ] Login → Dashboard: flujo completo funciona
- [ ] Dashboard muestra datos de suscripción del cliente
- [ ] Chat panel renderiza mensajes correctamente
- [ ] UsageMeter muestra porcentaje de consumo IA
- [ ] StatusSidebar muestra estado de integraciones
- [ ] ConversationList muestra lista de conversaciones

### 7.6 Persistencia de Sesión

- [ ] `secure-session-save` guarda tokens en `safeStorage`
- [ ] `secure-session-load` recupera tokens al reiniciar
- [ ] `secure-session-clear` limpia tokens al logout
- [ ] Tras login exitoso, reiniciar con mismo pendrive restaura sesión
- [ ] Tras login exitoso, reiniciar con otro pendrive no restaura sesión

### 7.7 IPC (Electron)

- [ ] `nordik:usb-serial` devuelve serial del pendrive
- [ ] `nordik:usb-present` detecta presencia de pendrive
- [ ] `nordik:hardware-bind-*` gestiona huella hardware
- [ ] Al desconectar pendrive, sesión se limpia y vuelve al gate

### 7.8 Feature Flags

- [ ] `NORDIK_SKIP_USB_GATE=1` omite puerta USB solo en dev
- [ ] Build empaquetado no permite `SKIP_USB_GATE`
- [ ] `DOT_ENV=development` vs `production` tiene comportamientos distintos

---

## 8. SEGURIDAD

### 8.1 JWT

- [ ] JWT access token expira correctamente (según configuración, ~15 min)
- [ ] JWT refresh token expira correctamente (~7 días)
- [ ] JWT firmado con RS256 (producción) o HS256 (desarrollo)
- [ ] JWT contiene claims: `sub`, `token_use`, `exp`, `iat`, `jti`
- [ ] Token revocado no puede usarse para acceder a endpoints protegidos

### 8.2 WebSocket (WS requiere auth)

- [ ] `/ws/notifications` rechaza conexión sin token (`WS_1008_POLICY_VIOLATION`)
- [ ] `/ws/notifications` acepta conexión con JWT válido vía query param `?token=`
- [ ] `/ws/notifications` acepta conexión con JWT válido vía header `Authorization: Bearer`
- [ ] `/ws/notifications` rechaza conexión con JWT expirado
- [ ] CERRIFICADO: NO existe bypass de desarrollo para WS sin auth

### 8.3 CORS

- [ ] CORS permite orígenes configurados en `CORS_ALLOW_ORIGINS`
- [ ] CORS rechaza orígenes no configurados
- [ ] Métodos permitidos: `GET`, `POST`, `PATCH`, `DELETE`, `OPTIONS`
- [ ] Headers permitidos: `Authorization`, `Content-Type`, `Accept`, `X-Admin-Key`
- [ ] `OPTIONS` preflight responde correctamente

### 8.4 Rate Limiting

- [ ] `/v1/auth/login` limitado a 5/min (429 tras exceder)
- [ ] `/v1/chat/send` limitado a 30/min
- [ ] `/v1/chat/send/stream` limitado a 10/min
- [ ] Rate limit key usa JWT `sub` (si Bearer) o IP (si anónimo)

### 8.5 Cifrado

- [ ] Token encryption key válida (Fernet)
- [ ] Chat encryption key válida en producción (fail-closed)
- [ ] Mensajes de chat cifrados en reposo

### 8.6 Headers de Seguridad

- [ ] SecurityHeadersMiddleware agrega headers de seguridad
- [ ] X-Content-Type-Options: nosniff
- [ ] X-Frame-Options: DENY
- [ ] Content-Security-Policy configurado
- [ ] HSTS configurado en producción

### 8.7 Sanitización

- [ ] Inputs se sanitizan contra inyección SQL
- [ ] Inputs se sanitizan contra XSS
- [ ] Logging no expone secretos ni tokens
- [ ] Error responses no exponen stack traces en producción

---

## 9. BACKEND (FastAPI)

### 9.1 Health Endpoints

- [ ] `GET /health` devuelve `{"status": "ok"}` con código `200`
- [ ] `GET /health/db` verifica tablas billing + chat; `200` si ok, `503` si faltan
- [ ] `GET /health/full` verifica DB + Redis + DeepSeek + Scheduler
- [ ] `GET /health/scheduler` verifica estado del AutomationScheduler
- [ ] `GET /health/circuit-breakers` muestra estado de circuit breakers

### 9.2 Capabilities

- [ ] `GET /v1/capabilities/` requiere JWT válido
- [ ] `GET /v1/capabilities/` devuelve lista de capacidades con `id`, `label`, `description`, `enabled_by_default`
- [ ] Capacidades incluyen: `chat_completion`, `whatsapp_channel_login`, `automation_plugins`, `image_generation`, `web_search`, `file_tools`, `remote_execution`
- [ ] `GET /v1/capabilities/{capability_id}` devuelve detalle de capacidad específica

### 9.3 Arranque del Backend

- [ ] Backend arranca con `python -m uvicorn app.main:app`
- [ ] Preflight de configuración pasa: `python scripts/preflight_config.py --strict`
- [ ] Schema bootstrap aplica columnas faltantes automáticamente
- [ ] DB retry con backoff exponencial (5 intentos) funciona
- [ ] Graceful shutdown: SIGTERM/SIGINT detiene servicios ordenadamente

### 9.4 Servicios (Lifespan)

- [ ] Firestore inicializa correctamente (o warning si no disponible)
- [ ] AutomationScheduler arranca y se monitorea health cada 30s
- [ ] ReminderService inicializa
- [ ] RetentionService inicializa (si configurado)
- [ ] TemplateService inicializa
- [ ] Redis fanout inicializa (si REDIS_URL configurada)
- [ ] Monitoreo de scheduler: auto-restart si muere

### 9.5 Modo Producción

- [ ] `NORDIK_ENV=production` desactiva `/docs` y `/redoc`
- [ ] `NORDIK_ENV=production` desactiva OAuth dev
- [ ] `NORDIK_ENV=production` requiere CHAT_ENCRYPTION_KEY
- [ ] `NORDIK_ENV=production` requiere CORS_ALLOW_ORIGINS
- [ ] `NORDIK_ENV=production` advierte sobre pepper por defecto

---

## 10. CONSUMO IA (Sprint 2.5)

### 10.1 Límite de Consumo

- [ ] `GET /v1/usage/summary` devuelve `limit_usd`, `consumed_usd`, `remaining_usd`, `percent`, `blocked`
- [ ] Límite es `$7.50 USD/mes` por usuario
- [ ] Al llegar al 100%, chat/vision/imagen devuelven `402` con `ai_usage_limit_exceeded`
- [ ] Al 80%, se muestra warning en UsageMeter
- [ ] `AI_USAGE_LIMIT_ENABLED=false` en dev desactiva bloqueo por tope

### 10.2 Tracking de Costos

- [ ] Chat: costo basado en tokens de entrada/salida de DeepSeek
- [ ] Vision: costo basado en requests de Vertex Vision
- [ ] Imágenes: costo basado en imágenes generadas por Vertex Imagen
- [ ] Breakdown del consumo separa chat, vision e image_gen

### 10.3 Recarga IA (Admin)

- [ ] `POST /v1/admin/topup-ia-usage` con X-Admin-Key válido recarga crédito
- [ ] Recarga aplica margen 25% Nordik / 75% usuario
- [ ] Recarga sin X-Admin-Key devuelve `403`
- [ ] Recarga con monto inválido devuelve `400`

---

## 11. IMÁGENES Y VISIÓN

### 11.1 Generación de Imágenes

- [ ] `POST /v1/images/generate` con prompt válido devuelve `200` + imagen(es) en base64
- [ ] Límite de 4 imágenes por request
- [ ] Resolución por defecto: `1024x1024`
- [ ] Con `AI_USAGE_LIMIT_ENABLED=true` y tope agotado, devuelve `402`
- [ ] Sin Vertex configurado, endpoint devuelve error claro

### 11.2 Visión

- [ ] `POST /v1/vision/analyze` analiza imagen y devuelve descripción
- [ ] Formatos soportados: JPEG, PNG, WebP
- [ ] Costo de visión se registra en `usage_service`

---

## 12. PERFIL FIRESTORE

- [ ] `GET /users/me/profile` devuelve perfil del cliente autenticado
- [ ] `PATCH /users/me/profile` actualiza y retorna perfil mergeado
- [ ] Sin Firebase configurado, backend arranca con warning pero no crash
- [ ] Perfil persiste en Firestore colección `users/{uid}`
- [ ] Onboarding guarda selección de IA en perfil

---

## 13. DOCUMENTOS

- [ ] `POST /v1/documents/generate` crea documento (docx/xlsx/txt/pdf) en Escritorio
- [ ] Carpeta "Nordik Trabajos" se crea en Escritorio automáticamente
- [ ] Templates de documentos se cargan correctamente
- [ ] Render de template produce documento con datos correctos

---

## 14. AUTOMATIZACIONES

- [ ] `POST /v1/automations/execute` ejecuta automatización
- [ ] `GET /v1/automations/history` devuelve historial de ejecuciones
- [ ] `GET /v1/automations/results/{id}` devuelve resultado específico
- [ ] Toggle activo/inactivo funciona
- [ ] Programación horaria ejecuta en el momento correcto
- [ ] Composite automations ejecutan pipelines multi-step

---

## 15. ADMIN PANEL (auto-venta1)

- [ ] Panel auto-venta1: crear, editar, eliminar clientes
- [ ] Panel auto-venta1: paginación y filtros
- [ ] Panel auto-venta1: export CSV
- [ ] Panel auto-venta1: modal edición guarda todos los campos
- [ ] `POST /api/clientes` crea cliente con `X-Admin-Api-Key`
- [ ] `GET /api/clientes` lista clientes con filtros
- [ ] `PATCH /api/clientes/{cedula}/vencimiento` actualiza fecha
- [ ] Pendrive provisioning: crear vault, asociar serial

---

## 16. TELEMETRÍA Y MONITOREO

- [ ] `POST /v1/telemetry/event` registra evento de telemetría
- [ ] Sentry captura errores en producción
- [ ] Circuit breakers se abren tras fallos consecutivos
- [ ] Circuit breakers se cierran tras recovery timeout
- [ ] Logs respetan nivel configurado (DEBUG/INFO/WARNING/ERROR/CRITICAL)

---

## 17. AGENT RUNTIME (M2)

- [ ] Chat PC: comandos de archivo funcionan (crear txt en Escritorio)
- [ ] Chat PC: búsqueda web + guardar archivo funciona
- [ ] WhatsApp: mención en grupo crea archivo en Escritorio
- [ ] WhatsApp: descarga de URL a Escritorio funciona
- [ ] Gmail: envío con OAuth activo funciona
- [ ] Unit tests del agente: `pytest app/tests/test_agent_*.py` en verde
- [ ] Agent run queue procesa tareas sin bloquear
- [ ] Planner multi-step funciona para tareas complejas
- [ ] Truth check previene respuestas incorrectas o inseguras

---

## 18. RENDIMIENTO Y ESCALA

- [ ] Backend responde `/health` en < 100ms
- [ ] Login completo < 2s (incluyendo validación de pendrive)
- [ ] Chat send < 30s para mensajes cortos
- [ ] Chat streaming primer token < 2s
- [ ] WebSocket notificaciones < 1s de latencia
- [ ] Base de datos soporta 1000+ clientes sin degradación
- [ ] Rate limiting no afecta tráfico legítimo

---

## RESUMEN DE EJECUCIÓN

| # | Sección | PASS/FAIL | Fecha | Tester |
|---|---------|-----------|-------|--------|
| 1 | Login JWT | [ ] | | |
| 2 | Chat IA | [ ] | | |
| 3 | Conversaciones | [ ] | | |
| 4 | WhatsApp | [ ] | | |
| 5 | Google | [ ] | | |
| 6 | Memoria | [ ] | | |
| 7 | Frontend | [ ] | | |
| 8 | Seguridad | [ ] | | |
| 9 | Backend | [ ] | | |
| 10 | Consumo IA | [ ] | | |
| 11 | Imágenes/Visión | [ ] | | |
| 12 | Perfil | [ ] | | |
| 13 | Documentos | [ ] | | |
| 14 | Automatizaciones | [ ] | | |
| 15 | Admin Panel | [ ] | | |
| 16 | Telemetría | [ ] | | |
| 17 | Agent Runtime | [ ] | | |
| 18 | Rendimiento | [ ] | | |

**Resultado final:** [ ] PASS / [ ] FAIL — [ ] Aprobado para demo/release

**Notas / Issues encontrados:**
- 
- 
- 
