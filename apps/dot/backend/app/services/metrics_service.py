"""Servicio de métricas Prometheus para monitoreo en tiempo real.

Expone contadores y gauges para chat IA, tokens, WhatsApp, automatizaciones,
circuit breakers, memoria y conexiones DB.

Uso:
    from app.services.metrics_service import metrics

    metrics.track_chat_message("deepseek", "deepseek-chat", 150, 400)
    metrics.track_ai_cost("chat", 0.0023)
    metrics.track_automation_execution("daily_report", "success")
"""

from __future__ import annotations

import logging

from prometheus_client import Counter, Gauge, Info

log = logging.getLogger("dot.metrics")


# ─── API-level metrics (auto from instrumentator) ────────────
# Se registran automáticamente vía prometheus-fastapi-instrumentator.
# requests_total, request_duration_seconds, etc.


# ─── Custom counters ─────────────────────────────────────────

CHAT_MESSAGES_TOTAL = Counter(
    "dot_chat_messages_total",
    "Total de mensajes de chat procesados",
    ["provider", "model"],
)

AI_TOKENS_CONSUMED = Counter(
    "dot_ai_tokens_consumed",
    "Total de tokens consumidos (entrada + salida)",
    ["operation"],  # chat, reasoning, vision, image_gen
)

AI_COST_USD = Counter(
    "dot_ai_cost_usd_total",
    "Costo total en USD acumulado por operación IA",
    ["operation"],
)

WHATSAPP_MESSAGES_TOTAL = Counter(
    "dot_whatsapp_messages_total",
    "Total de mensajes WhatsApp procesados",
    ["direction"],  # inbound, outbound
)

AUTOMATION_EXECUTIONS_TOTAL = Counter(
    "dot_automation_executions_total",
    "Total de ejecuciones de automatización",
    ["name", "status"],  # success, failure, timeout
)

MEMORY_OPERATIONS_TOTAL = Counter(
    "dot_memory_operations_total",
    "Total de operaciones de memoria (store, recall, forget, search)",
    ["operation_type"],
)


# ─── Custom gauges ───────────────────────────────────────────

ACTIVE_USERS = Gauge(
    "dot_active_users",
    "Usuarios conectados actualmente",
)

CIRCUIT_BREAKER_STATE = Gauge(
    "dot_circuit_breaker_state",
    "Estado del circuit breaker (0=closed, 1=open, 2=half_open)",
    ["breaker_name"],
)

DB_CONNECTIONS_ACTIVE = Gauge(
    "dot_db_connections_active",
    "Conexiones activas al pool de base de datos",
)

API_ERROR_RATE = Gauge(
    "dot_api_error_rate",
    "Tasa de error del API (ventana 5 minutos)",
)

API_AVG_LATENCY_SECONDS = Gauge(
    "dot_api_avg_latency_seconds",
    "Latencia promedio del API (ventana 5 minutos)",
)


# ─── Service Info ────────────────────────────────────────────

APP_INFO = Info(
    "dot_app_info",
    "Información de la aplicación DOT",
)


# ─── MetricsService ──────────────────────────────────────────

class MetricsService:
    """Fachada para registrar métricas personalizadas de negocio."""

    def track_chat_message(
        self,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
    ) -> None:
        """Registra un mensaje de chat y sus tokens."""
        CHAT_MESSAGES_TOTAL.labels(provider=provider, model=model).inc()
        total_tokens = tokens_in + tokens_out
        AI_TOKENS_CONSUMED.labels(operation="chat").inc(total_tokens)
        log.debug(
            "Métrica chat: provider=%s model=%s tokens_in=%d tokens_out=%d",
            provider, model, tokens_in, tokens_out,
        )

    def track_reasoning_tokens(self, tokens: int) -> None:
        """Registra tokens consumidos en razonamiento (DeepSeek-R1)."""
        AI_TOKENS_CONSUMED.labels(operation="reasoning").inc(tokens)

    def track_vision_tokens(self, tokens: int) -> None:
        """Registra tokens consumidos en visión (Gemini Vision)."""
        AI_TOKENS_CONSUMED.labels(operation="vision").inc(tokens)

    def track_image_generation(self, count: int = 1) -> None:
        """Registra generación de imágenes (Vertex Imagen)."""
        AI_TOKENS_CONSUMED.labels(operation="image_gen").inc(count)

    def track_ai_cost(self, operation: str, cost_usd: float) -> None:
        """Registra costo en USD de una operación IA."""
        AI_COST_USD.labels(operation=operation).inc(cost_usd)
        AI_TOKENS_CONSUMED.labels(operation=operation).inc(0)  # ensure label exists
        log.debug("Métrica costo IA: operation=%s cost=%.6f", operation, cost_usd)

    def track_whatsapp_message(self, direction: str) -> None:
        """Registra un mensaje WhatsApp entrante o saliente."""
        WHATSAPP_MESSAGES_TOTAL.labels(direction=direction).inc()

    def track_automation_execution(self, name: str, status: str) -> None:
        """Registra ejecución de automatización con su estado."""
        AUTOMATION_EXECUTIONS_TOTAL.labels(name=name, status=status).inc()

    def track_memory_operation(self, operation_type: str) -> None:
        """Registra operación de memoria: store, recall, forget, search."""
        MEMORY_OPERATIONS_TOTAL.labels(operation_type=operation_type).inc()

    def set_active_users(self, count: int) -> None:
        """Actualiza el gauge de usuarios activos."""
        ACTIVE_USERS.set(count)

    def set_circuit_breaker_state(self, breaker_name: str, state: str) -> None:
        """Actualiza el gauge de estado de circuit breaker.
        
        state: 'closed' → 0, 'open' → 1, 'half_open' → 2
        """
        state_map = {"closed": 0, "open": 1, "half_open": 2}
        value = state_map.get(state, -1)
        CIRCUIT_BREAKER_STATE.labels(breaker_name=breaker_name).set(value)

    def set_db_connections_active(self, count: int) -> None:
        """Actualiza el gauge de conexiones DB activas."""
        DB_CONNECTIONS_ACTIVE.set(count)

    def set_app_info(self, environment: str, version: str) -> None:
        """Registra información de la aplicación."""
        APP_INFO.info({
            "environment": environment,
            "version": version,
        })


# ─── Singleton ───────────────────────────────────────────────

metrics = MetricsService()
