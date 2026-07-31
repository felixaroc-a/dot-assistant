# Sprint 2.5 — Generación de imágenes y límite de consumo IA

> **Visión de producto unificada:** `docs/BIBLIA.md` §5 y §14. Todos los planes tienen las mismas capacidades; el límite $7.50/mes aplica a todos.

**Estado:** Diseño aprobado (sin implementación de código en este sprint-doc).  
**Rama de trabajo:** `sprint-2.5-image-gen` (desde `develop-felix1` tras merge de PR #1).  
**Dependencias:** Sprint 2 (Visión con Vertex AI) — mergeado.

---

## 1. Resumen ejecutivo

Sprint 2.5 entrega dos capacidades acopladas:

1. **Generación de imágenes** (texto → imagen) vía **Vertex AI Imagen**, disponible para **todos los planes** (mensual, trimestral, anual).
2. **Límite unificado de consumo IA** de **$7.50 USD/mes** por usuario/pendrive, que cuenta **todo** el consumo de IA (DeepSeek chat, Vertex Vision, Vertex Imagen).

El cliente ve un **medidor visual** permanente en la esquina superior izquierda del dashboard con el **porcentaje consumido** (ascendente) y colores semáforo.

---

## 2. Decisiones de diseño confirmadas

### A) Límite de uso — $7.50 USD/mes

| ID | Decisión |
|----|----------|
| A1 | El límite cuenta **todo** el consumo de IA: DeepSeek (chat), Vertex/Gemini (visión), Vertex Imagen (generación). |
| A2 | Al **100%** del límite → **bloquear todo** uso de IA. Mensaje al usuario: *"Ha alcanzado su límite de consumo de IA este mes. Si necesita recargar, vaya a la tienda más cercana."* |
| A3 | Contador por **pendrive + usuario**. Clave natural: `cliente_id` (UUID en `clientes_suscripcion`) + `hardware_token_hash` (serial del pendrive hasheado). Cada usuario tiene un pendrive asociado. |
| A4 | En **desarrollo**: consumo **ilimitado** para pruebas, pero el código del límite **debe existir** detrás de un feature flag / env var (`AI_USAGE_LIMIT_ENABLED=false` en dev). En producción: `AI_USAGE_LIMIT_ENABLED=true`. |

**Notas de implementación:**

- El backend valida el límite en **cada** request de IA (chat, visión, generación). El frontend no puede omitirlo.
- El mes de facturación es **calendario** (día 1 → último día del mes, timezone configurable vía `AI_USAGE_BILLING_TIMEZONE`, default `America/Bogota`).
- Al bloquear, responder **HTTP 402** (o **429** si se prefiere consistencia con rate-limit existente) con código de error estable: `ai_usage_limit_exceeded`.
- No hay degradación a modelo más barato al 100% (decisión A2: bloqueo total).

### B) Medidor visual de consumo

| ID | Decisión |
|----|----------|
| B5 | Mostrar **solo porcentaje consumido** (ascendente), ej. `"34% consumido"`. |
| B6 | Ubicación: **esquina superior izquierda** del dashboard, junto al logo/título (`WorkspaceHeader` o contenedor hermano). |
| B7 | Colores según **% consumido**: verde `<50%`, amarillo `50–80%`, rojo `>80%`. |
| B8 | Siempre visible mientras el usuario está autenticado en el dashboard. |

### C) Generación de imágenes

| ID | Decisión |
|----|----------|
| C9 | Resolución inicial **1024×1024**. Post-lanzamiento (fase 2): mínimo **1080p** (1920×1080 o equivalente según aspect ratio de Imagen). Documentar como entrega por fases. |
| C10 | **Cantidad de imágenes** determinada por contexto/prompt del usuario (no un número fijo por request). El backend interpreta el prompt y devuelve 1..N imágenes según intención detectada, con tope de seguridad configurable (`IMAGE_GEN_MAX_IMAGES_PER_REQUEST`, default `4`). |
| C11 | **Detección de intención** en español e inglés. Ejemplos: `genera imagen`, `dibuja`, `crea una imagen de…`, `generate an image of…`, `draw a picture of…`. |
| — | **Proveedor:** Vertex AI **Imagen** (mismo proyecto GCP y ADC que visión). |
| — | **Disparador (opción C):** botón **"Generar imagen"** en el chat **y** detección automática de frases en el mensaje. |
| — | **Planes:** disponible para **todos** (mensual, trimestral, anual). Eliminar restricción trimestral+ en catálogo de capacidades. |

### D) Git

- PR #1 (`dot-dev` → `develop-felix1`) mergeado.
- Rama `sprint-2.5-image-gen` creada para implementación.

---

## 3. Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│  Electron — DotChatPanel / WorkspaceHeader                       │
│  ┌──────────────┐  ┌─────────────────┐  ┌──────────────────┐  │
│  │ UsageMeter   │  │ Botón Generar   │  │ Detección frase  │  │
│  │ (top-left)   │  │ imagen          │  │ ES/EN en composer│  │
│  └──────┬───────┘  └────────┬────────┘  └────────┬─────────┘  │
└─────────┼───────────────────┼────────────────────┼──────────────┘
          │ GET /v1/usage/summary
          │ POST /v1/images/generate
          ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI — apps/dot/backend                                      │
│  usage_service          image_generation_service                 │
│    ├─ check_limit()       ├─ parse_image_count(prompt)         │
│    ├─ record_usage()      ├─ imagen_vertex_service (Imagen)    │
│    └─ monthly_aggregate     └─ store / return base64 URLs        │
│                                                                  │
│  Middleware/deps: require_product_jwt + assert_ai_usage_allowed  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
   DeepSeek API         Vertex Gemini          Vertex Imagen
   (chat)               (vision/analyze)       (images/generate)
          │                    │                    │
          └────────────────────┴────────────────────┘
                               │
                               ▼
                    Postgres — usage_tokens
                    (cliente_id, modelo, costo_total, …)
```

---

## 4. API — Endpoints nuevos y cambios

### 4.1 `GET /v1/usage/summary`

Resumen de consumo del mes en curso para el JWT autenticado.

**Auth:** Bearer JWT (`require_product_jwt`).

**Response 200:**

```json
{
  "cliente_id": "uuid",
  "period_start": "2026-07-01",
  "period_end": "2026-07-31",
  "limit_usd": 7.5,
  "consumed_usd": 2.55,
  "consumed_percent": 34,
  "remaining_usd": 4.95,
  "limit_enabled": true,
  "blocked": false
}
```

**Campos:**

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `consumed_percent` | int | 0–100, redondeado hacia abajo. Base del medidor UI. |
| `limit_enabled` | bool | `false` en dev cuando `AI_USAGE_LIMIT_ENABLED=false`. |
| `blocked` | bool | `true` si `consumed_usd >= limit_usd` y límite activo. |

**Errores:** 401 sin JWT; 403 `subscription_expired`.

**Polling:** el frontend puede refrescar al montar dashboard, tras cada respuesta de chat/visión/imagen, y cada 60 s en background (configurable).

---

### 4.2 `POST /v1/images/generate`

Genera una o más imágenes a partir de un prompt de texto.

**Auth:** Bearer JWT + validación de límite de uso + suscripción vigente.

**Request (JSON):**

```json
{
  "prompt": "Un gato astronauta en la luna, estilo acuarela",
  "count": null,
  "aspect_ratio": "1:1",
  "resolution": "1024x1024"
}
```

| Campo | Obligatorio | Descripción |
|-------|-------------|-------------|
| `prompt` | Sí | Texto descriptivo (1–4000 chars). |
| `count` | No | Si se omite, el servidor infiere del prompt (C10). |
| `aspect_ratio` | No | Default `1:1` en fase 1. |
| `resolution` | No | Default `1024x1024`. Fase 2: `1920x1080` cuando esté habilitado. |

**Response 200:**

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
  "prompt_used": "…",
  "count": 1,
  "usage": {
    "cost_usd": 0.04,
    "model": "imagen-3.0-generate-002"
  }
}
```

**Errores:**

| Código | Condición | `detail` / código |
|--------|-----------|-------------------|
| 400 | Prompt vacío o demasiado largo | `invalid_prompt` |
| 402 | Límite mensual agotado | `ai_usage_limit_exceeded` |
| 403 | Suscripción vencida | `subscription_expired` |
| 503 | Vertex Imagen no configurado | `image_generation_unavailable` |
| 500 | Error del proveedor | mensaje genérico sin filtrar secretos |

**Nota:** Versionar en `docs/public-api.md` y `docs/contracts-v1.md` al implementar.

---

### 4.3 Hooks en endpoints existentes

Registrar consumo y rechazar si `blocked` en:

| Endpoint | Servicio | Modelo registrado |
|----------|----------|-------------------|
| `POST /v1/chat/completions` (o ruta chat actual) | DeepSeek | `deepseek-chat` |
| `POST /v1/vision/analyze` | Vertex Gemini | `gemini-2.5-flash` (o valor de `GEMINI_VERTEX_MODEL`) |
| `POST /v1/images/generate` | Vertex Imagen | `IMAGEN_VERTEX_MODEL` |

Cada respuesta exitosa del proveedor debe llamar a `usage_service.record_usage(cliente_id, modelo, tokens_*, cost_usd)`.

---

## 5. Esquema de tracking de uso

### 5.1 Tabla existente: `usage_tokens`

Reutilizar el esquema definido en `docs/ARCHITECTURE.md` §4.2:

```sql
CREATE TABLE usage_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id UUID NOT NULL REFERENCES clientes_suscripcion(id),
    fecha DATE NOT NULL DEFAULT CURRENT_DATE,
    modelo VARCHAR(50) NOT NULL DEFAULT 'deepseek-chat',
    tokens_prompt BIGINT NOT NULL DEFAULT 0,
    tokens_completion BIGINT NOT NULL DEFAULT 0,
    tokens_cached BIGINT NOT NULL DEFAULT 0,
    costo_total DECIMAL(10, 6) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Extensiones recomendadas (migración Sprint 2.5):**

```sql
ALTER TABLE usage_tokens
  ADD COLUMN IF NOT EXISTS operation VARCHAR(32) NOT NULL DEFAULT 'chat',
  ADD COLUMN IF NOT EXISTS request_id VARCHAR(64);

-- operation: 'chat' | 'vision' | 'image_generation'
CREATE INDEX IF NOT EXISTS idx_usage_cliente_mes
  ON usage_tokens (cliente_id, fecha);
```

### 5.2 Agregación mensual

```sql
SELECT COALESCE(SUM(costo_total), 0) AS consumed_usd
FROM usage_tokens
WHERE cliente_id = :cliente_id
  AND fecha >= :period_start
  AND fecha <= :period_end;
```

### 5.3 Clave de negocio

- **Primaria:** `cliente_id` (del JWT tras login con cédula + pendrive).
- **Validación cruzada:** el `hardware_token_hash` del login debe coincidir con el registro en `clientes_suscripcion` (ya existe en flujo de auth).
- No se requiere tabla separada por serial: un cliente = un pendrive en el modelo actual.

### 5.4 Cálculo de costos (configurable)

Precios en env vars (ver §6). Ejemplo inicial:

| Operación | Variable de precio | Notas |
|-----------|------------------|-------|
| DeepSeek chat | `AI_COST_DEEPSEEK_INPUT_PER_1M`, `AI_COST_DEEPSEEK_OUTPUT_PER_1M` | Usar `usage` de la API |
| Vertex vision | `AI_COST_GEMINI_VISION_PER_IMAGE` o por token si el SDK lo expone | Por request |
| Imagen generate | `AI_COST_IMAGEN_PER_IMAGE` | Por imagen generada |

`usage_service` centraliza la fórmula; los routers no calculan costos inline.

---

## 6. Variables de entorno

Ver `docs/env-registry.md` (sección Sprint 2.5). Resumen:

| Variable | Dev default | Prod |
|----------|-------------|------|
| `AI_USAGE_LIMIT_ENABLED` | `false` | `true` |
| `AI_USAGE_MONTHLY_LIMIT_USD` | `7.5` | `7.5` |
| `AI_USAGE_BILLING_TIMEZONE` | `America/Bogota` | `America/Bogota` |
| `ENABLE_IMAGE_GENERATION` | `true` | `true` |
| `IMAGEN_VERTEX_MODEL` | `imagen-3.0-generate-002` | igual |
| `IMAGE_GEN_MAX_IMAGES_PER_REQUEST` | `4` | `4` |
| `IMAGE_GEN_DEFAULT_RESOLUTION` | `1024x1024` | `1024x1024` |
| `IMAGE_GEN_ENABLE_1080P` | `false` | `false` (fase 2) |

Reutilizar `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_APPLICATION_CREDENTIALS` de Vertex (visión).

**Deploy producción (comentario operativo):**

```bash
# En el .env del servidor apps/dot/backend:
AI_USAGE_LIMIT_ENABLED=true
AI_USAGE_MONTHLY_LIMIT_USD=7.5
ENABLE_IMAGE_GENERATION=true
# Verificar SA con rol Vertex AI User + Imagen API habilitada en GCP
```

---

## 7. Componentes UI

| Componente | Ubicación | Responsabilidad |
|------------|-----------|-----------------|
| `UsageMeter` | `features/dashboard/components/UsageMeter.tsx` | Barra o anillo + texto `"{n}% consumido"`. Colores B7. |
| Integración header | `WorkspaceHeader.tsx` o `DashboardShell.tsx` | Slot top-left B6. |
| `useUsageSummary` | `features/dashboard/hooks/useUsageSummary.ts` | Fetch `GET /v1/usage/summary`, refresh tras IA. |
| Botón "Generar imagen" | `ChatComposer.tsx` | Abre modo generación o envía con flag `image_generation: true`. |
| `imageGenerationIntent.ts` | `features/dashboard/components/chat/` | Regex/heurística ES+EN (C11). |
| `ImageGenerationBubble` | chat messages | Muestra grid de imágenes base64 devueltas. |
| Modal bloqueo | reutilizar `Toast` / banner | Mensaje A2 cuando API devuelve `ai_usage_limit_exceeded`. |
| i18n | `locales/es.json`, `en.json`, `pt.json` | Claves: `usage.consumed`, `usage.blocked`, `imageGen.button`, etc. |

**Estilos:** extender `workspace-header.css` y `dashboard-tokens.css` con variables `--usage-green`, `--usage-yellow`, `--usage-red`.

---

## 8. Detección de intención (chat)

### 8.1 Frases disparadoras (no exhaustivo)

**Español:** `genera (una )?imagen`, `dibuja`, `crea (una )?imagen`, `hazme (una )?foto`, `ilustra`.  
**Inglés:** `generate (an )?image`, `draw (a )?picture`, `create (an )?image of`, `make (a )?photo of`.

### 8.2 Flujo

1. Usuario escribe mensaje o pulsa "Generar imagen".
2. Si hay intención o botón → `POST /v1/images/generate` con el prompt (sin pasar por DeepSeek para la generación en sí).
3. Opcional: si el mensaje mezcla chat y generación, el backend puede devolver texto + imágenes en una sola respuesta compuesta (fase 1.1); en fase 1.0, priorizar generación cuando la intención es clara.

### 8.3 Inferencia de cantidad (C10)

Heurísticas en `image_generation_service`:

- Números explícitos: `"3 imágenes de…"`, `"generate 2 images"`.
- Plural sin número: default 2 si el prompt usa plural ("gatos", "variants").
- Sin indicación: **1 imagen**.

Siempre acotar por `IMAGE_GEN_MAX_IMAGES_PER_REQUEST`.

---

## 9. Catálogo de capacidades (cambio de plan)

Actualizar `openclaw_adapter.PLAN_CAPABILITIES`:

| Plan | Capacidades (Sprint 2.5) |
|------|--------------------------|
| mensual | `chat_completion`, `whatsapp_channel_login`, `web_search`, **`image_generation`** |
| trimestral | mensual + `automation_plugins` |
| anual | trimestral + `file_tools` (Fase 3+) |

`image_generation` sigue mapeando a `enable_image_gen` / `ENABLE_IMAGE_GENERATION` (renombrar alias `ENABLE_NEW_INTEGRATION` en implementación si se desea claridad).

---

## 10. Plan de pruebas (outline)

### 10.1 Backend

- [ ] `usage_service`: agregación mensual, percent, blocked al ≥100%.
- [ ] `AI_USAGE_LIMIT_ENABLED=false` → nunca bloquea; igual registra uso (opcional en dev).
- [ ] Chat/vision/image llaman `record_usage` con costos correctos.
- [ ] `POST /v1/images/generate`: prompt válido, count inferido, tope max images.
- [ ] 402 cuando límite excedido.
- [ ] Vertex Imagen mock en tests unitarios (sin llamadas reales a GCP).

### 10.2 Frontend

- [ ] `UsageMeter`: colores en 30%, 60%, 90% consumido.
- [ ] Medidor visible en dashboard autenticado.
- [ ] Botón "Generar imagen" dispara API.
- [ ] Frases ES/EN activan generación.
- [ ] Mensaje de bloqueo A2 al recibir 402.
- [ ] Imágenes se muestran en burbuja de chat.

### 10.3 E2E / manual (`docs/DOTTEST-SPRINT2.5.md` — crear al implementar)

- [ ] Flujo completo: login → ver medidor → generar imagen → % sube.
- [ ] Simular límite (env `AI_USAGE_MONTHLY_LIMIT_USD=0.01` en staging).
- [ ] Regresión: visión Sprint 2 sigue funcionando y suma al medidor.

### 10.4 Regresión

- [ ] `docs/regression-checklist.md` — ítems de auth, chat, visión, capabilities.

---

## 11. Fases de entrega

| Fase | Alcance |
|------|---------|
| **2.5.1** | `usage_service` + tabla/migración + `GET /v1/usage/summary` + hooks en chat/vision + `UsageMeter` |
| **2.5.2** | `POST /v1/images/generate` + Vertex Imagen + UI botón y burbujas |
| **2.5.3** | Detección automática de frases ES/EN en composer |
| **2.5.4 (post-launch)** | Resolución 1080p (`IMAGE_GEN_ENABLE_1080P=true`), ajuste fino de precios Imagen |

---

## 12. Riesgos y mitigaciones

| Riesgo | Mitigación |
|--------|------------|
| Costo Imagen mayor que chat | Tope de imágenes por request; precio por imagen en `usage_service` |
| CI fallando en PR #1 | Merge explícito del usuario; corregir CI en rama sprint antes de PR final |
| `ENABLE_NEW_INTEGRATION` poco claro | Alias documentado; migrar a `ENABLE_IMAGE_GENERATION` en settings |
| Usuario sin ADC en dev | Mocks en tests; documentar en `DOTTEST-SPRINT2.5.md` |

---

## 13. Documentos relacionados

| Documento | Acción |
|-----------|--------|
| `AGENTS.md` | Capabilities + nota $7.50/mes |
| `docs/env-registry.md` | Variables Sprint 2.5 |
| `docs/public-api.md` | Añadir endpoints al implementar |
| `docs/contracts-v1.md` | Versionar contratos al implementar |
| `docs/ARCHITECTURE.md` | Actualizar §3.5 cuando exista código de generación |
