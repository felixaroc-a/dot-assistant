"""Servicio de webhooks salientes (outbound webhooks).

Permite configurar URLs que DOT llama cuando ocurren eventos
(nueva conversación, resultado de automatización, recordatorio disparado).

Características:
- CRUD de webhooks por usuario
- Cola de entrega con reintentos (exponential backoff)
- Filtrado por tipo de evento
- Log de entregas
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx


log = logging.getLogger("dot.webhooks")

MAX_WEBHOOKS_PER_USER = 10
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2  # segundos (exponencial: 2, 4, 8)
REQUEST_TIMEOUT = 10  # segundos


class WebhookEvent(str, Enum):
    """Eventos que pueden disparar webhooks."""
    chat_new_message = "chat.new_message"
    chat_new_conversation = "chat.new_conversation"
    automation_completed = "automation.completed"
    automation_failed = "automation.failed"
    reminder_fired = "reminder.fired"
    whatsapp_inbound = "whatsapp.inbound"
    whatsapp_outbound = "whatsapp.outbound"
    memory_updated = "memory.updated"
    sub_agent_completed = "sub_agent.completed"
    sub_agent_failed = "sub_agent.failed"
    document_generated = "document.generated"


@dataclass
class WebhookConfig:
    """Configuración de un webhook."""
    id: str
    uid: str
    url: str
    events: list[str] = field(default_factory=lambda: ["chat.new_message"])
    secret: str = ""
    enabled: bool = True
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_fired_at: str | None = None
    delivery_count: int = 0
    failure_count: int = 0
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class WebhookDelivery:
    """Registro de una entrega de webhook."""
    id: str
    webhook_id: str
    event: str
    payload: dict[str, Any]
    status: str  # "pending", "delivered", "failed"
    status_code: int | None = None
    response_body: str = ""
    error: str = ""
    attempt: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None


class WebhookService:
    """Gestor de webhooks — singleton en memoria."""

    def __init__(self):
        self._webhooks: dict[str, dict[str, WebhookConfig]] = {}  # uid -> {webhook_id -> config}
        self._deliveries: list[WebhookDelivery] = []
        self._lock = asyncio.Lock()
        self._delivery_queue: asyncio.Queue[tuple[WebhookConfig, str, dict[str, Any]]] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._shutting_down = False

    # ── CRUD ───────────────────────────────────────────────────────

    async def create_webhook(
        self,
        uid: str,
        url: str,
        events: list[str] | None = None,
        secret: str = "",
        description: str = "",
        headers: dict[str, str] | None = None,
    ) -> WebhookConfig:
        """Crea un nuevo webhook para un usuario."""
        import uuid

        async with self._lock:
            user_webhooks = self._webhooks.setdefault(uid, {})

            enabled_count = sum(1 for w in user_webhooks.values() if w.enabled)
            if enabled_count >= MAX_WEBHOOKS_PER_USER:
                raise ValueError(
                    f"Límite de webhooks alcanzado ({MAX_WEBHOOKS_PER_USER}). "
                    "Desactiva o elimina uno existente."
                )

            webhook_id = str(uuid.uuid4())
            config = WebhookConfig(
                id=webhook_id,
                uid=uid,
                url=url.rstrip("/"),
                events=list(events or ["chat.new_message"]),
                secret=secret,
                description=description,
                headers=dict(headers or {}),
            )

            user_webhooks[webhook_id] = config
            log.info("Webhook creado uid=%s id=%s url=%s", uid[:8], webhook_id[:8], url)

        return config

    async def update_webhook(
        self,
        uid: str,
        webhook_id: str,
        *,
        url: str | None = None,
        events: list[str] | None = None,
        secret: str | None = None,
        enabled: bool | None = None,
        description: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> WebhookConfig | None:
        """Actualiza un webhook existente."""
        async with self._lock:
            user_webhooks = self._webhooks.get(uid, {})
            config = user_webhooks.get(webhook_id)

            if config is None:
                return None

            if url is not None:
                config.url = url.rstrip("/")
            if events is not None:
                config.events = events
            if secret is not None:
                config.secret = secret
            if enabled is not None:
                config.enabled = enabled
            if description is not None:
                config.description = description
            if headers is not None:
                config.headers = headers

            log.info("Webhook actualizado uid=%s id=%s", uid[:8], webhook_id[:8])

        return config

    async def delete_webhook(self, uid: str, webhook_id: str) -> bool:
        """Elimina un webhook."""
        async with self._lock:
            user_webhooks = self._webhooks.get(uid, {})
            if webhook_id in user_webhooks:
                del user_webhooks[webhook_id]
                log.info("Webhook eliminado uid=%s id=%s", uid[:8], webhook_id[:8])
                return True
        return False

    async def get_webhook(self, uid: str, webhook_id: str) -> WebhookConfig | None:
        """Obtiene un webhook específico."""
        async with self._lock:
            return self._webhooks.get(uid, {}).get(webhook_id)

    async def list_webhooks(self, uid: str) -> list[WebhookConfig]:
        """Lista todos los webhooks de un usuario."""
        async with self._lock:
            return list(self._webhooks.get(uid, {}).values())

    # ── Disparo ────────────────────────────────────────────────────

    async def fire_event(
        self,
        event: str,
        payload: dict[str, Any],
    ) -> int:
        """Dispara un evento a todos los webhooks que lo escuchan.

        Returns:
            Número de webhooks notificados.
        """
        count = 0
        async with self._lock:
            for uid, user_webhooks in self._webhooks.items():
                for config in user_webhooks.values():
                    if not config.enabled:
                        continue
                    if event not in config.events:
                        continue
                    await self._delivery_queue.put((config, event, payload))
                    count += 1

        if count > 0:
            log.debug("Evento '%s' encolado para %d webhooks", event, count)

        return count

    async def fire_event_for_user(
        self,
        uid: str,
        event: str,
        payload: dict[str, Any],
    ) -> int:
        """Dispara un evento solo a los webhooks de un usuario específico."""
        count = 0
        async with self._lock:
            user_webhooks = self._webhooks.get(uid, {})
            for config in user_webhooks.values():
                if not config.enabled:
                    continue
                if event not in config.events:
                    continue
                await self._delivery_queue.put((config, event, payload))
                count += 1

        return count

    # ── Worker de entrega ──────────────────────────────────────────

    async def start_worker(self) -> None:
        """Inicia el worker de entrega de webhooks."""
        if self._worker_task is not None:
            return

        self._worker_task = asyncio.create_task(
            self._delivery_loop(),
            name="webhook-delivery-worker",
        )
        log.info("Webhook delivery worker iniciado")

    async def stop_worker(self) -> None:
        """Detiene el worker de entrega."""
        self._shutting_down = True
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        log.info("Webhook delivery worker detenido")

    async def _delivery_loop(self) -> None:
        """Loop principal de entrega de webhooks."""
        while not self._shutting_down:
            try:
                config, event, payload = await asyncio.wait_for(
                    self._delivery_queue.get(),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                continue

            await self._deliver_webhook(config, event, payload)

    async def _deliver_webhook(
        self,
        config: WebhookConfig,
        event: str,
        payload: dict[str, Any],
    ) -> None:
        """Entrega un webhook con reintentos exponenciales."""
        import uuid

        delivery_id = str(uuid.uuid4())
        body = {
            "event": event,
            "webhook_id": config.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "DOT-Webhook/1.0",
            **config.headers,
        }

        if config.secret:
            headers["X-Webhook-Secret"] = config.secret

        success = False
        last_error = ""
        last_status = 0

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                    resp = await client.post(
                        config.url,
                        content=body_bytes,
                        headers=headers,
                    )

                config.delivery_count += 1
                config.last_fired_at = datetime.now(timezone.utc).isoformat()

                if 200 <= resp.status_code < 300:
                    delivery = WebhookDelivery(
                        id=delivery_id,
                        webhook_id=config.id,
                        event=event,
                        payload=body,
                        status="delivered",
                        status_code=resp.status_code,
                        response_body=resp.text[:500],
                        attempt=attempt,
                        completed_at=datetime.now(timezone.utc).isoformat(),
                    )
                    self._deliveries.append(delivery)
                    log.debug("Webhook entregado id=%s event=%s status=%d", config.id[:8], event, resp.status_code)
                    success = True
                    break
                else:
                    last_status = resp.status_code
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    log.warning(
                        "Webhook delivery intento %d id=%s event=%s status=%d",
                        attempt, config.id[:8], event, resp.status_code,
                    )

            except httpx.TimeoutException:
                last_error = "Timeout"
                log.warning("Webhook timeout id=%s event=%s attempt=%d", config.id[:8], event, attempt)
            except Exception as e:
                last_error = str(e)[:200]
                log.warning("Webhook error id=%s event=%s attempt=%d: %s", config.id[:8], event, attempt, e)

            if attempt < MAX_RETRIES:
                delay = RETRY_DELAY_BASE ** attempt
                await asyncio.sleep(delay)

        if not success:
            config.failure_count += 1
            delivery = WebhookDelivery(
                id=delivery_id,
                webhook_id=config.id,
                event=event,
                payload=body,
                status="failed",
                status_code=last_status or None,
                error=last_error,
                attempt=MAX_RETRIES,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            self._deliveries.append(delivery)
            log.error(
                "Webhook falló tras %d intentos id=%s event=%s: %s",
                MAX_RETRIES, config.id[:8], event, last_error,
            )

    def get_deliveries(
        self,
        webhook_id: str | None = None,
        limit: int = 50,
    ) -> list[WebhookDelivery]:
        """Obtiene el historial de entregas."""
        deliveries = self._deliveries
        if webhook_id:
            deliveries = [d for d in deliveries if d.webhook_id == webhook_id]
        return sorted(deliveries, key=lambda d: d.created_at, reverse=True)[:limit]


# ── Singleton ────────────────────────────────────────────────────────

_webhook_service: WebhookService | None = None


def get_webhook_service() -> WebhookService:
    """Devuelve el singleton WebhookService."""
    global _webhook_service
    if _webhook_service is None:
        _webhook_service = WebhookService()
    return _webhook_service


async def init_webhook_service() -> WebhookService:
    """Inicializa el servicio de webhooks."""
    service = get_webhook_service()
    await service.start_worker()
    log.info("WebhookService inicializado con delivery worker")
    return service


async def shutdown_webhook_service() -> None:
    """Apaga el servicio de webhooks."""
    service = get_webhook_service()
    await service.stop_worker()
    log.info("WebhookService apagado")
