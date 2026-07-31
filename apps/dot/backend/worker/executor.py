"""Ejecutor de tareas de automatizacion.

Contiene la logica de ejecucion extraida de AutomationScheduler.
Se ejecuta dentro del sandbox para aislamiento.

Timeout del sandbox (worker y execute_now):
- Agent/third-option/chat/vacío: 120s (multi-step tool calling).
- Otras integraciones: 30s.
- Override: env ``DOT_AGENT_SANDBOX_TIMEOUT`` (ver ``worker.sandbox.resolve_sandbox_timeout``).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.firebase_db import get_db as get_firestore_client

log = logging.getLogger("dot.worker.executor")


class AutomationExecutor:
    """Ejecuta instrucciones de automatizacion contra integraciones."""

    def execute(self, uid: str, auto: dict[str, Any]) -> str:
        """Punto de entrada unico: ejecuta una automatizacion y retorna el resultado.

        Soporta tanto automatizaciones simples como pipelines multi-paso (C2).
        """
        # C2: Si es un pipeline multi-paso, usar WorkflowExecutor
        if auto.get("is_pipeline") and auto.get("pipeline_steps"):
            return self.execute_pipeline(uid, auto)

        instruction = str(auto.get("instruction", "")).strip()
        if not instruction:
            raise RuntimeError("La automatizacion no tiene instruccion.")

        output_type = str(auto.get("output_type", "chat")).strip().lower()
        prior = str(auto.get("prior_output") or "").strip()
        step_type = str(auto.get("step_type") or "").strip().lower()

        # Trigger de chat: no inventar con LLM
        if step_type == "trigger" and self._integration_key(auto) in {"", "chat", "manual"}:
            return "Disparador listo: ejecución solicitada por el usuario."

        integration = self._integration_key(auto)
        # BIBLIA §20: third-option / chat / vacío = Agent Runtime (nunca LLM pelado)
        if integration in {"third-option", "chat", "manual", "agent", "dot", ""}:
            result = self._execute_agent(uid, instruction)
        elif integration == "gmail":
            result = self._execute_gmail(uid, instruction)
        elif integration in {"google-calendar", "google_calendar", "calendar"}:
            result = self._execute_calendar(uid, instruction)
        elif integration in {"whatsapp", "wa"}:
            result = self._execute_whatsapp(uid, instruction, prior_output=prior)
        elif integration in {"file", "files", "local_files", "filesystem", "local"}:
            result = self._execute_file(instruction)
        else:
            # Integración desconocida → Agent Runtime con tools (Gateway único)
            result = self._execute_agent(uid, instruction)

        # Post-procesamiento: campana de WhatsApp
        if output_type == "whatsapp_campaign":
            return self._process_whatsapp_campaign(uid, auto, result)

        return result

    # ─── C2: Pipeline multi-paso ──────────────────────────

    def execute_pipeline(self, uid: str, auto: dict[str, Any]) -> str:
        """Ejecuta un pipeline multi-paso usando WorkflowExecutor."""
        from worker.workflow_engine import (
            ConditionOperator,
            StepType,
            WorkflowDef,
            WorkflowExecutor,
            WorkflowStepDef,
        )

        pipeline_name = auto.get("name", "Pipeline")
        steps_raw = auto.get("pipeline_steps", [])
        if not steps_raw:
            raise RuntimeError("Pipeline sin pasos definidos.")

        # Construir WorkflowDef desde los pasos
        wf_steps: list[WorkflowStepDef] = []
        for i, s in enumerate(steps_raw):
            wf_step = WorkflowStepDef(
                id=s.get("id", f"step_{i + 1}"),
                type=StepType(s.get("type", "action")),
                integration=s.get("integration", "chat"),
                instruction=s.get("instruction", ""),
                condition_operator=ConditionOperator(s.get("condition_operator", "always")),
                condition_value=s.get("condition_value", ""),
                depends_on=s.get("depends_on", []) or ([f"step_{i}"] if i > 0 else []),
                timeout_seconds=s.get("timeout_seconds", 30),
            )
            wf_steps.append(wf_step)

        wf = WorkflowDef(
            id=auto.get("id", "pipeline"),
            name=pipeline_name,
            description=auto.get("instruction", ""),
            steps=wf_steps,
        )

        executor = WorkflowExecutor()
        result = executor.execute(uid, wf)

        log.info(
            "Pipeline %s ejecutado: %s (%d pasos, %d errores)",
            pipeline_name,
            "OK" if result.success else "FALLO",
            len(result.steps),
            sum(1 for s in result.steps if s.error),
        )

        return result.final_output

    # ─── Agent Runtime (tools reales) ────────────────────

    @staticmethod
    def _execute_agent(uid: str, instruction: str) -> str:
        """Ejecuta con Agent Runtime: LLM + tools reales (gmail, archivos, WA, web, docs…).

        Reemplaza a _execute_chat() para third-option y cualquier integracion
        desconocida. El agente decide que herramientas usar en runtime.
        """
        from app.application.agent.runtime import run_agent
        from app.application.agent.tools import build_default_registry

        registry = build_default_registry(include_web_search=True)

        tool_names = [s.name for s in registry.list_specs()]
        log.info(
            "Agent Runtime ejecutando automation uid=%s con %d tools: %s",
            uid[:8] if uid else "?",
            len(tool_names),
            ", ".join(tool_names),
        )

        result = run_agent(
            uid=uid,
            channel="automation",
            text=instruction,
            system_prompt=(
                "Eres DOT, el motor de automatizaciones del usuario. "
                "Tienes acceso a herramientas REALES para actuar en su PC, "
                "su Gmail, su WhatsApp y la web. NO eres un chatbot pasivo.\n\n"
                "REGLAS CRÍTICAS:\n"
                "1. Ejecuta la instrucción del usuario paso a paso usando las tools disponibles.\n"
                "2. NUNCA digas que no puedes hacer algo si tienes la tool para hacerlo.\n"
                "3. NUNCA sugieras servicios externos (Zapier, Make, IFTTT, etc.).\n"
                "4. Si una tool falla, explica el error en español claro y sugiere alternativa.\n"
                "5. Si el usuario pide \"avisar\" o \"notificar\" y no hay tool directa, "
                "usa send_whatsapp_message al número del dueño.\n"
                "6. Responde siempre en español, de forma directa y útil.\n"
                "7. No inventes resultados: solo reporta lo que las tools realmente devuelven."
            ),
            registry=registry,
            max_steps=15,
        )

        final = result.final_text.strip()
        if result.steps > 1:
            return (
                f"{final}\n\n"
                f"(Ejecutado en {result.steps} pasos con {len(result.tool_trace)} herramientas.)"
            )
        return final

    # ─── Chat / DeepSeek (legacy, sin tools) ─────────────

    @staticmethod
    def _execute_chat(instruction: str, prior_output: str = "") -> str:
        """DEPRECATED (BIBLIA §20): no usar. Autos agenticas van por _execute_agent.

        Conservado solo por compat tests legacy; redirige a Agent Runtime.
        """
        log.warning("_execute_chat deprecated → _execute_agent")
        if prior_output.strip():
            instruction = (
                f"{instruction}\n\nContexto de pasos previos:\n{prior_output.strip()[:4000]}"
            )
        return AutomationExecutor._execute_agent("system", instruction)

    @staticmethod
    def _write_summary_document(instruction: str, prior_output: str) -> str:
        """Guarda un .txt real en el Escritorio a partir de datos previos (sin mentir)."""
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        if not prior_output.strip():
            raise RuntimeError(
                "No puedo generar el documento: no hay datos reales de un paso de archivos anterior."
            )

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        body = (
            f"Resumen generado por DOT — {stamp}\n"
            f"Pedido: {instruction.strip()}\n"
            f"{'=' * 40}\n\n"
            f"{prior_output.strip()}\n"
        )
        filename = f"Resumen_DOT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        dest = f"~/Desktop/{filename}"
        raw = execute_local_tool_via_bridge("writeFile", path=dest, content=body)
        if not raw.get("ok"):
            err = str(raw.get("error") or "error al escribir")
            raise RuntimeError(
                f"No se pudo guardar el documento en el Escritorio: {err}. "
                "¿Está abierta la app DOT (bridge)?"
            )
        saved = str(raw.get("path") or dest)
        preview = prior_output.strip().replace("\n", " ")
        if len(preview) > 180:
            preview = preview[:180].rsplit(" ", 1)[0] + "…"
        return f"Documento guardado en {saved}. Contenido: {preview}"

    # ─── Archivos locales (bridge Electron real) ─────────

    @staticmethod
    def _bridge_read_text(path: str) -> dict[str, Any]:
        """Lee texto vía bridge: parseDocument para PDF/DOCX, readFile para texto plano."""
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        from app.application.agent.tools.read_document import MIME_MAP, _guess_mime

        mime = _guess_mime(path)
        if mime and Path(path).suffix.lower() in MIME_MAP:
            raw = execute_local_tool_via_bridge(
                "parseDocument",
                path=path,
                content=mime,
            )
            if raw.get("ok"):
                text = str(raw.get("text", raw.get("content", "")))
                return {
                    "ok": True,
                    "path": raw.get("path") or path,
                    "content": text,
                    "chars": len(text),
                }
            return raw

        return execute_local_tool_via_bridge("readFile", path=path)

    @staticmethod
    def _execute_file(instruction: str) -> str:
        """Lista o lee archivos reales vía bridge. No usa LLM (no puede mentir)."""
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        text = (instruction or "").strip()
        text_l = text.lower()

        if any(w in text_l for w in ("descargas", "downloads")):
            folder = "~/Downloads"
            folder_label = "Descargas"
        elif any(w in text_l for w in ("documentos", "documents")):
            folder = "~/Documents"
            folder_label = "Documentos"
        else:
            # Escritorio por defecto (también "PC", "archivos", etc.)
            folder = "~/Desktop"
            folder_label = "Escritorio"

        path_m = re.search(
            r"([A-Za-z]:\\[^\s\"']+|~/[^\s\"']+)",
            text,
        )
        explicit = path_m.group(1).rstrip(".,;") if path_m else None

        file_m = re.search(
            r"([\w\-]+\.(?:pdf|txt|docx?|xlsx?|csv|md|json|png|jpe?g))",
            text,
            re.IGNORECASE,
        )
        wants_read = bool(
            re.search(r"\b(leer|lee|abrir|abre|read|contenido de)\b", text_l)
        )

        # Lectura de ruta/archivo concreto
        if explicit and not explicit.endswith(("\\", "/")) and (
            wants_read or re.search(r"\.\w{2,5}$", explicit)
        ):
            raw = AutomationExecutor._bridge_read_text(explicit)
            if not raw.get("ok"):
                raise RuntimeError(
                    f"No se pudo leer «{explicit}»: {raw.get('error') or 'error'}. "
                    "¿Está abierta la app DOT?"
                )
            content = str(raw.get("content") or "")
            preview = content if len(content) <= 2500 else content[:2500] + "…"
            return (
                f"Archivo leído: {raw.get('path') or explicit}\n"
                f"({len(content)} caracteres)\n\n{preview}"
            )

        if file_m and wants_read:
            name = file_m.group(1)
            search = execute_local_tool_via_bridge(
                "searchFiles",
                query=name,
                search_root="all",
                scope="full",
            )
            results = search.get("results") if search.get("ok") else None
            if isinstance(results, list) and results:
                first = results[0] if isinstance(results[0], dict) else {}
                found_path = str(first.get("path") or "")
                if found_path:
                    raw = AutomationExecutor._bridge_read_text(found_path)
                    if raw.get("ok"):
                        content = str(raw.get("content") or "")
                        preview = content if len(content) <= 2500 else content[:2500] + "…"
                        return (
                            f"Archivo leído: {raw.get('path') or found_path}\n"
                            f"({len(content)} caracteres)\n\n{preview}"
                        )
            raise RuntimeError(
                f"No encontré el archivo «{name}» en el PC. "
                f"{search.get('error') or ''}".strip()
            )

        # Listado de carpeta (caso típico: resumen del escritorio)
        raw = execute_local_tool_via_bridge("listFiles", path=folder)
        if not raw.get("ok"):
            raise RuntimeError(
                f"No se pudo listar {folder_label}: {raw.get('error') or 'error'}. "
                "¿Está abierta la app DOT (bridge)?"
            )

        files = raw.get("files") or []
        abs_path = str(raw.get("path") or folder)
        if not isinstance(files, list):
            files = []

        if not files:
            return f"Carpeta {folder_label} ({abs_path}): sin archivos visibles."

        lines = [f"Archivos en {folder_label} ({abs_path}) — {len(files)} elementos:"]
        for entry in files[:50]:
            if isinstance(entry, dict):
                name = str(entry.get("name") or "")
                kind = "carpeta" if entry.get("isDirectory") else "archivo"
            else:
                name = str(entry)
                kind = "archivo"
            if name:
                lines.append(f"- {name} ({kind})")
        if len(files) > 50:
            lines.append(f"… y {len(files) - 50} más.")
        return "\n".join(lines)

    # ─── WhatsApp (envío real vía bridge Electron) ───────

    @staticmethod
    def _execute_whatsapp(uid: str, instruction: str, prior_output: str = "") -> str:
        """Envía un mensaje real al teléfono vinculado del usuario.

        Antes los pasos integration=whatsapp caían en _execute_chat y el LLM
        inventaba un 'enviado OK' sin llamar al bridge.
        """
        import asyncio

        from app.infrastructure.whatsapp.phone_resolver import to_e164
        from app.services.whatsapp_client import send_whatsapp_message
        from app.services.whatsapp_link import get_channel_state

        state = get_channel_state(uid)
        if not state.linked:
            raise RuntimeError(
                "WhatsApp no está vinculado. Vincula el canal antes de enviar."
            )

        to_raw = (state.phone_number or "").strip()
        # Permitir "a +58...:" o "to:+58" en la instrucción
        m = re.search(
            r"(?:a|para|to|destino)\s*[:\s]*(\+?\d[\d\s\-()]{7,}\d)",
            instruction,
            re.IGNORECASE,
        )
        if m:
            to_raw = m.group(1)

        if not to_raw:
            raise RuntimeError(
                "No hay destinatario WhatsApp. Vincula tu número o indica un teléfono en el paso."
            )

        to = to_e164(to_raw) or to_raw
        if "@" not in to and not to.startswith("+"):
            raise RuntimeError(
                f"Número WhatsApp inválido: «{to_raw}». Usa formato +58… o 0412…"
            )

        # Texto: mensaje explícito en instrucción + resumen humano de pasos previos
        from app.services.pipeline_message_format import build_whatsapp_user_message, humanize_step_output

        title = ""
        for prefix in (
            "Enviar por WhatsApp:",
            "Enviar por WhatsApp",
            "Notificar por WhatsApp:",
            "Notificar por WhatsApp",
        ):
            if prefix.lower() in instruction.lower():
                idx = instruction.lower().find(prefix.lower())
                title = instruction[idx + len(prefix) :].strip(" :.-")
                break
        if not title:
            title = instruction.strip()

        prior_chunks = [
            p.strip()
            for p in re.split(r"\n{2,}", prior_output or "")
            if p.strip()
        ]
        # Si prior viene como un solo bloque multilínea, úsalo entero
        if prior_output.strip() and not prior_chunks:
            prior_chunks = [prior_output.strip()]
        elif prior_output.strip() and len(prior_chunks) == 1 and "\n{" in prior_output:
            # Varios JSON pegados sin doble salto
            prior_chunks = [prior_output.strip()]

        text = build_whatsapp_user_message(title=title, prior_outputs=prior_chunks)
        text = humanize_step_output(text) if '"action"' in text else text

        if not text:
            raise RuntimeError("No hay texto para enviar por WhatsApp.")

        # Limitar tamaño típico de WA
        text = text.strip()[:3500]

        ok, err = asyncio.run(send_whatsapp_message(to, text))
        if not ok:
            raise RuntimeError(
                f"WhatsApp no enviado ({err or 'error'}). "
                "¿Está vinculado y el bridge de Electron activo?"
            )

        log.info("Pipeline WA enviado a %s (%d chars) uid=%s", to, len(text), uid[:8])
        return f"Mensaje WhatsApp enviado a {to} ({len(text)} caracteres)."

    # ─── Gmail ───────────────────────────────────────────

    @staticmethod
    def _execute_gmail(uid: str, instruction: str) -> str:
        from app.services import gmail_service

        lower = instruction.lower()
        if "resum" in lower:
            return gmail_service.summarize_unread(uid, max_results=10)

        if "buscar" in lower:
            query = _extract_after_keyword(instruction, "buscar") or "in:inbox"
            results = gmail_service.search_messages(uid, query=query, max_results=10)
            if not results:
                return f"No se encontraron correos para la consulta: {query}"
            lines = [
                f"- {m.get('subject', '(sin asunto)')} | {m.get('from', '')}"
                for m in results[:10]
            ]
            return f"Resultados Gmail ({len(results)}):\n" + "\n".join(lines)

        if "enviar" in lower:
            to = _extract_email(instruction)
            if not to:
                raise RuntimeError("No se detecto un correo destino para enviar el mensaje.")
            subject = _extract_after_keyword(instruction, "asunto") or "Mensaje desde DOT"
            body = _extract_after_keyword(instruction, "mensaje") or instruction
            sent = gmail_service.send_message(uid, to=to, subject=subject, body=body)
            return f"Correo enviado a {to}. ID: {sent.get('id', 'n/a')}"

        unread = gmail_service.list_unread(uid, max_results=20)
        if not unread:
            return "No tienes correos no leidos."
        lines = [
            f"- {m.get('subject', '(sin asunto)')} | {m.get('from', '')}"
            for m in unread[:20]
        ]
        return f"Correos no leidos ({len(unread)}):\n" + "\n".join(lines)

    # ─── Calendar ────────────────────────────────────────

    @staticmethod
    def _execute_calendar(uid: str, instruction: str) -> str:
        from app.services import calendar_service
        from app.services.whatsapp_intent import extract_datetime_from_text

        lower = instruction.lower()
        if "semana" in lower:
            events = calendar_service.list_week(uid)
            if not events:
                return "No hay eventos programados para esta semana."
            lines = [
                f"- {e.get('summary', '(sin titulo)')} | {e.get('start', '')}"
                for e in events[:20]
            ]
            return f"Agenda semanal ({len(events)}):\n" + "\n".join(lines)

        if "hoy" in lower or "agenda" in lower:
            events = calendar_service.list_today(uid)
            if not events:
                return "No hay eventos programados para hoy."
            lines = [
                f"- {e.get('summary', '(sin titulo)')} | {e.get('start', '')}"
                for e in events[:20]
            ]
            return f"Agenda de hoy ({len(events)}):\n" + "\n".join(lines)

        if "conflict" in lower or "disponib" in lower or "libre" in lower:
            dt = extract_datetime_from_text(instruction)
            start = datetime.strptime(f"{dt.get('date', '')} {dt.get('time', '')}", "%Y-%m-%d %H:%M")
            end = start + timedelta(minutes=30)
            conflicts = calendar_service.check_conflicts(uid, start, end)
            if not conflicts:
                return "No se detectaron conflictos para ese horario."
            lines = [f"- {c.get('start', '')} -> {c.get('end', '')}" for c in conflicts]
            return "Conflictos detectados:\n" + "\n".join(lines)

        dt = extract_datetime_from_text(instruction)
        start = datetime.strptime(f"{dt.get('date', '')} {dt.get('time', '')}", "%Y-%m-%d %H:%M")
        end = start + timedelta(minutes=30)
        summary = _extract_after_keyword(instruction, "titulo") or "Evento DOT"
        event = calendar_service.create_event(
            uid,
            summary=summary,
            start_dt=start,
            end_dt=end,
            description=f"Automatizacion ejecutada desde DOT.\n\nInstruccion:\n{instruction}",
        )
        return f"Evento creado: {event.get('summary', summary)} ({event.get('start', '')})"

    # ─── WhatsApp Campaign ──────────────────────────────

    @staticmethod
    def _parse_campaign_messages(result_text: str) -> list[dict[str, str]]:
        """Parsea lineas 'to: +584141234567 | text: mensaje' del resultado IA.

        Soporta variantes con o sin espacios alrededor de '|'.
        """
        messages: list[dict[str, str]] = []
        for line in result_text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Buscar patron: to:<numero> ... text:<mensaje>
            # Separar por |
            if "|" not in line:
                continue
            parts = line.split("|", 1)
            to_part = parts[0].strip()
            text_part = parts[1].strip() if len(parts) > 1 else ""

            # Extraer numero despues de "to:"
            to_match = re.search(r"to\s*:\s*(.+)", to_part, re.IGNORECASE)
            text_match = re.search(r"text\s*:\s*(.+)", text_part, re.IGNORECASE)

            if to_match and text_match:
                messages.append({
                    "to": to_match.group(1).strip(),
                    "text": text_match.group(1).strip(),
                })
        return messages

    def _process_whatsapp_campaign(
        self, uid: str, auto: dict[str, Any], result: str
    ) -> str:
        """Interpreta el resultado IA como campana de WhatsApp y envia los mensajes."""
        messages = self._parse_campaign_messages(result)
        if not messages:
            log.warning(
                "Campana WhatsApp sin mensajes validos parseados. auto=%s result_preview=%s",
                auto.get("id", "?")[:12], result[:200],
            )
            return (
                "No se encontraron mensajes validos en el resultado de la campana. "
                "El formato esperado es: to: +58... | text: mensaje"
            )

        from worker.whatsapp_sender import send_bulk_messages_sync

        auto_id = auto.get("id", "unknown")
        campaign_result = send_bulk_messages_sync(uid, auto_id, messages)

        # Persistir estadisticas en Firestore
        self._save_campaign_stats(uid, auto_id, campaign_result)

        sent = campaign_result["sent"]
        failed = campaign_result["failed"]
        total = campaign_result["total"]

        summary = (
            f"Campana WhatsApp completada: {sent}/{total} enviados"
            + (f", {failed} fallidos" if failed else "")
            + "."
        )
        if failed:
            failed_details = [
                d for d in campaign_result.get("details", [])
                if not d.get("ok")
            ]
            summary += "\n\nFallidos:\n" + "\n".join(
                f"- {d['to']}: {d.get('error', 'error')}" for d in failed_details[:10]
            )
        return summary

    @staticmethod
    def _save_campaign_stats(
        uid: str, auto_id: str, campaign_result: dict[str, Any]
    ) -> None:
        """Guarda estadisticas de campana en Firestore."""
        try:
            db = get_firestore_client()
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            doc_ref = (
                db.collection("users")
                .document(uid)
                .collection("automation_results")
                .document(auto_id)
                .collection("campaigns")
                .document(timestamp)
            )
            doc_ref.set({
                "automation_id": auto_id,
                "executed_at": campaign_result.get("executed_at") or datetime.now(timezone.utc).isoformat(),
                "sent": campaign_result.get("sent", 0),
                "failed": campaign_result.get("failed", 0),
                "total": campaign_result.get("total", 0),
                "details": campaign_result.get("details", []),
            })
            log.info(
                "Campana %s guardada en Firestore: %d/%d enviados",
                auto_id[:12], campaign_result.get("sent", 0), campaign_result.get("total", 0),
            )
        except Exception as e:
            log.warning("Error guardando stats de campana %s: %s", auto_id[:12], e)

    # ─── Persistencia de resultados ──────────────────────

    @staticmethod
    def save_result(uid: str, auto_id: str, result: str, output_type: str) -> None:
        """Guarda el resultado de ejecucion en Firestore y opcionalmente en archivo."""
        try:
            db = get_firestore_client()
            execution = {
                "automation_id": auto_id,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "result": result[:5000],
                "output_type": output_type,
            }
            db.collection("users").document(uid).collection("automation_executions").add(execution)

            if output_type in ("txt", "docx", "xlsx", "file"):
                from pathlib import Path

                desktop = Path.home() / "Desktop" / "DOT Trabajos"
                auto_name = auto_id[:8]
                (desktop / "Automatizaciones").mkdir(parents=True, exist_ok=True)
                filepath = desktop / "Automatizaciones" / f"{auto_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                filepath.write_text(result, encoding="utf-8")
                log.info("Resultado guardado en %s", filepath)
        except Exception as e:
            log.warning("Error guardando execution result: %s", e)

    @staticmethod
    def mark_pending(uid: str, auto_id: str, auto_name: str, result: str | None = None) -> None:
        """Marca resultados pendientes en el perfil del usuario."""
        try:
            db = get_firestore_client()
            preview = str(result or "").replace("\r", " ").replace("\n", " ").strip()[:280]
            db.collection("users").document(uid).set(
                {
                    "pending_automation_results": {
                        "has_new": True,
                        "last_auto_id": auto_id,
                        "last_auto_name": auto_name,
                        "last_executed_at": datetime.now(timezone.utc).isoformat(),
                        "last_result_preview": preview,
                    }
                },
                merge=True,
            )
        except Exception as e:
            log.warning("Error marcando pending results: %s", e)

    # ─── Helpers ─────────────────────────────────────────

    @staticmethod
    def _integration_key(auto: dict[str, Any]) -> str:
        return str(
            auto.get("integration_id")
            or auto.get("integrationId")
            or auto.get("integration")
            or ""
        ).strip().lower()


def _extract_email(text: str) -> str | None:
    match = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", text)
    return match.group(1) if match else None


def _extract_after_keyword(text: str, keyword: str) -> str:
    idx = text.lower().find(keyword.lower())
    if idx < 0:
        return ""
    return text[idx + len(keyword):].strip(" :.-")
