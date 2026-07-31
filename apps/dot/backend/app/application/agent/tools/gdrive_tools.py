"""Tools Google Drive API — M2S3-B.

5 tools reales para Google Drive usando API v3 con OAuth existente de DOT:
  - drive_list: listar archivos del usuario
  - drive_download: descargar archivo a ruta local
  - drive_upload: subir archivo desde ruta local
  - drive_share: compartir archivo con otro usuario
  - drive_search: busqueda avanzada de archivos

Google Docs/Sheets/Slides se exportan automaticamente a PDF/CSV/PPTX.
Si Google OAuth no esta configurado → "requiere vincular Google en Ajustes".

Usa el mismo OAuth de Gmail (scope drive.readonly incluido al vincular Gmail).
"""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from app.application.agent.ports import ToolResult
from app.application.agent.tools.local_files import execute_local_tool_via_bridge
from app.services.gmail_service import (
    GmailIntegrationError,
    MissingGmailCredentialsError,
    get_refreshed_access_token,
)

log = logging.getLogger("dot.agent.tools.gdrive")

DRIVE_SCOPE_MISSING_USER_MESSAGE = (
    "Tu cuenta Google no tiene permiso de Drive. "
    "Ve a Configuración → Google, desvincula y vuelve a conectar."
)
GOOGLE_NOT_LINKED_USER_MESSAGE = (
    "Google no está vinculado. Conecta tu cuenta en Configuración → Google "
    "para buscar y descargar archivos de Drive."
)
GOOGLE_SESSION_EXPIRED_USER_MESSAGE = (
    "Tu sesión de Google expiró. Ve a Configuración → Google, desvincula y vuelve a conectar."
)

# ──────────────────────────────────────────────
#  Helpers: rate-limit + env
# ──────────────────────────────────────────────

_last_call: dict[str, float] = {}


def _rate_limit(tool: str, min_interval: float = 0.5) -> None:
    """Espera si es necesario para respetar rate limit."""
    now = time.time()
    last = _last_call.get(tool, 0)
    wait = min_interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_call[tool] = time.time()


def _is_drive_scope_denied(resp: httpx.Response) -> bool:
    if resp.status_code != 403:
        return False
    text = (resp.text or "").lower()
    return (
        "insufficient authentication scopes" in text
        or "access not configured" in text
        or ("scope" in text and "insufficient" in text)
    )


def _drive_http_error(resp: httpx.Response, *, file_id: str | None = None) -> str | None:
    if resp.status_code == 401:
        return GOOGLE_SESSION_EXPIRED_USER_MESSAGE
    if _is_drive_scope_denied(resp):
        return DRIVE_SCOPE_MISSING_USER_MESSAGE
    if resp.status_code == 403:
        if file_id:
            return (
                f"No tengo permiso para acceder al archivo '{file_id}' en Google Drive. "
                "Verifica que exista y que tu cuenta tenga acceso."
            )
        return DRIVE_SCOPE_MISSING_USER_MESSAGE
    return None


def _oauth_error_message(exc: Exception) -> str:
    if isinstance(exc, MissingGmailCredentialsError):
        return GOOGLE_NOT_LINKED_USER_MESSAGE
    msg = str(exc).lower()
    if "insufficient" in msg or "403" in msg or "scope" in msg:
        return DRIVE_SCOPE_MISSING_USER_MESSAGE
    return f"No pude usar Google Drive: {exc}"


def _auth_headers(uid: str) -> tuple[dict[str, str] | None, str | None]:
    """Headers con token OAuth del usuario (mismo blob que Gmail)."""
    try:
        token = get_refreshed_access_token(uid)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }, None
    except (MissingGmailCredentialsError, GmailIntegrationError) as exc:
        return None, _oauth_error_message(exc)
    except Exception as exc:
        log.warning("drive oauth uid=%s: %s", uid[:8], exc)
        return None, _oauth_error_message(exc)


def _save_bytes_to_desktop(uid: str, relative_path: str, content: bytes) -> tuple[str | None, str | None]:
    """Persiste bytes en el PC del usuario vía bridge Electron."""
    _ = uid
    content_b64 = base64.b64encode(content).decode("ascii")
    result = execute_local_tool_via_bridge(
        "writeFileBytes",
        path=relative_path,
        content=content_b64,
    )
    if result.get("ok"):
        return str(result.get("path") or relative_path), None
    err = str(result.get("error") or "bridge_error")
    human = {
        "bridge_secret_not_configured": "Abre la app DOT en tu PC para guardar archivos.",
        "bridge_unreachable": "No pude llegar a tu PC. ¿Está abierta la app DOT?",
        "bridge_unauthorized": "El puente local rechazó la conexión.",
    }.get(err, err)
    return None, human


# ──────────────────────────────────────────────
#  Constantes de exportacion Google Docs
# ──────────────────────────────────────────────

_GOOGLE_EXPORT_MIME: dict[str, str] = {
    "application/vnd.google-apps.document": "application/pdf",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.google-apps.drawing": "application/pdf",
}

_EXPORT_EXTENSION: dict[str, str] = {
    "application/pdf": ".pdf",
    "text/csv": ".csv",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}


def _human_size(size_bytes: int | str) -> str:
    """Convierte bytes a formato legible."""
    try:
        size = int(size_bytes) if size_bytes else 0
    except (ValueError, TypeError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _resolve_destination_path(destination: str, file_name: str, ext: str) -> str:
    dest = destination.strip() or "~/Desktop"
    name_with_ext = file_name if Path(file_name).suffix else f"{file_name}{ext}"
    if dest.endswith(("/", "\\")):
        return f"{dest.rstrip('/\\\\')}/{name_with_ext}"
    lower = dest.lower()
    if lower in {"desktop", "escritorio", "~/desktop", "~/escritorio"}:
        return f"~/Desktop/{name_with_ext}"
    if not Path(dest).suffix and not dest.endswith(ext):
        return f"{dest.rstrip('/\\\\')}/{name_with_ext}"
    return dest


def drive_list_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lista los archivos de Google Drive del usuario. Permite filtrar por nombre."""
    try:
        headers, err_token = _auth_headers(uid)
        if err_token or not headers:
            return ToolResult(ok=False, output="", error=err_token or "Sin OAuth Google.")

        query_filter = str(arguments.get("query") or "").strip()
        limit = min(int(arguments.get("limit") or 20), 100)

        _rate_limit("drive_list")
        url = "https://www.googleapis.com/drive/v3/files"
        params: dict[str, str | int] = {
            "pageSize": limit,
            "fields": "files(id,name,mimeType,size,modifiedTime,webViewLink,owners)",
            "orderBy": "modifiedTime desc",
            "spaces": "drive",
        }

        # Construir query de filtro si hay texto
        q_parts: list[str] = ["trashed = false"]
        if query_filter:
            q_parts.append(f"name contains '{query_filter}'")
        params["q"] = " and ".join(q_parts)

        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error=GOOGLE_SESSION_EXPIRED_USER_MESSAGE,
                )
            drive_err = _drive_http_error(resp)
            if drive_err:
                return ToolResult(ok=False, output="", error=drive_err)
            resp.raise_for_status()
            data = resp.json()

        files = data.get("files", [])
        if not files:
            msg = f"📁 No se encontraron archivos en Google Drive" + (f" con nombre '{query_filter}'." if query_filter else ".")
            return ToolResult(ok=True, output=msg)

        lines = [
            f"📁 Google Drive — "
            + (f"'{query_filter}' " if query_filter else "")
            + f"({len(files)} archivos):\n"
        ]
        for i, f in enumerate(files, 1):
            name = (f.get("name") or "Sin nombre")[:80]
            mime = f.get("mimeType", "?")
            size = _human_size(f.get("size", 0))
            modified = (f.get("modifiedTime") or "")[:19].replace("T", " ")
            link = f.get("webViewLink", "")
            file_id = f.get("id", "?")

            # Tipo amigable
            type_icon = "📄"
            if "folder" in mime:
                type_icon = "📁"
            elif "spreadsheet" in mime:
                type_icon = "📊"
            elif "document" in mime:
                type_icon = "📝"
            elif "presentation" in mime:
                type_icon = "📽️"
            elif "image" in mime:
                type_icon = "🖼️"
            elif "video" in mime:
                type_icon = "🎬"
            elif "pdf" in mime:
                type_icon = "📕"

            lines.append(
                f"{i}. {type_icon} {name}\n"
                f"   ID: {file_id} | {size} | {modified}\n"
                f"   {link}"
            )

        return ToolResult(
            ok=True,
            output="\n".join(lines) + "\n\nFuente: Google Drive API v3",
        )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al listar archivos: {e}")
    except Exception as e:
        log.exception("drive_list uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  2. drive_download — Descargar archivo
# ──────────────────────────────────────────────

def drive_download_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Descarga un archivo de Google Drive al Escritorio del usuario (bridge)."""
    try:
        headers, err_token = _auth_headers(uid)
        if err_token or not headers:
            return ToolResult(ok=False, output="", error=err_token or "Sin OAuth Google.")

        file_id = str(arguments.get("file_id") or "").strip()
        if not file_id:
            return ToolResult(ok=False, output="", error="Falta file_id del archivo a descargar.")

        destination = str(arguments.get("destination") or "~/Desktop").strip()

        _rate_limit("drive_meta")
        meta_url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
        meta_params = {"fields": "name,mimeType,size"}

        with httpx.Client(timeout=15) as client:
            meta_resp = client.get(meta_url, params=meta_params, headers=headers)
            if meta_resp.status_code == 404:
                return ToolResult(
                    ok=False, output="",
                    error=f"Archivo con ID '{file_id}' no encontrado en Google Drive.",
                )
            if meta_resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error=GOOGLE_SESSION_EXPIRED_USER_MESSAGE,
                )
            drive_err = _drive_http_error(meta_resp, file_id=file_id)
            if drive_err:
                return ToolResult(ok=False, output="", error=drive_err)
            meta_resp.raise_for_status()
            meta = meta_resp.json()

        mime_type = meta.get("mimeType", "")
        file_name = meta.get("name", file_id)
        is_google_doc = mime_type in _GOOGLE_EXPORT_MIME

        _rate_limit("drive_download")
        with httpx.Client(timeout=60) as client:
            if is_google_doc:
                export_mime = _GOOGLE_EXPORT_MIME[mime_type]
                ext = _EXPORT_EXTENSION.get(export_mime, ".pdf")
                download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export"
                download_params = {"mimeType": export_mime}
            else:
                ext = Path(str(file_name)).suffix or ""
                download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
                download_params = {"alt": "media"}

            dl_resp = client.get(
                download_url,
                params=download_params,
                headers=headers,
            )
            if dl_resp.status_code != 200:
                drive_err = _drive_http_error(dl_resp, file_id=file_id)
                if drive_err:
                    return ToolResult(ok=False, output="", error=drive_err)
                err_body = ""
                try:
                    err_body = dl_resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al descargar archivo ({dl_resp.status_code}): {err_body}",
                )

            content = dl_resp.content

        dest_path = _resolve_destination_path(destination, str(file_name), ext)
        saved_path, save_err = _save_bytes_to_desktop(uid, dest_path, content)
        if save_err or not saved_path:
            return ToolResult(ok=False, output="", error=save_err or "No se pudo guardar en el Escritorio.")

        return ToolResult(
            ok=True,
            output=(
                f"⬇️ Archivo descargado con exito:\n"
                f"Nombre: {file_name}{(' → ' + ext) if is_google_doc else ''}\n"
                f"Tipo: {mime_type}\n"
                f"Tamaño: {_human_size(len(content))}\n"
                f"Guardado en: {saved_path}\n"
                f"Fuente: Google Drive API v3"
            ),
        )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al descargar archivo: {e}")
    except Exception as e:
        log.exception("drive_download uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  3. drive_upload — Subir archivo
# ──────────────────────────────────────────────

def drive_upload_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Sube un archivo local a Google Drive. Opcionalmente dentro de una carpeta especifica."""
    try:
        headers, err_token = _auth_headers(uid)
        if err_token or not headers:
            return ToolResult(ok=False, output="", error=err_token or "Sin OAuth Google.")

        filepath = str(arguments.get("filepath") or "").strip()
        if not filepath:
            return ToolResult(ok=False, output="", error="Falta filepath del archivo local a subir.")

        folder_id = str(arguments.get("folder_id") or "").strip()

        from app.services.gmail_service import _read_sandbox_path_bytes

        try:
            file_content = _read_sandbox_path_bytes(filepath)
        except GmailIntegrationError as exc:
            return ToolResult(ok=False, output="", error=str(exc))

        file_name = Path(filepath).name or "archivo"

        # Detectar MIME type basico por extension
        import mimetypes
        mime_type, _ = mimetypes.guess_type(file_name)
        if not mime_type:
            mime_type = "application/octet-stream"

        _rate_limit("drive_upload")
        upload_url = "https://www.googleapis.com/upload/drive/v3/files"
        params = {"uploadType": "multipart"}

        # Construir multipart upload
        metadata = {"name": file_name}
        if folder_id:
            metadata["parents"] = [folder_id]

        boundary = f"__nordik_drive_upload_{int(time.time())}__"

        body_parts = [
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{__import__('json').dumps(metadata)}\r\n",
            f"--{boundary}\r\n"
            f"Content-Type: {mime_type}\r\n\r\n",
        ]
        body_bytes = body_parts[0].encode("utf-8") + file_content + f"\r\n--{boundary}--\r\n".encode("utf-8")

        upload_headers = dict(headers)
        upload_headers["Content-Type"] = f"multipart/related; boundary={boundary}"

        with httpx.Client(timeout=60) as client:
            resp = client.post(
                upload_url,
                params=params,
                content=body_bytes,
                headers=upload_headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                uploaded_id = data.get("id", "?")
                uploaded_name = data.get("name", file_name)
                web_link = f"https://drive.google.com/file/d/{uploaded_id}/view"
                return ToolResult(
                    ok=True,
                    output=(
                        f"⬆️ Archivo subido con exito:\n"
                        f"Nombre: {uploaded_name}\n"
                        f"ID: {uploaded_id}\n"
                        f"Tamaño: {_human_size(len(file_content))}\n"
                        f"Link: {web_link}\n"
                        f"Fuente: Google Drive API v3"
                    ),
                )
            elif resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error="Token de Google invalido o expirado. Solicita al usuario que reconfigure Google Drive en Ajustes.",
                )
            elif resp.status_code == 403:
                return ToolResult(
                    ok=False, output="",
                    error="Permiso denegado. El token necesita scope 'https://www.googleapis.com/auth/drive.file' para subir archivos.",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:400]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al subir archivo ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al subir archivo: {e}")
    except Exception as e:
        log.exception("drive_upload uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  4. drive_share — Compartir archivo
# ──────────────────────────────────────────────

def drive_share_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Comparte un archivo/carpeta de Google Drive con otro usuario por email."""
    try:
        headers, err_token = _auth_headers(uid)
        if err_token or not headers:
            return ToolResult(ok=False, output="", error=err_token or "Sin OAuth Google.")

        file_id = str(arguments.get("file_id") or "").strip()
        if not file_id:
            return ToolResult(ok=False, output="", error="Falta file_id del archivo a compartir.")

        email = str(arguments.get("email") or "").strip()
        if not email:
            return ToolResult(ok=False, output="", error="Falta email del destinatario.")

        role = str(arguments.get("role") or "reader").strip().lower()
        valid_roles = {"reader", "commenter", "writer", "owner"}
        if role not in valid_roles:
            return ToolResult(
                ok=False, output="",
                error=f"Rol invalido: '{role}'. Usa: reader, commenter, writer o owner.",
            )

        _rate_limit("drive_share")
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}/permissions"
        params = {"sendNotificationEmail": "true"}

        body = {
            "role": role,
            "type": "user",
            "emailAddress": email,
        }

        with httpx.Client(timeout=15) as client:
            resp = client.post(
                url,
                params=params,
                json=body,
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                perm_id = data.get("id", "?")
                role_names = {
                    "reader": "Lector 👁️",
                    "commenter": "Comentador 💬",
                    "writer": "Editor ✏️",
                    "owner": "Propietario 👑",
                }
                return ToolResult(
                    ok=True,
                    output=(
                        f"✅ Archivo compartido con exito:\n"
                        f"Archivo ID: {file_id}\n"
                        f"Compartido con: {email}\n"
                        f"Rol: {role_names.get(role, role)}\n"
                        f"Permiso ID: {perm_id}\n"
                        f"Se envio notificacion por email.\n"
                        f"Fuente: Google Drive API v3"
                    ),
                )
            elif resp.status_code == 404:
                return ToolResult(
                    ok=False, output="",
                    error=f"Archivo con ID '{file_id}' no encontrado en Google Drive.",
                )
            elif resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error="Token de Google invalido o expirado. Solicita al usuario que reconfigure Google Drive en Ajustes.",
                )
            elif resp.status_code == 403:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Permiso denegado al compartir. Asegurate de ser propietario o editor del archivo. {err_body}",
                )
            else:
                err_body = ""
                try:
                    err_body = resp.text[:300]
                except Exception:
                    pass
                return ToolResult(
                    ok=False, output="",
                    error=f"Error al compartir archivo ({resp.status_code}): {err_body}",
                )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al compartir archivo: {e}")
    except Exception as e:
        log.exception("drive_share uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  5. drive_search — Busqueda avanzada
# ──────────────────────────────────────────────

def drive_search_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Busca archivos en Google Drive con filtros avanzados: nombre, tipo MIME y carpeta."""
    try:
        headers, err_token = _auth_headers(uid)
        if err_token or not headers:
            return ToolResult(ok=False, output="", error=err_token or "Sin OAuth Google.")

        name = str(arguments.get("name") or "").strip()
        mime_type = str(arguments.get("mime_type") or "").strip()
        folder_id = str(arguments.get("folder_id") or "").strip()
        limit = min(int(arguments.get("limit") or 20), 100)

        if not name and not mime_type and not folder_id:
            return ToolResult(
                ok=False, output="",
                error="Especifica al menos un filtro: name, mime_type o folder_id.",
            )

        _rate_limit("drive_search")
        url = "https://www.googleapis.com/drive/v3/files"
        params: dict[str, str | int] = {
            "pageSize": limit,
            "fields": "files(id,name,mimeType,size,modifiedTime,webViewLink,parents)",
            "orderBy": "modifiedTime desc",
            "spaces": "drive",
        }

        # Construir query de Drive API
        q_parts: list[str] = ["trashed = false"]
        if name:
            q_parts.append(f"name contains '{name}'")
        if mime_type:
            q_parts.append(f"mimeType = '{mime_type}'")
        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")
        params["q"] = " and ".join(q_parts)

        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code == 401:
                return ToolResult(
                    ok=False, output="",
                    error=GOOGLE_SESSION_EXPIRED_USER_MESSAGE,
                )
            drive_err = _drive_http_error(resp)
            if drive_err:
                return ToolResult(ok=False, output="", error=drive_err)
            resp.raise_for_status()
            data = resp.json()

        files = data.get("files", [])

        # Construir descripcion de filtros activos
        filters_desc: list[str] = []
        if name:
            filters_desc.append(f"nombre='{name}'")
        if mime_type:
            filters_desc.append(f"tipo='{mime_type}'")
        if folder_id:
            filters_desc.append(f"carpeta='{folder_id}'")

        if not files:
            return ToolResult(
                ok=True,
                output=f"🔍 No se encontraron archivos con los filtros: {', '.join(filters_desc)}.",
            )

        lines = [
            f"🔍 Google Drive — {', '.join(filters_desc)} ({len(files)} resultados):\n"
        ]
        for i, f in enumerate(files, 1):
            name_f = (f.get("name") or "Sin nombre")[:80]
            mime = f.get("mimeType", "?")
            size = _human_size(f.get("size", 0))
            modified = (f.get("modifiedTime") or "")[:19].replace("T", " ")
            link = f.get("webViewLink", "")
            file_id = f.get("id", "?")

            # Tipo amigable
            type_icon = "📄"
            if "folder" in mime:
                type_icon = "📁"
            elif "spreadsheet" in mime:
                type_icon = "📊"
            elif "document" in mime:
                type_icon = "📝"
            elif "presentation" in mime:
                type_icon = "📽️"
            elif "image" in mime:
                type_icon = "🖼️"
            elif "video" in mime:
                type_icon = "🎬"
            elif "pdf" in mime:
                type_icon = "📕"

            lines.append(
                f"{i}. {type_icon} {name_f}\n"
                f"   ID: {file_id} | {size} | {modified}\n"
                f"   {link}"
            )

        return ToolResult(
            ok=True,
            output="\n".join(lines) + "\n\nFuente: Google Drive API v3",
        )

    except httpx.HTTPError as e:
        return ToolResult(ok=False, output="", error=f"Error de red al buscar archivos: {e}")
    except Exception as e:
        log.exception("drive_search uid=%s: %s", uid[:8], e)
        return ToolResult(ok=False, output="", error=f"Error inesperado: {e}")


# ──────────────────────────────────────────────
#  TOOLS registry
# ──────────────────────────────────────────────

TOOLS = [
    ("drive_list", drive_list_handler),
    ("drive_download", drive_download_handler),
    ("drive_upload", drive_upload_handler),
    ("drive_share", drive_share_handler),
    ("drive_search", drive_search_handler),
]

# ──────────────────────────────────────────────
#  TOOL_SPECS — esquemas de parametros
# ──────────────────────────────────────────────

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "drive_list": {
        "description": "Lista los archivos de Google Drive del usuario. Permite filtrar por nombre.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto para filtrar archivos por nombre (opcional). Si no se especifica, lista todos.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Numero maximo de archivos a listar (default 20, max 100)",
                },
            },
        },
        "category": "storage",
        "capability": "B",
    },
    "drive_download": {
        "description": "Descarga un archivo de Google Drive al Escritorio del usuario. Google Docs/Sheets/Slides se exportan automaticamente a PDF/CSV/PPTX.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "ID del archivo en Google Drive. Se obtiene de drive_list o drive_search.",
                },
                "destination": {
                    "type": "string",
                    "description": "Ruta en el PC (ej: ~/Desktop o ~/Desktop/informe.pdf). Default: ~/Desktop",
                },
            },
            "required": ["file_id"],
        },
        "category": "storage",
        "capability": "B",
    },
    "drive_upload": {
        "description": "Sube un archivo local a Google Drive. Opcionalmente dentro de una carpeta especifica.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Ruta local del archivo a subir (ej: 'C:\\Users\\Usuario\\Desktop\\informe.pdf')",
                },
                "folder_id": {
                    "type": "string",
                    "description": "ID de la carpeta de Google Drive donde subir el archivo (opcional). Si no se especifica, se sube a la raiz.",
                },
            },
            "required": ["filepath"],
        },
        "category": "storage",
        "capability": "B",
    },
    "drive_share": {
        "description": "Comparte un archivo o carpeta de Google Drive con otro usuario por email. Envia notificacion automatica.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "ID del archivo o carpeta a compartir.",
                },
                "email": {
                    "type": "string",
                    "description": "Email del destinatario (debe ser cuenta Google)",
                },
                "role": {
                    "type": "string",
                    "description": "Rol del destinatario: 'reader' (solo ver), 'commenter' (comentar), 'writer' (editar), 'owner' (transferir propiedad). Default: 'reader'.",
                },
            },
            "required": ["file_id", "email"],
        },
        "category": "storage",
        "capability": "B",
    },
    "drive_search": {
        "description": "Busqueda avanzada en Google Drive por nombre, tipo de archivo y carpeta.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nombre del archivo a buscar (busqueda parcial, ej: 'informe')",
                },
                "mime_type": {
                    "type": "string",
                    "description": "Tipo MIME para filtrar (ej: 'application/pdf', 'application/vnd.google-apps.spreadsheet', 'image/png'). Lista completa: https://developers.google.com/drive/api/guides/mime-types",
                },
                "folder_id": {
                    "type": "string",
                    "description": "ID de la carpeta donde buscar (solo archivos dentro de esa carpeta)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Numero maximo de resultados (default 20, max 100)",
                },
            },
        },
        "category": "storage",
        "capability": "B",
    },
}

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    name: spec["parameters_schema"] for name, spec in TOOL_SPECS.items()
}
