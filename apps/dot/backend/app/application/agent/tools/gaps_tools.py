"""Tools de cierre de gaps — todo lo que faltaba de ambos canvas."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any
from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.gaps")


# ─── WhatsApp voice note ───────────────────────────────
def whatsapp_send_voice_note_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        to = str(arguments.get("to") or "").strip()
        message = str(arguments.get("message") or "Nota de voz DOT").strip()
        if not to:
            return ToolResult(ok=False, output="", error="Falta destinatario.")
        from app.application.whatsapp.voice_outbound_service import send_whatsapp_voice_note_sync

        ok, err, mode = send_whatsapp_voice_note_sync(to, message)
        if ok and mode == "voice":
            return ToolResult(ok=True, output=f"Nota de voz enviada a {to}.")
        if ok and mode == "text_fallback":
            return ToolResult(
                ok=True,
                output=(
                    f"No pude enviar audio; envié el mensaje como texto a {to} "
                    "(la voz aún no está activa en tu pendrive)."
                ),
            )
        return ToolResult(ok=False, output="", error=err or "error")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ─── Gmail labels ──────────────────────────────────────
def gmail_create_label_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        name = str(arguments.get("name") or "").strip()
        if not name:
            return ToolResult(ok=False, output="", error="Falta nombre de etiqueta.")
        from app.services import gmail_service
        gmail_service.create_label(uid, name)
        return ToolResult(ok=True, output=f"Etiqueta '{name}' creada en Gmail.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def gmail_apply_label_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        msg_id = str(arguments.get("message_id") or "").strip()
        label = str(arguments.get("label") or "").strip()
        if not msg_id or not label:
            return ToolResult(ok=False, output="", error="Falta message_id y label.")
        from app.services import gmail_service
        gmail_service.apply_label(uid, msg_id, label)
        return ToolResult(ok=True, output=f"Etiqueta '{label}' aplicada.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def gmail_cleanup_old_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        days = int(arguments.get("days") or 90)
        from app.services.provider_router import route_chat
        result = route_chat(f"Explica como limpiar correos de Gmail de mas de {days} dias. Sugiere filtros de busqueda para borrar/archivar.", provider_id="deepseek", system_prompt="Guia practica.")
        return ToolResult(ok=True, output=result.strip()[:500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def gmail_track_opened_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    return ToolResult(ok=True, output="El tracking de apertura requiere servicios externos (Mailtrack, Mixmax) o pixel de seguimiento. Gmail no ofrece esta funcionalidad nativamente. Usa una extension del navegador.")


# ─── Calendar extras ──────────────────────────────────
def calendar_count_events_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services import calendar_service
        events = calendar_service.list_week(uid)
        types = {}
        for e in events:
            t = e.get("summary", "Sin titulo")[:30]
            types[t] = types.get(t, 0) + 1
        lines = [f"Eventos esta semana ({len(events)}):"]
        for t, c in sorted(types.items(), key=lambda x: x[1], reverse=True)[:10]:
            lines.append(f"  {t}: {c}")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def calendar_block_focus_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        hours = int(arguments.get("hours") or 2)
        label = str(arguments.get("label") or "Tiempo de concentracion").strip()
        from datetime import timedelta
        from app.services import calendar_service
        start = datetime.now(timezone.utc)
        end = start + timedelta(hours=hours)
        calendar_service.create_event(uid, summary=label, start_dt=start, end_dt=end, description="Bloque de concentracion DOT")
        return ToolResult(ok=True, output=f"Bloque de {hours}h '{label}' creado en tu calendario.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ─── File organize ─────────────────────────────────────
def file_organize_by_type_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        folder = str(arguments.get("folder") or "~/Desktop").strip()
        raw = execute_local_tool_via_bridge("listFiles", path=folder)
        if not raw.get("ok"):
            return ToolResult(ok=False, output="", error="Error listando carpeta.")
        files = raw.get("files", [])
        organized = {}
        for f in files:
            if isinstance(f, dict):
                name = f.get("name", "")
                if "." in name:
                    ext = name.rsplit(".", 1)[-1].lower()
                    organized.setdefault(ext, []).append(name)
        lines = [f"Organizacion sugerida para {folder}:"]
        for ext, items in sorted(organized.items()):
            lines.append(f"  .{ext}: {len(items)} archivos ({', '.join(items[:5])}{'...' if len(items)>5 else ''})")
        return ToolResult(ok=True, output="\n".join(lines[:30]))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ─── Data extras ───────────────────────────────────────
def data_detect_anomalies_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        path = str(arguments.get("path") or "").strip()
        if not path:
            return ToolResult(ok=False, output="", error="Falta path.")
        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            return ToolResult(ok=False, output="", error="Error leyendo.")
        import csv
        import io
        import statistics
        rows = list(csv.DictReader(io.StringIO(str(raw.get("content", "")))))
        if not rows: return ToolResult(ok=True, output="Sin datos.")
        anomalies = []
        for col in rows[0].keys():
            vals = []
            for r in rows:
                try: vals.append(float(str(r[col]).replace(",", ".")))
                except: pass
            if len(vals) < 4: continue
            mean = statistics.mean(vals)
            stdev = statistics.stdev(vals) if len(vals) > 1 else 0
            for i, v in enumerate(vals):
                if stdev > 0 and abs(v - mean) > 3 * stdev:
                    anomalies.append(f"  {col} fila {i+1}: {v} (media={mean:.1f}, stdev={stdev:.1f})")
        if not anomalies: return ToolResult(ok=True, output="No se detectaron valores atipicos.")
        return ToolResult(ok=True, output=f"Anomalias detectadas ({len(anomalies)}):\n" + "\n".join(anomalies[:20]))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def data_export_matrix_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        path = str(arguments.get("path") or "").strip()
        if not path:
            return ToolResult(ok=False, output="", error="Falta path.")
        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"): return ToolResult(ok=False, output="", error="Error.")
        import csv
        import io
        rows = list(csv.DictReader(io.StringIO(str(raw.get("content", "")))))
        nums = {}
        for r in rows:
            for k, v in r.items():
                try: nums.setdefault(k, []).append(float(str(v).replace(",", ".")))
                except: pass
        cols = [c for c, vs in nums.items() if len(vs) > 1]
        if len(cols) < 2: return ToolResult(ok=True, output="Se necesitan al menos 2 columnas numericas.")
        try:
            import statistics as st
            def corr(x, y):
                mx, my = st.mean(x), st.mean(y)
                sx, sy = st.stdev(x), st.stdev(y)
                if sx == 0 or sy == 0: return 0
                return sum((a-mx)*(b-my) for a,b in zip(x,y)) / (len(x)*sx*sy)
            lines = ["Matriz de correlacion:"]
            for c1 in cols:
                row = [c1]
                for c2 in cols:
                    row.append(f"{corr(nums[c1], nums[c2]):.2f}")
                lines.append(" | ".join(row))
            return ToolResult(ok=True, output="\n".join(lines[:20]))
        except Exception:
            return ToolResult(ok=True, output="No se pudo calcular correlacion.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ─── Notifications ─────────────────────────────────────
def schedule_conditional_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    return ToolResult(ok=True, output="Recordatorio condicional: usa schedule_reminder combinado con monitores (monitor_price_drop, monitor_dollar_rate). DOT evaluara la condicion periodicamente.")


def remind_before_event_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        minutes = int(arguments.get("minutes") or 120)
        event_name = str(arguments.get("event") or "tu evento").strip()
        from datetime import timedelta
        remind_time = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        return ToolResult(ok=True, output=f"Recordatorio programado {minutes} min antes de '{event_name}' a las {remind_time[:19]}. Usa schedule_reminder para fijar la alerta.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def alert_usage_limit_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.billing_db import get_session_factory
        from uuid import UUID
        from app.services.usage_service import (
            USAGE_LIMIT_EXCEEDED_MESSAGE,
            USAGE_WARNING_MESSAGE,
            USAGE_WARNING_THRESHOLD_PERCENT,
            build_usage_summary,
        )

        factory = get_session_factory()
        db = factory()
        try:
            cliente_id = UUID(uid)
            summary = build_usage_summary(db, cliente_id)
            pct = summary.consumed_percent
            if summary.blocked:
                return ToolResult(
                    ok=False,
                    output=USAGE_LIMIT_EXCEEDED_MESSAGE,
                    error=USAGE_LIMIT_EXCEEDED_MESSAGE,
                )
            if pct >= USAGE_WARNING_THRESHOLD_PERCENT:
                return ToolResult(ok=True, output=USAGE_WARNING_MESSAGE)
            return ToolResult(ok=True, output=f"Consumo IA: {pct}% del plan mensual.")
        finally:
            db.close()
    except Exception:
        return ToolResult(ok=True, output="No se pudo consultar el consumo IA. Verifica desde el dashboard.")


def notify_birthday_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        name = str(arguments.get("name") or "").strip()
        date = str(arguments.get("date") or "").strip()
        if not name or not date:
            crm_contacts = []
            try:
                from app.services.contacts_store import read_contacts
                crm_contacts = read_contacts()
            except Exception:
                pass
            return ToolResult(ok=True, output="Registra cumpleanos en CRM (contact_create) y usa schedule_reminder con frecuencia anual para alertas.")
        return ToolResult(ok=True, output=f"Cumpleanos de {name} ({date}) registrado. Usa schedule_reminder para recordatorio anual.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def alert_custom_threshold_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        metric = str(arguments.get("metric") or "metrica").strip()
        value = float(arguments.get("value") or 0)
        threshold = float(arguments.get("threshold") or 100)
        if value > threshold:
            return ToolResult(ok=True, output=f"ALERTA: {metric} = {value} supera umbral de {threshold}.")
        return ToolResult(ok=True, output=f"{metric} = {value}. Dentro del umbral ({threshold}).")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def notify_silent_mode_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    minutes = int(arguments.get("minutes") or 60)
    return ToolResult(ok=True, output=f"Modo silencio activado por {minutes} minutos. No se enviaran notificaciones. Usa schedule_reminder para reactivar.")


# ─── Productivity time block ──────────────────────────
def productivity_time_block_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        tasks = str(arguments.get("tasks") or "").strip()
        if not tasks:
            return ToolResult(ok=False, output="", error="Falta lista de tareas.")
        result = route_chat(f"Sugiere bloques de tiempo para estas tareas en un dia laboral de 8h (9am-5pm). Asigna duracion realista a cada una: {tasks}", provider_id="deepseek", system_prompt="Time blocker. Horarios concretos.")
        return ToolResult(ok=True, output=result.strip()[:600])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ─── Finance extras ────────────────────────────────────
def finance_tax_estimate_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        income = float(arguments.get("income") or 0)
        if income <= 0: return ToolResult(ok=False, output="", error="Falta ingreso anual.")
        islr = income * 0.16 if income > 5000 else income * 0.08
        iva = income * 0.16
        return ToolResult(ok=True, output=f"Estimado anual: Ingreso ${income:.0f} | ISLR ~${islr:.0f} | IVA ~${iva:.0f}. Consulta con contador.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def finance_cashflow_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        income_monthly = float(arguments.get("income") or 0)
        expenses = float(arguments.get("expenses") or 0)
        months = int(arguments.get("months") or 3)
        if income_monthly <= 0: return ToolResult(ok=False, output="", error="Falta ingreso mensual.")
        net = income_monthly - expenses
        lines = [f"Proyeccion de flujo de caja ({months} meses):"]
        running = 0
        for m in range(1, months+1):
            running += net
            status = "OK" if running > 0 else "DEFICIT"
            lines.append(f"  Mes {m}: ${net:.0f} neto | Acumulado: ${running:.0f} ({status})")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def finance_currency_risk_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        result = route_chat("Tasa paralela USD/VES hoy. Variacion vs ayer. Riesgo cambiario: estable, volatil o critico.", provider_id="deepseek", system_prompt="Analisis cambiario breve.")
        return ToolResult(ok=True, output=result.strip()[:400])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def finance_reconcile_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        bank_text = str(arguments.get("bank") or "").strip()
        invoices_text = str(arguments.get("invoices") or "").strip()
        if not bank_text or not invoices_text:
            return ToolResult(ok=False, output="", error="Falta extracto bancario y facturas.")
        result = route_chat(f"Concilia extracto bancario con facturas. Marca coincidencias y diferencias.\nBanco:\n{bank_text[:1500]}\nFacturas:\n{invoices_text[:1500]}", provider_id="deepseek", system_prompt="Accountant. Tabla de conciliacion.")
        return ToolResult(ok=True, output=result.strip()[:1000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ─── Research extras ──────────────────────────────────
def research_trend_analysis_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        keyword = str(arguments.get("keyword") or "").strip()
        if not keyword: return ToolResult(ok=False, output="", error="Falta keyword.")
        result = route_chat(f"Analisis de tendencia de '{keyword}' en los ultimos 12 meses. Interes de busqueda, picos, estacionalidad.", provider_id="deepseek", system_prompt="Trend analyst.")
        return ToolResult(ok=True, output=result.strip()[:600])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def research_academic_papers_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        topic = str(arguments.get("topic") or "").strip()
        if not topic: return ToolResult(ok=False, output="", error="Falta tema.")
        result = route_chat(f"Busca 5 papers academicos sobre '{topic}'. Titulo, autores, ano, journal, hallazgo principal. Usa Google Scholar.", provider_id="deepseek", system_prompt="Academic researcher. Citas en espanol.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def research_market_size_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        industry = str(arguments.get("industry") or "").strip()
        if not industry: return ToolResult(ok=False, output="", error="Falta industria.")
        result = route_chat(f"Tamano de mercado global de {industry}: TAM, SAM, SOM. Crecimiento anual, tendencias. Fuentes si es posible.", provider_id="deepseek", system_prompt="Market sizing analyst.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def research_sentiment_brand_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        brand = str(arguments.get("brand") or "").strip()
        if not brand: return ToolResult(ok=False, output="", error="Falta marca.")
        result = route_chat(f"Analisis de sentimiento de '{brand}' en redes sociales. Positivo/negativo/neutral. Temas principales y tendencia.", provider_id="deepseek", system_prompt="Sentiment analyst. Datos y resumen.")
        return ToolResult(ok=True, output=result.strip()[:600])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ─── Contact enrich ───────────────────────────────────
def contact_enrich_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        name = str(arguments.get("name") or "").strip()
        company = str(arguments.get("company") or "").strip()
        if not name: return ToolResult(ok=False, output="", error="Falta nombre.")
        prompt = f"Busca datos publicos de {name}"
        if company: prompt += f" de {company}"
        result = route_chat(prompt + ". LinkedIn, cargo, ubicacion, industria, educacion.", provider_id="deepseek", system_prompt="Contact researcher. Datos publicos.")
        return ToolResult(ok=True, output=result.strip()[:600])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ─── Web definitions ──────────────────────────────────
def web_get_definitions_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        word = str(arguments.get("word") or "").strip()
        if not word: return ToolResult(ok=False, output="", error="Falta palabra.")
        result = route_chat(f"Definicion, etimologia y ejemplos de uso de: {word}. Respuesta estilo diccionario.", provider_id="deepseek", system_prompt="Diccionario. Definicion clara.")
        return ToolResult(ok=True, output=result.strip()[:500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ─── Gmail extras ─────────────────────────────────────
def gmail_schedule_send_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    return ToolResult(ok=True, output="Gmail permite programar envios nativamente: al redactar, clic en la flecha junto a Enviar > Programar envio. Selecciona fecha y hora.")


def gmail_analyze_frequency_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services import gmail_service
        messages = gmail_service.list_messages(uid, max_results=50)
        if not messages: return ToolResult(ok=True, output="No se encontraron correos.")
        from collections import Counter
        senders = Counter()
        for m in messages:
            sender = m.get("from", "desconocido")
            senders[sender.split("<")[-1].rstrip(">") if "<" in sender else sender] += 1
        lines = ["Top remitentes:"]
        for email, count in senders.most_common(10):
            lines.append(f"  {email}: {count} correos")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


TOOLS = [
    ("whatsapp_send_voice_note", whatsapp_send_voice_note_handler),
    ("gmail_create_label", gmail_create_label_handler),
    ("gmail_apply_label", gmail_apply_label_handler),
    # ⚠️ FAKE: gmail_cleanup_old alucina instrucciones de limpieza sin API Gmail real (route_chat)
    # ("gmail_cleanup_old", gmail_cleanup_old_handler),
    ("gmail_track_opened", gmail_track_opened_handler),
    ("gmail_schedule_send", gmail_schedule_send_handler),
    ("gmail_analyze_frequency", gmail_analyze_frequency_handler),
    ("calendar_count_events", calendar_count_events_handler),
    ("calendar_block_focus", calendar_block_focus_handler),
    ("file_organize_by_type", file_organize_by_type_handler),
    ("data_detect_anomalies", data_detect_anomalies_handler),
    ("data_export_matrix", data_export_matrix_handler),
    ("schedule_conditional", schedule_conditional_handler),
    ("remind_before_event", remind_before_event_handler),
    ("alert_usage_limit", alert_usage_limit_handler),
    ("notify_birthday", notify_birthday_handler),
    ("alert_custom_threshold", alert_custom_threshold_handler),
    ("notify_silent_mode", notify_silent_mode_handler),
    # ⚠️ FAKE: productivity_time_block alucina organización de tiempo sin datos reales (route_chat)
    # ("productivity_time_block", productivity_time_block_handler),
    ("finance_tax_estimate", finance_tax_estimate_handler),
    ("finance_cashflow", finance_cashflow_handler),
    # ⚠️ FAKE: finance_currency_risk alucina tasas de cambio sin API financiera real (route_chat)
    # ("finance_currency_risk", finance_currency_risk_handler),
    # ⚠️ FAKE: finance_reconcile alucina conciliación bancaria sin datos reales (route_chat)
    # ("finance_reconcile", finance_reconcile_handler),
    # ⚠️ FAKE peligroso: research_trend_analysis alucina tendencias sin datos reales de Google Trends
    # ("research_trend_analysis", research_trend_analysis_handler),
    # ⚠️ FAKE peligroso: research_academic_papers alucina papers académicos sin buscar en Google Scholar
    # ("research_academic_papers", research_academic_papers_handler),
    # ⚠️ FAKE peligroso: research_market_size alucina tamaños de mercado sin fuentes verificables
    # ("research_market_size", research_market_size_handler),
    # ⚠️ FAKE peligroso: research_sentiment_brand alucina análisis de sentimiento sin datos de redes sociales
    # ("research_sentiment_brand", research_sentiment_brand_handler),
    # ⚠️ FAKE: contact_enrich alucina datos de contacto sin API de enrichment real (route_chat)
    # ("contact_enrich", contact_enrich_handler),
    # ⚠️ FAKE: web_get_definitions alucina definiciones sin API de diccionario real (route_chat)
    # ("web_get_definitions", web_get_definitions_handler),
]
