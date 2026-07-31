# Guía de Desarrollo — Nordik-IA (DOT)

> **Versión:** 1.0  
> **Fecha:** 2026-07-19  
> **Audiencia:** Desarrolladores nuevos en Nordik-IA  
> **Producto:** DOT — Asistente IA de escritorio para Windows

---

## 1. Requisitos

| Dependencia | Versión | Notas |
|---|---|---|
| Node.js | 20+ | Recomendado 20 LTS |
| Python | 3.11+ | 3.14 usado en desarrollo |
| PostgreSQL | 14+ | Para billing y datos de suscripción |
| Git | 2.40+ | Control de versiones |
| npm | 10+ | Viene con Node 20 |

**Opcional (solo desarrollo con WhatsApp):**

- Cuenta de WhatsApp para test (un número secundario)
- Cuenta de Google Cloud (para Vertex AI, Gemini, Gmail/Calendar OAuth)

---

## 2. Clonar y levantar el proyecto

### 2.1 Clonar el repositorio

```bash
git clone <repo-url> Nordik-IA
cd Nordik-IA
```

### 2.2 Backend (FastAPI — puerto 8000)

```bash
cd apps/dot/backend

# Crear y activar entorno virtual
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS

# Instalar dependencias
pip install -r requirements.txt

# Copiar y configurar variables de entorno
cp .env.example .env
# Editar .env con tus valores (ver sección 8)

# Inicializar base de datos billing (PostgreSQL debe estar corriendo)
python scripts/init_billing_db.py

# Ejecutar migraciones Alembic
cd alembic
alembic upgrade head
cd ..

# Iniciar backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 2.3 Worker (procesos en segundo plano)

```bash
cd apps/dot/backend

# En otra terminal, con el venv activado:
python -m worker.worker_main --interval 3
```

### 2.4 Frontend (Electron + React + Vite)

```bash
cd apps/dot/frontend

# Instalar dependencias (con script de setup que baja Electron)
npm run setup

# Copiar variables de entorno
cp .env.example .env
# Editar .env con tus valores

# Iniciar en modo desarrollo (sin verificación de pendrive)
npm run desktop:no-usb
```

**Scripts útiles del frontend:**

| Script | Descripción |
|---|---|
| `npm run desktop` | Electron + Vite con verificación USB |
| `npm run desktop:no-usb` | Modo demo sin pendrive (DOT_DEMO_MODE=1) |
| `npm run backend:dev` | Arranca solo el backend |
| `npm run backend:dev:all` | Backend + worker simultáneos |
| `npm run test:backend` | Ejecuta tests del backend |
| `npm run test:coverage` | Tests con reporte de cobertura HTML |
| `npm run desktop:dist` | Build de producción para Windows |

---

## 3. Estructura de directorios (resumen de alto nivel)

```
Nordik-IA/
├── apps/
│   ├── dot/                    # Producto principal DOT
│   │   ├── backend/            # Backend FastAPI (Python)
│   │   │   ├── app/
│   │   │   │   ├── main.py     # Entry point de la API
│   │   │   │   ├── settings.py # Configuración de entorno
│   │   │   │   ├── routers/    # Endpoints REST
│   │   │   │   ├── services/   # Lógica de negocio
│   │   │   │   ├── application/# Capa de aplicación (DDD)
│   │   │   │   ├── domain/     # Dominio (DDD)
│   │   │   │   ├── infrastructure/ # Adaptadores externos
│   │   │   │   ├── schemas/    # Modelos Pydantic
│   │   │   │   └── tests/      # Tests unitarios e integración
│   │   │   ├── worker/         # Worker de tareas en segundo plano
│   │   │   ├── alembic/        # Migraciones de base de datos
│   │   │   └── requirements.txt
│   │   ├── frontend/           # Desktop app (Electron + React)
│   │   │   ├── src/            # Código React
│   │   │   │   ├── features/   # Features organizadas: auth, dashboard, onboarding
│   │   │   │   ├── lib/        # Utilidades compartidas, API client, i18n
│   │   │   │   └── shared/     # Constantes, temas, tipos
│   │   │   ├── electron/       # Main process de Electron (.cjs)
│   │   │   ├── config/         # Vite, electron-builder, ESLint
│   │   │   └── package.json
│   │   └── scripts/            # Scripts compartidos
│   ├── dot-admin/              # Panel de administración (backoffice)
│   └── dot-venta/              # App de ventas y provisión de pendrives
├── packages/
│   └── dot-billing/            # Paquete Python compartido (SQLAlchemy, bcrypt, hardware tokens)
├── infra/
│   ├── billing/                # Docker Compose PostgreSQL local + schema
│   ├── nginx/                  # Configuración de reverse proxy
│   └── observability/          # Prometheus + Grafana dashboards
├── docs/                       # Documentación (BIBLIA.md, MASTER-PLAN.md, contratos, etc.)
├── scripts/                    # Scripts de automatización y deploy
└── docker-compose.*.yml        # Compose files por entorno
```

---

## 4. Flujo de autenticación

El sistema usa autenticación de dos factores: **pendrive físico + credenciales**.

### 4.1 Proceso completo

1. **Inserción del pendrive DOT**
   - El usuario inserta un pendrive USB con un archivo `dot.vault` en la raíz
   - El vault contiene datos cifrados con AES-256-GCM vinculados al serial del USB
   - `electron/pendrive-gate.cjs` verifica el vault al arrancar

2. **Login con credenciales**
   - El usuario ingresa: cédula (E/J/V + dígitos) + contraseña
   - El serial del USB se envía junto con las credenciales
   - `POST /v1/auth/login` recibe: `{ cedula, password, hardware_serial }`

3. **Validación en backend**
   - Se busca al cliente en `clientes_suscripcion` por cédula
   - La contraseña se verifica con bcrypt
   - El serial se valida con SHA-256(serial + pepper) contra `hardware_token_hash`
   - Si todo coincide → se emite JWT (access + refresh con rotación)

4. **Sesión persistente**
   - El JWT access token se guarda en `safeStorage` del SO (cifrado)
   - El refresh token permite renovar la sesión sin re-login
   - Si el pendrive se desconecta, el monitor (`pendrive-gate.cjs`) emite `dot:usb-lost`
   - La app se bloquea hasta reconectar el mismo pendrive

5. **Modo Demo (solo desarrollo)**
   - `DOT_DEMO_MODE=1` + `app.isPackaged = false` → omite verificación USB
   - En producción (`app.isPackaged = true`), el modo demo se ignora automáticamente
   - Aparece un banner "MODO DEMO — Sin pendrive" en la pantalla de login

### 4.2 Diagrama simplificado

```
Usuario → Inserta USB → Login (cédula + clave) → Backend valida:
  ├── bcrypt(password) ✓
  ├── SHA-256(serial + pepper) ✓
  └── suscripción activa ✓
       → JWT emitido → Electron guarda en safeStorage → App lista
```

---

## 5. Cómo agregar una feature nueva

### Ejemplo real: Agregar un endpoint de "estadísticas semanales"

#### Paso 1: Definir el modelo de datos (si es necesario)

Si la feature requiere nueva tabla en PostgreSQL, crear migración Alembic:

```bash
cd apps/dot/backend
alembic revision -m "add_weekly_stats_table"
# Editar el archivo generado en alembic/versions/
alembic upgrade head
```

#### Paso 2: Crear el esquema Pydantic

```python
# apps/dot/backend/app/schemas/weekly_stats.py
from pydantic import BaseModel
from datetime import date

class WeeklyStatsResponse(BaseModel):
    week_start: date
    messages_sent: int
    ai_cost_usd: float
    automations_run: int
```

#### Paso 3: Crear el servicio

```python
# apps/dot/backend/app/services/weekly_stats_service.py
from datetime import date, timedelta

async def get_weekly_stats(cliente_id: str, week_start: date) -> dict:
    # Lógica de negocio aquí
    return {
        "week_start": week_start,
        "messages_sent": 42,
        "ai_cost_usd": 1.25,
        "automations_run": 3,
    }
```

#### Paso 4: Crear el router

```python
# apps/dot/backend/app/routers/weekly_stats.py
from fastapi import APIRouter, Depends
from app.auth_deps import get_current_user
from app.services.weekly_stats_service import get_weekly_stats
from app.schemas.weekly_stats import WeeklyStatsResponse

router = APIRouter(prefix="/v1/stats", tags=["stats"])

@router.get("/weekly", response_model=WeeklyStatsResponse)
async def weekly_stats(user=Depends(get_current_user)):
    return await get_weekly_stats(user.cliente_id, week_start=...)
```

#### Paso 5: Registrar el router en `main.py`

```python
# apps/dot/backend/app/main.py
from app.routers import weekly_stats
app.include_router(weekly_stats.router)
```

#### Paso 6: Agregar tests

```python
# apps/dot/backend/app/tests/test_weekly_stats.py
import pytest
from httpx import AsyncClient

@pytest.mark.anyio
async def test_weekly_stats_requires_auth(client: AsyncClient):
    response = await client.get("/v1/stats/weekly")
    assert response.status_code == 401
```

#### Paso 7: Conectar frontend (si aplica)

```typescript
// apps/dot/frontend/src/lib/api/weeklyStats.ts
import { apiClient } from './http'

export async function fetchWeeklyStats() {
  return apiClient.get('/v1/stats/weekly')
}
```

Ejecutar tests y verificar: `npm run test:coverage`

---

## 6. Cómo ejecutar tests

### Backend (Python)

```bash
cd apps/dot/frontend

# Tests rápidos (sin cobertura)
npm run test:backend

# Tests completos con reporte HTML de cobertura
npm run test:coverage
# Abrir coverage-report/index.html en el navegador
```

También se pueden ejecutar directamente desde el backend:

```bash
cd apps/dot/backend

# Todos los tests
python -m pytest app/tests/ -v

# Un archivo específico
python -m pytest app/tests/test_auth.py -v

# Con cobertura y fail-under 60%
python -m pytest app/tests/ --cov=app --cov-report=html --cov-fail-under=60
```

Configuración de coverage en `pyproject.toml`:
- `--cov-fail-under=60` → el build falla si coverage < 60%
- Reporte HTML en `coverage-report/`
- Excluye: tests, alembic, scripts, worker, `__pycache__`

### Frontend (TypeScript/React)

```bash
cd apps/dot/frontend

# Tests unitarios con Vitest
npm test

# Modo watch
npm run test:watch

# Tests end-to-end con Playwright
npm run test:e2e
```

### Worker

```bash
cd apps/dot/backend
python -m pytest worker/tests/ -v
```

---

## 7. Cómo hacer deploy

### 7.1 Build del instalador Windows

```bash
cd apps/dot/frontend

# Build completo (incrusta secretos + compila + empaqueta)
npm run dist:win

# El .exe se genera en release/
# DOT-Desktop-{version}-x64.exe (instalador NSIS)
# DOT-Desktop-{version}-x64-portable.exe (portable)
```

Configuración en `config/electron-builder.yml`:
- Instalador NSIS con selector de directorio
- Acceso directo en Escritorio y Menú Inicio
- Icono personalizado en `electron/icon.ico`
- Auto-updater via `electron-updater` (requiere feed URL configurado)

### 7.2 Deploy del backend a producción (GCP)

Ver `docs/DEPLOY-PROCEDURE.md` para el procedimiento completo. Resumen:

```bash
# 1. Conectar al servidor
ssh usuario@ip-servidor

# 2. Actualizar código
cd ~/Nordik-IA
git pull origin main

# 3. Aplicar migraciones
cd apps/dot/backend
source .venv/bin/activate
alembic upgrade head

# 4. Reiniciar servicios
pm2 restart nordik-api
pm2 restart nordik-worker

# 5. Verificar salud
curl https://nordikia.com/health
```

### 7.3 Base de datos (PostgreSQL)

- **Desarrollo local:** `docker compose -f infra/docker-compose.yml up -d` (levanta PostgreSQL + schema billing)
- **Migraciones:** `alembic upgrade head` (aplica cambios pendientes)
- **Backup:** `pg_dump -U nordik -d nordik_billing -Fc > backup.dump`
- **Schema canónico:** `infra/billing/schema.sql`

---

## 8. Variables de entorno esenciales

### Backend (`apps/dot/backend/.env`)

| Variable | Requerida | Descripción |
|---|---|---|
| `DOT_ENV` | Sí | `development` o `production` |
| `DATABASE_URL` | Sí | Conexión PostgreSQL: `postgresql+psycopg://user:pass@host:5432/nordik_billing` |
| `DEEPSEEK_API_KEY` | Sí | API key de DeepSeek para chat IA |
| `JWT_PRIVATE_KEY_PEM` | Prod | Clave privada RS256 para firmar JWTs |
| `JWT_PUBLIC_KEY_PEM` | Prod | Clave pública RS256 correspondiente |
| `JWT_SECRET` | Dev | Clave HS256 (solo desarrollo) |
| `TOKEN_ENCRYPTION_KEY` | Sí | Clave Fernet (32 bytes base64) para cifrar tokens OAuth |
| `HARDWARE_TOKEN_PEPPER` | Sí | Pepper para SHA-256 del serial USB |
| `ADMIN_API_KEY` | Sí | Clave para endpoints admin |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Sí | Ruta al JSON de service account de Firebase |
| `GOOGLE_CLIENT_SECRETS_PATH` | Opcional | Para OAuth de Google (Gmail/Calendar) |
| `GEMINI_API_KEY` | Opcional | Para voz STT y visión |
| `AI_USAGE_LIMIT_ENABLED` | Dev: `false` | Activar límite de $7.50/mes en producción |
| `CORS_ALLOW_ORIGINS` | Sí | Orígenes permitidos (frontend URL) |

### Frontend (`apps/dot/frontend/.env`)

| Variable | Requerida | Descripción |
|---|---|---|
| `VITE_API_BASE_URL` | Sí | URL del backend: `http://127.0.0.1:8000` |
| `DOT_DEMO_MODE` | Dev | `1` para omitir verificación USB en desarrollo |
| `VITE_DOT_DEMO_MODE` | Dev | Versión Vite de DOT_DEMO_MODE para el renderer |

### Docker (infraestructura local)

```bash
# Levantar PostgreSQL para desarrollo
docker compose -f infra/docker-compose.yml up -d

# Variables en infra/billing/.env.example
POSTGRES_USER=nordik
POSTGRES_PASSWORD=nordik_dev
POSTGRES_DB=nordik_billing
```

---

## 9. Recursos adicionales

| Documento | Ubicación | Contenido |
|---|---|---|
| BIBLIA (producto) | `docs/BIBLIA.md` | Visión, memoria, roadmap, decisiones de producto |
| Manual Maestro (ingeniería) | `docs/BIBLIA-SEGURIDAD-ESCALA.md` | Arquitectura, seguridad, escala, Diez Mandamientos |
| Plan de ejecución | `docs/MASTER-EXECUTION-PLAN.md` | Tareas pendientes por fase |
| Contratos API | `docs/contracts-v1.md` | Endpoints y sus contratos |
| Catálogo de secretos | `docs/secrets-catalog.md` | Qué API keys se necesitan y cómo obtenerlas |
| Checklist de regresión | `docs/regression-checklist.md` | Pruebas manuales antes de release |
| Modelo de amenazas | `docs/THREAT_MODEL.md` | Análisis de seguridad |
| Mapa de dependencias | `graphify-out/GRAPH_REPORT.md` | Grafo de módulos y dependencias |
| Runbooks | `docs/RUNBOOK-*.md` | Procedimientos de arranque, shutdown, recuperación |

---

## 10. Reglas del proyecto

1. **NO modificar** `auto-venta1/` ni `services/chatbot-cobro/` sin preguntar — son backoffice interno
2. **Mantener contratos** de `docs/contracts-v1.md`. Versionar endpoints si cambian
3. **Pasar regression-checklist.md** antes de mergear cambios mayores
4. **Consultar secrets-catalog.md** antes de pedir nuevas API keys
5. **Solo Windows** hasta nuevo aviso — no implementar soporte macOS/Linux
6. **Commits en español**, pequeños, atómicos — un cambio lógico por commit
7. **DOTEST obligatorio** después de cada tarea antes del commit
8. **Arquitectura Hexagonal + DDD** para features nuevas (ver BIBLIA §18)
9. El agente IA `openclaw` se usa desde npm registry para integraciones (Gmail, Calendar)
10. El límite de consumo IA es $7.50/mes por usuario/pendrive — no implementar gating por tier
