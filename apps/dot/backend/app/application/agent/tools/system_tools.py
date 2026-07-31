"""System tools para DOT Agent Runtime — F6e.

Clipboard, screenshots, system info, open apps, file watch, encrypt/decrypt.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import platform
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.system")

# ─── Estado para file_watch_folder ──────────────────────
_WATCH_STATE: dict[str, dict[str, str]] = {}


# ─── Helpers ────────────────────────────────────────────

def _get_desktop_path() -> str:
    """Devuelve ruta del Escritorio del usuario."""
    return str(Path.home() / "Desktop")


def _get_temp_path() -> str:
    """Devuelve ruta temporal del sistema."""
    return os.environ.get("TEMP", os.environ.get("TMP", str(Path.home())))


def _derive_fernet_key(password: str) -> bytes:
    """Deriva una clave Fernet de 32 bytes a partir de una contraseña."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


# ─── 1. clipboard_read ──────────────────────────────────

def clipboard_read_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lee el contenido del portapapeles del sistema."""
    try:
        import pyperclip

        text = pyperclip.paste()
        if not text:
            return ToolResult(ok=True, output="(portapapeles vacío)")
        preview = text if len(text) <= 4000 else text[:4000] + "…"
        return ToolResult(ok=True, output=preview)
    except ImportError:
        return ToolResult(
            ok=False,
            output="",
            error="pip install pyperclip required",
        )
    except Exception as e:
        log.warning("clipboard_read error uid=%s: %s", uid[:8] if uid else "?", e)
        return ToolResult(ok=False, output="", error=f"No pude leer el portapapeles: {e}")


# ─── 2. clipboard_write ─────────────────────────────────

def clipboard_write_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Escribe texto al portapapeles del sistema."""
    text = str(arguments.get("text") or "").strip()
    if not text:
        return ToolResult(ok=False, output="", error="Falta text para copiar al portapapeles.")

    try:
        import pyperclip

        pyperclip.copy(text)
        preview = text if len(text) <= 80 else text[:80] + "…"
        return ToolResult(ok=True, output=f"Copiado al portapapeles: {preview}")
    except ImportError:
        return ToolResult(
            ok=False,
            output="",
            error="pip install pyperclip required",
        )
    except Exception as e:
        log.warning("clipboard_write error uid=%s: %s", uid[:8] if uid else "?", e)
        return ToolResult(ok=False, output="", error=f"No pude escribir al portapapeles: {e}")


# ─── 3. screenshot_capture ──────────────────────────────

def screenshot_capture_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Captura toda la pantalla y guarda en Escritorio o ruta temporal."""
    try:
        from PIL import ImageGrab
    except ImportError:
        return ToolResult(
            ok=False,
            output="",
            error="pip install Pillow required",
        )

    try:
        img = ImageGrab.grab()
        custom_path = str(arguments.get("path") or "").strip()
        if custom_path:
            save_path = custom_path
            os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = os.path.join(_get_desktop_path(), f"screenshot_{timestamp}.png")

        img.save(save_path, "PNG")
        return ToolResult(
            ok=True,
            output=f"Captura de pantalla guardada en: {save_path}",
        )
    except Exception as e:
        log.warning("screenshot_capture error uid=%s: %s", uid[:8] if uid else "?", e)
        return ToolResult(ok=False, output="", error=f"No pude capturar pantalla: {e}")


# ─── 4. screenshot_region ───────────────────────────────

def screenshot_region_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Captura una región de la pantalla (bbox: x, y, width, height)."""
    try:
        from PIL import ImageGrab
    except ImportError:
        return ToolResult(
            ok=False,
            output="",
            error="pip install Pillow required",
        )

    try:
        x = arguments.get("x")
        y = arguments.get("y")
        width = arguments.get("width")
        height = arguments.get("height")

        if None in (x, y, width, height):
            return ToolResult(
                ok=False,
                output="",
                error="Faltan parámetros: x, y, width, height requeridos para captura de región.",
            )

        x, y, width, height = int(x), int(y), int(width), int(height)
        if width <= 0 or height <= 0:
            return ToolResult(
                ok=False,
                output="",
                error="width y height deben ser > 0.",
            )

        bbox = (x, y, x + width, y + height)
        img = ImageGrab.grab(bbox=bbox)

        custom_path = str(arguments.get("path") or "").strip()
        if custom_path:
            save_path = custom_path
            os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = os.path.join(_get_desktop_path(), f"screenshot_region_{timestamp}.png")

        img.save(save_path, "PNG")
        return ToolResult(
            ok=True,
            output=f"Captura de región ({x},{y} {width}x{height}) guardada en: {save_path}",
        )
    except Exception as e:
        log.warning("screenshot_region error uid=%s: %s", uid[:8] if uid else "?", e)
        return ToolResult(ok=False, output="", error=f"No pude capturar región: {e}")


# ─── 5. datetime_now (FREE-SK04) ────────────────────────

def datetime_now_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Devuelve fecha y hora actual; por defecto zona Venezuela (America/Caracas)."""
    tz_name = str(arguments.get("timezone") or "America/Caracas").strip()
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Caracas")
        tz_name = "America/Caracas"

    now = datetime.now(tz)
    weekday_es = (
        "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"
    )[now.weekday()]
    output = (
        f"Fecha y hora ({tz_name}): "
        f"{now.strftime('%Y-%m-%d %H:%M:%S')} ({weekday_es})"
    )
    return ToolResult(ok=True, output=output)


# ─── 6. system_info ─────────────────────────────────────

def system_info_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene información del sistema: OS, CPU, RAM, disco."""
    try:
        lines: list[str] = []

        # OS info
        uname = platform.uname()
        lines.append(f"Sistema: {uname.system} {uname.release} ({uname.version})")
        lines.append(f"Arquitectura: {uname.machine}")
        lines.append(f"Procesador: {uname.processor}")
        lines.append(f"Hostname: {uname.node}")

        # psutil (opcional)
        try:
            import psutil

            cpu_pct = psutil.cpu_percent(interval=0.3)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("C:\\")

            lines.append("")
            lines.append(f"CPU: {cpu_pct:.1f}% usado")
            lines.append(
                f"RAM: {mem.used / (1024**3):.1f} GB / {mem.total / (1024**3):.1f} GB "
                f"({mem.percent:.1f}%)"
            )
            lines.append(
                f"Disco C:: {disk.used / (1024**3):.1f} GB / {disk.total / (1024**3):.1f} GB "
                f"({disk.percent:.1f}%)"
            )
        except ImportError:
            lines.append("")
            lines.append("(psutil no instalado — sin métricas de CPU/RAM/Disco)")

        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        log.warning("system_info error uid=%s: %s", uid[:8] if uid else "?", e)
        return ToolResult(ok=False, output="", error=str(e))


# ─── 6. system_open_app ─────────────────────────────────

_SYSTEM_APPS: dict[str, str] = {
    "notepad": "notepad.exe",
    "calc": "calc.exe",
    "explorer": "explorer.exe",
    "mspaint": "mspaint.exe",
    "wordpad": "C:\\Program Files\\Windows NT\\Accessories\\wordpad.exe",
}


def system_open_app_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Abre una aplicación del sistema (allowlist: notepad, calc, explorer, mspaint, wordpad)."""
    app_name = str(arguments.get("app_name") or arguments.get("app") or "").strip().lower()
    if not app_name:
        return ToolResult(
            ok=False,
            output="",
            error="Falta app_name. Apps disponibles: notepad, calc, explorer, mspaint, wordpad.",
        )

    executable = _SYSTEM_APPS.get(app_name)
    if not executable:
        return ToolResult(
            ok=False,
            output="",
            error=(
                f"App '{app_name}' no permitida. "
                f"Solo: {', '.join(sorted(_SYSTEM_APPS.keys()))}."
            ),
        )

    try:
        if os.name == "nt":
            os.startfile(executable)
        else:
            subprocess.Popen([executable], shell=True)
        return ToolResult(ok=True, output=f"Aplicación abierta: {app_name}")
    except Exception as e:
        log.warning("system_open_app error uid=%s app=%s: %s", uid[:8] if uid else "?", app_name, e)
        return ToolResult(ok=False, output="", error=f"No pude abrir {app_name}: {e}")


# ─── 7. file_watch_folder ───────────────────────────────

def _hash_file(path: str) -> str:
    """Calcula SHA-256 de un archivo."""
    sha = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                sha.update(chunk)
        return sha.hexdigest()
    except OSError:
        return "UNREADABLE"


def _list_folder_with_hashes(folder: str) -> dict[str, str]:
    """Lista archivos en carpeta con sus hashes."""
    result: dict[str, str] = {}
    folder_path = Path(folder)
    if not folder_path.is_dir():
        return result
    try:
        for entry in folder_path.iterdir():
            if entry.is_file():
                abs_path = str(entry.resolve())
                result[entry.name] = _hash_file(abs_path)
    except PermissionError:
        pass
    return result


def file_watch_folder_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Monitorea una carpeta: guarda estado y compara con llamada anterior.

    Primera llamada: guarda snapshot.
    Segunda llamada+: compara y reporta cambios (nuevos, modificados, eliminados).
    """
    folder = str(arguments.get("folder") or arguments.get("path") or "").strip()
    if not folder:
        return ToolResult(ok=False, output="", error="Falta folder a monitorear.")

    folder_path = Path(folder).resolve()
    if not folder_path.is_dir():
        return ToolResult(
            ok=False,
            output="",
            error=f"La carpeta no existe o no es accesible: {folder}",
        )

    folder_key = str(folder_path)
    current_state = _list_folder_with_hashes(folder_key)
    previous_state = _WATCH_STATE.get(folder_key)

    _WATCH_STATE[folder_key] = current_state

    if previous_state is None:
        file_list = "\n".join(f"  {name}" for name in sorted(current_state.keys())[:50])
        total = len(current_state)
        if total > 50:
            file_list += f"\n  … y {total - 50} archivos más"
        return ToolResult(
            ok=True,
            output=(
                f"Monitoreo iniciado en: {folder_key}\n"
                f"Snapshot guardado ({total} archivos):\n{file_list or '  (vacío)'}"
            ),
        )

    added = sorted(set(current_state.keys()) - set(previous_state.keys()))
    removed = sorted(set(previous_state.keys()) - set(current_state.keys()))
    modified = sorted(
        name for name in set(current_state.keys()) & set(previous_state.keys())
        if current_state[name] != previous_state[name]
    )

    parts: list[str] = [f"Cambios detectados en: {folder_key}"]
    if added:
        parts.append(f"Nuevos ({len(added)}):")
        parts.extend(f"  + {name}" for name in added[:30])
        if len(added) > 30:
            parts.append(f"  … y {len(added) - 30} más")
    if modified:
        parts.append(f"Modificados ({len(modified)}):")
        parts.extend(f"  ~ {name}" for name in modified[:30])
        if len(modified) > 30:
            parts.append(f"  … y {len(modified) - 30} más")
    if removed:
        parts.append(f"Eliminados ({len(removed)}):")
        parts.extend(f"  - {name}" for name in removed[:30])
        if len(removed) > 30:
            parts.append(f"  … y {len(removed) - 30} más")
    if not (added or modified or removed):
        parts.append("Sin cambios desde la última verificación.")

    return ToolResult(ok=True, output="\n".join(parts))


# ─── 8. file_encrypt ────────────────────────────────────

def file_encrypt_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Encripta un archivo con contraseña usando Fernet (cryptography).

    Lee el archivo via bridge, encripta, escribe resultado.
    """
    path = str(arguments.get("path") or "").strip()
    password = str(arguments.get("password") or arguments.get("key") or "").strip()
    output_path = str(arguments.get("output_path") or "").strip()

    if not path:
        return ToolResult(ok=False, output="", error="Falta path del archivo a encriptar.")
    if not password:
        return ToolResult(ok=False, output="", error="Falta password para encriptar.")

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return ToolResult(
            ok=False,
            output="",
            error="pip install cryptography required",
        )

    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            err = raw.get("error", "error desconocido")
            return ToolResult(ok=False, output="", error=f"No pude leer el archivo: {err}")

        content = str(raw.get("content") or "")
        if not content:
            return ToolResult(ok=False, output="", error="El archivo está vacío.")

        key = _derive_fernet_key(password)
        fernet = Fernet(key)
        encrypted = fernet.encrypt(content.encode("utf-8"))
        encrypted_b64 = base64.urlsafe_b64encode(encrypted).decode("ascii")

        dest = output_path if output_path else path
        write_raw = execute_local_tool_via_bridge("writeFile", path=dest, content=encrypted_b64)
        if not write_raw.get("ok"):
            err = write_raw.get("error", "error desconocido")
            return ToolResult(ok=False, output="", error=f"No pude escribir el archivo encriptado: {err}")

        return ToolResult(
            ok=True,
            output=f"Archivo encriptado con Fernet: {dest}",
        )
    except Exception as e:
        log.warning("file_encrypt error uid=%s: %s", uid[:8] if uid else "?", e)
        return ToolResult(ok=False, output="", error=str(e))


# ─── 9. file_decrypt ────────────────────────────────────

def file_decrypt_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Desencripta un archivo Fernet con contraseña.

    Lee archivo encriptado via bridge, desencripta, escribe resultado.
    """
    path = str(arguments.get("path") or "").strip()
    password = str(arguments.get("password") or arguments.get("key") or "").strip()
    output_path = str(arguments.get("output_path") or "").strip()

    if not path:
        return ToolResult(ok=False, output="", error="Falta path del archivo a desencriptar.")
    if not password:
        return ToolResult(ok=False, output="", error="Falta password para desencriptar.")

    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError:
        return ToolResult(
            ok=False,
            output="",
            error="pip install cryptography required",
        )

    try:
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        raw = execute_local_tool_via_bridge("readFile", path=path)
        if not raw.get("ok"):
            err = raw.get("error", "error desconocido")
            return ToolResult(ok=False, output="", error=f"No pude leer el archivo: {err}")

        encrypted_b64 = str(raw.get("content") or "").strip()
        if not encrypted_b64:
            return ToolResult(ok=False, output="", error="El archivo está vacío o no es un archivo encriptado válido.")

        try:
            encrypted = base64.urlsafe_b64decode(encrypted_b64.encode("ascii"))
        except Exception:
            return ToolResult(
                ok=False,
                output="",
                error="El archivo no tiene formato de encriptación válido (base64 esperado).",
            )

        key = _derive_fernet_key(password)
        fernet = Fernet(key)

        try:
            decrypted = fernet.decrypt(encrypted).decode("utf-8")
        except InvalidToken:
            return ToolResult(
                ok=False,
                output="",
                error="Contraseña incorrecta o archivo corrupto.",
            )

        dest = output_path if output_path else path
        write_raw = execute_local_tool_via_bridge("writeFile", path=dest, content=decrypted)
        if not write_raw.get("ok"):
            err = write_raw.get("error", "error desconocido")
            return ToolResult(ok=False, output="", error=f"No pude escribir el archivo desencriptado: {err}")

        return ToolResult(
            ok=True,
            output=f"Archivo desencriptado: {dest}",
        )
    except Exception as e:
        log.warning("file_decrypt error uid=%s: %s", uid[:8] if uid else "?", e)
        return ToolResult(ok=False, output="", error=str(e))


# ─── Export ─────────────────────────────────────────────

TOOLS: list[tuple[str, Any]] = [
    ("clipboard_read", clipboard_read_handler),
    ("clipboard_write", clipboard_write_handler),
    ("screenshot_capture", screenshot_capture_handler),
    ("screenshot_region", screenshot_region_handler),
    ("datetime_now", datetime_now_handler),
    ("system_info", system_info_handler),
    ("system_open_app", system_open_app_handler),
    ("file_watch_folder", file_watch_folder_handler),
    ("file_encrypt", file_encrypt_handler),
    ("file_decrypt", file_decrypt_handler),
]
