"""Integración Gmail para automatizaciones de DOT."""
from __future__ import annotations

import base64
import logging
import mimetypes
import os
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app import crypto_tokens
from app.firebase_db import get_user_google_tokens_ciphertext

log = logging.getLogger("dot.gmail_service")


class GmailIntegrationError(RuntimeError):
    """Error base de integración Gmail."""


class MissingGmailCredentialsError(GmailIntegrationError):
    """No existen credenciales OAuth válidas para Gmail."""


def _load_google_credentials(user_id: str) -> Credentials:
    ciphertext = get_user_google_tokens_ciphertext(user_id)
    if not ciphertext:
        raise MissingGmailCredentialsError(
            "Gmail no está vinculado para este usuario."
        )

    token_data = crypto_tokens.decrypt_token_blob(ciphertext)
    token = token_data.get("token")
    refresh_token = token_data.get("refresh_token")
    token_uri = token_data.get("token_uri")
    client_id = token_data.get("client_id")
    client_secret = token_data.get("client_secret")
    scopes = token_data.get("scopes")

    if not all([token, refresh_token, token_uri, client_id, client_secret]):
        raise GmailIntegrationError(
            "El token OAuth de Google está incompleto para este usuario."
        )

    return Credentials(
        token=str(token),
        refresh_token=str(refresh_token),
        token_uri=str(token_uri),
        client_id=str(client_id),
        client_secret=str(client_secret),
        scopes=[str(s) for s in scopes] if isinstance(scopes, list) else None,
    )


def _gmail_service(user_id: str):
    creds = _load_google_credentials(user_id)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def count_unread(user_id: str) -> int:
    """Cuenta correos no leídos sin descargar el cuerpo (sin IA)."""
    service = _gmail_service(user_id)
    response = (
        service.users()  # type: ignore[no-untyped-call]
        .messages()
        .list(userId="me", q="is:unread", maxResults=1)
        .execute()
    )
    estimate = response.get("resultSizeEstimate")
    if isinstance(estimate, int):
        return max(0, estimate)
    messages = response.get("messages") or []
    return len(messages)


def list_unread(user_id: str, max_results: int = 20) -> list[dict[str, Any]]:
    service = _gmail_service(user_id)
    response = (
        service.users()  # type: ignore[no-untyped-call]
        .messages()
        .list(userId="me", q="is:unread", maxResults=max(1, min(max_results, 50)))
        .execute()
    )
    messages = response.get("messages") or []
    items: list[dict[str, Any]] = []
    for item in messages:
        msg_id = item.get("id")
        if not msg_id:
            continue
        detail = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="metadata", metadataHeaders=["From", "Subject", "Date"])
            .execute()
        )
        headers = detail.get("payload", {}).get("headers", [])
        by_name = {h.get("name", "").lower(): h.get("value", "") for h in headers}
        items.append(
            {
                "id": msg_id,
                "from": by_name.get("from", ""),
                "subject": by_name.get("subject", "(sin asunto)"),
                "date": by_name.get("date", ""),
                "snippet": detail.get("snippet", ""),
            }
        )
    return items


def search_messages(user_id: str, query: str, max_results: int = 20) -> list[dict[str, Any]]:
    service = _gmail_service(user_id)
    response = (
        service.users()  # type: ignore[no-untyped-call]
        .messages()
        .list(userId="me", q=query, maxResults=max(1, min(max_results, 50)))
        .execute()
    )
    messages = response.get("messages") or []
    items: list[dict[str, Any]] = []
    for item in messages:
        msg_id = item.get("id")
        if not msg_id:
            continue
        detail = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        headers = detail.get("payload", {}).get("headers", [])
        by_name = {h.get("name", "").lower(): h.get("value", "") for h in headers}
        items.append(
            {
                "id": msg_id,
                "from": by_name.get("from", ""),
                "to": by_name.get("to", ""),
                "subject": by_name.get("subject", "(sin asunto)"),
                "snippet": detail.get("snippet", ""),
            }
        )
    return items


def _read_sandbox_path_bytes(path: str) -> bytes:
    """Lee bytes de una ruta sandbox del PC vía bridge o filesystem local (tests)."""
    from app.application.agent.tools.local_files import execute_local_tool_via_bridge

    result = execute_local_tool_via_bridge("readFileBytes", path=path)
    if isinstance(result, dict) and result.get("ok"):
        b64 = result.get("content_base64") or result.get("contentBase64")
        if b64:
            return base64.b64decode(str(b64))
        content = result.get("content")
        if isinstance(content, str):
            return content.encode("utf-8")

    expanded = os.path.expanduser(os.path.expandvars(path))
    if os.path.isfile(expanded):
        with open(expanded, "rb") as handle:
            return handle.read()

    err = result.get("error") if isinstance(result, dict) else "archivo no accesible"
    raise GmailIntegrationError(f"No se pudo leer adjunto en {path}: {err}")


def _resolve_attachment_spec(spec: dict[str, Any]) -> tuple[str, bytes]:
    """Resuelve un adjunto desde filename + content_base64 o path sandbox."""
    path = str(spec.get("path") or "").strip()
    filename = str(spec.get("filename") or "").strip()
    if not filename and path:
        filename = os.path.basename(os.path.expanduser(path))
    if not filename:
        raise GmailIntegrationError("Adjunto sin filename.")

    raw_content = spec.get("content_base64")
    if raw_content is None:
        raw_content = spec.get("content_bytes")
    if raw_content is None:
        raw_content = spec.get("content")

    if isinstance(raw_content, (bytes, bytearray)):
        return filename, bytes(raw_content)
    if isinstance(raw_content, str) and raw_content.strip():
        try:
            return filename, base64.b64decode(raw_content, validate=True)
        except Exception as exc:
            raise GmailIntegrationError(
                f"content_base64 inválido para adjunto {filename}."
            ) from exc

    if path:
        return filename, _read_sandbox_path_bytes(path)

    raise GmailIntegrationError(
        f"Adjunto {filename} requiere content_base64 o path sandbox."
    )


def _normalize_attachments(
    attachments: list[Any] | None,
) -> list[tuple[str, bytes]]:
    if not attachments:
        return []
    resolved: list[tuple[str, bytes]] = []
    for item in attachments:
        if not isinstance(item, dict):
            raise GmailIntegrationError("Cada adjunto debe ser un objeto JSON.")
        resolved.append(_resolve_attachment_spec(item))
    return resolved


def _build_email_mime(
    *,
    to: str,
    subject: str,
    body: str,
    body_html: str | None = None,
    attachments: list[tuple[str, bytes]] | None = None,
) -> MIMEText | MIMEMultipart:
    subject_value = subject or "(sin asunto)"
    atts = attachments or []

    if not atts:
        subtype = "html" if body_html else "plain"
        mime = MIMEText(body_html or body or "", subtype)
        mime["to"] = to
        mime["subject"] = subject_value
        return mime

    msg = MIMEMultipart()
    msg["to"] = to
    msg["subject"] = subject_value

    if body_html:
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(body or "", "plain"))
        alt.attach(MIMEText(body_html, "html"))
        msg.attach(alt)
    else:
        msg.attach(MIMEText(body or "", "plain"))

    for filename, content in atts:
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        maintype, _, subtype = mime_type.partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        part = MIMEBase(maintype, subtype)
        part.set_payload(content)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)

    return msg


def send_message(
    user_id: str,
    to: str,
    subject: str,
    body: str,
    *,
    body_html: str | None = None,
    attachments: list[Any] | None = None,
) -> dict[str, Any]:
    service = _gmail_service(user_id)
    resolved_attachments = _normalize_attachments(attachments)
    mime = _build_email_mime(
        to=to,
        subject=subject,
        body=body,
        body_html=body_html,
        attachments=resolved_attachments,
    )
    encoded = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
    sent = (
        service.users()  # type: ignore[no-untyped-call]
        .messages()
        .send(userId="me", body={"raw": encoded})
        .execute()
    )
    return {"id": sent.get("id"), "thread_id": sent.get("threadId")}


def summarize_unread(user_id: str, max_results: int = 10) -> str:
    unread = list_unread(user_id, max_results=max_results)
    if not unread:
        return "No tienes correos no leidos."

    context = "\n".join(
        f"- De: {m.get('from', '')} | Asunto: {m.get('subject', '')} | Snippet: {m.get('snippet', '')}"
        for m in unread
    )

    try:
        from app.services.provider_router import route_chat

        summary = route_chat(
            (
                "Resume en español los siguientes correos no leídos en 5 viñetas máximas, "
                "priorizando urgencia y próximos pasos:\n\n"
                f"{context}"
            ),
            provider_id="deepseek",
            system_prompt="Eres un asistente de productividad y correo.",
        )
        return summary
    except Exception:
        log.exception("Fallo al resumir correos con IA; devolviendo resumen simple")
        return (
            "Resumen rápido de no leídos:\n"
            + "\n".join(f"- {m.get('subject', '(sin asunto)')}" for m in unread[:5])
        )


def get_refreshed_access_token(user_id: str) -> str:
    """Devuelve access token Google vigente (refresca si expiró)."""
    from google.auth.transport.requests import Request

    creds = _load_google_credentials(user_id)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    token = creds.token
    if not token:
        raise GmailIntegrationError("El token OAuth de Google está vacío.")
    return str(token)


def _header_map(headers: list[dict[str, Any]]) -> dict[str, str]:
    return {str(h.get("name", "")).lower(): str(h.get("value", "")) for h in headers}


def _decode_body_data(data: str) -> str:
    if not data:
        return ""
    pad = "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode(data + pad)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def _extract_body_from_payload(payload: dict[str, Any]) -> str:
    mime = str(payload.get("mimeType") or "")
    body_data = payload.get("body", {}).get("data")
    if body_data and mime.startswith("text/"):
        return _decode_body_data(str(body_data))

    parts = payload.get("parts") or []
    plain = ""
    html = ""
    for part in parts:
        pmime = str(part.get("mimeType") or "")
        if pmime == "text/plain" and not plain:
            plain = _decode_body_data(str(part.get("body", {}).get("data") or ""))
        elif pmime == "text/html" and not html:
            html = _decode_body_data(str(part.get("body", {}).get("data") or ""))
        elif part.get("parts"):
            nested = _extract_body_from_payload(part)
            if nested.strip():
                return nested
    if plain.strip():
        return plain
    if html.strip():
        import re

        return re.sub(r"<[^>]+>", " ", html)
    return ""


def _walk_attachment_parts(payload: dict[str, Any], parts_out: list[dict[str, Any]]) -> None:
    for part in payload.get("parts") or []:
        filename = str(part.get("filename") or "").strip()
        att_id = part.get("body", {}).get("attachmentId")
        if filename and att_id:
            parts_out.append(part)
        if part.get("parts"):
            _walk_attachment_parts(part, parts_out)


def _message_metadata(service: Any, msg_id: str) -> dict[str, Any]:
    detail = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=msg_id,
            format="metadata",
            metadataHeaders=["From", "Subject", "Date", "To"],
        )
        .execute()
    )
    headers = detail.get("payload", {}).get("headers", [])
    by_name = _header_map(headers)
    return {
        "id": msg_id,
        "from": by_name.get("from", ""),
        "to": by_name.get("to", ""),
        "subject": by_name.get("subject", "(sin asunto)"),
        "date": by_name.get("date", ""),
        "snippet": detail.get("snippet", ""),
    }


def list_messages(user_id: str, max_results: int = 20) -> list[dict[str, Any]]:
    service = _gmail_service(user_id)
    response = (
        service.users()
        .messages()
        .list(userId="me", maxResults=max(1, min(max_results, 50)))
        .execute()
    )
    messages = response.get("messages") or []
    items: list[dict[str, Any]] = []
    for item in messages:
        msg_id = item.get("id")
        if not msg_id:
            continue
        items.append(_message_metadata(service, str(msg_id)))
    return items


def read_message(user_id: str, message_id: str) -> str:
    service = _gmail_service(user_id)
    detail = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    headers = _header_map(detail.get("payload", {}).get("headers", []))
    body = _extract_body_from_payload(detail.get("payload", {}) or {})
    return (
        f"Asunto: {headers.get('subject', '(sin asunto)')}\n"
        f"De: {headers.get('from', '?')}\n"
        f"Fecha: {headers.get('date', '')}\n"
        f"ID: {message_id}\n\n"
        f"{body.strip() or '(sin cuerpo legible)'}"
    )


def download_attachments(
    user_id: str,
    message_id: str,
    *,
    download_dir: str = "~/Desktop/DOT Trabajos/Gmail",
) -> list[str]:
    """Descarga adjuntos de un correo al PC vía bridge (Escritorio sandbox)."""
    from app.application.agent.tools.local_files import execute_local_tool_via_bridge

    service = _gmail_service(user_id)
    detail = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    parts: list[dict[str, Any]] = []
    _walk_attachment_parts(detail.get("payload", {}) or {}, parts)
    if not parts:
        return []

    saved: list[str] = []
    dest_base = download_dir.rstrip("/\\")
    for part in parts:
        att_id = str(part.get("body", {}).get("attachmentId") or "")
        filename = str(part.get("filename") or f"adjunto_{att_id[:8]}").strip()
        if not att_id:
            continue
        att = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=att_id)
            .execute()
        )
        raw_data = str(att.get("data") or "")
        if not raw_data:
            continue
        pad = "=" * (-len(raw_data) % 4)
        content = base64.urlsafe_b64decode(raw_data + pad)
        content_b64 = base64.b64encode(content).decode("ascii")
        dest_path = f"{dest_base}/{filename}"
        result = execute_local_tool_via_bridge(
            "writeFileBytes",
            path=dest_path,
            content=content_b64,
        )
        if not result.get("ok"):
            err = str(result.get("error") or "bridge_error")
            raise GmailIntegrationError(
                f"No pude guardar «{filename}» en el Escritorio: {err}"
            )
        saved.append(str(result.get("path") or dest_path))
    return saved


def get_thread(user_id: str, thread_id: str) -> list[dict[str, Any]]:
    service = _gmail_service(user_id)
    thread = (
        service.users()
        .threads()
        .get(
            userId="me",
            id=thread_id,
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        )
        .execute()
    )
    items: list[dict[str, Any]] = []
    for msg in thread.get("messages") or []:
        msg_id = msg.get("id")
        if not msg_id:
            continue
        headers = _header_map(msg.get("payload", {}).get("headers", []))
        items.append(
            {
                "id": msg_id,
                "from": headers.get("from", ""),
                "subject": headers.get("subject", "(sin asunto)"),
                "snippet": msg.get("snippet", ""),
                "date": headers.get("date", ""),
            }
        )
    return items


def mark_read(user_id: str, message_id: str) -> None:
    service = _gmail_service(user_id)
    (
        service.users()
        .messages()
        .modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]})
        .execute()
    )


def archive(user_id: str, message_id: str) -> None:
    service = _gmail_service(user_id)
    (
        service.users()
        .messages()
        .modify(userId="me", id=message_id, body={"removeLabelIds": ["INBOX"]})
        .execute()
    )


def trash(user_id: str, message_id: str) -> None:
    service = _gmail_service(user_id)
    service.users().messages().trash(userId="me", id=message_id).execute()


def reply(
    user_id: str,
    message_id: str,
    body: str,
    *,
    attachments: list[Any] | None = None,
) -> dict[str, Any]:
    service = _gmail_service(user_id)
    original = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "Subject"],
        )
        .execute()
    )
    headers = _header_map(original.get("payload", {}).get("headers", []))
    to = headers.get("from", "")
    subject = headers.get("subject", "(sin asunto)")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    return send_message(
        user_id,
        to=to,
        subject=subject,
        body=body,
        attachments=attachments,
    )
