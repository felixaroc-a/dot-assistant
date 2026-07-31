"""DOT API -- FastAPI con routers separados, logging y rate limiting.

T01: Scheduler 100% AsyncIOScheduler con health check + auto-restart.
I06b: SlowAPI rate limits por endpoint.
Edge cases: graceful shutdown signals (SIGTERM/SIGINT), DB retry con backoff.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import timezone as dt_timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator.metrics import latency
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import crypto_tokens
from app.dependencies.limiter import limiter
from app.firebase_db import init_firebase
from app.jwt_keys import get_jwt_signing_config, jwt_configured
from app.routers import (
    admin_analytics,
    admin_secrets,
    auth,
    automations,
    briefing,
    capabilities,
    chat,
    chat_conversations,
    code_execution,
    contacts,
    cron,
    document_analysis,
    documents,
    health,
    images,
    memory,
    oauth,
    outlook,
    pendrive,
    pendrive_recovery,
    pendrive_admin,
    plugins,
    pptx,
    proactive_triggers,
    self_service,
    sub_agents,
    support,
    support_admin,
    swarm,
    usb_provisioning,
    profile,
    store,
    templates,
    telemetry,
    tools,
    updates,
    usage,
    vision,
    voice,
    media,
    webhooks,
    whatsapp_channel,
    whatsapp_messaging,
    whatsapp_automation,
    whatsapp_remote,
    signal_channel,
    line_channel,
    teams_channel,
    ws,
    workboard,
)
from app.routers.automations import pipelines_router, automation_templates_router
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from app.middleware.request_logging import RequestLoggingMiddleware
from app.security.headers import SecurityHeadersMiddleware
from app.services.input_sanitizer import InputSanitizerMiddleware
from app.services.automation_scheduler import AutomationScheduler
from app.services.cron_service import CronService
from app.services.error_messages import translate_error, translate_http_exception
from app.services.reminder_service import ReminderService
from app.services.retention_service import RetentionService
from app.services.template_service import TemplateService
from app.settings import settings

from dot_billing.logging_config import configure_logging

configure_logging(
    service_name="dot.api",
    level=settings.log_level,
    logtail_token=settings.logtail_source_token,
    logtail_host=settings.logtail_host,
)
log = logging.getLogger("dot.api")

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.dot_env,
        integrations=[
            FastApiIntegration(),
            LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR),
        ],
        traces_sample_rate=0.2,
        send_default_pii=False,
    )
    log.info("Sentry APM inicializado (env=%s)", settings.dot_env)

# Métodos HTTP expuestos por el API (templates DELETE, profile PATCH, etc.)
CORS_ALLOW_METHODS = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]


# ─── System backup (Billing-Ops) ─────────────────────────────────

def _run_system_backup() -> None:
    """Ejecuta backup completo del sistema diariamente."""
    try:
        log.info("Iniciando backup automático del sistema...")
        result = subprocess.run(
            [
                sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "backup_full.py"),
                "--keep", "7",
            ],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode == 0:
            log.info("Backup automático completado OK")
        else:
            log.error("Backup automático falló (código %d): %s", result.returncode, result.stderr[-500:])
    except subprocess.TimeoutExpired:
        log.error("Backup automático: timeout (>600s)")
    except Exception as e:
        log.exception("Backup automático: error inesperado: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Iniciando DOT API (entorno: %s)", settings.dot_env)

    # T01: graceful shutdown signals
    _shutdown_event = asyncio.Event()
    _loop = asyncio.get_running_loop()

    def _on_sigterm() -> None:
        log.warning("SIGTERM recibido — iniciando apagado graceful")
        _shutdown_event.set()

    def _on_sigint() -> None:
        log.warning("SIGINT recibido — iniciando apagado graceful")
        _shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            _loop.add_signal_handler(sig, _on_sigterm if sig == signal.SIGTERM else _on_sigint)
        except (NotImplementedError, RuntimeError):
            log.debug("Signal handler no disponible para %s en Windows", sig.name if hasattr(sig, 'name') else sig)

    pepper = settings.hardware_token_pepper.strip()
    if pepper:
        if len(pepper) < 32:
            log.critical(
                "HARDWARE_TOKEN_PEPPER debe tener al menos 32 caracteres. Tiene %d.",
                len(pepper),
            )
        os.environ["HARDWARE_TOKEN_PEPPER"] = pepper
    else:
        log.critical(
            "hardware_token_pepper vacio en settings. "
            "Establezca HARDWARE_TOKEN_PEPPER en .env. "
            "El login con pendrive fallara."
        )
    # Detectar valores default/dev que no deberian usarse en produccion
    _known_defaults = frozenset({
        "dot-pendrive-v1-dev-only-change-in-prod",
        "dev-only-change-hardware-token-pepper",
    })
    if pepper in _known_defaults:
        log.critical(
            "HARDWARE_TOKEN_PEPPER tiene el valor por defecto '%s'. "
            "Cambielo por un secreto unico antes de produccion.",
            pepper,
        )

    firebase_ok = False
    try:
        init_firebase()
        log.info("Firestore conectado")
        firebase_ok = True
    except Exception:
        log.warning(
            "Modo offline — Firestore no disponible. Usando SQLite local."
        )

    # Inicializar scheduler de automatizaciones
    app.state.auto_scheduler = AutomationScheduler()
    app.state.auto_scheduler.start()
    from app.services.automation_scheduler import set_active_scheduler

    set_active_scheduler(app.state.auto_scheduler)
    log.info("AutomationScheduler inicializado y corriendo")

    if firebase_ok:
        def _hydrate_automations_bg() -> None:
            try:
                from app.services.automation_bootstrap import (
                    hydrate_all_scheduled_automations,
                    hydrate_all_scheduled_pipelines,
                )

                hydrate_all_scheduled_automations(app.state.auto_scheduler)
                hydrate_all_scheduled_pipelines(app.state.auto_scheduler)
                app.state.auto_scheduler.mark_ready()
            except Exception:
                log.warning("No se pudieron rehidratar automatizaciones al arranque", exc_info=True)

        asyncio.create_task(
            asyncio.to_thread(_hydrate_automations_bg),
            name="hydrate-automations",
        )
    app.state.reminder_service = ReminderService(enabled=firebase_ok)
    from app.services.reminder_service import set_active_reminder_service

    set_active_reminder_service(app.state.reminder_service)
    log.info("ReminderService inicializado")
    retention_ok = firebase_ok and settings.retention_scheduler_enabled
    app.state.retention_service = RetentionService(enabled=retention_ok)
    log.info(
        "RetentionService inicializado (enabled=%s, days=%d)",
        retention_ok,
        settings.retention_days,
    )
    app.state.template_service = TemplateService(enabled=firebase_ok)
    log.info("TemplateService inicializado")

    # C3: Servicio de plantillas de automatización
    from app.services.automation_template_service import AutomationTemplateService
    app.state.auto_template_service = AutomationTemplateService(enabled=firebase_ok)
    log.info("AutomationTemplateService inicializado")
    if firebase_ok:
        def _seed_auto_templates_bg() -> None:
            try:
                count = app.state.auto_template_service.seed_default_templates()
                if count:
                    log.info("Seed de plantillas de automatización: %d insertadas.", count)
            except Exception:
                log.warning("No se pudo hacer seed de plantillas de automatización", exc_info=True)

        asyncio.create_task(
            asyncio.to_thread(_seed_auto_templates_bg),
            name="seed-auto-templates",
        )

    # CronService: tareas programadas recurrentes de usuarios
    app.state.cron_service = CronService(enabled=firebase_ok)
    app.state.cron_service.start()
    from app.services.cron_service import set_active_cron_service

    set_active_cron_service(app.state.cron_service)
    if firebase_ok:
        def _hydrate_cron_jobs_bg() -> None:
            try:
                count = app.state.cron_service.load_all_persisted_jobs()
                log.info("Rehidratados %d jobs cron desde Firestore", count)
            except Exception:
                log.warning("No se pudieron rehidratar jobs cron al arranque", exc_info=True)

        asyncio.create_task(
            asyncio.to_thread(_hydrate_cron_jobs_bg),
            name="hydrate-cron-jobs",
        )
    log.info("CronService inicializado")

    # Security: Rotación automática de secretos cada 30 días
    from app.services.secret_rotation_service import get_secret_rotation_service

    secret_rotation = get_secret_rotation_service()
    secret_rotation.schedule_rotation(cron_service=app.state.cron_service)
    log.info("SecretRotationService: rotación automática programada cada 30 días")

    # Billing-Ops: Backup automático diario del sistema (Postgres + Firestore + GCS)
    _backup_scheduler = AsyncIOScheduler(timezone=dt_timezone.utc)
    try:
        _backup_scheduler.add_job(
            _run_system_backup,
            trigger=CronTrigger(hour=3, minute=0, timezone=dt_timezone.utc),
            id="system_backup_daily",
            name="System Backup (Postgres + Firestore + GCS)",
            replace_existing=True,
        )
        _backup_scheduler.start()
        log.info("BackupScheduler: programado diario a las 03:00 UTC")
    except Exception as e:
        log.warning("BackupScheduler no pudo iniciar: %s", e)
    app.state.backup_scheduler = _backup_scheduler

    if not settings.google_client_secrets_path.is_file():
        log.warning(
            "Google OAuth client_secret.json no encontrado en %s. OAuth no estara disponible.",
            settings.google_client_secrets_path,
        )

    # P0 (Manual Maestro): fail-closed en producción para chat_crypto
    if settings.is_production and not settings.chat_encryption_key.strip():
        log.critical(
            "PRODUCCION: CHAT_ENCRYPTION_KEY no configurada. "
            "Los mensajes cifrados de chat no podrán descifrarse. "
            "Configure CHAT_ENCRYPTION_KEY en .env antes del próximo despliegue."
        )

    if not settings.token_encryption_key.strip():
        log.warning("TOKEN_ENCRYPTION_KEY no configurada. Tokens OAuth no funcionaran.")
    else:
        try:
            crypto_tokens.encrypt_token_blob({"probe": True})
            log.info("Fernet encryption key valida")
        except Exception as e:
            log.error("TOKEN_ENCRYPTION_KEY invalida: %s", e)

    if jwt_configured():
        try:
            cfg = get_jwt_signing_config()
            log.info("JWT configurado (%s)", cfg.algorithm)
        except Exception as e:
            log.error("Configuracion JWT invalida: %s", e)
    else:
        log.warning("JWT no configurado. Login no estara disponible.")

    if settings.is_production and not settings.cors_allow_origins.strip():
        log.warning("CORS_ALLOW_ORIGINS vacio en produccion.")

    # Edge cases: reintentos con backoff exponencial al startup DB
    db_ok = False
    if settings.database_url.strip() and (
        settings.testing.strip() != "1"
        or settings.dot_env.strip().lower() == "development"
    ):
        max_retries = 5
        base_delay = 1.0
        for attempt in range(1, max_retries + 1):
            try:
                from app.billing_db import get_engine
                from app.services.db_schema_bootstrap import ensure_backend_schema
                from app.services.db_schema_checklist import format_missing_tables_hint

                schema, applied = ensure_backend_schema(get_engine())
                if applied:
                    log.info("Columnas IA añadidas en arranque: %s", ", ".join(applied))
                if not schema.ok_billing_minimum:
                    log.critical(
                        "Esquema BD incompleto (billing): %s",
                        format_missing_tables_hint(schema, enable_chat=False),
                    )
                elif not schema.ok_chat:
                    log.error(
                        "Tablas chat faltantes tras bootstrap; GET /v1/chat fallará. %s",
                        format_missing_tables_hint(schema, enable_chat=True),
                    )
                elif not schema.ok_auth:
                    log.critical(
                        "Tablas auth faltantes tras bootstrap; login fallará. %s",
                        format_missing_tables_hint(schema, enable_chat=False),
                    )
                else:
                    log.info("Esquema BD al día (billing + chat + auth)")
                db_ok = True
                break
            except Exception as exc:
                delay = base_delay * (2 ** (attempt - 1))
                if attempt < max_retries:
                    log.warning(
                        "BD no disponible (intento %d/%d), reintentando en %.1fs: %s",
                        attempt, max_retries, delay, exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    log.error("Bootstrap de esquema BD falló tras %d intentos: %s", max_retries, exc)

    # Sandbox de código: verificar disponibilidad al arranque
    if settings.code_execution_enabled:
        try:
            from app.services.code_execution_service import get_code_execution_service

            sandbox_svc = get_code_execution_service()
            if sandbox_svc.is_available():
                log.info("Sandbox Docker disponible (dot-sandbox:latest)")
            else:
                log.warning(
                    "CODE_EXECUTION_ENABLED=true pero sandbox Docker no disponible. "
                    "Ejecute: docker build -f apps/dot/backend/Dockerfile.sandbox "
                    "-t dot-sandbox apps/dot/backend/"
                )
        except Exception as e:
            log.warning("No se pudo verificar sandbox Docker: %s", e)

    from app.services.ws_manager import start_redis_fanout

    start_redis_fanout(asyncio.get_running_loop())

    # T01: health monitoring del scheduler con auto-restart
    async def _monitor_scheduler_health() -> None:
        """Verifica el scheduler cada 30s y lo reinicia si murió."""
        await asyncio.sleep(10)  # dar tiempo al initial hydration
        while not _shutdown_event.is_set():
            try:
                scheduler = getattr(app.state, "auto_scheduler", None)
                if scheduler is not None and not scheduler.is_alive and scheduler._started:
                    log.critical("Scheduler murió! Intentando reinicio automático...")
                    try:
                        scheduler._scheduler = AsyncIOScheduler(timezone=dt_timezone.utc)
                        scheduler.start()
                        scheduler._restart_count += 1
                        log.info("Scheduler reiniciado exitosamente (reinicio #%d)",
                                 scheduler._restart_count)
                    except Exception as restart_err:
                        log.critical("No se pudo reiniciar el scheduler: %s", restart_err)
            except Exception as e:
                log.warning("Health monitor error: %s", e)
            await asyncio.sleep(30)

    scheduler_monitor_task = asyncio.create_task(
        _monitor_scheduler_health(),
        name="scheduler-health-monitor",
    )

    # MCP: inicializar cliente MCP con auto-discovery
    from app.services.mcp_service import init_mcp, shutdown_mcp
    from app.application.agent.tools import build_default_registry

    _mcp_registry = build_default_registry(
        include_web_search=bool(settings.enable_web_search)
    )
    try:
        await init_mcp(_mcp_registry)
    except Exception:
        log.warning("MCP initialization failed — continuing without MCP tools", exc_info=True)

    # MCP Server: exponer DOT como servidor MCP (si MCP_SERVER_ENABLED)
    if settings.mcp_server_enabled:
        from app.services.mcp_server import init_mcp_server

        try:
            init_mcp_server(_mcp_registry)
            log.info("MCP Server habilitado — DOT expuesto como servidor MCP")
        except Exception:
            log.warning("MCP Server initialization failed", exc_info=True)

    # Ollama: auto-descubrir modelos locales
    if settings.ollama_enabled:
        from app.services.model_registry import auto_discover_ollama_models

        try:
            ollama_models = auto_discover_ollama_models()
            log.info("Ollama: %d modelos locales descubiertos", len(ollama_models))
        except Exception:
            log.warning("Ollama auto-discovery failed", exc_info=True)

    # Sub-agentes: inicializar gestor con idle monitor
    from app.services.sub_agent_service import init_sub_agent_manager, shutdown_sub_agent_manager

    try:
        sub_agent_mgr = await init_sub_agent_manager()
        log.info("SubAgentManager inicializado")
    except Exception:
        log.warning("SubAgentManager initialization failed", exc_info=True)

    # Webhooks: inicializar servicio de webhooks salientes
    from app.services.webhook_service import init_webhook_service, shutdown_webhook_service

    try:
        await init_webhook_service()
        log.info("WebhookService inicializado")
    except Exception:
        log.warning("WebhookService initialization failed", exc_info=True)

    # Plugin System: inicializar gestor de plugins + marketplace
    from app.services.plugin_system import create_plugin_manager
    from app.services.plugin_marketplace import PluginMarketplace

    _plugins_dir = _BACKEND_ROOT / "plugin-examples"
    app.state.plugin_manager = create_plugin_manager(
        plugins_dir=_plugins_dir,
        registry=_mcp_registry,
        hot_reload=settings.plugin_hot_reload,
        enabled=settings.plugin_system_enabled,
    )
    app.state.plugin_marketplace = PluginMarketplace(
        marketplace_url=settings.plugin_marketplace_url,
        plugins_dir=_plugins_dir,
    )

    if app.state.plugin_manager is not None:
        # Cargar plugins preinstalados
        try:
            count = app.state.plugin_manager.load_all_from_directory(_plugins_dir)
            log.info("PluginManager: %d plugin(s) cargados al arranque", count)
        except Exception:
            log.warning("Error cargando plugins al arranque", exc_info=True)

        if settings.plugin_hot_reload:
            await app.state.plugin_manager.start_hot_reload()
            log.info("Plugin hot-reload watcher iniciado")
    else:
        log.info("Sistema de plugins deshabilitado (PLUGIN_SYSTEM_ENABLED=false)")

    yield
    # Graceful shutdown: cancelar monitor, detener servicios
    _shutdown_event.set()
    if scheduler_monitor_task and not scheduler_monitor_task.done():
        scheduler_monitor_task.cancel()
        try:
            await scheduler_monitor_task
        except asyncio.CancelledError:
            pass
    from app.services.ws_manager import stop_redis_fanout

    stop_redis_fanout()
    if hasattr(app.state, "auto_scheduler"):
        from app.services.automation_scheduler import set_active_scheduler

        app.state.auto_scheduler.shutdown()
        set_active_scheduler(None)
        log.info("AutomationScheduler detenido")
    if hasattr(app.state, "reminder_service"):
        from app.services.reminder_service import set_active_reminder_service

        app.state.reminder_service.shutdown()
        set_active_reminder_service(None)
        log.info("ReminderService detenido")
    if hasattr(app.state, "retention_service"):
        app.state.retention_service.shutdown()
        log.info("RetentionService detenido")
    if hasattr(app.state, "cron_service"):
        from app.services.cron_service import set_active_cron_service

        app.state.cron_service.shutdown()
        set_active_cron_service(None)
        log.info("CronService detenido")
    if hasattr(app.state, "backup_scheduler"):
        app.state.backup_scheduler.shutdown(wait=False)
        log.info("BackupScheduler detenido")
    # Plugin System: detener hot-reload y descargar plugins
    if hasattr(app.state, "plugin_manager") and app.state.plugin_manager is not None:
        try:
            await app.state.plugin_manager.stop_hot_reload()
        except Exception:
            log.warning("Error deteniendo plugin hot-reload", exc_info=True)
        try:
            app.state.plugin_manager.shutdown()
        except Exception:
            log.warning("Error en shutdown de PluginManager", exc_info=True)
        log.info("PluginManager detenido")
    try:
        await shutdown_mcp()
    except Exception:
        log.warning("Error apagando MCP", exc_info=True)
    try:
        await shutdown_sub_agent_manager()
    except Exception:
        log.warning("Error apagando SubAgentManager", exc_info=True)
    try:
        await shutdown_webhook_service()
    except Exception:
        log.warning("Error apagando WebhookService", exc_info=True)
    log.info("DOT API detenido")


app = FastAPI(
    title="DOT API",
    description="Backend SaaS: autenticacion JWT, perfil Firestore, OAuth Google",
    version="1.1.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get("/api-docs", include_in_schema=False)
async def api_docs_page():
    return FileResponse(Path(__file__).resolve().parent.parent / "templates" / "api_docs.html")


@app.get("/admin/analytics", include_in_schema=False)
async def admin_analytics_dashboard():
    return FileResponse(
        Path(__file__).resolve().parent.parent / "templates" / "admin" / "analytics.html"
    )

# I06b — SlowAPI en código (capa además de Nginx).
# Usamos SlowAPIASGIMiddleware (ASGI puro): NO consume el body como SlowAPIMiddleware
# (BaseHTTPMiddleware), que rompía login/refresh JSON.
# Gate: desactivado en pytest (TESTING=1) o si RATE_LIMIT_ENABLED=false.
# Rate limits:
#   /v1/chat/send:         30/min
#   /v1/chat/send/stream:  10/min
#   /v1/chat/completion:   30/min
#   /v1/auth/login:         5/min
#   /v1/auth/*:            10/min (refresh/logout), /me: 30/min
#   Resto:                 60/min (default)
if settings.rate_limit_enabled and settings.testing.strip() != "1":
    from slowapi.middleware import SlowAPIASGIMiddleware

    app.add_middleware(SlowAPIASGIMiddleware)
    log.info("SlowAPI rate limiting activado (capa app)")
else:
    log.info("SlowAPI rate limiting desactivado (RATE_LIMIT_ENABLED=%s, TESTING=%s)",
             settings.rate_limit_enabled, settings.testing.strip())

# Middlewares ASGI puros (NO BaseHTTPMiddleware).
# Orden de ejecucion (ultimo agregado = primero en procesar):
# 1. RequestLoggingMiddleware (outermost) -> log entry/exit
# 2. InputSanitizerMiddleware -> escanea SQLi, XSS, path traversal, command injection
# 3. SecurityHeadersMiddleware -> valida host, agrega headers
# 4. CORSMiddleware (innermost) -> maneja CORS

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(InputSanitizerMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=CORS_ALLOW_METHODS,
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Admin-Key"],
)

# ─── Prometheus metrics ──────────────────────────────────────
if settings.metrics_enabled:
    _instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=False,
        should_instrument_requests_inprogress=True,
        should_respect_env_var=False,
    )
    _instrumentator.add(latency(buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)))
    _instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=True)
    log.info("Prometheus metrics expuesto en /metrics")

    # Registrar info de la app
    from app.services.metrics_service import metrics as metrics_svc
    metrics_svc.set_app_info(settings.dot_env, "1.1.0")


app.include_router(health.router)
app.include_router(admin_analytics.router)
app.include_router(admin_secrets.router)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(oauth.router)
app.include_router(chat.router)
app.include_router(chat_conversations.router)
app.include_router(contacts.router)
app.include_router(memory.router)
app.include_router(memory.search_router)
app.include_router(documents.router)
app.include_router(pptx.router)
app.include_router(telemetry.router)
app.include_router(usage.router)
app.include_router(capabilities.router)
app.include_router(cron.router)
app.include_router(briefing.router)
app.include_router(store.router)
app.include_router(plugins.router)
app.include_router(automations.router)
app.include_router(proactive_triggers.router)
app.include_router(pipelines_router)
app.include_router(automation_templates_router)
app.include_router(pendrive.router)
app.include_router(pendrive_recovery.router)
app.include_router(pendrive_admin.router)
app.include_router(self_service.router)
app.include_router(usb_provisioning.router)
app.include_router(vision.router)
app.include_router(voice.router)
app.include_router(images.router)
app.include_router(whatsapp_channel.router)
app.include_router(whatsapp_messaging.router)
app.include_router(whatsapp_automation.router)
app.include_router(whatsapp_remote.router)
app.include_router(signal_channel.router)
app.include_router(line_channel.router)
app.include_router(teams_channel.router)
app.include_router(outlook.router)
app.include_router(ws.router)
app.include_router(updates.router)
app.include_router(support.router)
app.include_router(support_admin.router)
app.include_router(sub_agents.sub_agents_router)
app.include_router(sub_agents.mcp_router)
app.include_router(code_execution.router)
app.include_router(tools.router)
app.include_router(document_analysis.router)
app.include_router(webhooks.router)
app.include_router(swarm.router)
app.include_router(media.router)
app.include_router(workboard.router)

# MCP Server: expone DOT como servidor MCP (gate: MCP_SERVER_ENABLED)
from app.routers import mcp as mcp_server_router  # noqa: E402

app.include_router(mcp_server_router.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    user_message = translate_http_exception(exc.status_code, str(exc.detail))
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": user_message, "error_id": str(uuid.uuid4())[:8]},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    log.warning("ValueError en %s", request.url.path)
    return JSONResponse(status_code=400, content={"detail": "Solicitud invalida."})


@app.exception_handler(PermissionError)
async def permission_error_handler(request: Request, exc: PermissionError):
    log.warning("PermissionError en %s", request.url.path)
    return JSONResponse(status_code=403, content={"detail": "Acceso denegado."})


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    user_message = translate_error(str(exc))
    log.exception("Unhandled error en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": user_message, "error_id": str(uuid.uuid4())[:8]},
    )
