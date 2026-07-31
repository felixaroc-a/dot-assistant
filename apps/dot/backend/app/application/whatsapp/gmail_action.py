"""Acciones Gmail en lenguaje natural vía JSON del asistente (D1).

Esquema:
  {"action":"gmail_send","to":"a@b.com","subject":"Asunto","body":"Cuerpo"}
  Adjuntos opcionales:
  {"attachments":[{"filename":"cv.pdf","content_base64":"..."}]}
  {"attachments":[{"filename":"cv.pdf","path":"~/Desktop/cv.pdf"}]}
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.application.whatsapp.local_tool_parse import extract_first_json_object

log = logging.getLogger("dot.gmail_action")

_GMAIL_JSON = re.compile(
    r"\{[\s\S]*\"action\"\s*:\s*\"gmail_send\"[\s\S]*\}\s*$",
    re.IGNORECASE,
)

GMAIL_SEND_SYSTEM_HINT = (
    "ENVÍO DE CORREO (Gmail):\n"
    "Si el usuario pide enviar un correo y tienes Gmail vinculado, responde ÚNICAMENTE "
    "con JSON válido (sin markdown) con este esquema:\n"
    '{"action":"gmail_send","to":"destinatario@email.com","subject":"Asunto","body":"Cuerpo del mensaje",'
    '"attachments":[{"filename":"archivo.pdf","path":"~/Desktop/archivo.pdf"}]}\n'
    "Adjuntos opcionales: filename + path sandbox o content_base64. "
    "Si Gmail no está vinculado o faltan datos (to/subject), responde en texto humano "
    "pidiendo conectar Google o completar los datos. Nunca inventes direcciones."
)


def _parse_attachments(raw: Any) -> list[dict[str, Any]] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    attachments: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        attachments.append(dict(item))
    return attachments or None


def parse_gmail_send_action(text: str) -> dict[str, Any] | None:
    data = extract_first_json_object(text)
    if not data:
        return None
    if str(data.get("action") or "").lower() != "gmail_send":
        return None
    to = str(data.get("to") or "").strip()
    subject = str(data.get("subject") or "").strip()
    body = data.get("body")
    if not to or "@" not in to:
        return None
    if not isinstance(body, str):
        body = str(body or "")
    action: dict[str, Any] = {
        "to": to,
        "subject": subject or "(sin asunto)",
        "body": body,
    }
    body_html = data.get("body_html")
    if isinstance(body_html, str) and body_html.strip():
        action["body_html"] = body_html
    attachments = _parse_attachments(data.get("attachments"))
    if attachments:
        action["attachments"] = attachments
    return action


def strip_gmail_send_json(text: str) -> str:
    cleaned = _GMAIL_JSON.sub("", text or "").strip()
    return cleaned or (text or "").strip()


def execute_gmail_send(uid: str, action: dict[str, Any]) -> str:
    """Ejecuta envío; mensaje humano fail-closed si no hay OAuth."""
    from app.services.gmail_service import (
        GmailIntegrationError,
        MissingGmailCredentialsError,
        send_message,
    )

    try:
        sent = send_message(
            uid,
            to=str(action["to"]),
            subject=str(action.get("subject") or "(sin asunto)"),
            body=str(action.get("body") or ""),
            body_html=str(action["body_html"]) if action.get("body_html") else None,
            attachments=action.get("attachments"),
        )
        msg_id = sent.get("id") or "?"
        attachment_note = ""
        attachments = action.get("attachments") or []
        if attachments:
            attachment_note = f" con {len(attachments)} adjunto(s)"
        return (
            f"Correo enviado a {action['to']} "
            f"con asunto «{action.get('subject') or '(sin asunto)'}»"
            f"{attachment_note} "
            f"(id={msg_id})."
        )
    except MissingGmailCredentialsError:
        return (
            "Para enviar correos necesitas conectar tu cuenta de Google (Gmail) "
            "en la configuración de DOT. Abre la app y vincula Google; luego inténtalo de nuevo."
        )
    except GmailIntegrationError as e:
        log.warning("Gmail integración falló uid=%s: %s", uid[:8], e)
        return (
            "No pude enviar el correo con Gmail ahora. "
            "Revisa que Google esté vinculado y vuelve a intentarlo."
        )
    except Exception:
        log.exception("Error inesperado enviando Gmail uid=%s", uid[:8])
        return "Hubo un error al enviar el correo. Intenta de nuevo en unos minutos."


def apply_gmail_send_if_present(uid: str, assistant_text: str) -> str:
    """Si la respuesta contiene gmail_send, ejecuta y sustituye por texto humano."""
    action = parse_gmail_send_action(assistant_text)
    if not action:
        return assistant_text
    spoken = strip_gmail_send_json(assistant_text)
    result = execute_gmail_send(uid, action)
    if spoken and spoken != assistant_text and "gmail_send" not in spoken:
        return f"{spoken}\n\n{result}".strip()
    return result
