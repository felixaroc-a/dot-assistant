"""Worker de automatizaciones - proceso independiente.

Arranque (desde apps/dot/backend):
    python -m worker.worker_main

Dev (desde apps/dot/frontend):
    npm run worker:dev
    npm run backend:dev:all   # API + worker en paralelo

Produccion (PM2):
    pm2 start ecosystem.config.cjs --only dot-worker

El worker:
1. Carga configuracion (Firebase, logging)
2. Consume TaskQueue (SQLite en worker/tasks.db)
3. Hace polling de tareas pendientes cada N segundos
4. Ejecuta cada tarea dentro del sandbox
5. Persiste resultados en Firestore
6. Emite heartbeat periódico para monitoreo

Requisito: el API (AutomationScheduler) encola tareas al disparar triggers;
sin este proceso las automatizaciones programadas no se ejecutan.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Asegurar que el backend esta en el path
_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

log = logging.getLogger("dot.worker")

# Heartbeat: cada cuantos segundos loguear que el worker sigue vivo
HEARTBEAT_INTERVAL_SECONDS = 60


def bootstrap() -> None:
    """Configura Firebase y logging para el worker."""
    from dot_billing.logging_config import configure_logging

    configure_logging(service_name="dot.worker", level="INFO")

    from app.firebase_db import init_firebase

    try:
        init_firebase()
        log.info("Firebase inicializado")
    except FileNotFoundError:
        log.warning("Firebase service account no encontrado. Continuando sin Firebase.")
    except Exception as e:
        log.error("Error inicializando Firebase: %s", e)


def worker_loop(
    *,
    interval: float = 3.0,
    timeout_secs: int = 30,
    db_path: str | Path | None = None,
    once: bool = False,
) -> None:
    """Loop principal del worker."""
    from worker.executor import AutomationExecutor
    from worker.sandbox import (
        ExecutionSandbox,
        SandboxError,
        SandboxTimeoutError,
        resolve_sandbox_timeout,
        validate_automation_payload,
    )
    from worker.task_queue import TaskQueue

    queue = TaskQueue(db_path) if db_path else TaskQueue()
    executor = AutomationExecutor()
    default_timeout_secs = timeout_secs

    # Recuperar tareas stale al arrancar (margen sobre timeout máximo agent)
    stale_margin = max(default_timeout_secs, resolve_sandbox_timeout(agent_default=120)) * 2
    recovered = queue.reset_stale(max_seconds=stale_margin)
    if recovered:
        log.info("Tareas stale recuperadas al arranque: %d", recovered)

    log.info(
        "Worker iniciado (interval=%.1fs, timeout_base=%ds, agent=120s, once=%s)",
        interval, default_timeout_secs, once,
    )

    # Contadores para heartbeat y diagnostico
    tasks_processed = 0
    tasks_failed = 0
    start_time = time.monotonic()
    last_heartbeat = start_time

    def process_task(task: dict[str, Any]) -> None:
        """Procesa una tarea: valida, ejecuta y persiste."""
        nonlocal tasks_processed, tasks_failed

        task_id = task["id"]
        uid = task["uid"]
        payload = task["payload"]

        log.info(
            "Procesando tarea %s (uid=%s, auto=%s)",
            task_id[:8], uid[:8], payload.get("name", "?")[:20],
        )

        try:
            validate_automation_payload(payload)

            task_timeout = resolve_sandbox_timeout(
                payload,
                default=default_timeout_secs,
                agent_default=120,
            )
            sandbox = ExecutionSandbox(timeout_seconds=task_timeout)

            result = sandbox.run(
                lambda: executor.execute(uid, payload),
                context=f"{payload.get('name', 'unknown')[:20]} ({uid[:8]})",
            )

            output_type = payload.get("output_type", "chat")
            executor.save_result(uid, payload["id"], result, output_type)
            executor.mark_pending(uid, payload["id"], payload.get("name", "Sin nombre"), result)

            queue.complete(task_id, result)
            tasks_processed += 1
            log.info("Tarea completada: %s (%d chars)", task_id[:8], len(result))
        except (SandboxError, SandboxTimeoutError) as e:
            log.error("Tarea fallida por sandbox: %s - %s", task_id[:8], e)
            queue.fail(task_id, str(e))
            tasks_failed += 1
        except Exception as e:
            log.exception("Tarea fallida inesperadamente: %s - %s", task_id[:8], e)
            queue.fail(task_id, str(e))
            tasks_failed += 1

    try:
        while True:
            try:
                task = queue.dequeue(timeout=interval)
                if task:
                    process_task(task)

                # Heartbeat periodico
                now = time.monotonic()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                    uptime_minutes = (now - start_time) / 60.0
                    pending = queue.pending_count()
                    log.info(
                        "[HEARTBEAT] worker vivo | uptime=%.1fmin | "
                        "procesadas=%d fallidas=%d pendientes=%d",
                        uptime_minutes, tasks_processed, tasks_failed, pending,
                    )
                    last_heartbeat = now
            except Exception as e:
                log.exception("Error en loop principal: %s", e)
                # Breve pausa para evitar spin en caso de error persistente
                time.sleep(1.0)

            if once:
                break
    except KeyboardInterrupt:
        log.info("Worker detenido por usuario")
    finally:
        uptime_total = (time.monotonic() - start_time) / 60.0
        log.info(
            "Worker finalizado | uptime=%.1fmin | procesadas=%d fallidas=%d",
            uptime_total, tasks_processed, tasks_failed,
        )
        queue.clear_old(max_age_days=7)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Worker de automatizaciones DOT")
    parser.add_argument(
        "--db-path", type=str, default=None,
        help="Ruta a la base de datos SQLite de cola",
    )
    parser.add_argument(
        "--interval", type=float, default=3.0,
        help="Intervalo de polling en segundos (default: 3.0)",
    )
    parser.add_argument(
        "--timeout", type=int, default=30,
        help="Timeout de ejecucion por tarea en segundos (default: 30)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Ejecutar una sola tarea y salir",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    bootstrap()
    loop_kwargs = {
        "interval": args.interval,
        "timeout_secs": args.timeout,
        "once": args.once,
    }
    if args.db_path:
        loop_kwargs["db_path"] = args.db_path
    worker_loop(**loop_kwargs)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
