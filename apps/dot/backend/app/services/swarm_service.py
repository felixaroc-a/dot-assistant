"""Agent Swarm Manager — múltiples agentes en paralelo con coordinación.

Extiende SubAgentManager para soportar modo swarm:
- Divide un objetivo en N subtareas
- Lanza N sub-agentes en paralelo
- Espera a que todos terminen
- Un coordinador mergea los resultados

GOAL 5: Arquitectura de swarms estilo OpenClaw.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.services.sub_agent_service import (
    SubAgentManager,
    get_sub_agent_manager,
)

log = logging.getLogger("dot.swarm")


@dataclass
class SwarmConfig:
    """Configuración de un swarm."""
    goal: str
    sub_goals: list[str] = field(default_factory=list)
    max_parallel: int = 4
    timeout_seconds: float = 600.0
    coordinator_model: str = "auto"
    merge_strategy: str = "concise"  # "concise", "full", "vote"


@dataclass
class SwarmResult:
    """Resultado de una ejecución swarm."""
    swarm_id: str
    goal: str
    status: str  # "completed", "partial", "failed", "timeout"
    sub_results: list[dict[str, Any]] = field(default_factory=list)
    merged_result: str = ""
    coordinator_notes: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    duration_seconds: float = 0.0
    agents_used: int = 0
    agents_completed: int = 0
    agents_failed: int = 0


@dataclass
class SwarmState:
    """Estado runtime de un swarm."""
    swarm_id: str
    uid: str
    config: SwarmConfig
    sub_agent_ids: list[str] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    status: str = "pending"
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None


class SwarmManager:
    """Gestor de swarms — ejecuta múltiples sub-agentes en paralelo."""

    def __init__(self):
        self._swarms: dict[str, SwarmState] = {}  # swarm_id -> SwarmState
        self._sub_agent_manager: SubAgentManager = get_sub_agent_manager()

    async def launch_swarm(
        self,
        uid: str,
        goal: str,
        *,
        sub_goals: list[str] | None = None,
        max_parallel: int = 4,
        timeout_seconds: float = 600.0,
        registry: Any = None,
    ) -> str:
        """Lanza un swarm de agentes en paralelo.

        Si no se proporcionan sub_goals, el swarm usa el LLM para
        dividir el objetivo en subtareas.

        Args:
            uid: ID del usuario.
            goal: Objetivo principal del swarm.
            sub_goals: Lista de sub-objetivos (o None para auto-dividir).
            max_parallel: Máximo de agentes simultáneos.
            timeout_seconds: Timeout máximo del swarm.
            registry: Tool registry para los sub-agentes.

        Returns:
            swarm_id único.
        """
        # Auto-dividir si no hay sub_goals
        if not sub_goals:
            sub_goals = await self._divide_goal(goal, max_parallel)
            log.info("Swarm auto-dividió goal en %d sub-goals", len(sub_goals))

        swarm_id = str(uuid.uuid4())
        config = SwarmConfig(
            goal=goal,
            sub_goals=sub_goals,
            max_parallel=min(max_parallel, len(sub_goals)),
            timeout_seconds=timeout_seconds,
        )

        swarm_state = SwarmState(
            swarm_id=swarm_id,
            uid=uid,
            config=config,
            status="running",
        )

        self._swarms[swarm_id] = swarm_state

        # Lanzar sub-agentes con límite de paralelismo
        sub_results = []
        semaphore = asyncio.Semaphore(config.max_parallel)

        async def _run_sub_goal(idx: int, sub_goal: str) -> dict[str, Any]:
            async with semaphore:
                agent_id = str(uuid.uuid4())
                swarm_state.sub_agent_ids.append(agent_id)

                log.info(
                    "Swarm sub-agente %d/%d lanzado: %s",
                    idx + 1, len(sub_goals), sub_goal[:80],
                )

                try:
                    # Lanzar sub-agente y esperar
                    sub_agent_id = self._sub_agent_manager.spawn_sub_agent(
                        uid=uid,
                        name=f"Swarm-{idx + 1}",
                        goal=sub_goal,
                        registry=registry,
                    )

                    result = await asyncio.to_thread(
                        self._sub_agent_manager.wait_for_sub_agent,
                        uid,
                        sub_agent_id,
                        timeout=timeout_seconds / max(len(sub_goals), 1),
                    )

                    return {
                        "index": idx,
                        "goal": sub_goal,
                        "agent_id": sub_agent_id,
                        "status": result["status"] if result else "timeout",
                        "result": result.get("result_summary", "") if result else "",
                        "error": result.get("error_message", "") if result else "Timeout",
                    }
                except Exception as e:
                    return {
                        "index": idx,
                        "goal": sub_goal,
                        "agent_id": agent_id,
                        "status": "failed",
                        "result": "",
                        "error": str(e),
                    }

        # Ejecutar todos los sub-goals en paralelo
        tasks = [
            _run_sub_goal(i, goal)
            for i, goal in enumerate(sub_goals)
        ]

        try:
            sub_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            sub_results = [{
                "index": i,
                "goal": g,
                "status": "timeout",
                "error": "Swarm timeout",
            } for i, g in enumerate(sub_goals)]

        # Procesar resultados
        results = []
        for r in sub_results:
            if isinstance(r, Exception):
                results.append({"status": "error", "error": str(r)})
            else:
                results.append(r)

        swarm_state.results = results

        completed = sum(1 for r in results if r.get("status") == "completed")
        failed = sum(1 for r in results if r.get("status") in ("failed", "timeout", "error"))

        # Mergear resultados con LLM
        merged = await self._merge_results(goal, results)

        swarm_result = SwarmResult(
            swarm_id=swarm_id,
            goal=goal,
            status="completed" if failed == 0 else ("partial" if completed > 0 else "failed"),
            sub_results=results,
            merged_result=merged,
            duration_seconds=0.0,  # se calculará al finalizar
            agents_used=len(sub_goals),
            agents_completed=completed,
            agents_failed=failed,
        )

        swarm_state.status = swarm_result.status
        swarm_state.completed_at = datetime.now(timezone.utc).isoformat()

        log.info(
            "Swarm completado id=%s status=%s completed=%d failed=%d",
            swarm_id[:8], swarm_result.status, completed, failed,
        )

        return swarm_result

    async def get_swarm_status(self, swarm_id: str) -> dict[str, Any] | None:
        """Devuelve el estado de un swarm."""
        state = self._swarms.get(swarm_id)
        if state is None:
            return None

        return {
            "swarm_id": state.swarm_id,
            "status": state.status,
            "goal": state.config.goal,
            "sub_goals": state.config.sub_goals,
            "sub_agent_ids": state.sub_agent_ids,
            "results": state.results,
            "started_at": state.started_at,
            "completed_at": state.completed_at,
        }

    async def _divide_goal(self, goal: str, max_parts: int = 4) -> list[str]:
        """Divide un objetivo en sub-objetivos usando heurística + LLM.

        Fallback: división naïve si no hay LLM disponible.
        """
        # Intentar con LLM
        try:
            from app.settings import settings

            prompt = (
                f"Divide este objetivo en {max_parts} sub-tareas independientes que puedan "
                f"ejecutarse en paralelo. Responde SOLO con una lista numerada, una tarea por línea, "
                f"sin explicaciones adicionales.\n\n"
                f"Objetivo: {goal}\n\n"
                f"Sub-tareas (máximo {max_parts}):"
            )

            # Usar DeepSeek por defecto
            api_key = (settings.deepseek_api_key or "").strip()
            if not api_key:
                raise RuntimeError("No API key")

            import httpx
            url = (settings.deepseek_api_base or "https://api.deepseek.com/v1").rstrip("/") + "/chat/completions"
            payload = {
                "model": settings.deepseek_chat_model or "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "Eres un planificador de tareas. Responde solo con la lista."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.5,
                "max_tokens": 500,
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"].strip()

            # Parsear lista numerada
            sub_goals = []
            for line in text.split("\n"):
                line = line.strip()
                # Remove leading numbers like "1.", "1)", "1 -", etc.
                import re
                line = re.sub(r"^\d+[\.\)\-]\s*", "", line).strip()
                if line and len(line) > 5:
                    sub_goals.append(line)

            if sub_goals:
                return sub_goals[:max_parts]

        except Exception as e:
            log.debug("LLM division failed, usando heurística: %s", e)

        # Fallback heurístico
        # Dividir por verbos de acción comunes o por frases
        markers = [
            "investigar", "analizar", "buscar", "crear", "generar", "escribir",
            "comparar", "evaluar", "revisar", "extraer", "resumir", "calcular",
        ]

        parts = [goal.strip()]
        for marker in markers:
            new_parts = []
            for part in parts:
                if marker in part.lower() and len(new_parts) < max_parts:
                    idx = part.lower().find(marker)
                    if idx > 5:
                        before = part[:idx].strip()
                        after = part[idx:].strip()
                        if before:
                            new_parts.append(before)
                        new_parts.append(after)
                    else:
                        new_parts.append(part)
                else:
                    new_parts.append(part)
            parts = new_parts

        if len(parts) == 1:
            # Dividir por "y" o ";"
            text = parts[0]
            for sep in ["; ", " y ", ", "]:
                if sep in text:
                    parts = [p.strip() for p in text.split(sep) if len(p.strip()) > 10]
                    break

        return parts[:max_parts]

    async def _merge_results(
        self,
        goal: str,
        sub_results: list[dict[str, Any]],
    ) -> str:
        """Mergea resultados de sub-agentes en un resumen cohesivo."""
        # Construir resumen de resultados
        results_text = ""
        for i, r in enumerate(sub_results):
            status = r.get("status", "unknown")
            goal_text = r.get("goal", f"Tarea {i + 1}")
            result_text = r.get("result", "") or r.get("error", "")
            emoji = "✓" if status == "completed" else "✗"
            results_text += f"{emoji} [{status}] {goal_text}\n   {result_text[:300]}\n\n"

        # Intentar merge con LLM
        try:
            from app.settings import settings

            prompt = (
                f"Objetivo principal: {goal}\n\n"
                f"Resultados de sub-tareas ejecutadas en paralelo:\n\n{results_text}\n\n"
                f"Genera un resumen ejecutivo cohesivo que integre todos los resultados "
                f"en español. Incluye hallazgos clave, conclusiones y recomendaciones si aplica. "
                f"Mantén la respuesta concisa (máximo 600 caracteres)."
            )

            api_key = (settings.deepseek_api_key or "").strip()
            if not api_key:
                raise RuntimeError("No API key")

            import httpx
            url = (settings.deepseek_api_base or "https://api.deepseek.com/v1").rstrip("/") + "/chat/completions"
            payload = {
                "model": settings.deepseek_chat_model or "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "Eres un coordinador experto que sintetiza resultados de agentes en paralelo."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 800,
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()

        except Exception as e:
            log.debug("LLM merge failed, usando merge heurístico: %s", e)

        # Fallback heurístico
        completed = [r for r in sub_results if r.get("status") == "completed"]
        failed = [r for r in sub_results if r.get("status") not in ("completed",)]

        merged = f"Resultados del swarm ({len(completed)}/{len(sub_results)} completados):\n\n"
        for r in completed:
            merged += f"✓ {r.get('goal', '')[:100]}: {r.get('result', '')[:200]}\n"
        if failed:
            merged += f"\nTareas no completadas ({len(failed)}):\n"
            for r in failed:
                merged += f"✗ {r.get('goal', '')[:100]}: {r.get('error', 'Error desconocido')[:150]}\n"

        return merged


# ── Singleton ────────────────────────────────────────────────────────

_swarm_manager: SwarmManager | None = None


def get_swarm_manager() -> SwarmManager:
    """Devuelve el singleton SwarmManager."""
    global _swarm_manager
    if _swarm_manager is None:
        _swarm_manager = SwarmManager()
    return _swarm_manager
