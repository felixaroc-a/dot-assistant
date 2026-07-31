"""
Circuit Breaker para servicios externos (DeepSeek, Vertex Vision, etc.).

Implementa el patrón Circuit Breaker con 3 estados:
  - CLOSED: operación normal, las llamadas pasan directamente
  - OPEN: bloqueado, las llamadas se rechazan inmediatamente
  - HALF_OPEN: periodo de prueba, se permite un número limitado de llamadas

Thread-safe con threading.Lock.
Sin dependencias externas, solo Python stdlib.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger("dot.circuit_breaker")

# T06b — alineado con PLAN-ESTRATEGICO (3 fallos → OPEN, recovery 60s)
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_RECOVERY_TIMEOUT = 60.0

# ── Registro global para health check ──────────────────────────
_breakers: dict[str, "CircuitBreaker"] = {}


def get_all_breakers() -> dict[str, "CircuitBreaker"]:
    """Devuelve todos los breakers registrados."""
    return dict(_breakers)


def register_breaker(breaker: "CircuitBreaker") -> None:
    """Registra un breaker en el catálogo global."""
    _breakers[breaker.name] = breaker


# ── Estados ─────────────────────────────────────────────────────
CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(RuntimeError):
    """Se lanza cuando el circuit breaker está OPEN y bloquea la llamada."""


@dataclass
class CircuitBreakerStats:
    """Snapshot del estado de un breaker para health checks."""
    name: str
    state: str
    failure_count: int
    failure_threshold: int
    recovery_timeout: float
    half_open_max: int
    half_open_attempts: int
    last_failure_time: float | None
    last_success_time: float | None
    open_since: float | None
    total_successes: int
    total_failures: int


class CircuitBreaker:
    """Circuit Breaker thread-safe para proteger llamadas a servicios externos.

    Estados:
      CLOSED → OPEN: al alcanzar failure_threshold fallos consecutivos
      OPEN → HALF_OPEN: tras recovery_timeout segundos
      HALF_OPEN → CLOSED: en el primer éxito
      HALF_OPEN → OPEN: en el primer fallo (vuelve a abrir inmediatamente)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        recovery_timeout: float = DEFAULT_RECOVERY_TIMEOUT,
        half_open_max: int = 1,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold debe ser >= 1")
        if recovery_timeout < 0:
            raise ValueError("recovery_timeout debe ser >= 0")
        if half_open_max < 1:
            raise ValueError("half_open_max debe ser >= 1")

        self.name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max = half_open_max

        self._lock = threading.Lock()
        self._state: str = CLOSED
        self._failure_count: int = 0
        self._half_open_attempts: int = 0
        self._last_failure_time: float | None = None
        self._last_success_time: float | None = None
        self._open_since: float | None = None
        self._total_successes: int = 0
        self._total_failures: int = 0

        # Auto-registro para health check
        register_breaker(self)

    # ── Propiedades ─────────────────────────────────────────────

    @property
    def state(self) -> str:
        """Estado actual del breaker (CLOSED, OPEN, HALF_OPEN)."""
        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    @property
    def failure_threshold(self) -> int:
        return self._failure_threshold

    @property
    def recovery_timeout(self) -> float:
        return self._recovery_timeout

    @property
    def half_open_max(self) -> int:
        return self._half_open_max

    @property
    def last_failure_time(self) -> float | None:
        with self._lock:
            return self._last_failure_time

    @property
    def last_success_time(self) -> float | None:
        with self._lock:
            return self._last_success_time

    # ── Lógica de transición ────────────────────────────────────

    def _transition_to_open(self) -> None:
        """Transición interna: CLOSED/HALF_OPEN → OPEN."""
        self._state = OPEN
        self._open_since = time.monotonic()
        log.warning(
            "CircuitBreaker '%s' → OPEN (failure_count=%d, threshold=%d)",
            self.name,
            self._failure_count,
            self._failure_threshold,
        )

    def _transition_to_half_open(self) -> None:
        """Transición interna: OPEN → HALF_OPEN."""
        self._state = HALF_OPEN
        self._half_open_attempts = 0
        self._open_since = None
        log.info("CircuitBreaker '%s' → HALF_OPEN", self.name)

    def _transition_to_closed(self) -> None:
        """Transición interna: HALF_OPEN → CLOSED."""
        self._state = CLOSED
        self._failure_count = 0
        log.info("CircuitBreaker '%s' → CLOSED", self.name)

    # ── API pública ─────────────────────────────────────────────

    def acquire(self) -> bool:
        """Intenta adquirir permiso para ejecutar la llamada protegida.

        Returns:
            True si la llamada debe proceder, False si el breaker está OPEN.
        """
        with self._lock:
            if self._state == CLOSED:
                return True

            if self._state == OPEN:
                elapsed = time.monotonic() - (self._open_since or time.monotonic())
                if elapsed >= self._recovery_timeout:
                    self._transition_to_half_open()
                    return True
                return False

            if self._state == HALF_OPEN:
                if self._half_open_attempts < self._half_open_max:
                    self._half_open_attempts += 1
                    return True
                return False

            return True  # fallback seguro

    def on_success(self) -> None:
        """Registra una llamada exitosa."""
        with self._lock:
            self._total_successes += 1
            self._last_success_time = time.monotonic()

            if self._state == HALF_OPEN:
                self._transition_to_closed()
            elif self._state == CLOSED:
                self._failure_count = 0

    def on_failure(self) -> None:
        """Registra una llamada fallida."""
        with self._lock:
            self._total_failures += 1
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == HALF_OPEN:
                self._transition_to_open()
            elif self._state == CLOSED and self._failure_count >= self._failure_threshold:
                self._transition_to_open()

    def reset(self) -> None:
        """Resetea el breaker a estado CLOSED (útil para pruebas/manual)."""
        with self._lock:
            self._state = CLOSED
            self._failure_count = 0
            self._half_open_attempts = 0
            self._last_failure_time = None
            self._open_since = None
            log.info("CircuitBreaker '%s' reseteado a CLOSED", self.name)

    # ── Stats ───────────────────────────────────────────────────

    def snapshot(self) -> CircuitBreakerStats:
        """Devuelve una copia inmutable del estado actual del breaker."""
        with self._lock:
            return CircuitBreakerStats(
                name=self.name,
                state=self._state,
                failure_count=self._failure_count,
                failure_threshold=self._failure_threshold,
                recovery_timeout=self._recovery_timeout,
                half_open_max=self._half_open_max,
                half_open_attempts=self._half_open_attempts,
                last_failure_time=self._last_failure_time,
                last_success_time=self._last_success_time,
                open_since=self._open_since,
                total_successes=self._total_successes,
                total_failures=self._total_failures,
            )

    # ── Decorador de conveniencia ───────────────────────────────

    def call(self, fn, *args, **kwargs):
        """Ejecuta fn(*args, **kwargs) protegido por el circuit breaker.

        Si el breaker está OPEN, lanza CircuitBreakerOpenError.
        Si la llamada falla, registra el fallo y relanza la excepción original.
        """
        if not self.acquire():
            raise CircuitBreakerOpenError(
                f"Servicio '{self.name}' no disponible temporalmente"
            )
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.on_failure()
            raise
        else:
            self.on_success()
            return result


# ── Breakers predefinidos ───────────────────────────────────────

deepseek_breaker = CircuitBreaker(
    name="deepseek",
    failure_threshold=DEFAULT_FAILURE_THRESHOLD,
    recovery_timeout=DEFAULT_RECOVERY_TIMEOUT,
    half_open_max=1,
)

vertex_vision_breaker = CircuitBreaker(
    name="vertex_vision",
    failure_threshold=DEFAULT_FAILURE_THRESHOLD,
    recovery_timeout=DEFAULT_RECOVERY_TIMEOUT,
    half_open_max=1,
)
