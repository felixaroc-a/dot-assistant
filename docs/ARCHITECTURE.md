# DOT — Documento de Arquitectura

> **Versión:** 2.0 · 2026-07-01
> **Estado:** Constitución técnica del proyecto. **Visión de producto unificada:** `docs/BIBLIA.md` (gana ante contradicciones de planes/features).
> **Próxima revisión:** Al completar el primer sprint de desarrollo.

---

## Prólogo

Este documento es la **constitución** de DOT. Define qué construimos, por qué lo construimos así, y cómo todas las piezas encajan. No es un manual técnico — es el **plano del sistema**.

**Cómo se usa:**
- Cada decisión aquí documentada tiene una razón explícita
- Si agregas una feature, primero verifica que no contradiga este plano
- Si encuentras un bug, el código se desvió del plano — corrígelo
- Si el plano ya no refleja la realidad, actualízalo **antes** de cambiar el código
- **Nada se programa sin pasar por este documento primero**

---

## 1. Filosofía del Producto

### 1.1 ¿Qué es DOT?

DOT es un asistente IA de escritorio para Windows que:

1. **Se conecta a WhatsApp escaneando un QR** — sin configuración técnica
2. **Actúa en tu PC** — busca archivos, descarga documentos, automatiza tareas
3. **Se integra con Google** (Gmail, Calendar) — autorización con un clic vía OAuth
4. **Ejecuta automatizaciones** — instrucciones en lenguaje natural que DOT ejecuta por ti

**La promesa:** *"En 2 minutos escaneas un QR y desde ese momento tienes un asistente que vive en tu PC y en tu WhatsApp. Todo desde un pendrive que es tu llave de acceso."*

**Casos de uso reales:**
- "Descarga este PDF que está en mi Gmail y guárdalo en Escritorio"
- "Manda este archivo a mi WhatsApp"
- "Échale un ojo a los correos del banco y dime si hay facturas pendientes"
- "Créame una carpeta en Documentos con el nombre de la empresa"

### 1.2 ¿Qué NO es DOT?

- No es un chatbot web más (tipo ChatGPT web)
- No es un IDE. No está hecho para programar
- No es una app móvil
- No requiere servidor, Docker, o terminal
- No es open source. El código es propietario

### 1.3 Principios de diseño (ordenados por prioridad)

| Prioridad | Principio | Por qué |
|-----------|-----------|---------|
| **P0** | **Sin terminal** | El cliente final nunca ve una línea de comandos |
| **P0** | **El pendrive es la llave** | Sin el USB físico no hay acceso. El producto ES el pendrive. No se puede usar DOT sin él |
| **P0** | **Offline-first** | En Venezuela el internet es malo y caro. DOT funciona aunque la conexión sea intermitente |
| **P1** | **Configuración cero** | El vendedor preconfigura todo. El cliente solo conecta el USB, autoriza, y ya |
| **P1** | **Interfaz tipo Apple** | Blanco, negro, minimalista. Sin ruido visual. Experiencia premium |
| **P1** | **Seguridad ante todo** | Zero-trust. Seguridad primero, rendimiento después, costo después |
| **P2** | **Escalabilidad consciente** | Arquitectura pensada para crecer, pero se implementa cuando se necesita |
| **P2** | **Código limpio** | Archivos <300 líneas, una responsabilidad por función, pruebas obligatorias |

### 1.4 Perfil de usuario

**Cliente final:**
- No tiene conocimientos técnicos
- Usa WhatsApp y Gmail diariamente
- Quiere automatizar tareas repetitivas en su PC
- No sabe qué es una API ni le interesa
- Usa Windows 10 u 11
- Su internet puede ser lento o inestable

**Vendedor (interno de la empresa):**
- Personal que entrega el producto al cliente
- Preconfigura el pendrive con las credenciales del cliente usando DOT-Venta
- Es el punto de contacto físico con el cliente

### 1.5 Planes de precios

| Plan | Precio | ¿Qué incluye? | Límites de uso |
|------|--------|---------------|----------------|
| **Único** | **$10/mes** | **Todas las capacidades**: chat IA, WhatsApp, integración Google, automatizaciones, plugins, file tools, visión. Automatizaciones ilimitadas. | **$7.50/mes en costos de IA** (~50M tokens combinados). 25% de ganancia mínima por usuario. |

**¿Por qué este límite?** El negocio debe ser sostenible. Con $10/mes de ingreso, si la IA le cuesta a la empresa más de $7.50, no hay negocio. El límite está en ese punto: **25% de margen mínimo garantizado por usuario**.

### Cálculo de costos reales (DeepSeek)

| Tipo de token | Precio por 1M |
|--------------|---------------|
| Input normal | $0.14 |
| Input guardado (caché) | $0.028 |
| Output (respuesta) | $0.28 |

**Costo promedio ponderado** (uso típico: 70% input, 10% caché, 20% output):

= (0.70 × $0.14) + (0.10 × $0.028) + (0.20 × $0.28)
= $0.098 + $0.0028 + $0.056
= **$0.1568 por 1M de tokens ponderados**

**Límite en tokens:** $7.50 ÷ $0.1568 × 1M = **~47.8M tokens/mes** → Redondeamos a **50M tokens/mes** (45% de margen real).

Los costos de Gemini (visión) se agregarán cuando se defina el modelo exacto. Se acumulan contra el mismo límite de $7.50/mes.

### Cómo se controla el límite

1. Cada request a la IA registra: modelo, `tokens_prompt`, `tokens_completion`, `tokens_cached` (si aplica)
2. El backend calcula el **costo en dólares** de cada request usando los precios actuales configurados
3. Tabla `usage_tokens` acumula por cliente: fecha, modelo, tokens_in, tokens_out, costo_total
4. Al 80% del límite ($6.00): notificación push al usuario + alerta al admin
5. Al 100% ($7.50): el chat continúa con el modelo de menor costo y se ofrece recarga de tokens
6. El backend valida este límite **en cada request** — el frontend no puede saltárselo
7. Si un usuario excede consistentemente el límite, se evalúa plan empresarial personalizado

---

## 2. El Ecosistema DOT

DOT no es una app sola. Es un **ecosistema de 3 aplicaciones** que trabajan juntas:

```
┌──────────────────────────────────────────────────────────────┐
│                     ECOSISTEMA DOT                            │
│                                                              │
│  ┌─────────────────┐   ┌─────────────────┐   ┌────────────┐  │
│  │   DOT-Admin      │   │   DOT-Venta     │   │    DOT     │  │
│  │   (Backoffice)   │──►│   (Vendedor)    │──►│  (Cliente) │  │
│  │                  │   │                 │   │            │  │
│  │  Crea vendedores │   │  Crea clientes  │   │ Asistente  │  │
│  │  Gestiona         │   │  Prepara USB    │   │ IA desktop │  │
│  │  suscripciones   │   │  Entrega DOT    │   │ Chat, WA,  │  │
│  │  Estadísticas    │   │  al cliente     │   │ Google...  │  │
│  └─────────────────┘   └─────────────────┘   └────────────┘  │
│                                                              │
│         ┌─────────────────────────────────────┐              │
│         │      Comparten: PostgreSQL           │              │
│         │      (clientes_suscripcion)          │              │
│         └─────────────────────────────────────┘              │
└──────────────────────────────────────────────────────────────┘
```

### 2.1 DOT-Admin (Backoffice interno)

**¿Qué es?** Panel administrativo para el dueño/administrador del servicio.

**Funciones:**
- Crear y gestionar vendedores (login, permisos)
- Ver estadísticas de ventas, suscripciones activas, vencimientos
- Configurar precios y planes
- Reportes de uso y facturación

**Tecnología:** FastAPI + Jinja2 (o React) en puerto 8001.

### 2.2 DOT-Venta (App del vendedor)

**¿Qué es?** Aplicación de escritorio para Windows que usan los vendedores para preparar y entregar el producto.

**Funciones:**
- Registrar nuevos clientes (cédula, nombre, email, plan)
- **Preparar pendrive USB** con:
  - Hardware token único (PendriveID) — el serial del USB se registra contra el cliente
  - Instalador portable de DOT (`DOT-portable.exe`)
  - Recovery key cifrada
- Entregar el USB al cliente físicamente

**Tecnología:** React 19 + Electron 40 + FastAPI (backend propio, puerto 8001).

**Ubicación del código:** `apps/dot-venta/`

### 2.3 DOT (App del cliente final)

**¿Qué es?** El producto que usa el cliente. Un asistente IA de escritorio.

**Funciones:**
- Chat con IA (DeepSeek)
- WhatsApp (enviar/recibir mensajes vía OpenClaw)
- Gmail y Google Calendar (vía OAuth 2.0)
- Automatizaciones en lenguaje natural
- Visión de imágenes (Gemini)
- Búsqueda web

**Tecnología:** React 19 + Electron 40 + FastAPI (backend, puerto 8000).

**Ubicación del código:** `apps/dot/`

---

## 3. Vista General del Sistema

### 3.1 Diagrama de arquitectura

```
┌──────────────────────────────────────────────────────────────────┐
│                    PC DEL CLIENTE (Windows)                       │
│                                                                   │
│  ┌──────────────────┐   ┌────────────────┐   ┌────────────────┐  │
│  │   Renderer        │   │   Preload      │   │  Electron Main  │  │
│  │  (React 19 + Vite)│◄──┤  (context      │◄──┤  (Node.js)      │  │
│  │  TypeScript 5.7   │   │   Bridge)      │   │                 │  │
│  │                   │   │                │   │  safeStorage ◄──┤──┤
│  │  Zustand (estado) │   │  40+ APIs      │   │  Pendrive Vault │  │
│  │  i18n (idiomas)   │   │  expuestas     │   │  OpenClaw proc  │  │
│  │  Router v7        │   │                │   │  Auto-updater   │  │
│  └────────┬──────────┘   └────────────────┘   └────────┬────────┘  │
│           │                                             │           │
│           │  HTTPS (producción)                         │           │
│           │  HTTP (desarrollo local)                    │           │
└───────────┼─────────────────────────────────────────────┼───────────┘
            │                                             │
            ▼                                             ▼
┌──────────────────────┐   ┌──────────────────────────────────────┐
│   FastAPI :8000       │   │     OpenClaw (proceso Node.js)      │
│   (Python 3.11+)      │   │     npm package externo             │
│                       │   │                                      │
│  23 routers           │   │  - Login WhatsApp vía QR             │
│  31 services          │   │  - Envío/recepción de mensajes       │
│  Rate limiting        │   │  - Plugins de automatización         │
│  Sentry + Logtail     │   │                                      │
│  Worker (automatiz.)  │   └──────────────────────────────────────┘
└──────┬────────┬──────┘
       │        │
       ▼        ▼
┌────────────┐  ┌────────────────────────────┐
│  Postgres 14 │  │      Firestore (Google)    │
│             │  │                             │
│ clientes_   │  │  users/{uid}               │
│ suscripcion │  │  user_google_tokens/{id}   │
│ usage_tokens│  │  (cifrado con Fernet)       │
│ reminder_   │  │                             │
│ outbox      │  └────────────────────────────┘
└────────────┘
```

### 3.2 Componentes del sistema

| Componente | Tecnología | Puerto | Rol |
|------------|------------|--------|-----|
| **Frontend DOT** | React 19 + TypeScript 5.7 + Vite 6 | 5173 (dev) | Interfaz de usuario del cliente |
| **Electron DOT** | Electron 40 + electron-builder 26 | - | Shell de escritorio nativo Windows |
| **Backend DOT** | Python 3.11+ + FastAPI | 8000 | API REST + WebSocket + Worker |
| **Worker DOT** | Python (proceso hijo del backend) | - | Sandbox para ejecutar automatizaciones |
| **OpenClaw** | Node.js (paquete npm: `openclaw`) | - | Bridge para WhatsApp |
| **Frontend DOT-Venta** | React 19 + Electron 42 | - | App del vendedor |
| **Backend DOT-Venta** | Python 3.11+ + FastAPI | 8001 | API del vendedor |
| **PostgreSQL** | 14+ | 5432 | Datos transaccionales (suscripciones, uso) |
| **Firestore** | Firebase (Google) | - | Perfiles flexibles y tokens OAuth cifrados |

### 3.3 Flujo de extremo a extremo

```
CLIENTE RECIBE SU PENDRIVE DOT
  │
  ▼
Conecta el USB en su PC Windows
  │
  ▼
AutoPlay pregunta: "¿Ejecutar DOT-portable.exe?" → Usuario acepta
  │
  ▼
Primera ejecución:
  ├── DOT se INSTALA en Program Files (con permiso del usuario)
  ├── Se registra en Inicio de Windows (arranca con el sistema)
  └── El acceso completo requiere el USB conectado
  │
  ▼
App inicia → Splash → LoginScreen
  │
  ▼
Usuario ingresa cédula + contraseña
  │
  ▼
Electron lee el serial del USB conectado
  │
  ▼
POST /v1/auth/login {cedula, password, hardware_serial}
  → Backend valida contra Postgres
  → bcrypt(password) ✅ + hardware_token_hash == SHA-256(serial+pepper) ✅
  → fecha_vencimiento >= today ✅
  │
  ▼
JWT emitido → guardado en safeStorage (cifrado del SO, NO localStorage)
  │
  ▼
PendriveAppGate confirma que el USB sigue conectado
  │
  ▼
OnboardingFlow (7 pasos):
  1. Seleccionar canal (WhatsApp)
  2. Escanear QR (OpenClaw procesa el login)
  3. Elegir integraciones (Gmail, Calendar)
  4. Autenticar Google OAuth
  5. Resumen de integraciones
  6. Confirmación final
  7. Elegir nombre preferido
  │
  ▼
Dashboard → Chat IA + Automatizaciones
```

### 3.4 Decisiones arquitectónicas clave

| Decisión | Elegida | Descartada | Razón |
|----------|---------|------------|-------|
| **Capa de datos** | Postgres + Firestore | Solo Postgres | Postgres para datos transaccionales (JOINs, ACID). Firestore para perfiles flexibles sin schema fijo |
| **Autenticación** | JWT propio (RS256) | Firebase Auth | Control total sobre validación, rotación y revocación. Sin depender de terceros |
| **IA principal** | DeepSeek API | OpenAI, Gemini | Costo ($10/mes vs $50+), buena calidad en español |
| **Visión** | Vertex AI (Gemini) — ver §3.5 | DeepSeek (no soporta visión) | Análisis de imágenes; Vertex recomendado en prod |
| **WhatsApp** | OpenClaw (npm) | WhatsApp Business API | Sin aprobación de Meta, sin costo fijo mensual, sin burocracia |
| **Desktop** | Electron | Tauri, NW.js | safeStorage nativo, ecosistema maduro, distribución Windows sencilla |
| **USD como llave** | Pendrive físico | Token blando | Seguridad real: el atacante necesita acceso FÍSICO al USB |
| **Backend validation** | Servidor valida todo | Solo frontend | El servidor es la autoridad final. El frontend es solo la interfaz |
| **Código compartido** | `dot-billing` (editable) | Copiar código | Un solo lugar para modelos SQLAlchemy, cambios sincronizados |

---

### 3.5 Visión y generación de imágenes

Sprint 2 entrega **análisis de imágenes** (describe, OCR, preguntas sobre una foto adjunta). La generación activa de imágenes (texto → imagen) queda en **Sprint 2.5**; no implementar ni prometer esa capacidad hasta actualizar este apartado.

#### Proveedor recomendado: Vertex AI

Vertex AI es el proveedor recomendado en producción: trazas de latencia, control de costos en GCP y las credenciales permanecen en el servidor (el cliente Electron nunca recibe API keys de Gemini).

| Modo | `GEMINI_PROVIDER` | Proyecto / región | Credenciales | Modelo |
|------|-------------------|-------------------|--------------|--------|
| **Recomendado** | `vertex` | `GOOGLE_CLOUD_PROJECT` (alias `GCP_PROJECT`), `GOOGLE_CLOUD_LOCATION` (default `us-central1`) | ADC vía `GOOGLE_APPLICATION_CREDENTIALS` (JSON de cuenta de servicio) o `gcloud auth application-default login` en dev | `GEMINI_VERTEX_MODEL` (default `gemini-2.5-flash`) |
| **Fallback** | `api_key` (default en código si no se define) | — | `GEMINI_API_KEY` | `GEMINI_MODEL` (default `gemini-1.5-flash`) |

Con Vertex son obligatorios `GOOGLE_CLOUD_PROJECT` y ADC válido (`GOOGLE_APPLICATION_CREDENTIALS` o login ADC local). `GOOGLE_CLOUD_LOCATION` y `GEMINI_VERTEX_MODEL` tienen default en servidor. La cuenta de servicio debe tener permisos para invocar modelos generativos en Vertex (p. ej. rol *Vertex AI User*). El backend requiere el paquete Python `vertexai` (Vertex AI SDK).

**Credenciales:** Vertex usa Application Default Credentials. En `.env` del backend define `GOOGLE_APPLICATION_CREDENTIALS` apuntando al JSON de la cuenta de servicio (puede ser el mismo archivo que `FIREBASE_SERVICE_ACCOUNT_PATH` si esa SA tiene rol Vertex). `FIREBASE_SERVICE_ACCOUNT_PATH` alimenta Firebase Admin SDK; no sustituye por sí sola a `GOOGLE_APPLICATION_CREDENTIALS` para Vertex.

#### Flujo en runtime

```
DotChatPanel (adjunto / drag / paste)
  → POST /v1/vision/analyze  (JWT + multipart: file, prompt?)
  → vision_service.analyze_image()
       ├── GEMINI_PROVIDER=vertex → vision_vertex_service (SDK vertexai)
       └── GEMINI_PROVIDER=api_key → Gemini REST (generativelanguage.googleapis.com)
  → { "result": "..." } → burbuja del asistente en chat
```

Límites: imágenes `image/jpeg`, `image/png`, `image/webp`; máximo 10 MB (validación frontend y backend). Autenticación: JWT de producto (`require_product_jwt`); suscripción vencida en el token → 403 `subscription_expired`. No hay gating por capability `image_generation` en v1.

**Prompt por defecto:** el chat Electron envía `Analiza esta imagen y describe lo importante.` si el usuario no escribe texto (`useChat.ts`). Llamadas directas a la API sin `prompt` usan el default del router: `Describe esta imagen en detalle.`

#### Documentación relacionada

| Documento | Contenido |
|-----------|-----------|
| `docs/env-registry.md` | Variables `GEMINI_*`, `GOOGLE_CLOUD_*`, `GOOGLE_APPLICATION_CREDENTIALS` |
| `docs/public-api.md` | Contrato HTTP de `POST /v1/vision/analyze` |
| `docs/DOTTEST-SPRINT2.md` | Pruebas manuales Sprint 2 (adjuntar, drag, paste, temas) |

**Sin secretos en el repo:** API keys, JSON de cuentas de servicio y rutas reales viven solo en `.env` local o secretos del servidor.

---

## 4. Modelo de Datos

### 4.1 Postgres — `clientes_suscripcion`

**Propósito:** Fuente de verdad para autenticación y suscripciones.

```sql
CREATE TABLE clientes_suscripcion (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cedula VARCHAR(32) UNIQUE NOT NULL,
    clave_acceso VARCHAR(128) NOT NULL,
    hardware_token_hash VARCHAR(128) NOT NULL UNIQUE,  -- OBLIGATORIO. SHA-256(serial + pepper)
    fecha_vencimiento DATE NOT NULL,
    plan VARCHAR(20) NOT NULL DEFAULT 'mensual',
    telefono VARCHAR(32),
    correo VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_clientes_cedula ON clientes_suscripcion(cedula);
CREATE INDEX idx_clientes_hardware ON clientes_suscripcion(hardware_token_hash);
```

**Notas:**
- `hardware_token_hash` es **OBLIGATORIO**. Sin pendrive no hay DOT. El cliente no puede acceder sin su USB
- `clave_acceso` usa bcrypt. Si hay clients legacy con texto plano, migrar con script
- `fecha_vencimiento < today` → acceso denegado. Simple, sin ambigüedad

### 4.2 Postgres — `usage_tokens`

**Propósito:** Control de consumo de API de IA para límites por plan.

```sql
CREATE TABLE usage_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID NOT NULL REFERENCES clientes_suscripcion(id),
    fecha DATE NOT NULL DEFAULT CURRENT_DATE,
    modelo VARCHAR(50) NOT NULL DEFAULT 'deepseek-chat',
    tokens_prompt BIGINT NOT NULL DEFAULT 0,
    tokens_completion BIGINT NOT NULL DEFAULT 0,
    tokens_cached BIGINT NOT NULL DEFAULT 0,
    costo_total DECIMAL(10, 6) NOT NULL DEFAULT 0,  -- En dólares, calculado con precios actuales
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_usage_cliente_fecha ON usage_tokens(cliente_id, fecha);
```

**Cómo funciona:**
- Cada request a la IA devuelve metadatos de uso
- El backend calcula el costo en dólares con los precios del proveedor
- Acumula en `usage_tokens` y suma `costo_total` del mes en curso
- Cuando `SUM(costo_total)` del mes ≥ $6.00: alerta al usuario (80%)
- Cuando ≥ $7.50: degradación del modelo y oferta de recarga (100%)
- Un usuario normal consume ~$3-5/mes en tokens (~20-35M tokens)

### 4.3 Postgres — `subscription_reminder_outbox`

**Propósito:** Ledger de recordatorios de vencimiento (idempotente).

```sql
CREATE TABLE subscription_reminder_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID REFERENCES clientes_suscripcion(id),
    reminder_type VARCHAR(50) NOT NULL,
    sent_at TIMESTAMP DEFAULT NOW(),
    channel VARCHAR(20) DEFAULT 'whatsapp',
    status VARCHAR(20) DEFAULT 'sent'
);
```

### 4.4 Firestore — `users/{uid}`

**Propósito:** Perfil de usuario, configuraciones y automatizaciones guardadas.

```json
{
  "uid": "<cliente_id UUID>",
  "display_name": "string",
  "channel_id": "string",
  "ai_provider_id": "deepseek",
  "integrations": ["gmail", "calendar"],
  "automation_summary": "string",
  "onboarding_completed": true,
  "saved_automations": [
    {
      "id": "uuid",
      "name": "Descargar facturas",
      "integration_id": "gmail",
      "instruction": "Busca facturas de este mes y descárgalas",
      "active": true,
      "output_type": "files",
      "schedule": "0 9 * * 1"
    }
  ],
  "costo_ia_mes_actual": 3.45,           -- En dólares, para mostrar consumo al usuario
  "limite_costo_ia_mensual": 7.50,        -- Límite en dólares para este cliente
  "updated_at": "timestamp"
}
```

### 4.5 Firestore — `user_google_tokens/{id}`

**Propósito:** Tokens OAuth de Google, SIEMPRE cifrados con Fernet.

```json
{
  "id": "<cliente_id>",
  "encrypted_credentials": "<Fernet-encrypted blob>",
  "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
  "created_at": "timestamp",
  "updated_at": "timestamp"
}
```

### 4.6 Regla de dos bases de datos

| Criterio | Postgres | Firestore |
|----------|----------|-----------|
| Datos | Suscripciones, auth, billing, uso | Perfiles, config, tokens OAuth |
| Consultas | JOINs, transacciones ACID | Lecturas individuales por ID |
| Escritura | Backend + DOT-Venta + DOT-Admin | Solo backend (DOT) |
| Cifrado | En reposo (disco) | Fernet por campo sensible |

**Regla:** JOINs y transacciones van a Postgres. Perfiles flexibles sin joins van a Firestore.

---

## 5. Seguridad

### 5.1 Modelo de confianza: ZERO TRUST

**Supuesto:** El atacante controla el PC del usuario. Puede descompilar el binario, inspeccionar memoria, interceptar tráfico local, manipular disco.

**Respuesta:** El servidor es la autoridad final. No importa lo que haga el cliente, el servidor siempre valida.

### 5.2 Activos críticos

| Activo | Dónde está | Si se compromete |
|--------|-----------|------------------|
| JWT access/refresh | safeStorage del OS (cifrado) | Suplantación de sesión |
| Llave RSA de JWT | Servidor (`.env`) | Firma de tokens arbitrarios |
| Tokens OAuth Google | Firestore (cifrado Fernet) | Acceso a Gmail/Calendar |
| Service Account Firebase | Solo servidor | Lectura/escritura Firestore |
| IPC OpenClaw | Main process | Ejecución de código vía npm |

### 5.3 Controles implementados

| Control | Estado | Cómo funciona |
|---------|--------|---------------|
| **JWT asimétrico RS256** | ✅ | Servidor firma. Cliente no puede modificar claims. Clave privada solo en servidor |
| **Segundo factor físico (USB)** | ✅ | Sin el pendrive conectado no hay acceso. SHA-256(serial + pepper) se verifica en servidor |
| **safeStorage** | ✅ | JWT guardados con API de cifrado del SO. Ni siquiera Electron puede leerlos sin el usuario |
| **Rotación de refresh tokens** | ✅ | Cada refresh emite uno nuevo. Reutilizar el anterior = revocación de toda la familia |
| **CSP en Electron** | ✅ | Content-Security-Policy. Solo orígenes explícitos permitidos |
| **CORS estricto** | ✅ | Sin comodines. Orígenes explícitos |
| **Rate limiting** | ✅ | 10 intentos/min login, 30/min API general |
| **Fernet para tokens** | ✅ | OAuth tokens cifrados en Firestore. Clave independiente para chats |
| **Allowlist de plugins npm** | ✅ | Solo paquetes aprobados pueden instalarse |
| **Anti-DevTools producción** | ✅ | DevTools bloqueado en builds release |
| **Validación servidor** | ✅ | El frontend solo muestra/esconde. El servidor SIEMPRE valida |
| **Límite de tokens** | ✅ | Control de consumo de IA por cliente. Se valida servidor-side |

### 5.4 Pendientes de seguridad (priorizados)

| # | Hallazgo | Severidad | Prioridad | Dependencia |
|---|----------|-----------|-----------|-------------|
| S-01 | Sin HTTPS en producción | **Crítica** | **Sprint 3** | Requiere dominio o Cloudflare Tunnel |
| S-02 | Fail-open en cifrado de chats | Alta | **Sprint 2** | Fix en crypto_service: falla duro si falta clave |
| S-03 | WebSocket acepta "anon" | Alta | **Sprint 0** | Validar JWT en conexión WebSocket |
| S-04 | Sin firma de código (Authenticode) | Media | **Sprint 3** | Certificado de firma (~$300/año) |
| S-05 | Secretos en historial git | Media | **Sprint 0** | Rotación + scrub de historial |

### 5.5 Principios inquebrantables (de los documentos maestros)

1. **"Primero seguro, luego rápido, luego barato"** — No se sacrifica seguridad por velocidad
2. **HTTPS obligatorio en producción** — JWT nunca viajan en texto plano
3. **Fail-closed** — Si falta una clave de cifrado, el sistema falla. No cae a texto plano
4. **Zero-trust** — No confiar en nada del lado del cliente
5. **Validación servidor-side** — El frontend es decorativo, el servidor es la autoridad
6. **No hardcodear secrets nunca** — Ni en desarrollo

---

## 6. Autenticación y Sesiones

### 6.1 Flujo de login

```
                Frontend                    Backend                  Postgres
                   │                          │                        │
                   │  POST /v1/auth/login      │                        │
                   │  {cedula, password,       │                        │
                   │   hardware_serial}        │                        │
                   │─────────────────────────►│                        │
                   │                          │  SELECT FROM           │
                   │                          │  clientes_suscripcion  │
                   │                          │  WHERE cedula = ?      │
                   │                          │───────────────────────►│
                   │                          │◄───────────────────────│
                   │                          │  (fila del cliente)    │
                   │                          │                        │
                   │                          │  Validaciones:         │
                   │                          │  1. bcrypt(password)   │
                   │                          │     == clave_acceso    │
                   │                          │  2. SHA256(serial +    │
                   │                          │     pepper) ==         │
                   │                          │     hardware_token_hash│
                   │                          │  3. fecha_vencimiento  │
                   │                          │     >= today           │
                   │                          │                        │
                   │  {access_token,          │                        │
                   │   refresh_token,         │                        │
                   │   cliente}               │                        │
                   │◄─────────────────────────│                        │
                   │                          │                        │
                   │  Guardar en safeStorage  │                        │
                   │  (NUNCA localStorage)    │                        │
```

### 6.2 Rotación de tokens

**Access Token (RS256):**
- Duración: 30 minutos
- Contenido: `sub` (cliente_id), `cedula`, `plan`, `pendrive_bound`, `iat`, `exp`
- Transporte: `Authorization: Bearer <token>`

**Refresh Token (UUID v4):**
- Duración: 7 días
- Almacenamiento: Tabla `token_family` con hash SHA-256
- Rotación: Cada refresh emite un nuevo par
- Seguridad: Reutilizar uno antiguo = revocación de toda la familia. El usuario debe hacer login de nuevo

### 6.3 Login con pendrive (único flujo permitido)

1. Cliente conecta el USB. **Si no hay USB, no hay DOT**
2. Electron detecta el pendrive y lee el serial vía WMI
3. Frontend envía `{ cedula, password, hardware_serial }` al backend
4. Backend verifica las 3 condiciones (cedula, contraseña, USB)
5. JWT emitido. El servidor sabe que este token nació con `pendrive_bound: true`
6. Si el USB se desconecta durante la sesión, la app debe mostrar pantalla de reconexión

### 6.4 El USB como llave física — ¿cómo funciona en la práctica?

**Al conectar el USB por primera vez:**
1. Windows AutoPlay pregunta: "¿Ejecutar DOT-portable.exe?" → El usuario acepta
2. DOT se ejecuta desde el USB. En la primera ejecución:
   - Se **instala en Program Files** con permiso del usuario (como cualquier programa)
   - Se registra en **Inicio de Windows** (arranca automáticamente con el sistema)
   - El acceso completo requiere tener el USB conectado
3. Si el USB está conectado, DOT inicia sesión automáticamente (sesión recordada)
4. Si el USB NO está conectado, DOT se abre pero muestra: *"Conecta tu pendrive DOT para continuar"*

**Si intentan copiar DOT a otro PC:**
- Sin el vault del USB, el login falla (el servidor rechaza el hardware_serial)
- El servidor es la autoridad final, no importa qué binario tengan

**Sobre "indescifrable":**
- El binario se ofusca con `electron-builder` + `asar` + ofuscación
- Nada es 100% indescifrable. La seguridad real está en el servidor

### 6.5 Flujo de "Pendrive Perdido" (Backup y Reactivación en Tienda)

**Política de negocio:** La `recovery_key` **no es la vía principal** de recuperación. El modelo de negocio prioriza la venta de un pendrive nuevo con descuento en tienda física (DOT-Venta). El flujo de `recovery_key` (ver §6.6) queda como vía **secundaria/opcional/deprecated** mientras exista en código; no se elimina sin decisión explícita del producto.

**Flujo deseado (fase futura — documentado, no implementado por completo):**

1. **Reporte de pérdida:** El usuario reporta la pérdida del pendrive desde la app (cédula + contraseña). El backend inicia un proceso de backup/descarga del contexto disponible en servidor.
2. **Backup en servidor:** Se preserva el contexto del usuario almacenado en Firestore (`users/{uid}`) y datos de suscripción en Postgres (`clientes_suscripcion`). El objetivo es no perder conversaciones, perfil y configuración.
3. **Estado en base de datos:** El backend marca el serial antiguo como bloqueado/invalidado en `clientes_suscripcion` (p. ej. estado `PENDING_RECOVERY`) para evitar suplantación.
4. **Notificación al administrador:** Solicitud visible en `DOT-Admin` con cédula, historial de compra y tienda asignada.
5. **Venta de pendrive nuevo:** El cliente adquiere un pendrive DOT nuevo con **descuento** en tienda. El vendedor en `DOT-Venta` activa el nuevo serial asociado a la misma cédula.
6. **Restauración en tienda:** En el punto de venta (DOT-Venta), el contexto respaldado se restaura al nuevo pendrive antes de entregarlo al cliente (o en el primer login con el USB nuevo, según implementación futura).

> **Limitación actual (no prometer al cliente):** No se garantiza restauración **completa** del contexto hasta unificar Firestore + Postgres en una única fuente de verdad coherente. Hasta entonces, la restauración puede ser parcial según qué datos residan en cada store.

### 6.6 Login sin pendrive vía recovery_key (secundario / deprecated)

> **Estado:** Vía **secundaria y opcional**. No sustituye al flujo principal de §6.5 (pendrive nuevo en tienda). El código existente (`POST /v1/pendrive/recovery-login`, banner de guardado de clave) se mantiene; la biblia lo marca como deprecated para nuevas integraciones de producto.

Para acceso temporal inmediato antes de ir a la tienda (si el cliente conservó su `recovery_key`):

1. `POST /v1/pendrive/recovery-login` con `{ cedula, password, recovery_key }`
2. La recovery_key se guardó en Firestore durante la provisión del USB
3. JWT emitido por **24 horas** con `recovery: true` y `pendrive_bound: false`
4. El frontend muestra banner: *"Conecta tu pendrive lo antes posible"*
5. No puede operar con plenas garantías sin reconectar un USB válido después de 24 h

### 6.7 OAuth Google

```
POST /oauth/google/start (requiere JWT válido)
  → { authorization_url, state }
  → Usuario autoriza en el navegador
  → Google redirige a /oauth/google/callback
  → Backend intercambia el code por tokens
  → Tokens cifrados con Fernet → Firestore
  → Frontend consulta GET /oauth/google/status

Scopes:
  - gmail.modify (leer y enviar correos)
  - calendar.events (leer y crear eventos)
```

---

## 7. Interfaz de Usuario

### 7.1 Filosofía de diseño

DOT debe verse y sentirse como un producto Apple de gama premium, con un enfoque absoluto en la simplicidad y el minimalismo:

- **Colores:** Estrictamente monocromático. Blanco (`#FFFFFF`), negro (`#000000`), y grises Apple (`#1C1C1E`, `#2C2C2E`, `#8E8E93`, `#F5F5F7`). **Cero azul, cero morado, cero colores de acento.**
- **Tipografía:** SF Pro (primaria), Inter (fallback).
- **Espaciado:** Generoso, limpio, con suficiente respiración entre elementos.
- **Iconos:** SF Symbols o equivalente minimalista en escala de grises.
- **Bordes:** Esquinas redondeadas (12px), sombras sutiles en lugar de líneas divisorias marcadas.
- **Tema Claro/Oscuro (Inversión Pura):** El modo claro es la inversión exacta del modo oscuro (lo blanco pasa a negro, lo negro pasa a blanco), sin introducir paletas de colores intermedias o extrañas.
- **Máxima:** *"Parece que lo hizo Apple. Simplicidad absoluta."*

### 7.2 Paleta de colores

| Elemento | Tema claro | Tema oscuro |
|----------|-----------|-------------|
| Fondo | `#FFFFFF` | `#000000` |
| Superficie | `#F5F5F7` | `#1C1C1E` |
| Texto primario | `#000000` | `#FFFFFF` |
| Texto secundario | `#6E6E73` | `#98989D` |
| Acento (links/botones) | `#000000` | `#FFFFFF` |
| Bordes | `#E5E5EA` | `#2C2C2E` |
| Éxito | `#30D158` | `#30D158` |
| Error | `#FF453A` | `#FF453A` |

### 7.3 Especificaciones UI Clave (Sprint 1.5)

#### 7.3.1 Splash Cinematográfico (Siempre al iniciar)
- **Pantalla inicial:** 100% fondo negro (o blanco en modo claro).
- **Animación de la esfera:** Una esfera blanca (u oscura en modo claro) cae desde la parte superior-izquierda hacia el centro con una animación fluida (`framer-motion`).
- **Efecto de rebote:** Al llegar al centro, realiza un primer rebote fuerte y seco, cayendo en seco (estilo Apple) para quedarse estática en el centro.
- **Aparición de "DOT":** Con una animación suave de desvanecimiento y escala, aparece el texto **"DOT"** en el centro (estilo título de película cinematográfica).
- **Transición:** La esfera y el texto se desvanecen para dar paso a la pantalla de Login o al Dashboard.

#### 7.3.2 Burbujas de Chat (Diferenciadas y sin azul)
- **Mensajes del Usuario (Tú):**
  - *Tema Oscuro:* Burbuja negra pura (`#000000`) con borde gris muy sutil (`#2C2C2E`), texto blanco (`#FFFFFF`), alineado a la derecha.
  - *Tema Claro:* Burbuja blanca pura (`#FFFFFF`) con borde gris muy sutil (`#E5E5EA`), texto negro (`#000000`), alineado a la derecha.
- **Mensajes de DOT (Asistente):**
  - *Tema Oscuro:* Burbuja gris claro (`#F5F5F7`), texto negro (`#000000`), alineado a la izquierda.
  - *Tema Claro:* Burbuja gris superficie (`#F5F5F7`), texto negro (`#000000`), alineado a la izquierda.
- **Sin colores de acento:** Ninguna burbuja de chat debe contener color azul u otros tonos.

#### 7.3.3 WhatsApp QR (Progreso Guiado)
- **Sin porcentaje flotante:** No se muestra ningún indicador numérico de porcentaje en pantalla.
- **Flujo de vinculación:** Mientras se genera el código QR, se muestra el texto **"Generando QR..."** junto a una barra de progreso minimalista que avanza suavemente (sin etiqueta de %).
- **Visualización:** Al completarse la generación, la barra y el texto se desvanecen suavemente para mostrar el código QR limpio y listo para escanear.

#### 7.3.4 Alineación y Centrado General
- **Header:** El encabezado del dashboard y la barra superior deben estar perfectamente centrados y alineados con el contenedor del chat.
- **Cerrar Sesión:** El botón de "Cerrar sesión" debe estar perfectamente alineado y posicionado en la barra superior o en un menú contextual limpio, eliminando cualquier comportamiento donde se desplace hacia abajo o hacia la derecha de forma desordenada.

### 7.4 Mapa de pantallas

```
SplashScreen (logo DOT, fondo negro, 2s)
  │
  ▼
¿Hay sesión guardada en safeStorage?
  ├── NO  → LoginScreen
  │          └── Cédula + Contraseña + Botón "Ingresar"
  │          └── Indicador USB (¿conectado?)
  │
  └── SÍ  → PendriveAppGate
              │
              ▼
         ¿Pendrive conectado?
              ├── NO  → "Conecta tu pendrive DOT"
              │          (espera hasta que detecte USB)
              │
              └── SÍ  → OnboardingFlow
                          │
                          ▼
                    ¿Onboarding completado?
                          ├── NO  → Paso 1/7: Elegir canal (WhatsApp)
                          │          Paso 2/7: Escanear QR
                          │          Paso 3/7: Elegir integraciones
                          │          Paso 4/7: Autenticación Google
                          │          Paso 5/7: Resumen
                          │          Paso 6/7: Confirmación
                          │          Paso 7/7: Nombre preferido
                          │
                          └── SÍ  → DashboardShell
                                      │
                                      ▼
                              ┌───────────────┬────────────────┐
                              │ Automation    │ Chat Panel     │ Panel contextual
                              │ Sidebar       │ (streaming)    │ (se abre cuando
                              │               │                │ corresponde)
                              └───────────────┴────────────────┘
```

### 7.4 Componentes del dashboard

| Componente | Función |
|------------|---------|
| **WorkspaceHeader** | Nombre del agente, toggle tema (oscuro/claro), indicadores WhatsApp/Google/WS, logout |
| **AutomationSidebar** | Lista de automatizaciones guardadas, toggle on/off, botón "Ejecutar ahora" |
| **DotChatPanel** | Chat con IA, streaming, historial infinito, slash commands, adjuntar archivos |
| **DocumentCreatorModal** | Generar documentos (PDF, DOCX, XLSX) desde chat |
| **AutomationDrawer** | Crear/editar automatizaciones con selector de schedule |
| **Banners** | Notificaciones: reconectar USB, recovery key pendiente, actualización disponible |

---

## 8. Electron / Desktop

### 8.1 Arquitectura de procesos

```
┌──────────────────────────────────────────────────────────┐
│                  Electron Main Process                    │
│                                                          │
│  main.cjs → Ventana, seguridad, ciclo de vida            │
│  preload.cjs → 40+ APIs expuestas via contextBridge      │
│  ipc-handlers.cjs → Todos los IPC handlers registrados   │
│                                                          │
│  Módulos:                                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │secure-   │ │usb-serial│ │pendrive- │ │openclaw- │   │
│  │storage   │ │.cjs      │ │*.cjs (4) │ │process   │   │
│  │(safeStor)│ │(WMI USB) │ │(gate,    │ │(QR,login)│   │
│  │          │ │          │ │ vault,   │ │          │   │
│  │          │ │          │ │ crypto,  │ │          │   │
│  │          │ │          │ │ VHD)     │ │          │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                │
│  │local-    │ │security  │ │auto-     │                │
│  │tools     │ │.cjs (CSP)│ │launch.cjs│                │
│  │(sandbox  │ │          │ │(Inicio   │                │
│  │ archivos)│ │          │ │ Windows) │                │
│  └──────────┘ └──────────┘ └──────────┘                │
└──────────────────────────────────────────────────────────┘
           │                         │
           ▼                         ▼
┌────────────────────┐   ┌──────────────────────────┐
│ Renderer Process   │   │ OpenClaw Child Process    │
│ (React 19 + Vite)  │   │ (Node.js sandbox)         │
│                    │   │                           │
│ Chat / Dashboard   │   │ Login QR WhatsApp         │
│ Onboarding / Auto  │   │ Enviar/recibir mensajes   │
│                    │   │ Plugins automations       │
└────────────────────┘   └──────────────────────────┘
```

### 8.2 Archivos del proceso main

| Archivo | Propósito |
|---------|-----------|
| `main.cjs` | Ventana, ciclo de vida, CSP, single instance lock |
| `preload.cjs` | Expone APIs al renderer via contextBridge |
| `ipc-handlers.cjs` | Registro de todos los canales IPC |
| `secure-storage.cjs` | safeStorage del SO (cifrar/descifrar JWT) |
| `usb-serial.cjs` | Detectar USB, leer serial vía WMI |
| `windows-usb-detect.cjs` | Algoritmo de detección de dispositivos USB |
| `pendrive-crypto.cjs` | Crypto del vault (Fernet, HMAC) |
| `pendrive-gate.cjs` | Verificar que el pendrive correcto está conectado |
| `pendrive-vault.cjs` | Creación y verificación del vault |
| `openclaw-process.cjs` | Spawn y gestión del proceso OpenClaw |
| `openclaw-remote.cjs` | Comandos remotos desde WhatsApp |
| `openclaw-allowlist.cjs` | Lista blanca de plugins permitidos |
| `local-tools.cjs` | Sandbox de filesystem (leer/escribir archivos) |
| `security.cjs` | Políticas CSP, headers de seguridad |
| `auto-launch.cjs` | Registro en Inicio de Windows |
| `load-backend-env.cjs` | Cargar variables de entorno para el backend |

### 8.3 Canales IPC

**Sesión:**
- `dot:secure-session-save` — Guardar JWT en safeStorage
- `dot:secure-session-load` — Cargar JWT desde safeStorage
- `dot:secure-session-clear` — Limpiar sesión (logout)

**Pendrive:**
- `dot:usb-serial` — Leer serial del USB conectado
- `dot:pendrive-setup` — Inicializar/configurar pendrive
- `dot:pendrive-gate-status` — Verificar estado del gate

**OpenClaw:**
- `dot:whatsapp-qr-data-url` — Obtener QR como data URL
- `dot:openclaw-start-whatsapp-login` — Iniciar login WhatsApp
- `dot:openclaw-stop` — Detener proceso OpenClaw
- `dot:openclaw-install-plugins` — Instalar plugins de automatización
- `dot:openclaw-data` — (Main → Renderer) Datos stdout/stderr
- `dot:openclaw-exit` — (Main → Renderer) Proceso terminó

**Utilidad:**
- `dot:open-url` — Abrir URL en navegador externo
- `dot:system-notify` — Notificación nativa de Windows
- `dot:automation-notify` — Notificación de resultado de automatización
- `dot:reminder-task-create` — Crear tarea programada en Windows (schtasks)
- `dot:local-tools` — Leer/escribir archivos (sandbox)
- `dot:hardware-bind` — Vincular hardware a sesión
- `dot:updates-check-now` — Verificar actualizaciones
- `dot:updates-install-now` — Instalar actualización

### 8.4 Instalación en el PC del cliente (Opción C)

**Primera ejecución desde el USB:**

1. Windows AutoPlay detecta el USB y ofrece ejecutar `DOT-portable.exe`
2. El usuario acepta. DOT arranca desde el USB
3. En la primera ejecución:
   - DOT pregunta: *"¿Quieres instalar DOT en este equipo para que arranque automáticamente?"*
   - El usuario acepta (o no)
   - Si acepta: DOT se copia a `%LocalAppData%\DOT\` y se registra en Inicio de Windows (`shell:Startup`)
   - Si no acepta: DOT funciona desde el USB en modo portable
4. En adelante, DOT arranca con Windows. Pero el acceso a la cuenta requiere el USB

**Nota importante:** Esta instalación no es sigilosa. Windows muestra el diálogo de control de cuentas (UAC) y el usuario debe aprobar. Es comportamiento normal de cualquier aplicación legítima.

### 8.5 Pendrive Vault

El pendrive contiene:
1. **Vault cifrado** (partición oculta o archivo VHD):
   - `hardware_token_hash` (lo que espera el servidor)
   - Recovery key
   - Configuración del cliente
2. **Instalador portable**: `DOT-portable.exe`

El vault se crea durante la provisión por el vendedor con DOT-Venta.

### 8.6 OpenClaw Bridge

OpenClaw es un paquete npm que proporciona:
- Login a WhatsApp via QR code
- Envío y recepción de mensajes
- Cliente HTTP para webhooks de Meta

Se ejecuta como proceso hijo. Electron se comunica via stdin/stdout y un server HTTP local.

---

## 9. APIs y Contratos

### 9.1 API Backend DOT (FastAPI :8000)

| Grupo | Endpoints | Auth |
|-------|-----------|------|
| Auth | 5 | No requiere / Bearer JWT |
| Perfil | 2 | Bearer JWT |
| OAuth Google | 3 | Bearer JWT |
| WhatsApp Channel | 4 | Bearer JWT |
| Chat | 9 | Bearer JWT |
| Vision | 1 | Bearer JWT |
| Documentos | 1 | Bearer JWT |
| Plantillas | 4 | Bearer JWT |
| Automatizaciones | 4 | Bearer JWT |
| Capacidades | 2 | Bearer JWT |
| Telemetría | 1 | Bearer JWT |
| Pendrive/Recovery | 11 | Mixta |
| USB Provisioning | 3 | Admin-Key |
| Health | 2 | No requiere |
| WebSocket | 1 | JWT |

**Total: ~52 endpoints.** Detalle completo en `docs/contracts-v1.md`.

### 9.2 APIs internas

| API | Puerto | Usada por | Auth |
|-----|--------|-----------|------|
| DOT-Admin | 8001 | Backoffice interno | X-Admin-Api-Key |
| DOT-Venta | 8001 (segundo proceso) | App del vendedor | JWT propio |
| Chatbot-Cobro | 8080 | Recordatorios WhatsApp | Meta webhook |

### 9.3 Principios de diseño de API

1. **Versionado explícito:** `/v1/`
2. **Respuestas consistentes:** Errores con `code` + `detail`
3. **Rate limiting:** 10/min login, 30/min API, 120/min lecturas
4. **Idempotencia:** POST de creación devuelven el recurso
5. **Validación siempre servidor:** El frontend puede mentir, el servidor no
6. **WebSocket:** Solo notificaciones en tiempo real. Validar JWT en conexión

---

## 10. Automatizaciones y Worker

### 10.1 ¿Qué es una automatización?

Una instrucción en lenguaje natural que DOT ejecuta:

> *"Todos los lunes a las 9am, busca en Gmail las facturas de la semana pasada y descárgalas a una carpeta llamada Facturas"*

### 10.2 Arquitectura

```
Frontend (crea automatización)
  │
  ▼
POST /v1/automations → Backend guarda en Firestore
  │
  ▼
Automation Scheduler (APScheduler) → ¡se dispara el cron!
  │
  ▼
Worker (proceso hijo Python):
  ├── Task Queue → Sandbox → Workflow Engine
  ├── ¿Usa Gmail? → Google API (token OAuth)
  ├── ¿Usa WhatsApp? → OpenClaw bridge
  ├── ¿Usa filesystem? → local-tools (sandbox)
  └── ¿Usa IA? → DeepSeek API
  │
  ▼
Resultado → Firestore + notificación al usuario
```

### 10.3 Tipos de automatizaciones

| Tipo | Descripción | Integración |
|------|-------------|-------------|
| **Gmail** | Leer, buscar, descargar correos | Google API (OAuth) |
| **Calendar** | Crear eventos, consultar agenda | Google API (OAuth) |
| **WhatsApp** | Enviar mensajes, responder automáticamente | OpenClaw |
| **Filesystem** | Leer/escribir archivos en el PC | local-tools sandbox |
| **IA** | Resumir, traducir, analizar contenido | DeepSeek / Gemini |
| **Compuestas** | Secuencia de pasos (buscar → extraer → guardar) | Combinación |

---

## 11. Despliegue y Operaciones

### 11.1 Estado actual

| Componente | Entorno | ¿En producción? |
|------------|---------|-----------------|
| Backend DOT | Dev local (127.0.0.1:8000) | ❌ No |
| Frontend DOT | Dev local (127.0.0.1:5173) | ❌ No |
| Electron DOT | Dev local (npm run desktop) | ❌ No |
| DOT-Venta | Dev local | ❌ No |
| Postgres | Docker local | ❌ No |
| Servidor GCP | VM provisionada | ✅ Sí (vacía) |
| Dominio | Pendiente | ❌ No |

### 11.2 Roadmap — Sprints priorizados

```
Sprint 0 (ARREGLOS URGENTES) — 1-2 días
  ├── [P0] Crear electron/usb-serial.cjs (archivo faltante)
  ├── [P0] Arreglar ws.py — agregar parámetro cfg
  ├── [P0] Desactivar DEV_SKIP_LOGIN, probar login real
  └── [P1] Limpiar archivos residuales de la raíz del frontend

Sprint 1 (FUNDACIONES) — 1 semana
  ├── Simplificar interfaz a estilo Apple (negro/blanco)
  ├── Probar flujo completo: login → onboarding → chat
  ├── Probar WhatsApp: QR → linked → enviar mensaje
  └── Tests de integración frontend-backend

Sprint 2 (AUTOMATIZACIONES) — 1 semana
  ├── Probar creación y ejecución de automatizaciones
  ├── Verificar worker + sandbox + task queue
  ├── Arreglar fail-open en cifrado de chats (S-02)
  └── Notificaciones de resultados

Sprint 3 (PRODUCCIÓN) — 1 semana
  ├── Configurar HTTPS (Cloudflare Tunnel o dominio)
  ├── Firmar código (Authenticode) para el .exe
  ├── Configurar auto-updater de Electron
  ├── Build de instalador oficial
  └── Deploy a servidor GCP
```

### 11.3 Checklist de producción

- [ ] HTTPS configurado
- [ ] Variables de entorno de producción en servidor
- [ ] Firebase service account en servidor
- [ ] Google OAuth credentials de producción
- [ ] JWT con RS256 (no HS256)
- [ ] Sentry APM habilitado
- [ ] Auto-updater apuntando a releases
- [ ] Firma de código (Authenticode)
- [ ] ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH = false
- [ ] DEV_SKIP_LOGIN = false
- [ ] Firestore security rules configuradas

### 11.4 Tareas estratégicas pendientes

- **[P0/P1 técnico] Puente WhatsApp real desde OpenClaw/Baileys** — Sprint 1 cerró el onboarding con el canal en estado “pendiente de verificación”, pero el backend aún no recibe una señal legítima de `linked: true` emitida por OpenClaw (o por Baileys cuando se actualice el runtime). La tarea consiste en capturar el evento de conexión real que confirma que WhatsApp está listo, propagarlo al servicio `whatsapp_link` y exponerlo al dashboard/worker para que el estado refleje “WhatsApp vinculado” sin depender de revalidaciones manuales. También se debe documentar cómo el frontend muestra el nuevo estado y cómo los workers confían en esa señal para automatizaciones. Esta es una tarea técnica independiente que se planifica como P1/P0 en el backlog posterior al Sprint 1.

---

## 12. Principios de Desarrollo (El Decálogo)

1. **Una cosa a la vez.** No mezclamos refactor con features nuevas. Nunca.
2. **Pruebas antes que código.** No se acepta "confío en que funciona". Test: rojo → verde → refactor.
3. **Commits pequeños.** Cada commit hace una cosa. Mensajes descriptivos.
4. **Código muerto se elimina.** No "por si acaso". Si no se usa, no está.
5. **Archivos < 300 líneas.** Si crece, se divide. Sin excepción.
6. **No romper contratos.** `docs/contracts-v1.md` es ley. Si cambia, se versiona.
7. **Seguridad en cada decisión.** ¿Estoy exponiendo datos sensibles? ¿Hardcodeando algo? ¿Validando del lado correcto?
8. **El cliente no ve una terminal.** Nunca. Jamás. Punto.
9. **El servidor es la autoridad.** El frontend solo muestra. Validar siempre del lado del servidor.
10. **Documentar las decisiones.** Si algo no es obvio, se explica. En el código o en docs.

---

## Apéndice A: Glosario

| Término | Significado |
|---------|-------------|
| **DOT** | Asistente IA de escritorio. Producto principal. Nombre definitivo |
| **DOT-Venta** | App del vendedor para preconfigurar pendrives (ex NordikVenta) |
| **DOT-Admin** | Panel de administración interno (ex auto-venta1) |
| **OpenClaw** | Paquete npm que provee bridge WhatsApp |
| **Pendrive** | USB físico. ES la llave de acceso. Sin él no hay DOT |
| **Vault** | Datos cifrados en el pendrive (token + recovery key) |
| **Fernet** | Algoritmo de cifrado simétrico (Python `cryptography`) |
| **safeStorage** | API de Electron para cifrar datos con credenciales del SO |
| **Gate** | Mecanismo que verifica el pendrive antes de dar acceso |
| **Worker** | Proceso hijo Python que ejecuta automatizaciones en sandbox |
| **Token** | Unidad de medida de consumo de API de IA. 1M tokens ~ $0.14 |

---

## Apéndice B: Documentos relacionados

| Documento | Qué contiene |
|-----------|-------------|
| `docs/contracts-v1.md` | Contratos API detallados (52 endpoints, versionados) |
| `docs/THREAT_MODEL.md` | Modelo de amenazas con DFD y matriz de riesgos |
| `docs/ATTACK_SURFACE.md` | Superficie de ataque detallada |
| `docs/PENTEST_REPORT.md` | Reporte de pruebas de penetración con CVSS |
| `docs/SECURITY-SCALABILITY-MASTERPLAN.md` | Plan maestro de seguridad + escalabilidad a 5 años |
| `docs/SCALABILITY-PLAN-COMPLETE.md` | Roadmap detallado de escalabilidad (100 a 5M usuarios) |
| `docs/env-registry.md` | Registro completo de variables de entorno |
| `docs/public-api.md` | API pública resumida (incl. Vision / Vertex) |
| `docs/DOTTEST-SPRINT2.md` | Guía de pruebas manuales Sprint 2 (visión) |
| `docs/secrets-catalog.md` | Catálogo de secrets por servicio |
| `docs/regression-checklist.md` | 127 items de verificación pre-release |
| `docs/production-checklist.md` | Checklist de salida a producción |
| `docs/RUNBOOK-STARTUP.md` | Procedimiento de inicio del sistema |

---

*Este documento es la constitución del proyecto DOT. Cualquier cambio requiere acuerdo explícito. Versión 2.0 — 1 de julio de 2026.*
