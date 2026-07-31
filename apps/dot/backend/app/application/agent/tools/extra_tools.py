"""Extra tool handlers — DOT Agent Runtime Fase 7.

12 handlers: web_search_images, web_get_stock, web_url_shorten, web_get_timezone,
web_reverse_geocode, gmail_detect_phishing, whatsapp_analyze_sentiment,
whatsapp_export_chat, whatsapp_auto_label, whatsapp_get_contact_info,
productivity_daily_summary, productivity_weekly_report.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.extra")


# ═══════════════════════════════════════════════════════════════
# 1. web_search_images — Buscar URLs de imágenes via DeepSeek
# ═══════════════════════════════════════════════════════════════

def web_search_images_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca imágenes relacionadas con una query y devuelve URLs."""
    try:
        from app.services.provider_router import route_chat

        query = str(arguments.get("query") or arguments.get("q") or "").strip()
        if not query:
            return ToolResult(ok=False, output="", error="Falta query de búsqueda.")

        result = route_chat(
            f"Lista URLs de imágenes para: {query}. "
            f"Da exactamente 5 URLs reales de imágenes libres de bancos como "
            f"Unsplash, Pexels o Pixabay. Responde SOLO en formato JSON array de strings. "
            f"Ejemplo: [\"https://...\", \"https://...\"]. Sin markdown, sin explicación.",
            provider_id="deepseek",
            system_prompt=(
                "Eres un buscador de imágenes. Responde SOLO con un JSON array "
                "de 5 URLs reales de imágenes libres. Sin markdown, sin texto extra."
            ),
        )

        # Intentar parsear como JSON
        try:
            urls = json.loads(result.strip())
            if isinstance(urls, list) and all(isinstance(u, str) for u in urls):
                return ToolResult(
                    ok=True,
                    output=json.dumps(urls[:5], ensure_ascii=False),
                )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # Si no es JSON válido, devolver el texto crudo
        return ToolResult(ok=True, output=(result.strip() or "No se encontraron imágenes.")[:2000])

    except Exception as e:
        log.warning("web_search_images error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════
# 2. web_get_stock — Precio actual de acción o criptomoneda
# ═══════════════════════════════════════════════════════════════

def web_get_stock_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene el precio actual de una acción o criptomoneda."""
    try:
        from app.services.provider_router import route_chat

        ticker = str(arguments.get("ticker") or arguments.get("symbol") or "").strip().upper()
        if not ticker:
            return ToolResult(ok=False, output="", error="Falta ticker/symbol (ej: AAPL, BTC).")

        result = route_chat(
            f"Precio actual de {ticker}. Responde solo con el numero y la moneda "
            f"(ej: 185.64 USD o 67234.10 USD). Si es cripto, aclara si es USD. "
            f"Si no tienes datos actualizados, di 'Datos no disponibles'.",
            provider_id="deepseek",
            system_prompt=(
                "Eres un ticker financiero. Responde SOLO con precio y moneda. "
                "Sin explicación, sin puntuación extra."
            ),
        )
        return ToolResult(ok=True, output=result.strip()[:200])

    except Exception as e:
        log.warning("web_get_stock error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════
# 3. web_url_shorten — Acortar URL
# ═══════════════════════════════════════════════════════════════

def web_url_shorten_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Acorta una URL (requiere API key de servicio externo)."""
    try:
        url = str(arguments.get("url") or arguments.get("long_url") or "").strip()
        if not url:
            return ToolResult(ok=False, output="", error="Falta URL a acortar.")

        # Intentar acortar via TinyURL (no requiere API key)
        import urllib.request

        api_url = f"https://tinyurl.com/api-create.php?url={urllib.parse.quote(url, safe='')}"
        try:
            with urllib.request.urlopen(api_url, timeout=10) as resp:
                short = resp.read().decode("utf-8").strip()
            if short and short.startswith("http"):
                return ToolResult(ok=True, output=short)
        except Exception:
            pass

        # Fallback: explicar que requiere API key
        return ToolResult(
            ok=True,
            output=(
                f"No se pudo acortar automáticamente. URL original: {url}\n"
                "Para acortamiento confiable se requiere una API key de Bitly, "
                "Rebrandly o similar. La URL original sigue siendo válida."
            ),
        )

    except Exception as e:
        log.warning("web_url_shorten error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════
# 4. web_get_timezone — Zona horaria de una ciudad
# ═══════════════════════════════════════════════════════════════

def web_get_timezone_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene la zona horaria actual de una ciudad."""
    try:
        from app.services.provider_router import route_chat

        city = str(arguments.get("city") or arguments.get("location") or "").strip()
        if not city:
            return ToolResult(ok=False, output="", error="Falta ciudad/ubicación.")

        result = route_chat(
            f"Zona horaria actual de {city}. Responde SOLO con el UTC offset "
            f"(ej: UTC-4, UTC+1, UTC+5:30) y el nombre de la zona si aplica. "
            f"Sin explicación adicional.",
            provider_id="deepseek",
            system_prompt=(
                "Eres un experto en zonas horarias. Responde SOLO con el offset UTC. "
                "Sin explicación."
            ),
        )
        return ToolResult(ok=True, output=result.strip()[:100])

    except Exception as e:
        log.warning("web_get_timezone error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════
# 5. web_reverse_geocode — Coordenadas GPS a dirección
# ═══════════════════════════════════════════════════════════════

def web_reverse_geocode_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Convierte coordenadas (lat, lon) a dirección aproximada."""
    try:
        from app.services.provider_router import route_chat

        lat = arguments.get("lat") or arguments.get("latitude")
        lon = arguments.get("lon") or arguments.get("lng") or arguments.get("longitude")

        if lat is None or lon is None:
            return ToolResult(
                ok=False, output="",
                error="Falta lat y lon (latitud y longitud).",
            )

        result = route_chat(
            f"Dirección aproximada para coordenadas lat={lat}, lon={lon}. "
            f"Responde SOLO con la dirección: calle, ciudad, país si es posible. "
            f"Sin explicación.",
            provider_id="deepseek",
            system_prompt=(
                "Eres un geocodificador inverso. Responde SOLO con la dirección. "
                "Sin explicación."
            ),
        )
        return ToolResult(ok=True, output=result.strip()[:500])

    except Exception as e:
        log.warning("web_reverse_geocode error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════
# 6. gmail_detect_phishing — Verificar si un correo es phishing
# ═══════════════════════════════════════════════════════════════

def gmail_detect_phishing_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Analiza el contenido de un correo y verifica si parece phishing."""
    try:
        from app.services.provider_router import route_chat

        # Aceptar: texto directo o subject + body + sender
        text = str(arguments.get("text") or arguments.get("content") or "").strip()
        subject = str(arguments.get("subject") or "").strip()
        sender = str(arguments.get("sender") or arguments.get("from") or "").strip()
        body = str(arguments.get("body") or "").strip()

        # Componer contenido completo
        if not text:
            parts = []
            if sender:
                parts.append(f"Remitente: {sender}")
            if subject:
                parts.append(f"Asunto: {subject}")
            if body:
                parts.append(f"Cuerpo: {body}")
            text = "\n".join(parts)

        if not text:
            return ToolResult(ok=False, output="", error="Falta contenido del correo a analizar.")

        result = route_chat(
            f"Analiza este correo. ¿Parece phishing? Responde SI/NO y razón en 1 frase.\n\n"
            f"{text[:3000]}",
            provider_id="deepseek",
            system_prompt=(
                "Eres un analista de seguridad. Responde SOLO 'SI' o 'NO' seguido "
                "de una razón en una frase. Formato: 'SI: razón' o 'NO: razón'."
            ),
        )
        return ToolResult(ok=True, output=result.strip()[:500])

    except Exception as e:
        log.warning("gmail_detect_phishing error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════
# 7. whatsapp_analyze_sentiment — Sentimiento de mensaje WA
# ═══════════════════════════════════════════════════════════════

def whatsapp_analyze_sentiment_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Analiza el sentimiento de un mensaje: positivo, negativo o neutral."""
    try:
        from app.services.provider_router import route_chat

        text = str(arguments.get("text") or arguments.get("message") or "").strip()
        if not text:
            return ToolResult(ok=False, output="", error="Falta texto del mensaje a analizar.")

        result = route_chat(
            f"Analiza el sentimiento de este mensaje: positivo, negativo o neutral. "
            f"Responde SOLO 1 palabra.\n\nMensaje: {text[:800]}",
            provider_id="deepseek",
            system_prompt=(
                "Eres un analizador de sentimiento. Responde SOLO una palabra: "
                "positivo, negativo o neutral. Sin explicación, sin puntuación."
            ),
        )
        sentiment = result.strip().lower()
        # Normalizar a una de las 3 opciones
        if "posit" in sentiment:
            sentiment = "positivo"
        elif "negat" in sentiment:
            sentiment = "negativo"
        else:
            sentiment = "neutral"
        return ToolResult(ok=True, output=sentiment)

    except Exception as e:
        log.warning("whatsapp_analyze_sentiment error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════
# 8. whatsapp_export_chat — Exportar conversación a TXT/CSV
# ═══════════════════════════════════════════════════════════════

def _get_dot_trabajos_dir() -> Path:
    desktop = Path(os.path.expanduser("~/Desktop"))
    dot_dir = desktop / "DOT Trabajos" / "WhatsApp Exports"
    dot_dir.mkdir(parents=True, exist_ok=True)
    return dot_dir


def whatsapp_export_chat_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Exporta mensajes de WhatsApp de un contacto a archivo TXT o CSV."""
    try:
        from app.application.whatsapp.inbound_service import get_message_store

        phone = str(arguments.get("phone") or arguments.get("contact") or "").strip()
        fmt = str(arguments.get("format") or arguments.get("fmt") or "txt").strip().lower()

        if not phone:
            return ToolResult(
                ok=False, output="",
                error="Falta phone (número del contacto a exportar).",
            )
        if fmt not in ("txt", "csv"):
            fmt = "txt"

        store = get_message_store()
        messages = store.list_for_uid(uid, phone=phone, limit=500)

        if not messages:
            return ToolResult(
                ok=True,
                output=f"No hay mensajes con {phone} para exportar.",
            )

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        phone_clean = "".join(ch for ch in phone if ch.isdigit())[-10:]

        if fmt == "csv":
            filename = f"chat_{phone_clean}_{ts}.csv"
            filepath = _get_dot_trabajos_dir() / filename
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "direction", "phone", "text"])
                for m in reversed(messages):
                    writer.writerow([
                        m.timestamp,
                        m.direction,
                        m.from_phone if m.direction == "inbound" else m.to_phone,
                        m.text or "",
                    ])
        else:
            filename = f"chat_{phone_clean}_{ts}.txt"
            filepath = _get_dot_trabajos_dir() / filename
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"Chat WhatsApp con {phone} — Exportado {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
                f.write("=" * 60 + "\n\n")
                for m in reversed(messages):
                    direction = "→ Enviado" if m.direction == "outbound" else "← Recibido"
                    f.write(f"[{m.timestamp[:19]}] {direction}\n")
                    f.write(f"{m.text or '(sin texto)'}\n")
                    f.write("-" * 40 + "\n")

        log.info(
            "whatsapp_export_chat uid=%s phone=%s fmt=%s path=%s count=%d",
            uid[:8], phone_clean, fmt, filepath, len(messages),
        )

        return ToolResult(
            ok=True,
            output=(
                f"Chat exportado: {len(messages)} mensajes.\n"
                f"Archivo: {filepath}\n"
                f"Formato: {fmt.upper()}"
            ),
        )

    except Exception as e:
        log.warning("whatsapp_export_chat error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════
# 9. whatsapp_auto_label — Etiquetar contacto automáticamente
# ═══════════════════════════════════════════════════════════════

def whatsapp_auto_label_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Etiqueta un contacto según el contenido de sus mensajes."""
    try:
        from app.services.provider_router import route_chat
        from app.application.whatsapp.inbound_service import get_message_store

        phone = str(arguments.get("phone") or arguments.get("contact") or "").strip()
        if not phone:
            return ToolResult(ok=False, output="", error="Falta phone del contacto a etiquetar.")

        store = get_message_store()
        messages = store.list_for_uid(uid, phone=phone, limit=20)

        if not messages:
            return ToolResult(
                ok=True,
                output="No hay mensajes de este contacto para analizar. Etiqueta sugerida: otro",
            )

        # Extraer textos recientes
        recent_texts = "\n".join(
            f"- {m.text[:200]}" for m in messages[:10] if m.text
        )

        result = route_chat(
            f"Este contacto de WhatsApp habla principalmente de: "
            f"clientes, proveedores, familia, trabajo, otro.\n\n"
            f"Mensajes recientes:\n{recent_texts[:3000]}\n\n"
            f"Responde SOLO 1 palabra con la categoría que mejor lo describe.",
            provider_id="deepseek",
            system_prompt=(
                "Eres un clasificador de contactos. Categorías válidas: "
                "clientes, proveedores, familia, trabajo, otro. "
                "Responde SOLO 1 palabra. Sin explicación."
            ),
        )

        label = result.strip().lower()
        valid_labels = {"clientes", "proveedores", "familia", "trabajo", "otro"}
        if label not in valid_labels:
            label = "otro"

        return ToolResult(ok=True, output=label)

    except Exception as e:
        log.warning("whatsapp_auto_label error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════
# 10. whatsapp_get_contact_info — Información de contacto WA
# ═══════════════════════════════════════════════════════════════

def whatsapp_get_contact_info_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene datos de un contacto: nombre sugerido, último mensaje, frecuencia."""
    try:
        from collections import Counter
        from app.application.whatsapp.inbound_service import get_message_store

        phone = str(arguments.get("phone") or arguments.get("contact") or "").strip()
        if not phone:
            return ToolResult(ok=False, output="", error="Falta phone del contacto.")

        store = get_message_store()
        messages = store.list_for_uid(uid, phone=phone, limit=200)

        if not messages:
            return ToolResult(
                ok=True,
                output=f"No se encontraron mensajes con {phone}. Sin información disponible.",
            )

        phone_clean = "".join(ch for ch in phone if ch.isdigit())[-10:]

        # Último mensaje
        last_msg = messages[0]
        last_text = (last_msg.text or "")[:200]
        last_ts = last_msg.timestamp[:19] if last_msg.timestamp else "desconocido"
        last_dir = "enviado" if last_msg.direction == "outbound" else "recibido"

        # Frecuencia: mensajes por mes (aproximado)
        total = len(messages)
        if total >= 2:
            try:
                ts_first = messages[-1].timestamp
                ts_last = messages[0].timestamp
                d1 = datetime.fromisoformat(ts_first[:19].replace(" ", "T"))
                d2 = datetime.fromisoformat(ts_last[:19].replace(" ", "T"))
                days = max((d2 - d1).days, 1)
                msgs_per_day = round(total / days, 2)
            except (ValueError, TypeError, IndexError):
                msgs_per_day = total
        else:
            msgs_per_day = total

        # Nombre sugerido: buscar menciones comunes
        names_counter: Counter[str] = Counter()
        for m in messages:
            if m.text and m.direction == "inbound":
                # Buscar patrón "Soy X" o "Me llamo X" o saludos
                text_lower = m.text.lower()
                if any(phrase in text_lower for phrase in ("soy ", "me llamo ", "mi nombre es ")):
                    # Tomar las siguientes 2-3 palabras
                    words = m.text.split()
                    for i, w in enumerate(words):
                        if w.lower() in ("soy", "llamo"):
                            if i + 1 < len(words):
                                name_candidate = words[i + 1].strip(".,!?¿¡:;")
                                if len(name_candidate) > 1 and name_candidate[0].isupper():
                                    names_counter[name_candidate] += 1

        suggested_name = names_counter.most_common(1)[0][0] if names_counter else "No detectado"

        # Dirección (inbound vs outbound)
        inbound_count = sum(1 for m in messages if m.direction == "inbound")
        outbound_count = total - inbound_count

        output_parts = [
            f"Información de contacto: {phone_clean}",
            f"  Nombre sugerido: {suggested_name}",
            f"  Total mensajes: {total} (recibidos: {inbound_count}, enviados: {outbound_count})",
            f"  Frecuencia: ~{msgs_per_day} msgs/día",
            f"  Último mensaje ({last_dir}): [{last_ts}] {last_text}",
        ]
        return ToolResult(ok=True, output="\n".join(output_parts))

    except Exception as e:
        log.warning("whatsapp_get_contact_info error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════
# 11. productivity_daily_summary — Resumen diario
# ═══════════════════════════════════════════════════════════════

def _safe_call_handler(handler_func: Any, uid: str, args: dict) -> str:
    """Llama un handler y devuelve su output o mensaje de error."""
    try:
        result = handler_func(uid, args)
        if getattr(result, "ok", False):
            return getattr(result, "output", "") or "(sin datos)"
        return f"(error: {getattr(result, 'error', 'desconocido')})"
    except Exception as e:
        return f"(no disponible: {e})"


def productivity_daily_summary_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera un resumen diario: correos no leídos, eventos de hoy y mensajes WA recientes."""
    try:
        from app.services.provider_router import route_chat

        sections: dict[str, str] = {}

        # ── Gmail ──
        try:
            from app.application.agent.tools.gmail_read import gmail_list_unread_handler
            gmail_result = gmail_list_unread_handler(uid, {"max_results": 15})
            sections["correos"] = gmail_result.output if gmail_result.ok else "(Gmail no disponible)"
        except ImportError:
            sections["correos"] = "(Gmail no vinculado o modulo no disponible)"

        # ── Calendar ──
        try:
            from app.application.agent.tools.calendar import calendar_list_today_handler
            cal_result = calendar_list_today_handler(uid, {})
            sections["eventos"] = cal_result.output if cal_result.ok else "(Calendario no disponible)"
        except ImportError:
            sections["eventos"] = "(Google Calendar no vinculado o modulo no disponible)"

        # ── WhatsApp ──
        try:
            from app.application.agent.tools.whatsapp_tools import whatsapp_read_recent_handler
            wa_result = whatsapp_read_recent_handler(uid, {"limit": 15})
            sections["whatsapp"] = wa_result.output if wa_result.ok else "(WhatsApp no disponible)"
        except ImportError:
            try:
                from app.application.whatsapp.inbound_service import get_message_store
                store = get_message_store()
                msgs = store.list_for_uid(uid, limit=15)
                if msgs:
                    lines = []
                    for m in msgs:
                        direction = "→" if m.direction == "outbound" else "←"
                        lines.append(
                            f"{direction} [{m.timestamp[:19]}] {m.from_phone[-10:]}: {(m.text or '')[:200]}"
                        )
                    sections["whatsapp"] = f"Últimos {len(msgs)} mensajes WA:\n" + "\n".join(lines)
                else:
                    sections["whatsapp"] = "Sin mensajes recientes de WhatsApp."
            except Exception:
                sections["whatsapp"] = "(WhatsApp no disponible)"

        # ── Componer resumen con IA ──
        prompt = (
            f"Genera un resumen ejecutivo diario en español con estos datos:\n\n"
            f"=== CORREOS NO LEÍDOS ===\n{sections.get('correos', 'Sin datos')}\n\n"
            f"=== EVENTOS DE HOY ===\n{sections.get('eventos', 'Sin datos')}\n\n"
            f"=== WHATSAPP RECIENTE ===\n{sections.get('whatsapp', 'Sin datos')}\n\n"
            f"Estructura: 1) Resumen general (2 frases), 2) Pendientes importantes, "
            f"3) Eventos/recordatorios del día. Sé conciso y accionable."
        )

        summary = route_chat(
            prompt[:6000],
            provider_id="deepseek",
            system_prompt=(
                "Eres un asistente ejecutivo. Generas resúmenes diarios concisos "
                "en español, con viñetas accionables. Máximo 15 líneas."
            ),
        )

        header = f"📋 Resumen diario — {datetime.now().strftime('%d/%m/%Y')}\n{'=' * 50}\n"
        return ToolResult(ok=True, output=header + summary.strip())

    except Exception as e:
        log.warning("productivity_daily_summary error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════
# 12. productivity_weekly_report — Reporte semanal
# ═══════════════════════════════════════════════════════════════

def productivity_weekly_report_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera un reporte semanal: correos no leídos, eventos de la semana y mensajes WA."""
    try:
        from app.services.provider_router import route_chat

        sections: dict[str, str] = {}

        # ── Gmail (no leídos) ──
        try:
            from app.application.agent.tools.gmail_read import gmail_list_unread_handler
            gmail_result = gmail_list_unread_handler(uid, {"max_results": 20})
            sections["correos"] = gmail_result.output if gmail_result.ok else "(Gmail no disponible)"
        except ImportError:
            sections["correos"] = "(Gmail no vinculado o modulo no disponible)"

        # ── Calendar (semana) ──
        try:
            from app.application.agent.tools.calendar import calendar_list_week_handler
            cal_result = calendar_list_week_handler(uid, {})
            sections["eventos"] = cal_result.output if cal_result.ok else "(Calendario no disponible)"
        except ImportError:
            sections["eventos"] = "(Google Calendar no vinculado o modulo no disponible)"

        # ── WhatsApp ──
        try:
            from app.application.agent.tools.whatsapp_tools import whatsapp_read_recent_handler
            wa_result = whatsapp_read_recent_handler(uid, {"limit": 30})
            sections["whatsapp"] = wa_result.output if wa_result.ok else "(WhatsApp no disponible)"
        except ImportError:
            try:
                from app.application.whatsapp.inbound_service import get_message_store
                store = get_message_store()
                msgs = store.list_for_uid(uid, limit=30)
                if msgs:
                    lines = []
                    for m in msgs:
                        direction = "→" if m.direction == "outbound" else "←"
                        lines.append(
                            f"{direction} [{m.timestamp[:19]}] {m.from_phone[-10:]}: {(m.text or '')[:200]}"
                        )
                    sections["whatsapp"] = f"Últimos {len(msgs)} mensajes WA:\n" + "\n".join(lines)
                else:
                    sections["whatsapp"] = "Sin mensajes recientes de WhatsApp."
            except Exception:
                sections["whatsapp"] = "(WhatsApp no disponible)"

        # ── Componer reporte semanal con IA ──
        prompt = (
            f"Genera un reporte semanal ejecutivo en español con estos datos:\n\n"
            f"=== CORREOS NO LEÍDOS ===\n{sections.get('correos', 'Sin datos')}\n\n"
            f"=== EVENTOS DE LA SEMANA ===\n{sections.get('eventos', 'Sin datos')}\n\n"
            f"=== WHATSAPP RECIENTE ===\n{sections.get('whatsapp', 'Sin datos')}\n\n"
            f"Estructura: 1) Resumen general (3 frases), 2) Tareas pendientes, "
            f"3) Próximos eventos, 4) Recomendaciones para la semana. "
            f"Sé conciso y accionable. Máximo 20 líneas."
        )

        summary = route_chat(
            prompt[:6000],
            provider_id="deepseek",
            system_prompt=(
                "Eres un asistente ejecutivo. Generas reportes semanales concisos "
                "en español, con secciones claras y viñetas accionables."
            ),
        )

        header = (
            f"📊 Reporte semanal — {datetime.now().strftime('%d/%m/%Y')}\n"
            f"{'=' * 50}\n"
        )
        return ToolResult(ok=True, output=header + summary.strip())

    except Exception as e:
        log.warning("productivity_weekly_report error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=str(e))


# ═══════════════════════════════════════════════════════════════
# TOOLS export
# ═══════════════════════════════════════════════════════════════

TOOLS: list[tuple[str, Any]] = [
    # ⚠️ FAKE: web_search_images alucina URLs de imágenes sin API real (route_chat)
    # ("web_search_images", web_search_images_handler),
    # ⚠️ FAKE peligroso: web_get_stock alucina precios de acciones sin API financiera real
    # ("web_get_stock", web_get_stock_handler),
    ("web_url_shorten", web_url_shorten_handler),
    # ⚠️ FAKE: web_get_timezone alucina zonas horarias sin API real (route_chat)
    # ("web_get_timezone", web_get_timezone_handler),
    # ⚠️ FAKE: web_reverse_geocode alucina direcciones sin API de geocodificación real (route_chat)
    # ("web_reverse_geocode", web_reverse_geocode_handler),
    # ⚠️ FAKE peligroso: gmail_detect_phishing alucina análisis de seguridad sin escanear headers reales
    # ("gmail_detect_phishing", gmail_detect_phishing_handler),
    # ⚠️ FAKE: whatsapp_analyze_sentiment alucina análisis de sentimiento sin NLP real (route_chat)
    # ("whatsapp_analyze_sentiment", whatsapp_analyze_sentiment_handler),
    ("whatsapp_export_chat", whatsapp_export_chat_handler),
    # ⚠️ FAKE: whatsapp_auto_label alucina etiquetas sin modelo de clasificación real (route_chat)
    # ("whatsapp_auto_label", whatsapp_auto_label_handler),
    ("whatsapp_get_contact_info", whatsapp_get_contact_info_handler),
    # ⚠️ FAKE: productivity_daily_summary alucina resumen ejecutivo sin datos consolidados reales (route_chat)
    # ("productivity_daily_summary", productivity_daily_summary_handler),
    # ⚠️ FAKE: productivity_weekly_report alucina reporte semanal sin datos reales (route_chat)
    # ("productivity_weekly_report", productivity_weekly_report_handler),
]
