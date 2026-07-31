"""Configuracion central con pydantic-settings."""
from __future__ import annotations

import logging
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("dot.settings")

# Ruta absoluta al .env del backend (independiente del cwd del proceso).
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_ROOT / ".env"
_REPO_ROOT = _BACKEND_ROOT.parents[1]


def _resolve_backend_path(value: Path | str) -> Path:
    """Resuelve rutas relativas contra apps/dot/backend, no el cwd del proceso."""
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (_BACKEND_ROOT / path).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._check_production_secrets()

    @field_validator("google_client_secrets_path", "firebase_service_account_path", mode="before")
    @classmethod
    def _resolve_path_fields(cls, value: Path | str) -> Path | str:
        if value is None or value == "":
            return value
        return _resolve_backend_path(value)

    def _check_production_secrets(self):
        if not self.is_production:
            return
        missing = []
        if not self.hardware_token_pepper:
            missing.append("HARDWARE_TOKEN_PEPPER")
        if not self.jwt_secret and not self.jwt_private_key_pem:
            missing.append("JWT_SECRET o JWT_PRIVATE_KEY_PEM")
        if not self.token_encryption_key:
            missing.append("TOKEN_ENCRYPTION_KEY")
        if not self.admin_api_key:
            missing.append("ADMIN_API_KEY")
        if missing:
            log.critical(
                "PRODUCTION: Secrets faltantes: %s", ", ".join(missing)
            )

    dot_env: str = "development"

    database_url: str = ""

    # RS256 (producción)
    jwt_private_key_pem: str = ""
    jwt_public_key_pem: str = ""

    # HS256 legacy (solo desarrollo)
    jwt_secret: str = ""

    jwt_access_expires_minutes: int = 30
    jwt_refresh_expires_days: int = 30

    token_encryption_key: str = ""
    chat_encryption_key: str = ""

    firebase_service_account_path: Path = Path(
        Path(__file__).resolve().parent.parent / "firebase-service-account.json"
    )
    oauth_state_ttl_minutes: int = 15

    google_client_secrets_path: Path = (
        _REPO_ROOT / "infra" / "credentials" / "client_secret.json"
    )
    oauth_redirect_uri: str = "http://127.0.0.1:8000/oauth/google/callback"
    scope_gmail: str = "https://www.googleapis.com/auth/gmail.modify"
    scope_calendar: str = "https://www.googleapis.com/auth/calendar.events"
    scope_drive: str = "https://www.googleapis.com/auth/drive.readonly"

    cors_allow_origins: str = ""

    # Host header validation (producción)
    trusted_hosts: str = "127.0.0.1,localhost"

    allow_oauth_dev_without_firebase_auth: str = ""

    # SSL pinning opcional (lista de SHA-256 de certificados, separados por coma)
    api_tls_pin_sha256: str = ""

    # En producción: refresh/revocación solo en Firestore (sin memoria de proceso)
    refresh_use_firestore_only: str = ""

    # Tests: permite fallback en memoria sin Firestore
    testing: str = ""

    # Feature flags (ramas sin despliegue completo)
    enable_chat: bool = False
    enable_new_integration: bool = False
    enable_image_generation: bool = True

    # Pendrive USB (llave física DOT)
    hardware_token_pepper: str = ""

    # API key para acceso admin (auto-venta1 / panel)
    admin_api_key: str = ""

    # Chat: proveedor por defecto (Fase 1+)
    default_chat_provider: str = "default"

    # Búsqueda web
    enable_web_search: bool = True
    enable_web_search_in_chat: bool = True  # Detección automática en chat

    # Sentry APM (monitoreo de errores)
    sentry_dsn: str = ""

    # --- Logging centralizado ---
    logtail_source_token: str = ""
    logtail_host: str = "https://logs.betterstack.com"
    log_level: str = "INFO"

    # Deepseek API
    deepseek_api_key: str = Field("", env="DEEPSEEK_API_KEY")
    default_chat_model: str = "deepseek-chat"
    # T06b: timeout soft chat/proxy (30s). Agent/automation usan deepseek_agent_timeout_seconds.
    deepseek_chat_timeout_seconds: int = 30
    deepseek_agent_timeout_seconds: int = 180

    # D03: Auto-updater — URL base del feed de actualizaciones Electron
    dot_updater_url: str = ""

    # FASE 2.2: multi-step planner activado por defecto
    planner_enabled: bool = Field(default=True, env="PLANNER_ENABLED")
    # FREE-PL02: draft_plan vía LLM barato cuando hay DeepSeek (off by default)
    planner_llm: bool = Field(default=False, env="PLANNER_LLM")
    # FASE 2.2: reflexión post-paso — re-evalúa pasos restantes tras fallo parcial (on by default)
    planner_reflect: bool = Field(default=True, env="PLANNER_REFLECT")
    # PL06: continuar con el siguiente paso si uno falla (off by default)
    planner_continue_on_error: bool = Field(default=False, env="PLANNER_CONTINUE_ON_ERROR")

    # FREE-BR01: browser agent Electron local (Chromium embebido + CDP, off by default)
    browser_agent_enabled: bool = Field(default=False, env="BROWSER_AGENT_ENABLED")

    # FREE-AU01: composite automations orchestrator (off by default)
    automations_composite_enabled: bool = Field(
        default=False, env="AUTOMATIONS_COMPOSITE_ENABLED"
    )

    # FREE-AU03: calendar event triggers for automations (off by default)
    automations_calendar_triggers: bool = Field(
        default=False, env="AUTOMATIONS_CALENDAR_TRIGGERS"
    )

    # FREE-AU04: WhatsApp keyword triggers for automations (off by default)
    automations_wa_triggers: bool = Field(
        default=False, env="AUTOMATIONS_WA_TRIGGERS"
    )

    # FREE-DC01: doc/CV extraction pipeline (off by default)
    doc_pipeline_enabled: bool = Field(default=False, env="DOC_PIPELINE_ENABLED")

    # FREE-DC03: chunk size for large docs
    doc_pipeline_chunk_size: int = Field(default=3000, env="DOC_PIPELINE_CHUNK_SIZE")

    # FREE-DC04: LLM structured extraction (off by default; requires DEEPSEEK_API_KEY)
    doc_pipeline_llm: bool = Field(default=False, env="DOC_PIPELINE_LLM")

    # FREE-M06: embeddings locales para recuperación semántica de hechos (on by default in Fase 1.3)
    memory_embeddings_enabled: bool = Field(
        default=True, env="MEMORY_EMBEDDINGS_ENABLED"
    )

    # Sandbox de ejecución de código (Docker, off by default por seguridad)
    code_execution_enabled: bool = Field(
        default=True, env="CODE_EXECUTION_ENABLED"
    )

    # FREE-I03: Redis local opcional (cache / pub-sub WS futuro). Vacío = deshabilitado.
    redis_url: str = Field(default="", env="REDIS_URL")

    # MCP Server: expone DOT's ToolRegistry como servidor MCP (para Claude Desktop, Cursor, etc.)
    # Transportes: stdio (stdin/stdout) + SSE (HTTP /v1/mcp/sse).
    # Deshabilitado por defecto. Activar solo si se necesita exponer DOT externamente via MCP.
    mcp_server_enabled: bool = Field(default=False, env="MCP_SERVER_ENABLED")

    # Ollama: modelos locales via Ollama (http://localhost:11434).
    # Requiere Ollama instalado y corriendo. Sin API key — todo local y gratuito.
    # Modelos se auto-descubren via GET /api/tags.
    ollama_enabled: bool = Field(default=False, env="OLLAMA_ENABLED")
    ollama_base_url: str = Field(default="http://localhost:11434", env="OLLAMA_BASE_URL")

    # Límite unificado de consumo IA (Sprint 2.5)
    ai_usage_limit_enabled: bool = False
    ai_usage_monthly_limit_usd: float = 7.5
    ai_usage_billing_timezone: str = "America/Bogota"
    ai_cost_deepseek_input_per_1m: float = 0.14
    ai_cost_deepseek_output_per_1m: float = 0.28
    ai_cost_deepseek_reasoner_input_per_1m: float = 0.55
    ai_cost_deepseek_reasoner_output_per_1m: float = 2.19
    ai_cost_gemini_vision_per_request: float = 0.001
    ai_cost_imagen_per_image: float = 0.04
    # Gemini chat costs (per 1M tokens)
    ai_cost_gemini_flash_input_per_1m: float = 0.15
    ai_cost_gemini_flash_output_per_1m: float = 0.60
    ai_cost_gemini_pro_input_per_1m: float = 1.25
    ai_cost_gemini_pro_output_per_1m: float = 5.00
    # OpenAI chat costs (per 1M tokens)
    ai_cost_openai_mini_input_per_1m: float = 0.15
    ai_cost_openai_mini_output_per_1m: float = 0.60
    ai_cost_openai_4o_input_per_1m: float = 2.50
    ai_cost_openai_4o_output_per_1m: float = 10.00
    # Anthropic chat costs (per 1M tokens)
    ai_cost_anthropic_haiku_input_per_1m: float = 0.25
    ai_cost_anthropic_haiku_output_per_1m: float = 1.25
    ai_cost_anthropic_sonnet_input_per_1m: float = 3.00
    ai_cost_anthropic_sonnet_output_per_1m: float = 15.00

    # Generación de imágenes (Vertex Imagen — Sprint 2.5)
    imagen_vertex_model: str = "imagen-3.0-generate-002"
    image_gen_max_images_per_request: int = 4
    image_gen_default_resolution: str = "1024x1024"
    image_gen_enable_1080p: bool = False

    # Media Engine — generación multi-proveedor (Música, Video, Imágenes mejoradas)
    media_enabled: bool = Field(default=True, env="MEDIA_ENABLED")
    music_enabled: bool = Field(default=True, env="MUSIC_ENABLED")
    video_enabled: bool = Field(default=True, env="VIDEO_ENABLED")

    # Proveedores de música
    suno_api_key: str = Field(default="", env="SUNO_API_KEY")
    udio_api_key: str = Field(default="", env="UDIO_API_KEY")

    # Proveedores de video
    runway_api_key: str = Field(default="", env="RUNWAY_API_KEY")

    # Proveedores de imágenes alternativos
    replicate_api_key: str = Field(default="", env="REPLICATE_API_KEY")

    # Proveedor preferido de imágenes (auto = mejor disponible)
    image_generation_provider: str = Field(
        default="auto",
        env="IMAGE_GENERATION_PROVIDER",
    )

    # Gemini API (Google)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
    gemini_provider: str = Field("api_key", env="GEMINI_PROVIDER")
    gemini_vertex_model: str = "gemini-2.5-flash"
    google_cloud_project: str = Field(
        "",
        env=["GOOGLE_CLOUD_PROJECT", "GCP_PROJECT"],
    )
    google_cloud_location: str = Field("us-central1", env="GOOGLE_CLOUD_LOCATION")
    google_translate_api_key: str = ""

    @property
    def image_generation_enabled(self) -> bool:
        return bool(self.enable_image_generation or self.enable_new_integration)

    @property
    def normalized_gemini_provider(self) -> str:
        provider = (self.gemini_provider or "api_key").strip().lower()
        if provider not in {"api_key", "vertex"}:
            return "api_key"
        return provider

    # OpenAI API (ChatGPT) — también usado para Whisper STT
    openai_api_key: str = ""

    # Anthropic API (Claude)
    anthropic_api_key: str = ""

    # Groq API (Llama, Mixtral — FREE tier)
    groq_api_key: str = ""

    # Multi-model routing (Fase multi-model)
    model_routing_enabled: bool = True

    # ElevenLabs TTS (voz premium)
    elevenlabs_api_key: str = ""

    # Microsoft 365 / Outlook — integración enterprise (400M+ Office 365 users)
    outlook_enabled: bool = Field(default=False, env="OUTLOOK_ENABLED")
    azure_client_id: str = Field(default="", env="AZURE_CLIENT_ID")
    azure_tenant_id: str = Field(default="", env="AZURE_TENANT_ID")
    azure_client_secret: str = Field(default="", env="AZURE_CLIENT_SECRET")
    outlook_redirect_uri: str = Field(
        default="http://127.0.0.1:8000/v1/outlook/callback",
        env="OUTLOOK_REDIRECT_URI",
    )

    # Skills FREE — clima (OpenWeatherMap) y noticias (NewsAPI + RSS fallback)
    openweather_api_key: str = Field("", env="OPENWEATHER_API_KEY")
    newsapi_key: str = Field("", env="NEWSAPI_KEY")

    # Workboard: Kanban + Goal Trees para multi-agent coordination
    workboard_enabled: bool = Field(default=False, env="WORKBOARD_ENABLED")

    # Plugin System (al estilo OpenClaw's ClawHub)
    plugin_system_enabled: bool = Field(default=False, env="PLUGIN_SYSTEM_ENABLED")
    plugin_marketplace_url: str = Field(default="", env="PLUGIN_MARKETPLACE_URL")
    plugin_hot_reload: bool = Field(default=False, env="PLUGIN_HOT_RELOAD")

    # DEPRECADO: OpenClaw API (WhatsApp) — reemplazado por Baileys bridge
    # openclaw_api_url: str = ""

    # WA-07: Whitelist de comandos remotos permitidos (JSON string)
    allowed_remote_commands_json: str = '["download-file","system-info"]'

    # Webhook de WhatsApp (Baileys / bridge Electron envia mensajes entrantes aqui)
    whatsapp_webhook_url: str = "http://localhost:8000/v1/whatsapp/inbound"
    whatsapp_webhook_secret: str = ""

    # Bridge local Electron -> Baileys (envio outbound desde backend)
    whatsapp_bridge_url: str = "http://127.0.0.1:18790"
    whatsapp_bridge_secret: str = ""
    whatsapp_bridge_port: int = 18790

    # Política de auto-respuesta WhatsApp (Fase A):
    # - dot_group_mention: solo grupo "DOT" + mención "DOT" (+ opcional self)
    # - self_only: solo responder si from == teléfono vinculado del usuario
    # - all: permitir auto-reply a cualquier remitente (no recomendado aún)
    whatsapp_reply_policy: str = "dot_group_mention"
    whatsapp_reply_group_name: str = "DOT"
    whatsapp_reply_mention_token: str = "DOT"
    whatsapp_reply_require_mention: bool = True
    whatsapp_reply_require_self: bool = True
    # JIDs @g.us del grupo DOT (cuando Baileys no trae subject). Separados por coma.
    whatsapp_reply_group_jids: str = ""

    # Monitoreo: Prometheus metrics + Grafana dashboards
    metrics_enabled: bool = True
    metrics_port: int = 8000  # mismo puerto que la app, endpoint /metrics
    grafana_enabled: bool = False  # solo archivos de dashboards, no el servicio

    # I06b: Rate limiting (SlowAPI). Desactivar solo para load testing.
    rate_limit_enabled: bool = True

    # Retención D5 / T11 — purge memoria/chats/automaciones/OAuth tras 3 meses
    retention_days: int = 90
    retention_job_enabled: bool = True
    retention_job_cron_hour_utc: int = 4
    retention_activity_throttle_seconds: int = 3600

    # Dev: acceso amplio al disco del PC (Electron lo aplica; el prompt también).
    # En producción (DOT_ENV=production) siempre false.
    dot_full_disk_access: bool = False
    dot_demo_mode: bool = False

    @property
    def is_production(self) -> bool:
        return self.dot_env.strip().lower() == "production"

    @property
    def full_disk_access_enabled(self) -> bool:
        """True en desarrollo con DOT_FULL_DISK_ACCESS o DOT_DEMO_MODE."""
        if self.is_production:
            return False
        return bool(self.dot_full_disk_access or self.dot_demo_mode)

    @property
    def retention_scheduler_enabled(self) -> bool:
        """Cron D5 activo salvo tests o flag explícito en false."""
        if self.testing.strip() == "1":
            return False
        return bool(self.retention_job_enabled)

    @property
    def cors_origins(self) -> list[str]:
        raw = self.cors_allow_origins.strip()
        if raw:
            return [x.strip() for x in raw.split(",") if x.strip()]
        if self.is_production:
            return []
        # "null" = origen de Electron cuando carga file:// (fallback).
        # Preferir http://127.0.0.1:5173 via vite/preview en desktop.
        return [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "null",
        ]

    @property
    def trusted_hosts_list(self) -> list[str]:
        raw = self.trusted_hosts.strip()
        if not raw:
            return []
        return [x.strip() for x in raw.split(",") if x.strip()]

    @property
    def scopes(self) -> list[str]:
        return [self.scope_calendar, self.scope_gmail]

    @property
    def valid_google_integrations(self) -> frozenset:
        return frozenset({"gmail", "google-calendar"})

    @property
    def jwt_expires_minutes_clamped(self) -> int:
        return max(5, min(self.jwt_access_expires_minutes, 24 * 60))

    @property
    def use_firestore_token_store_only(self) -> bool:
        if self.testing.strip() == "1":
            return False
        if self.refresh_use_firestore_only.strip() == "1":
            return True
        return self.is_production

    @property
    def allow_dev_oauth(self) -> bool:
        if self.allow_oauth_dev_without_firebase_auth.strip() == "1":
            if self.is_production:
                raise RuntimeError(
                    "ALLOW_OAUTH_DEV_WITHOUT_FIREBASE_AUTH=1 no permitido con DOT_ENV=production."
                )
            return True
        return False

    @property
    def allowed_remote_commands(self) -> list[str]:
        import json as _json
        raw = self.allowed_remote_commands_json.strip()
        if not raw:
            return ["download-file", "system-info"]
        try:
            cmds = _json.loads(raw)
            if isinstance(cmds, list):
                return [str(c).strip() for c in cmds if c]
        except (ValueError, TypeError):
            log.warning("ALLOWED_REMOTE_COMMANDS_JSON invalido, usando default")
        return ["download-file", "system-info"]

    def google_scopes_for_integrations(self, integrations: list[str] | None) -> list[str]:
        if not integrations:
            return list(self.scopes)
        scopes: list[str] = []
        for key in integrations:
            k = key.strip().lower()
            if k == "gmail":
                scopes.append(self.scope_gmail)
                scopes.append(self.scope_drive)
            elif k == "google-calendar":
                scopes.append(self.scope_calendar)
        return scopes or list(self.scopes)


settings = Settings()
