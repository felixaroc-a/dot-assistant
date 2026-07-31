# Storage Backups — PostgreSQL to GCS

Backups automatizados de PostgreSQL a Google Cloud Storage para Nordik-IA.

## Overview

El script `backup-to-gcs.py` realiza:

1. `pg_dump -Fc` (custom format, comprimido y paralelizable)
2. Compresión adicional con gzip (opcional, flag `--compress`)
3. Upload a GCS con nombre fechado: `nordik_nordikdb_YYYYMMDD_HHMMSS.dump.gz`
4. Limpieza automática de backups expirados según `--retention-days`
5. Soporte para `--dry-run` (vuelca localmente sin subir)

## Prerequisites

- Python 3.11+
- PostgreSQL client tools (`pg_dump`) v14+
- `google-cloud-storage` library (`pip install google-cloud-storage`)
- Service account con permisos `storage.objects.create` y `storage.objects.delete` sobre el bucket

### Configurar GCS Bucket

```bash
# Crear bucket (si no existe)
gsutil mb -l us-central1 -c STANDARD gs://nordik-prod-db-backups

# Aplicar lifecycle rules
gsutil lifecycle set lifecycle.json gs://nordik-prod-db-backups

# Verificar
gsutil lifecycle get gs://nordik-prod-db-backups
```

### Configurar Service Account

```bash
# Crear service account
gcloud iam service-accounts create nordik-backup-sa \
  --display-name="Nordik DB Backup Service Account"

# Dar permisos sobre el bucket
gsutil iam ch \
  serviceAccount:nordik-backup-sa@PROJECT.iam.gserviceaccount.com:objectAdmin \
  gs://nordik-prod-db-backups

# Descargar key (guardar en infra/credentials/, NO comitear)
gcloud iam service-accounts keys create infra/credentials/nordik-backup-sa-key.json \
  --iam-account=nordik-backup-sa@PROJECT.iam.gserviceaccount.com
```

## Usage

### Manual backup

```bash
python backup-to-gcs.py \
  --db-host 127.0.0.1 \
  --db-port 5432 \
  --db-user nordik_admin \
  --db-pass "$DB_PASS" \
  --db-name nordikdb \
  --bucket nordik-prod-db-backups \
  --compress \
  --retention-days 30
```

### Dry run (volcar localmente sin subir)

```bash
python backup-to-gcs.py \
  --db-host 127.0.0.1 \
  --db-user nordik_admin \
  --db-pass "$DB_PASS" \
  --db-name nordikdb \
  --bucket nordik-prod-db-backups \
  --compress \
  --dry-run
```

### Con directorio de dumps personalizado

```bash
python backup-to-gcs.py ... --dump-dir /var/backups/nordik
```

## Cron Job Scheduling

### Linux (crontab)

Ejecutar backup diario a las 3:00 AM UTC:

```cron
# Nordik-IA daily backup — 3:00 AM UTC
0 3 * * * cd /opt/nordik-ia && python infra/storage-backups/backup-to-gcs.py \
  --db-host 127.0.0.1 --db-user nordik_admin --db-pass "$DB_PASS" \
  --db-name nordikdb --bucket nordik-prod-db-backups --compress \
  >> /var/log/nordik-backup.log 2>&1
```

### Google Cloud Scheduler + Cloud Run Jobs (recomendado para Cloud SQL)

1. **Containeriza el script** con Docker:

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y postgresql-client
RUN pip install google-cloud-storage
COPY backup-to-gcs.py /app/
WORKDIR /app
ENTRYPOINT ["python", "backup-to-gcs.py"]
```

2. **Crea un Cloud Run Job:**

```bash
gcloud run jobs create nordik-db-backup \
  --image us-central1-docker.pkg.dev/PROJECT/nordik/backup:latest \
  --region us-central1 \
  --set-env-vars "DB_HOST=/cloudsql/PROJECT:us-central1:nordik-db,DB_USER=nordik_admin,DB_NAME=nordikdb,BUCKET=nordik-prod-db-backups" \
  --set-secrets "DB_PASS=nordik-db-password:latest" \
  --service-account nordik-backup-sa@PROJECT.iam.gserviceaccount.com \
  --add-cloudsql-instances PROJECT:us-central1:nordik-db
```

3. **Programa con Cloud Scheduler:**

```bash
gcloud scheduler jobs create http nordik-daily-backup \
  --schedule="0 3 * * *" \
  --time-zone="America/Lima" \
  --uri="https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/PROJECT/jobs/nordik-db-backup:run" \
  --http-method POST \
  --oauth-service-account-email nordik-backup-sa@PROJECT.iam.gserviceaccount.com
```

## Lifecycle Rules

Aplicadas via `lifecycle.json`:

| Acción | Condición | Efecto |
|--------|-----------|--------|
| Transition to Nearline | age > 7 days | Reduce costo de almacenamiento |
| Transition to Archive | age > 90 days | Almacenamiento de largo plazo |
| Delete | age > 365 days | Eliminación definitiva |

Esto mantiene backups diarios por 30 días con costo optimizado.

## Monitoring

### Verificar último backup manualmente

```bash
gsutil ls -l gs://nordik-prod-db-backups/ | tail -5
```

### Cloud Monitoring Alert (recomendado)

Crear alerta si no hay backup en las últimas 26 horas:

```bash
gcloud monitoring policies create \
  --display-name="Nordik DB — No backup in 26h" \
  --condition-filter='metric.type="storage.googleapis.com/object_count" AND resource.labels.bucket_name="nordik-prod-db-backups"' \
  --condition-threshold-value=0 \
  --condition-threshold-duration=1560s \
  --condition-comparison=COMPARISON_LT \
  --notification-channels=PROJECTS/nordik-prod/notificationChannels/XXX
```

### Verificar ciclo de vida

```bash
gsutil lifecycle get gs://nordik-prod-db-backups
```

### Logs

Los logs del script se escriben a stdout con timestamps en formato:

```
[2026-07-24 03:00:01] INFO — === PostgreSQL Backup to GCS ===
[2026-07-24 03:00:15] INFO — Upload complete — nordik_nordikdb_20260724_030000.dump.gz
[2026-07-24 03:00:20] INFO — === Backup completed successfully ===
```

## Restore from Backup

### Desde GCS

```bash
# Descargar backup
gsutil cp gs://nordik-prod-db-backups/nordik_nordikdb_20260724_030000.dump.gz .

# Descomprimir
gunzip nordik_nordikdb_20260724_030000.dump.gz

# Restaurar via Cloud SQL Proxy
pg_restore \
  -h 127.0.0.1 -p 5433 \
  -U postgres -d nordikdb \
  -j 4 --clean --if-exists --no-owner --no-acl \
  nordik_nordikdb_20260724_030000.dump
```

### Validar backup sin restaurar

```bash
pg_restore --list nordik_nordikdb_20260724_030000.dump | head -20
```

## Secrets Management

Las credenciales de base de datos NO deben estar en texto plano. Opciones:

1. **Secret Manager** (producción): `DB_PASS=projects/PROJECT/secrets/nordik-db-password/versions/latest`
2. **Variables de entorno** (desarrollo): `export DB_PASS=$(cat infra/credentials/db-pass.txt)`
3. **Cloud Run secrets** (Cloud Run Jobs): `--set-secrets DB_PASS=nordik-db-password:latest`

Nunca comitear contraseñas al repositorio.
