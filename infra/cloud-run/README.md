# Cloud Run — nordik-api

Despliegue serverless del backend FastAPI DOT (`apps/dot/backend`) en Google Cloud Run, región **southamerica-west1** (Santiago, Chile).

## Arquitectura

```
┌──────────────────────────────────────────────────────┐
│                   Cloud Run                          │
│  ┌────────────────────────────────────────────┐      │
│  │  nordik-api (FastAPI :8000)                │      │
│  │  • 0–10 instancias, autoescalado           │      │
│  │  • Concurrency: 80 req/instancia           │      │
│  │  • Timeout: 300s                           │      │
│  │  • 512Mi RAM, 1 vCPU                       │      │
│  └───────┬──────────────┬─────────────────────┘      │
│          │              │                             │
│    ┌─────▼─────┐  ┌─────▼─────┐                      │
│    │ Cloud SQL │  │  Memory-  │                      │
│    │ Postgres  │  │  store    │                      │
│    │  (billing)│  │  (Redis)  │                      │
│    └───────────┘  └───────────┘                      │
└──────────────────────────────────────────────────────┘
```

## Requisitos previos

1. **GCP Project** `nordikia` con billing habilitado.
2. **Artifact Registry** repo `nordik-repo` en `southamerica-west1`.
3. **Cloud SQL** instancia Postgres `nordik-postgres` con IP privada.
4. **VPC connector** serverless `nordik-vpc-connector` en `southamerica-west1`.
5. **Secret Manager** con todos los secretos listados en `service.yaml`.
6. **Service Account** `nordik-api-sa@nordikia.iam.gserviceaccount.com` con roles:
   - `roles/run.invoker`
   - `roles/cloudsql.client`
   - `roles/secretmanager.secretAccessor`
   - `roles/vpcaccess.user`

## Secretos requeridos en Secret Manager

| Nombre del secreto | Contenido | Ejemplo |
|---|---|---|
| `nordik-database-url` | URL conexión Postgres (Cloud SQL) | `postgresql+psycopg://user:pass@/nordik_billing?unix_sock=/cloudsql/nordikia:northamerica-south1:nordik-postgres/.s.PGSQL.5432` |
| `nordik-jwt-private-key` | PEM clave privada RS256 | `-----BEGIN PRIVATE KEY-----\n...` |
| `nordik-jwt-public-key` | PEM clave pública RS256 | `-----BEGIN PUBLIC KEY-----\n...` |
| `nordik-token-encryption-key` | Fernet key (32B base64) | `abc123...=` |
| `nordik-chat-encryption-key` | Fernet key (32B base64) **distinta** | `xyz789...=` |
| `nordik-admin-api-key` | API key para endpoints admin | `sk-admin-...` |
| `nordik-hardware-token-pepper` | Pepper para SHA-256(serial+pepper) | Valor fijo seguro |
| `nordik-deepseek-api-key` | DeepSeek API key | `sk-...` |
| `nordik-gemini-api-key` | Gemini API key | `AIza...` |
| `nordik-google-translate-api-key` | Google Translate API key | `AIza...` |
| `nordik-sentry-dsn` | Sentry DSN | `https://...@sentry.io/...` |
| `nordik-openweather-api-key` | OpenWeatherMap API key | `abc123...` |
| `nordik-newsapi-key` | NewsAPI key | `abc123...` |
| `nordik-security-webhook-url` | Discord/Slack webhook | `https://discord.com/...` |
| `nordik-whatsapp-webhook-secret` | Secret webhook WhatsApp | `urlsafe base64 32B` |
| `nordik-whatsapp-bridge-secret` | Secret bridge WhatsApp | `urlsafe base64 32B` |
| `nordik-logtail-source-token` | Better Stack source token | `abc123...` |
| `nordik-firebase-service-account` | JSON service account Firebase (archivo) | `{"type":"service_account",...}` |
| `nordik-oauth-client-secret` | JSON OAuth client secret Google (archivo) | `{"web":{"client_id":"...",...}}` |
| `nordik-redis-url` | *(opcional)* URL Redis Memorystore | `redis://10.x.x.x:6379/0` |

## Primer despliegue

### 1. Construir imagen vía Cloud Build

```bash
gcloud builds submit \
  --config infra/cloud-run/cloudbuild.yaml \
  --project nordikia \
  .
```

El `Dockerfile` está en `apps/dot/backend/Dockerfile` y el contexto de build es la raíz del repo (por los `COPY packages/...` y `COPY apps/dot/backend/...`).

### 2. Desplegar servicio

```bash
gcloud run services replace infra/cloud-run/service.yaml \
  --project nordikia \
  --region southamerica-west1
```

### 3. Verificar despliegue

```bash
gcloud run services describe nordik-api \
  --region southamerica-west1 \
  --format="value(status.url)"
```

El comando devuelve la URL pública del servicio. Visitar `{URL}/health` debe responder `{"status":"ok"}`.

## Actualizar servicio

```bash
# Reconstruir y desplegar nueva revisión
gcloud builds submit \
  --config infra/cloud-run/cloudbuild.yaml \
  --project nordikia \
  .

gcloud run services replace infra/cloud-run/service.yaml \
  --project nordikia \
  --region southamerica-west1
```

La directiva `traffic.latestRevision: true` envía el 100% del tráfico a la nueva revisión automáticamente.

## Rollback

```bash
# Listar revisiones
gcloud run revisions list \
  --service nordik-api \
  --region southamerica-west1

# Redirigir tráfico a revisión anterior
gcloud run services update-traffic nordik-api \
  --to-revisions REVISION_ANTERIOR=100 \
  --region southamerica-west1
```

## Monitoreo

- **Logs:** Cloud Logging (`gcloud run services logs read nordik-api`)
- **Métricas:** Cloud Monitoring → Dashboards en `infra/observability/dashboards/`
- **Errores:** Sentry (DSN configurado vía Secret Manager)

## Escalado

| Parámetro | Valor | Descripción |
|---|---|---|
| `minScale` | 0 | Scale-to-zero: sin tráfico = sin costo |
| `maxScale` | 10 | Máximo 10 instancias simultáneas |
| `concurrency` | 80 | Hasta 80 requests por instancia |
| `timeout` | 300s | Requests largos (streaming IA, generación imágenes) |

## Costos estimados (sin tráfico)

- **Cloud Run:** $0/mes con 0 instancias (scale-to-zero)
- **Cloud SQL:** ~$9/mes (db-f1-micro, 10GB SSD)
- **Memorystore:** ~$36/mes (Basic M1, 1GB) — si se habilita
- **Secret Manager:** ~$0.06/secret/mes × 18 secretos ≈ $1.08/mes
- **Artifact Registry:** ~$0.10/GB/mes

**Total base:** ~$10–$46/mes según si Redis está habilitado.

## Notas

- El VPC connector usa `private-ranges-only` para que el tráfico a Cloud SQL y Memorystore vaya por red privada (más seguro, sin IPs públicas).
- Los secretos tipo archivo (Firebase SA, OAuth client) se montan como volumen en `/secrets/`, no como variables de entorno.
- El `OAUTH_REDIRECT_URI` debe actualizarse con la URL real del servicio una vez desplegado.
- Para desarrollo local, usar `docker-compose` en `infra/` en lugar de Cloud Run.
