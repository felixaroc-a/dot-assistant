"""Tools Microsoft 365 / Outlook para el Agent Runtime.

Herramientas que permiten al agente gestionar correo, calendario y contactos
de la cuenta Microsoft 365 / Outlook del usuario.

Auth: AZURE_CLIENT_ID + AZURE_TENANT_ID + AZURE_CLIENT_SECRET (Azure AD app).
Gate: OUTLOOK_ENABLED=true en .env.
Sin config → "requiere vincular cuenta Microsoft 365 en Ajustes".

Referencia: https://learn.microsoft.com/en-us/graph/api/overview
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from app.application.agent.ports import ToolResult
from app.settings import settings

log = logging.getLogger("dot.agent.tools.outlook")

# ─── Gate helper ──────────────────────────────────────────────────────

def _check_enabled(uid: str) -> str | None:
    """Retorna mensaje de error si Outlook no está habilitado/configurado."""
    if not settings.outlook_enabled:
        return (
            "Microsoft 365 / Outlook no habilitado. "
            "El usuario debe activar OUTLOOK_ENABLED=true en Ajustes."
        )

    missing = []
    if not settings.azure_client_id:
        missing.append("AZURE_CLIENT_ID")
    if not settings.azure_tenant_id:
        missing.append("AZURE_TENANT_ID")
    if not settings.azure_client_secret:
        missing.append("AZURE_CLIENT_SECRET")

    if missing:
        return (
            f"Microsoft 365 / Outlook no configurado. Faltan: {', '.join(missing)}. "
            "Solicita al usuario que configure las credenciales en Ajustes "
            "(requiere registrar una app en Azure AD: portal.azure.com → App Registrations "
            "con permisos delegados Mail.Read, Mail.Send, Calendars.ReadWrite, Contacts.Read)."
        )

    from app.services.outlook_service import _token_cache
    if uid not in _token_cache:
        return (
            "Cuenta Microsoft 365 no vinculada. "
            "Solicita al usuario que vincule su cuenta en Ajustes → Integraciones → Outlook. "
            "Necesita iniciar sesión con su cuenta Microsoft 365 y autorizar los permisos."
        )
    return None


def _run_async(coro):
    """Ejecuta una coroutine en el event loop actual o crea uno nuevo."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ─── EMAIL TOOLS ──────────────────────────────────────────────────────

def outlook_list_emails(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lista los correos recientes de la bandeja de entrada de Microsoft 365 / Outlook.

    Args:
        top: Cantidad máxima de correos a retornar (default 10, max 50).
        folder: Carpeta de correo — inbox (por defecto), sentitems, drafts, deleteditems.
        query: Término de búsqueda opcional (KQL: from:fulano, subject:factura, etc.)

    Returns:
        ToolResult con lista de correos (subject, from, received, preview).
    """
    error_msg = _check_enabled(uid)
    if error_msg:
        return ToolResult(ok=False, output="", error=error_msg)

    top = min(int(arguments.get("top") or 10), 50)
    folder = str(arguments.get("folder") or "inbox").strip().lower()
    query = str(arguments.get("query") or "").strip()

    try:
        from app.services.outlook_service import list_inbox, search_messages

        if query:
            result = _run_async(search_messages(uid, query=query, top=top, folder=folder))
        else:
            result = _run_async(list_inbox(uid, top=top, folder=folder))

        emails = result.get("emails", [])
        if not emails:
            return ToolResult(ok=True, output=f"No hay correos en '{folder}'." + (" (búsqueda: {query})" if query else ""))

        lines = []
        for e in emails[:top]:
            read = "✓" if e.get("is_read") else "●"
            lines.append(
                f"{read} [{e.get('received', '?')[:16]}] {e.get('from_name', '?')}: "
                f"{e.get('subject', '(sin asunto)')[:80]}"
            )

        header = f"Bandeja '{folder}' ({len(emails)} correos)"
        if query:
            header += f" — búsqueda: \"{query}\""
        return ToolResult(ok=True, output=header + ":\n" + "\n".join(lines))
    except PermissionError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        log.warning("outlook_list_emails error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"No pude leer tus correos: {e}")


def outlook_send_email(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Envía un correo desde la cuenta Microsoft 365 / Outlook del usuario.

    Args:
        to: Email del destinatario (string). Para múltiples: "a@x.com, b@y.com".
        subject: Asunto del correo.
        body: Cuerpo del mensaje (texto plano).
        cc: Emails en copia (opcional, separados por coma).
        body_type: "Text" (por defecto) o "HTML".

    Returns:
        ToolResult con confirmación de envío o error.
    """
    error_msg = _check_enabled(uid)
    if error_msg:
        return ToolResult(ok=False, output="", error=error_msg)

    to_raw = str(arguments.get("to") or "").strip()
    subject = str(arguments.get("subject") or "").strip()
    body_text = str(arguments.get("body") or arguments.get("message") or "").strip()
    cc_raw = str(arguments.get("cc") or "").strip()
    body_type = str(arguments.get("body_type") or "Text").strip()

    if not to_raw:
        return ToolResult(ok=False, output="", error="Falta el destinatario (to).")
    if not subject:
        return ToolResult(ok=False, output="", error="Falta el asunto (subject).")
    if not body_text:
        return ToolResult(ok=False, output="", error="Falta el cuerpo del mensaje (body).")

    to_list = [e.strip() for e in to_raw.split(",") if e.strip()]
    cc_list = [e.strip() for e in cc_raw.split(",") if e.strip()] if cc_raw else None

    try:
        from app.services.outlook_service import send_message

        result = _run_async(send_message(
            uid,
            to=to_list,
            subject=subject,
            body=body_text,
            body_type=body_type if body_type in ("Text", "HTML") else "Text",
            cc=cc_list,
        ))

        return ToolResult(
            ok=True,
            output=f"Correo enviado a {', '.join(to_list[:3])}: \"{subject[:60]}\" (id={result['message_id']}).",
        )
    except PermissionError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        log.warning("outlook_send_email error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"No pude enviar el correo: {e}")


def outlook_search_emails(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca correos en Microsoft 365 / Outlook usando KQL (Keyword Query Language).

    Args:
        query: Término de búsqueda. Soporta KQL: from:juan, subject:factura,
               hasAttachments:true, received:>2026-07-01, etc.
        top: Cantidad máxima de resultados (default 20, max 50).
        folder: Carpeta donde buscar (default: inbox).

    Returns:
        ToolResult con resultados de la búsqueda.
    """
    error_msg = _check_enabled(uid)
    if error_msg:
        return ToolResult(ok=False, output="", error=error_msg)

    query = str(arguments.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, output="", error="Falta el término de búsqueda (query).")

    top = min(int(arguments.get("top") or 20), 50)
    folder = str(arguments.get("folder") or "inbox").strip().lower()

    try:
        from app.services.outlook_service import search_messages

        result = _run_async(search_messages(uid, query=query, top=top, folder=folder))

        emails = result.get("emails", [])
        if not emails:
            return ToolResult(ok=True, output=f"No se encontraron correos para: \"{query}\" en '{folder}'.")

        lines = []
        for e in emails[:top]:
            lines.append(
                f"[{e.get('received', '?')[:16]}] {e.get('from_name', '?')}: "
                f"{e.get('subject', '(sin asunto)')[:80]}"
            )

        return ToolResult(
            ok=True,
            output=f"Resultados para \"{query}\" en '{folder}' ({len(emails)}):\n" + "\n".join(lines),
        )
    except PermissionError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        log.warning("outlook_search_emails error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"No pude buscar correos: {e}")


# ─── CALENDAR TOOLS ───────────────────────────────────────────────────

def outlook_list_events(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lista los eventos del calendario Microsoft 365 / Outlook del usuario.

    Args:
        start: Fecha inicio ISO (default: hoy). Ej: 2026-07-24T00:00:00
        end: Fecha fin ISO (default: +7 días). Ej: 2026-07-31T23:59:59
        top: Cantidad máxima de eventos (default 20, max 50).

    Returns:
        ToolResult con lista de eventos (subject, start, end, location, organizer).
    """
    error_msg = _check_enabled(uid)
    if error_msg:
        return ToolResult(ok=False, output="", error=error_msg)

    start_str = str(arguments.get("start") or "").strip() or None
    end_str = str(arguments.get("end") or "").strip() or None
    top = min(int(arguments.get("top") or 20), 50)

    try:
        from app.services.outlook_service import list_events

        result = _run_async(list_events(uid, start_date=start_str, end_date=end_str, top=top))

        events = result.get("events", [])
        if not events:
            rango = f"{start_str or 'hoy'} a {end_str or '+7 días'}"
            return ToolResult(ok=True, output=f"No hay eventos en el rango: {rango}.")

        lines = []
        for e in events[:top]:
            inicio = e.get("start", "?")[:16]
            fin = e.get("end", "?")[:16]
            loc = f" @ {e.get('location', '')}" if e.get("location") else ""
            lines.append(f"• {inicio} → {fin} | {e.get('subject', '(sin título)')}{loc}")

        rango = f"{result.get('start', '?')[:10]} → {result.get('end', '?')[:10]}"
        return ToolResult(
            ok=True,
            output=f"Calendario Outlook ({len(events)} eventos, {rango}):\n" + "\n".join(lines),
        )
    except PermissionError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        log.warning("outlook_list_events error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"No pude consultar tu calendario: {e}")


def outlook_create_event(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Crea un evento en el calendario Microsoft 365 / Outlook del usuario.

    Args:
        subject: Título del evento.
        start: Fecha/hora inicio ISO 8601. Ej: 2026-07-25T15:00:00
        end: Fecha/hora fin ISO 8601.
        duration_minutes: Duración en minutos (si no se especifica end, default 60).
        location: Ubicación opcional.
        body: Descripción/notas opcionales.
        attendees: Lista de emails de asistentes (separados por coma).

    Returns:
        ToolResult con confirmación de creación o error.
    """
    error_msg = _check_enabled(uid)
    if error_msg:
        return ToolResult(ok=False, output="", error=error_msg)

    subject = str(arguments.get("subject") or arguments.get("title") or "").strip()
    if not subject:
        return ToolResult(ok=False, output="", error="Falta el título del evento (subject).")

    start_raw = str(arguments.get("start") or arguments.get("start_time") or "").strip()
    end_raw = str(arguments.get("end") or arguments.get("end_time") or "").strip()
    dur_min = int(arguments.get("duration_minutes") or 0)

    if not start_raw:
        return ToolResult(ok=False, output="", error="Falta la fecha/hora de inicio (start). Usa formato ISO 8601.")

    try:
        start_dt = datetime.fromisoformat(start_raw)
    except ValueError:
        return ToolResult(
            ok=False, output="",
            error=f"Formato de fecha inválido: {start_raw}. Usa ISO 8601 (YYYY-MM-DDTHH:MM:SS).",
        )

    if end_raw:
        try:
            end_dt = datetime.fromisoformat(end_raw)
        except ValueError:
            end_dt = start_dt + timedelta(minutes=max(15, dur_min or 60))
    elif dur_min:
        end_dt = start_dt + timedelta(minutes=max(15, min(dur_min, 480)))
    else:
        end_dt = start_dt + timedelta(minutes=60)

    location = str(arguments.get("location") or "").strip() or None
    body_text = str(arguments.get("body") or arguments.get("description") or "").strip() or None

    attendees_raw = str(arguments.get("attendees") or "").strip()
    attendees = [a.strip() for a in attendees_raw.split(",") if a.strip()] if attendees_raw else None

    try:
        from app.services.outlook_service import create_event

        result = _run_async(create_event(
            uid,
            subject=subject,
            start_dt=start_dt,
            end_dt=end_dt,
            location=location,
            body=body_text,
            attendees=attendees,
        ))

        return ToolResult(
            ok=True,
            output=(
                f"Evento creado en Outlook: \"{subject}\" "
                f"({start_raw} → {(end_dt).isoformat()})"
                + (f" con {len(attendees)} asistentes" if attendees else "")
                + f" (id={result['event_id'][:12]})."
            ),
        )
    except PermissionError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        log.warning("outlook_create_event error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"No pude crear el evento: {e}")


def outlook_get_free_slots(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Encuentra horarios libres en el calendario Microsoft 365 / Outlook del usuario.

    Args:
        start: Fecha inicio ISO. Ej: 2026-07-25T00:00:00
        end: Fecha fin ISO. Ej: 2026-07-25T23:59:59
        duration_minutes: Duración mínima del slot (default 30, min 15).

    Returns:
        ToolResult con lista de slots libres.
    """
    error_msg = _check_enabled(uid)
    if error_msg:
        return ToolResult(ok=False, output="", error=error_msg)

    start_str = str(arguments.get("start") or "").strip()
    end_str = str(arguments.get("end") or "").strip()
    duration = max(15, int(arguments.get("duration_minutes") or 30))

    if not start_str or not end_str:
        return ToolResult(
            ok=False, output="",
            error="Faltan fechas de rango (start y end). Ej: 2026-07-25T00:00:00 a 2026-07-25T23:59:59",
        )

    try:
        from app.services.outlook_service import get_free_slots

        result = _run_async(get_free_slots(
            uid,
            start_date=start_str,
            end_date=end_str,
            duration_minutes=duration,
        ))

        slots = result.get("slots", [])
        if not slots:
            return ToolResult(ok=True, output=f"No hay slots libres de {duration}min entre {start_str[:10]} y {end_str[:10]}.")

        lines = []
        for s in slots[:10]:
            lines.append(f"• {s.get('start', '?')[:16]} → {s.get('end', '?')[:16]} ({s.get('duration_min', duration)}min)")

        return ToolResult(
            ok=True,
            output=f"Slots libres de {duration}min ({result.get('total_slots', 0)} total):\n" + "\n".join(lines),
        )
    except PermissionError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        log.warning("outlook_free_slots error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"No pude buscar slots libres: {e}")


# ─── CONTACTS TOOLS ───────────────────────────────────────────────────

def outlook_list_contacts(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lista los contactos de Microsoft 365 / Outlook del usuario.

    Args:
        top: Cantidad máxima de contactos (default 30, max 100).
        query: Búsqueda por nombre o email (opcional).

    Returns:
        ToolResult con lista de contactos (nombre, emails, empresa, cargo).
    """
    error_msg = _check_enabled(uid)
    if error_msg:
        return ToolResult(ok=False, output="", error=error_msg)

    top = min(int(arguments.get("top") or 30), 100)
    query = str(arguments.get("query") or "").strip() or None

    try:
        from app.services.outlook_service import list_contacts

        result = _run_async(list_contacts(uid, top=top, query=query))

        contacts = result.get("contacts", [])
        if not contacts:
            msg = "No hay contactos en Microsoft 365."
            if query:
                msg = f"No se encontraron contactos para: \"{query}\"."
            return ToolResult(ok=True, output=msg)

        lines = []
        for c in contacts[:top]:
            email_str = ", ".join(c.get("emails", [])[:2])
            company = f" — {c.get('company', '')}" if c.get("company") else ""
            lines.append(f"• {c.get('display_name', '?')} | {email_str}{company}")

        header = f"Contactos Outlook ({len(contacts)})"
        if query:
            header += f" — búsqueda: \"{query}\""
        return ToolResult(ok=True, output=header + ":\n" + "\n".join(lines))
    except PermissionError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        log.warning("outlook_list_contacts error uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"No pude leer tus contactos: {e}")


# ─── Registro ──────────────────────────────────────────────────────────

TOOLS = [
    ("outlook_list_emails", outlook_list_emails),
    ("outlook_send_email", outlook_send_email),
    ("outlook_search_emails", outlook_search_emails),
    ("outlook_list_events", outlook_list_events),
    ("outlook_create_event", outlook_create_event),
    ("outlook_get_free_slots", outlook_get_free_slots),
    ("outlook_list_contacts", outlook_list_contacts),
]
