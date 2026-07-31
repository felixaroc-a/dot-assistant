# Redis Memorystore — Nordik-IA

Redis cache centralizado para el backend DOT, corriendo en Google Cloud Memorystore (Redis) con acceso privado vía VPC connector serverless.

## Estado

**Actualmente diferido.** Redis no es requisito crítico para el MVP actual de DOT. Se documenta la infraestructura para activarla cuando la escala lo justifique.

**Motivos para diferir:**
- El backend actual funciona correctamente sin cache distribuido.
- Memorystore BASIC (1GB) cuesta ~$36/mes — gasto innecesario en etapa temprana.
- La cache en memoria por instancia de Cloud Run es suficiente para <100 usuarios activos.

**Cuándo activar:**
- Rate limiting distribuido (necesario con >1 instancia Cloud Run).
- Cache de sesiones JWT (evitar consultas Firestore por cada request).
- Cache de respuestas IA frecuentes (reducir latencia y costo DeepSeek/Gemini).

## Arquitectura

```
┌──────────────────────────────┐
│         VPC nordikia         │
│                              │
│  ┌────────────┐  ┌─────────┐ │
│  │ Cloud Run  │  │Memory-  │ │
│  │ nordik-api ├──┤store    │ │
│  │    :8000   │  │Redis    │ │
│  └─────┬──────┘  │BASIC 1GB│ │
│        │         └─────────┘ │
│  ┌─────▼──────┐              │
│  │ Cloud SQL  │              │
│  │ Postgres   │              │
│  └────────────┘              │
│                              │
│  ┌────────────────────────┐  │
│  │ VPC Connector          │  │
│  │ Serverless (10.8.0.0/28)│  │
│  └────────────────────────┘  │
└──────────────────────────────┘
```

## Especificaciones

| Parámetro | Valor |
|---|---|
| **Tier** | BASIC (sin failover) |
| **Capacidad** | 1 GB |
| **Región** | southamerica-west1 (Santiago) |
| **Versión Redis** | 7.x (latest estable) |
| **Red** | VPC `nordikia-vpc`, solo IP privada |
| **Rango IP autorizado** | 10.8.0.0/28 (VPC connector serverless) |
| **Auth** | AUTH string (gestionado por GCP) |
| **Persistencia** | Ninguna (BASIC tier no soporta RDB/AOF) |
| **Costo estimado** | ~$36/mes |

## Despliegue vía Terraform

La configuración Terraform está en `infra/redis/terraform/`. El pipeline `cloudbuild.yaml` automatiza el despliegue.

### Requisitos previos

1. **GCS bucket** para Terraform state:
   ```bash
   gsutil mb -l southamerica-west1 gs://nordikia-tfstate
   gsutil versioning set on gs://nordikia-tfstate
   ```

2. **APIs habilitadas:**
   ```bash
   gcloud services enable \
     redis.googleapis.com \
     vpcaccess.googleapis.com \
     servicenetworking.googleapis.com \
     --project nordikia
   ```

3. **Service Account** `nordik-build-sa@nordikia.iam.gserviceaccount.com` con roles:
   - `roles/redis.admin` (Memorystore)
   - `roles/vpcaccess.admin` (VPC connector)
   - `roles/compute.networkAdmin` (firewall rules)
   - `roles/secretmanager.admin` (guardar connection string)
   - `roles/iam.serviceAccountUser`

### Ejecutar despliegue

```bash
# Vía Cloud Build (recomendado)
gcloud builds submit \
  --config infra/redis/cloudbuild.yaml \
  --no-source \
  --project nordikia

# Vía Terraform directo (desarrollo/testing)
cd infra/redis/terraform
terraform init \
  -backend-config="bucket=nordikia-tfstate" \
  -backend-config="prefix=redis"
terraform apply \
  -var="project_id=nordikia" \
  -var="region=southamerica-west1"
```

### Destruir (⚠️ irreversible — datos se pierden)

```bash
cd infra/redis/terraform
terraform destroy \
  -var="project_id=nordikia" \
  -var="region=southamerica-west1"
```

## Habilitar Redis en el backend

Cuando se active Redis, descomentar en `infra/cloud-run/service.yaml`:

```yaml
- name: REDIS_URL
  valueFrom:
    secretKeyRef:
      key: latest
      name: nordik-redis-url
```

Y en el código backend (`apps/dot/backend/app/core/`), configurar el cliente Redis:

```python
import redis.asyncio as aioredis
from app.core.settings import settings

redis_client: aioredis.Redis | None = None

async def get_redis() -> aioredis.Redis:
    global redis_client
    if redis_client is None:
        redis_url = settings.redis_url  # poblado desde REDIS_URL env var
        if redis_url:
            redis_client = aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
    return redis_client
```

## Monitoreo

- **Cloud Monitoring:** métricas de Memorystore (memoria usada, conexiones, hits/misses).
- **Dashboard:** agregar panel `nordik-cache` a `infra/observability/dashboards/nordik-database.json`.

## Alternativas consideradas

| Alternativa | Pros | Contras | Decisión |
|---|---|---|---|
| **Memorystore** | Nativo GCP, baja latencia, VPC privado | ~$36/mes, tier BASIC sin failover | ✅ Elegido (cuando se active) |
| **Upstash Redis** | ~$0.2/mes para 100MB, serverless | Tráfico sale de la VPC, latencia de red pública | ❌ Descarte por seguridad |
| **En memoria (dict)** | Gratis, cero configuración | No compartido entre instancias, se pierde en scale-to-zero | ✅ Actual (MVP) |

## Notas de seguridad

- Memorystore solo acepta conexiones desde la VPC (sin IP pública). El VPC connector serverless es el único puente desde Cloud Run.
- La AUTH string de Redis se rota automáticamente por GCP y no se expone en variables de entorno.
- El secreto `nordik-redis-url` en Secret Manager solo es accesible por la SA de Cloud Run (`nordik-api-sa`).
