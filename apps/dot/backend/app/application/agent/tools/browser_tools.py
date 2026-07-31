"""Browser tools potentes (capa B) — navigate/extract/click/type/wait/price + 15 ops CDP nuevas (M1S2-A)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

import httpx

from app.application.agent.browser_uid_context import get_browser_tool_uid
from app.application.agent.ports import ToolResult
from app.settings import settings

log = logging.getLogger("dot.agent.tools.browser")


def _resolve_browser_uid(explicit_uid: str | None = None) -> str | None:
    """Uid efectivo: argumento explícito, payload del bridge o contexto de ejecución."""
    if explicit_uid:
        return explicit_uid
    return get_browser_tool_uid()


def _browser_bridge_allowed(uid: str | None) -> tuple[bool, str]:
    """Evalúa si el bridge CDP puede usarse para este usuario.

    Prioridad:
      1. Política del usuario (Config → Privacidad) — gana sobre BROWSER_AGENT_ENABLED.
      2. Flag global BROWSER_AGENT_ENABLED — fallback legacy / entornos de desarrollo.
      3. Si ninguno permite → mensaje en español para activar en Configuración.
    """
    from app.services.tool_policy_service import (
        BROWSER_WEB_DISABLED_MESSAGE,
        is_browser_web_enabled,
    )

    effective_uid = _resolve_browser_uid(uid)
    if effective_uid and is_browser_web_enabled(effective_uid):
        return True, ""

    if settings.browser_agent_enabled:
        return True, ""

    return False, BROWSER_WEB_DISABLED_MESSAGE


# ---------------------------------------------------------------------------
# BR06 — ERROR HANDLING: códigos, clasificación y sugerencias de recuperación
# ---------------------------------------------------------------------------

class BrowserErrorCode(IntEnum):
    """Códigos canónicos de error del browser bridge (CDP/red/configuración)."""
    UNKNOWN = 0
    BRIDGE_UNREACHABLE = 1001
    BRIDGE_UNAUTHORIZED = 1002
    BRIDGE_SECRET_NOT_CONFIGURED = 1003
    BRIDGE_DISABLED = 1004
    TIMEOUT = 2001
    NAVIGATION_FAILED = 2002
    NAVIGATION_TIMEOUT = 2003
    SELECTOR_NOT_FOUND = 3001
    CLICK_FAILED = 3002
    TYPE_FAILED = 3003
    FILL_FAILED = 3004
    HOVER_FAILED = 3005
    SCROLL_FAILED = 3006
    PRESS_KEY_FAILED = 3007
    SELECT_FAILED = 3008
    UPLOAD_FAILED = 3009
    PRICE_DETECTION_FAILED = 3010
    PDF_FAILED = 3011
    SCREENSHOT_FAILED = 3012
    EXTRACT_FAILED = 3013
    EXECUTE_JS_FAILED = 3014
    COOKIE_FAILED = 3015
    NETWORK_INTERCEPT_FAILED = 3016
    SESSION_FAILED = 4001
    SESSION_NOT_FOUND = 4002
    SESSION_OPEN_FAILED = 4003
    SESSION_CLOSE_FAILED = 4004
    INVALID_RESPONSE = 5001
    AGENT_DISABLED = 5002
    SERVER_ERROR = 5003


# Mapeo de substrings de error → BrowserErrorCode
_ERROR_SUBSTR_MAP: list[tuple[str, BrowserErrorCode]] = [
    ("bridge_unreachable", BrowserErrorCode.BRIDGE_UNREACHABLE),
    ("bridge_unauthorized", BrowserErrorCode.BRIDGE_UNAUTHORIZED),
    ("bridge_secret_not_configured", BrowserErrorCode.BRIDGE_SECRET_NOT_CONFIGURED),
    ("browser_agent_deshabilitado", BrowserErrorCode.BRIDGE_DISABLED),
    # Específicos antes que generales (orden importa)
    ("open_session", BrowserErrorCode.SESSION_OPEN_FAILED),
    ("close_session", BrowserErrorCode.SESSION_CLOSE_FAILED),
    ("session", BrowserErrorCode.SESSION_FAILED),
    ("navigate_failed", BrowserErrorCode.NAVIGATION_FAILED),
    ("wait", BrowserErrorCode.TIMEOUT),
    ("timeout", BrowserErrorCode.NAVIGATION_TIMEOUT),
    ("selector", BrowserErrorCode.SELECTOR_NOT_FOUND),
    ("click_failed", BrowserErrorCode.CLICK_FAILED),
    ("type_failed", BrowserErrorCode.TYPE_FAILED),
    ("fill_failed", BrowserErrorCode.FILL_FAILED),
    ("hover_failed", BrowserErrorCode.HOVER_FAILED),
    ("scroll_failed", BrowserErrorCode.SCROLL_FAILED),
    ("press_key_failed", BrowserErrorCode.PRESS_KEY_FAILED),
    ("select_failed", BrowserErrorCode.SELECT_FAILED),
    ("upload", BrowserErrorCode.UPLOAD_FAILED),
    ("price_failed", BrowserErrorCode.PRICE_DETECTION_FAILED),
    ("pdf_failed", BrowserErrorCode.PDF_FAILED),
    ("screenshot_failed", BrowserErrorCode.SCREENSHOT_FAILED),
    ("extract_failed", BrowserErrorCode.EXTRACT_FAILED),
    ("execute_js_failed", BrowserErrorCode.EXECUTE_JS_FAILED),
    ("cookie", BrowserErrorCode.COOKIE_FAILED),
    ("network_intercept", BrowserErrorCode.NETWORK_INTERCEPT_FAILED),
    ("invalid_bridge_response", BrowserErrorCode.INVALID_RESPONSE),
    ("agent_disabled", BrowserErrorCode.AGENT_DISABLED),
    ("5", BrowserErrorCode.SERVER_ERROR),
]


@dataclass
class _BrowserErrorInfo:
    """Información estructurada de un error del browser bridge."""
    code: BrowserErrorCode
    raw_error: str
    suggestion: str = ""


def _classify_browser_error(error_str: str) -> _BrowserErrorInfo:
    """Clasifica un string de error del bridge en un código canónico con sugerencia."""
    error_lower = error_str.lower().replace(" ", "_")
    for substr, code in _ERROR_SUBSTR_MAP:
        if substr in error_lower:
            return _BrowserErrorInfo(code=code, raw_error=error_str, suggestion=_suggest_recovery(code))
    return _BrowserErrorInfo(
        code=BrowserErrorCode.UNKNOWN,
        raw_error=error_str,
        suggestion=_suggest_recovery(BrowserErrorCode.UNKNOWN),
    )


def _suggest_recovery(code: BrowserErrorCode) -> str:
    """Devuelve una sugerencia de recuperación para un código de error conocido."""
    suggestions: dict[BrowserErrorCode, str] = {
        BrowserErrorCode.BRIDGE_UNREACHABLE:
            "Abre la app de escritorio DOT e inténtalo de nuevo.",
        BrowserErrorCode.BRIDGE_UNAUTHORIZED:
            "No pude conectar con la app de escritorio. Ciérrala y ábrela de nuevo.",
        BrowserErrorCode.BRIDGE_SECRET_NOT_CONFIGURED:
            "Abre la app de escritorio DOT e inténtalo de nuevo.",
        BrowserErrorCode.BRIDGE_DISABLED:
            "Activa 'DOT puede usar webs' en Configuración → Privacidad.",
        BrowserErrorCode.TIMEOUT:
            "La operación excedió el tiempo de espera. Aumenta timeout_ms o verifica conectividad.",
        BrowserErrorCode.NAVIGATION_TIMEOUT:
            "La página tardó demasiado en cargar. Intenta con una URL más simple o verifica red.",
        BrowserErrorCode.NAVIGATION_FAILED:
            "No se pudo navegar a la URL. Verifica que la URL sea válida y accesible.",
        BrowserErrorCode.SELECTOR_NOT_FOUND:
            "No encontré ese elemento en la página. Pide otro dato o prueba con la página completa.",
        BrowserErrorCode.CLICK_FAILED:
            "No se pudo hacer clic en el elemento. Verifica que el selector sea correcto y el elemento esté visible.",
        BrowserErrorCode.TYPE_FAILED:
            "No se pudo escribir en el campo. Asegúrate de que sea un input/textarea editable.",
        BrowserErrorCode.FILL_FAILED:
            "No se pudo rellenar el campo del formulario. Verifica el selector y que el campo esté habilitado.",
        BrowserErrorCode.HOVER_FAILED:
            "No se pudo hacer hover sobre el elemento. Verifica que el selector sea correcto.",
        BrowserErrorCode.SCROLL_FAILED:
            "No se pudo hacer scroll. La página podría no tener scroll en esa dirección.",
        BrowserErrorCode.PRESS_KEY_FAILED:
            "No se pudo presionar la tecla. Verifica el nombre de la tecla (enter, tab, escape, etc.).",
        BrowserErrorCode.SELECT_FAILED:
            "No se pudo seleccionar la opción. Verifica que el <select> y la opción existan.",
        BrowserErrorCode.UPLOAD_FAILED:
            "No se pudo subir el archivo. Verifica que la ruta sea válida y el input sea de tipo file.",
        BrowserErrorCode.PRICE_DETECTION_FAILED:
            "No encontré un precio claro en esa página. Pide otro enlace o describe qué buscas.",
        BrowserErrorCode.PDF_FAILED:
            "No se pudo generar el PDF. La página podría estar vacía o no haber terminado de cargar.",
        BrowserErrorCode.SCREENSHOT_FAILED:
            "No se pudo capturar el screenshot. Verifica que la página esté completamente cargada.",
        BrowserErrorCode.EXTRACT_FAILED:
            "No se pudo extraer texto de la página. La página podría estar vacía o no haber cargado.",
        BrowserErrorCode.EXECUTE_JS_FAILED:
            "El código JavaScript falló. Revisa la sintaxis y que el contexto de la página sea el correcto.",
        BrowserErrorCode.COOKIE_FAILED:
            "No se pudieron obtener/establecer las cookies. Verifica la URL y formato de cookies.",
        BrowserErrorCode.NETWORK_INTERCEPT_FAILED:
            "No se pudo interceptar el tráfico de red. Intenta iniciar la captura de nuevo.",
        BrowserErrorCode.SESSION_FAILED:
            "Error de sesión. La sesión podría haber expirado o no existir.",
        BrowserErrorCode.SESSION_NOT_FOUND:
            "Sesión no encontrada. Abre una nueva sesión con browser_open.",
        BrowserErrorCode.SESSION_OPEN_FAILED:
            "No se pudo abrir la sesión. Verifica que la URL sea válida y el bridge esté funcionando.",
        BrowserErrorCode.SESSION_CLOSE_FAILED:
            "No se pudo cerrar la sesión. Puede que ya estuviera cerrada.",
        BrowserErrorCode.INVALID_RESPONSE:
            "El bridge devolvió una respuesta inesperada. Reinicia Electron o verifica la versión del bridge.",
        BrowserErrorCode.SERVER_ERROR:
            "Error del servidor bridge (5xx). Puede ser un error temporal — reintenta.",
        BrowserErrorCode.AGENT_DISABLED:
            "Activa 'DOT puede usar webs' en Configuración → Privacidad.",
        BrowserErrorCode.UNKNOWN:
            "Error desconocido. Revisa los logs del backend y del bridge para más detalles.",
    }
    return suggestions.get(code, suggestions[BrowserErrorCode.UNKNOWN])


# ---------------------------------------------------------------------------
# BR02 — RETRY LOGIC: _bridge_browser con reintentos y backoff exponencial
# ---------------------------------------------------------------------------

_BRIDGE_RETRY_MAX = 3
_BRIDGE_RETRY_BACKOFF_BASE = 1.0


def _is_retryable_error(error: Exception, status_code: int | None = None) -> bool:
    """Determina si un error del bridge es reintentable."""
    if isinstance(error, httpx.ConnectError):
        return True
    if status_code is not None and status_code >= 500:
        return True
    if isinstance(error, httpx.TimeoutException):
        return True
    return False


def _bridge_browser_with_retry(
    operation: str,
    max_retries: int = _BRIDGE_RETRY_MAX,
    backoff_base: float = _BRIDGE_RETRY_BACKOFF_BASE,
    **fields: Any,
) -> dict[str, Any]:
    """Ejecuta _bridge_browser con reintentos y backoff exponencial.

    Solo reintenta en ConnectError, TimeoutException y respuestas 5xx.
    """
    last_error: dict[str, Any] | None = None
    last_exception: Exception | None = None

    for attempt in range(1, max_retries + 2):  # intento 1..max_retries+1
        try:
            result = _bridge_browser(operation, **fields)
            if not result.get("ok") and isinstance(result.get("error"), str):
                error_str = str(result["error"])
                if "5" in error_str[:3] or "server_error" in error_str.lower():
                    if attempt <= max_retries:
                        wait_s = backoff_base * (2 ** (attempt - 1))
                        log.warning(
                            "bridge retry %d/%d para %s tras error 5xx: %s (esperando %.1fs)",
                            attempt, max_retries, operation, error_str, wait_s,
                        )
                        time.sleep(wait_s)
                        last_error = result
                        continue
            return result
        except httpx.ConnectError as e:
            last_exception = e
            if attempt <= max_retries:
                wait_s = backoff_base * (2 ** (attempt - 1))
                log.warning(
                    "bridge retry %d/%d para %s tras ConnectError (esperando %.1fs)",
                    attempt, max_retries, operation, wait_s,
                )
                time.sleep(wait_s)
                continue
        except httpx.TimeoutException as e:
            last_exception = e
            if attempt <= max_retries:
                wait_s = backoff_base * (2 ** (attempt - 1))
                log.warning(
                    "bridge retry %d/%d para %s tras TimeoutException (esperando %.1fs)",
                    attempt, max_retries, operation, wait_s,
                )
                time.sleep(wait_s)
                continue
        except Exception as e:
            log.warning("browser bridge falló en intento %d: %s", attempt, e)
            return {"ok": False, "error": str(e)}
        break

    if last_error is not None:
        return last_error
    if last_exception is not None:
        return {"ok": False, "error": f"bridge_unreachable_after_{max_retries}_retries"}
    return {"ok": False, "error": "unknown_bridge_error"}


def _bridge_browser(operation: str, **fields: Any) -> dict[str, Any]:
    payload_uid = fields.get("uid")
    request_uid = payload_uid if isinstance(payload_uid, str) and payload_uid else None
    allowed, deny_message = _browser_bridge_allowed(request_uid)
    if not allowed:
        return {"ok": False, "error": deny_message}

    secret = settings.whatsapp_bridge_secret.strip()
    if not secret and settings.testing.strip() != "1":
        return {"ok": False, "error": "bridge_secret_not_configured"}

    url_bridge = (
        f"{(settings.whatsapp_bridge_url or 'http://127.0.0.1:18790').rstrip('/')}"
        f"/v1/tools/execute"
    )
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Bridge-Secret"] = secret
    payload: dict[str, Any] = {"operation": operation, **fields}
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url_bridge, json=payload, headers=headers)
            if resp.status_code == 401:
                return {"ok": False, "error": "bridge_unauthorized"}
            data = resp.json() if resp.content else {}
            return data if isinstance(data, dict) else {"ok": False, "error": "invalid_bridge_response"}
    except httpx.ConnectError:
        return {"ok": False, "error": "bridge_unreachable"}
    except Exception as e:
        log.warning("browser bridge falló: %s", e)
        return {"ok": False, "error": str(e)}


def _err(raw: dict[str, Any], fallback: str) -> ToolResult:
    from app.services.error_messages import sanitize_user_message

    err = str(raw.get("error") or raw.get("message") or fallback)
    error_info = _classify_browser_error(err)
    if error_info.suggestion:
        err = f"{err}\nSugerencia: {error_info.suggestion}"
    return ToolResult(ok=False, output="", error=sanitize_user_message(err))


# ---------------------------------------------------------------------------
# BR03 — SESSION MANAGEMENT: tracking, list, close_all, auto-cleanup
# ---------------------------------------------------------------------------

_SESSION_MAX_AGE_SECONDS = 30 * 60  # 30 minutos


@dataclass
class _SessionInfo:
    uid: str
    url: str = ""
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)


# Dict compartido de sesiones activas: uid → _SessionInfo
_browser_sessions: dict[str, _SessionInfo] = {}


def _cleanup_expired_sessions() -> int:
    """Elimina sesiones con más de _SESSION_MAX_AGE_SECONDS de inactividad."""
    now = time.time()
    expired = [
        uid for uid, s in _browser_sessions.items()
        if now - s.last_used > _SESSION_MAX_AGE_SECONDS
    ]
    for uid in expired:
        log.info("auto-cleanup de sesión expirada: %s (último uso hace %.0fs)", uid, now - _browser_sessions[uid].last_used)
        del _browser_sessions[uid]
    if expired:
        log.info("auto-cleanup: %d sesiones expiradas eliminadas", len(expired))
    return len(expired)


def _track_session(uid: str, url: str = "") -> None:
    """Registra o actualiza una sesión en el tracker."""
    _cleanup_expired_sessions()
    if uid in _browser_sessions:
        _browser_sessions[uid].last_used = time.time()
        if url:
            _browser_sessions[uid].url = url
    else:
        _browser_sessions[uid] = _SessionInfo(uid=uid, url=url)


def _remove_session(uid: str) -> bool:
    """Elimina una sesión del tracker. Retorna True si existía."""
    if uid in _browser_sessions:
        del _browser_sessions[uid]
        return True
    return False


def browser_list_sessions_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lista todas las sesiones activas de navegador para un uid. Sin args requeridos."""
    _cleanup_expired_sessions()
    # Filtrar sesiones cuyo uid empiece con el uid del usuario (permite sub-sesiones)
    user_sessions = {
        k: v for k, v in _browser_sessions.items()
        if k == uid or k.startswith(f"{uid}_")
    }
    if not user_sessions:
        return ToolResult(ok=True, output=f"No hay sesiones activas para {uid}.")
    lines = [f"Sesiones activas para {uid} ({len(user_sessions)}):"]
    for sid, sinfo in user_sessions.items():
        age_s = int(time.time() - sinfo.created_at)
        idle_s = int(time.time() - sinfo.last_used)
        lines.append(
            f"  • {sid}: url={sinfo.url or 'N/A'}, "
            f"creada hace {age_s}s, inactiva {idle_s}s"
        )
    return ToolResult(ok=True, output="\n".join(lines))


def browser_close_all_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Cierra todas las sesiones de navegador para un uid. Sin args requeridos."""
    _cleanup_expired_sessions()
    user_sessions = [
        sid for sid in _browser_sessions
        if sid == uid or sid.startswith(f"{uid}_")
    ]
    if not user_sessions:
        return ToolResult(ok=True, output=f"No hay sesiones activas para cerrar ({uid}).")

    closed = 0
    errors: list[str] = []
    for sid in user_sessions:
        raw = _bridge_browser("browserCloseSessionExtract", uid=sid)
        if raw.get("ok"):
            _remove_session(sid)
            closed += 1
        else:
            errors.append(f"{sid}: {raw.get('error', 'unknown')}")
            # Intentar remover del tracker de todas formas
            _remove_session(sid)

    if errors:
        return ToolResult(
            ok=False,
            output="",
            error=f"Cerradas {closed}/{len(user_sessions)} sesiones. Errores: {'; '.join(errors)}",
        )
    return ToolResult(
        ok=True,
        output=f"Todas las sesiones cerradas ({closed}) para {uid}.",
    )


# ---------------------------------------------------------------------------
# M1S1 — HANDLERS EXISTENTES (7)
# ---------------------------------------------------------------------------

def browser_navigate_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Entra a una página web (URL http/https) y la abre para leer contenido con JavaScript. Args: url."""
    url = str(arguments.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, output="", error="Falta url.")
    raw = _bridge_browser("browserNavigate", url=url)
    if not raw.get("ok"):
        return _err(raw, "navigate_failed")
    return ToolResult(
        ok=True,
        output=f"Navegué a {raw.get('url')} (host={raw.get('host')}). Título: {raw.get('title')}",
    )


def browser_extract_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Lee el texto visible de la página web abierta. Args: selector (CSS, default body)."""
    selector = str(arguments.get("selector") or "body").strip() or "body"
    raw = _bridge_browser("browserExtract", selector=selector)
    if not raw.get("ok"):
        return _err(raw, "extract_failed")
    text = str(raw.get("text") or "")
    title = str(raw.get("title") or "").strip()
    title_line = f"Título: {title}\n" if title else ""
    return ToolResult(
        ok=True,
        output=(
            f"{title_line}URL: {raw.get('url')}\n"
            f"Selector: {selector}\nChars: {raw.get('chars')}\n---\n{text}"
        ),
    )


def browser_click_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Click en elemento CSS de la página abierta. Args: selector."""
    selector = str(arguments.get("selector") or "").strip()
    if not selector:
        return ToolResult(ok=False, output="", error="Falta selector.")
    raw = _bridge_browser("browserClick", selector=selector)
    if not raw.get("ok"):
        return _err(raw, "click_failed")
    return ToolResult(
        ok=True,
        output=f"Click en {selector} → {raw.get('clicked')} (url={raw.get('url')})",
    )


def browser_type_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Escribe texto en input/textarea. Args: selector, text; clear opcional."""
    selector = str(arguments.get("selector") or "").strip()
    text = str(arguments.get("text") or arguments.get("value") or "")
    if not selector:
        return ToolResult(ok=False, output="", error="Falta selector.")
    clear = arguments.get("clear", True)
    raw = _bridge_browser("browserType", selector=selector, text=text, clear=bool(clear))
    if not raw.get("ok"):
        return _err(raw, "type_failed")
    return ToolResult(ok=True, output=f"Escribí {raw.get('chars')} chars en {selector}")


def browser_wait_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Espera selector o texto en página. Args: selector y/o text_contains, timeout_ms."""
    selector = str(arguments.get("selector") or "").strip()
    text_contains = str(
        arguments.get("text_contains") or arguments.get("textContains") or ""
    ).strip()
    if not selector and not text_contains:
        return ToolResult(ok=False, output="", error="Falta selector o text_contains.")
    timeout_ms = arguments.get("timeout_ms") or arguments.get("timeoutMs") or 15000
    raw = _bridge_browser(
        "browserWait",
        selector=selector,
        textContains=text_contains,
        timeoutMs=int(timeout_ms),
    )
    if not raw.get("ok"):
        return _err(raw, "wait_timeout")
    return ToolResult(
        ok=True,
        output=f"Listo tras {raw.get('waited_ms')} ms (url={raw.get('url')})",
    )


def browser_get_price_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Extrae precio de la página abierta (Amazon/ML/heurística). Llama tras browser_navigate."""
    raw = _bridge_browser("browserGetPrice")
    if not raw.get("ok"):
        return _err(raw, "price_failed")
    price = raw.get("price")
    if not price:
        return ToolResult(
            ok=True,
            output=(
                f"No detecté un precio claro en {raw.get('url')}. "
                f"Título: {raw.get('title') or 'N/A'}. "
                f"Prueba browser_extract o pide otro enlace."
            ),
        )
    return ToolResult(
        ok=True,
        output=(
            f"Precio detectado: {price}\n"
            f"Título: {raw.get('title')}\n"
            f"URL: {raw.get('url')}\n"
            f"Otros: {raw.get('money_in_page')}"
        ),
    )


# ---------------------------------------------------------------------------
# M1S2-A — NUEVOS HANDLERS CDP (15)
# ---------------------------------------------------------------------------

def browser_pdf_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Genera PDF de la página actual vía CDP (Page.printToPDF) y lo guarda en ~/Desktop.

    Args:
        url: URL opcional — navega antes de generar el PDF.
        filepath / filename / path: ruta opcional (p. ej. Escritorio/informe.pdf).
        landscape: orientación horizontal (default False).
    """
    url = str(arguments.get("url") or "").strip()
    if url:
        nav = _bridge_browser("browserNavigate", url=url)
        if not nav.get("ok"):
            return _err(nav, "navigate_failed")

    filepath = str(
        arguments.get("filepath")
        or arguments.get("filename")
        or arguments.get("path")
        or ""
    ).strip()
    bridge_args: dict[str, Any] = {"landscape": bool(arguments.get("landscape", False))}
    if filepath:
        bridge_args["filepath"] = filepath
    raw = _bridge_browser("browserPdf", **bridge_args)
    if not raw.get("ok"):
        return _err(raw, "pdf_failed")
    saved_to = str(raw.get("saved_to") or raw.get("relative_path") or "").strip()
    lines = [
        "PDF de la página web guardado en el Escritorio.",
        f"Ruta: {saved_to}" if saved_to else "Ruta: (no disponible)",
        f"URL: {raw.get('url', 'N/A')}",
        f"Título: {raw.get('title', '') or 'N/A'}",
    ]
    size_bytes = raw.get("size_bytes")
    if isinstance(size_bytes, int) and size_bytes > 0:
        lines.append(f"Tamaño: {size_bytes} bytes.")
    return ToolResult(ok=True, output="\n".join(lines))


def browser_get_cookies_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene cookies de la página actual vía CDP (Network.getCookies)."""
    urls = arguments.get("urls", None)
    raw = _bridge_browser("browserGetCookies", urls=urls)
    if not raw.get("ok"):
        return _err(raw, "get_cookies_failed")
    cookies = raw.get("cookies", [])
    count = raw.get("count", 0)
    return ToolResult(
        ok=True,
        output=f"{count} cookies obtenidas de {raw.get('url')}.\n---\n{cookies}",
    )


def browser_set_cookies_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Establece cookies en la página actual vía CDP (Network.setCookie). Args: cookies (array)."""
    cookies = arguments.get("cookies")
    if not cookies:
        return ToolResult(ok=False, output="", error="Falta cookies (array de dicts con name, value, url/domain).")
    raw = _bridge_browser("browserSetCookies", cookies=cookies)
    if not raw.get("ok"):
        return _err(raw, "set_cookies_failed")
    return ToolResult(
        ok=True,
        output=f"Cookies establecidas: {raw.get('set')}/{raw.get('total')} exitosas.",
    )


def browser_scroll_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Hace scroll vertical en la página vía CDP (Input.dispatchMouseEvent mouseWheel). Args: delta_y, repeat."""
    delta_y = arguments.get("delta_y") or arguments.get("deltaY") or 500
    delta_x = arguments.get("delta_x") or arguments.get("deltaX") or 0
    repeat = arguments.get("repeat", 1)
    raw = _bridge_browser("browserScroll", delta_y=int(delta_y), delta_x=int(delta_x), repeat=int(repeat))
    if not raw.get("ok"):
        return _err(raw, "scroll_failed")
    return ToolResult(
        ok=True,
        output=f"Scroll: deltaY={raw.get('deltaY')}, deltaX={raw.get('deltaX')}, repeticiones={raw.get('repeat')}.",
    )


def browser_network_intercept_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Intercepta requests de red vía CDP (Network.enable + requestWillBeSent). Args: action (start/snapshot/stop)."""
    action = str(arguments.get("action") or "start").strip().lower()
    raw = _bridge_browser("browserNetworkIntercept", action=action)
    if not raw.get("ok"):
        return _err(raw, "network_intercept_failed")
    if action == "snapshot" or action == "stop":
        captured = raw.get("captured", [])
        count = raw.get("count", 0)
        return ToolResult(
            ok=True,
            output=f"Network intercept ({action}): {count} requests capturadas.\n---\n{captured}",
        )
    return ToolResult(ok=True, output=f"Network intercept {action}.")


def browser_execute_js_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Ejecuta JavaScript en la página vía CDP (Runtime.evaluate). Args: code."""
    code = str(arguments.get("code") or "").strip()
    if not code:
        return ToolResult(ok=False, output="", error="Falta code (código JS a ejecutar).")
    await_promise = arguments.get("await_promise") or arguments.get("awaitPromise") or False
    raw = _bridge_browser("browserExecuteJS", code=code, awaitPromise=bool(await_promise))
    if not raw.get("ok"):
        return _err(raw, "execute_js_failed")
    result = raw.get("result", {})
    return ToolResult(
        ok=True,
        output=f"JS ejecutado en {raw.get('url')}.\nResultado: {result.get('value', result)}",
    )


def browser_fill_form_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Rellena múltiples campos de formulario. Args: fields (dict selector→valor), submit (selector opcional)."""
    fields = arguments.get("fields")
    if not fields or not isinstance(fields, dict):
        return ToolResult(ok=False, output="", error="Falta fields (dict: {\"selector\": \"valor\", ...}).")
    submit = str(arguments.get("submit") or "").strip() or None
    raw = _bridge_browser("browserFillForm", fields=fields, submit=submit)
    if not raw.get("ok"):
        return _err(raw, "fill_form_failed")
    filled = raw.get("filled", [])
    submitted = raw.get("submitted", False)
    msg = f"Formulario rellenado: {len(filled)} campos."
    if submitted:
        msg += " Enviado."
    return ToolResult(ok=True, output=f"{msg}\nDetalle: {filled}")


def browser_wait_for_navigation_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Espera a que termine la navegación vía CDP (Page.frameStoppedLoading). Args: timeout_ms."""
    timeout_ms = arguments.get("timeout_ms") or arguments.get("timeoutMs") or 30000
    raw = _bridge_browser("browserWaitForNavigation", timeoutMs=int(timeout_ms))
    if not raw.get("ok"):
        return _err(raw, "wait_navigation_timeout")
    return ToolResult(
        ok=True,
        output=f"Navegación completa: {raw.get('url')}. Título: {raw.get('title')}",
    )


def browser_get_page_title_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene el título de la página actual vía CDP (Runtime.evaluate)."""
    raw = _bridge_browser("browserGetPageTitle")
    if not raw.get("ok"):
        return _err(raw, "get_title_failed")
    return ToolResult(
        ok=True,
        output=f"Título: {raw.get('title')} (url={raw.get('url')})",
    )


def browser_get_page_url_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Obtiene la URL actual de la página vía CDP (Runtime.evaluate)."""
    raw = _bridge_browser("browserGetPageURL")
    if not raw.get("ok"):
        return _err(raw, "get_url_failed")
    return ToolResult(ok=True, output=f"URL actual: {raw.get('url')}")


def browser_select_option_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Selecciona una opción de un <select>. Args: selector, value."""
    selector = str(arguments.get("selector") or "").strip()
    value = str(arguments.get("value") or arguments.get("text") or "")
    if not selector:
        return ToolResult(ok=False, output="", error="Falta selector.")
    if not value:
        return ToolResult(ok=False, output="", error="Falta value (texto o valor de la opción).")
    raw = _bridge_browser("browserSelectOption", selector=selector, value=value)
    if not raw.get("ok"):
        return _err(raw, "select_failed")
    return ToolResult(
        ok=True,
        output=f"Seleccionado '{raw.get('selected')}' en {selector} (índice {raw.get('index')}).",
    )


def browser_hover_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Hace hover sobre un elemento vía CDP (DOM.getBoxModel + Input.dispatchMouseEvent). Args: selector."""
    selector = str(arguments.get("selector") or "").strip()
    if not selector:
        return ToolResult(ok=False, output="", error="Falta selector.")
    raw = _bridge_browser("browserHover", selector=selector)
    if not raw.get("ok"):
        return _err(raw, "hover_failed")
    pos = raw.get("position", {})
    via = raw.get("via", "cdp")
    return ToolResult(
        ok=True,
        output=f"Hover sobre {selector} (via={via}) en posición {pos}. URL: {raw.get('url')}",
    )


def browser_press_key_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Presiona una tecla especial vía CDP (Input.dispatchKeyEvent). Args: key (enter, tab, escape, arrowup, etc.)."""
    key = str(arguments.get("key") or "").strip().lower()
    if not key:
        return ToolResult(ok=False, output="", error="Falta key (ej: enter, tab, escape, arrowdown, ctrl+c).")
    raw = _bridge_browser("browserPressKey", key=key)
    if not raw.get("ok"):
        return _err(raw, "press_key_failed")
    return ToolResult(
        ok=True,
        output=f"Tecla '{raw.get('key')}' presionada (code={raw.get('code')}). URL: {raw.get('url')}",
    )


def browser_upload_file_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Sube un archivo a un input[type=file] vía CDP (DOM.setFileInputFiles). Args: filepath, selector."""
    filepath = str(arguments.get("filepath") or arguments.get("file_path") or "").strip()
    if not filepath:
        return ToolResult(ok=False, output="", error="Falta filepath (ruta del archivo a subir).")
    selector = str(arguments.get("selector") or 'input[type="file"]').strip()
    raw = _bridge_browser("browserUploadFile", filepath=filepath, selector=selector)
    if not raw.get("ok"):
        return _err(raw, "upload_file_failed")
    return ToolResult(
        ok=True,
        output=f"Archivo cargado en {selector}: {raw.get('file')}. URL: {raw.get('url')}",
    )


def browser_stealth_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Activa modo stealth anti-detección vía CDP (Page.addScriptToEvaluateOnNewDocument). Oculta que es Electron."""
    raw = _bridge_browser("browserStealth")
    if not raw.get("ok"):
        return _err(raw, "stealth_failed")
    injected = raw.get("injected", [])
    return ToolResult(
        ok=True,
        output=f"Stealth activado. {raw.get('message')}\nInyecciones: {injected}",
    )


# ---------------------------------------------------------------------------
# BR02 — browser_screenshot real (CDP Page.captureScreenshot → base64 PNG)
# ---------------------------------------------------------------------------

def browser_screenshot_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Captura screenshot de la página actual y lo guarda en ~/Desktop.

    Args:
        full_page: True para capturar la página completa.
        format: png o jpeg (default png).
        filepath / filename / path: ruta opcional (p. ej. Escritorio/mi-captura.png).
    """
    format_ = str(arguments.get("format") or "png").strip().lower()
    full_page = arguments.get("full_page") or arguments.get("fullPage") or False
    filepath = str(
        arguments.get("filepath")
        or arguments.get("filename")
        or arguments.get("path")
        or ""
    ).strip()
    bridge_args: dict[str, Any] = {"format": format_, "fullPage": bool(full_page)}
    if filepath:
        bridge_args["filepath"] = filepath
    raw = _bridge_browser("browserScreenshot", **bridge_args)
    if not raw.get("ok"):
        return _err(raw, "screenshot_failed")
    saved_to = str(raw.get("saved_to") or raw.get("relative_path") or "").strip()
    lines = [
        f"Captura {format_.upper()} guardada en el Escritorio.",
        f"Ruta: {saved_to}" if saved_to else "Ruta: (no disponible)",
        f"URL: {raw.get('url', 'N/A')}",
        f"Título: {raw.get('title', '') or 'N/A'}",
    ]
    size_bytes = raw.get("size_bytes")
    if isinstance(size_bytes, int) and size_bytes > 0:
        lines.append(f"Tamaño: {size_bytes} bytes.")
    return ToolResult(ok=True, output="\n".join(lines))


# ---------------------------------------------------------------------------
# BR04 — browser_fill real (single-field set value + input/change events)
# ---------------------------------------------------------------------------

def browser_fill_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Rellena un campo individual de formulario con set value + dispatch input/change events. Args: selector, value."""
    selector = str(arguments.get("selector") or "").strip()
    value = str(arguments.get("value") or arguments.get("text") or "")
    if not selector:
        return ToolResult(ok=False, output="", error="Falta selector.")
    if not value:
        return ToolResult(ok=False, output="", error="Falta value.")
    raw = _bridge_browser("browserFill", selector=selector, value=value)
    if not raw.get("ok"):
        return _err(raw, "fill_failed")
    return ToolResult(
        ok=True,
        output=f"Campo {selector} ← '{value}' (tag={raw.get('tag')}, url={raw.get('url')})",
    )


# ---------------------------------------------------------------------------
# BR05 — browser_open / browser_do / browser_close (session multi-step)
# ---------------------------------------------------------------------------

def browser_open_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Abre sesión de navegador multi-step para un uid. Args: url, uid (opcional, default=uid del usuario)."""
    url = str(arguments.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, output="", error="Falta url.")
    raw = _bridge_browser("browserOpenSession", url=url, uid=uid)
    if not raw.get("ok"):
        return _err(raw, "open_session_failed")
    _track_session(uid, url=raw.get("url", url))
    return ToolResult(
        ok=True,
        output=(
            f"Sesión abierta para {uid}. "
            f"Navegué a {raw.get('url')} (host={raw.get('host')}). "
            f"Título: {raw.get('title')}. "
            f"Sesiones activas: {len(_browser_sessions)}."
        ),
    )


def browser_do_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Ejecuta JS en la sesión activa vía CDP Runtime.evaluate. Args: js_code, uid."""
    js_code = str(arguments.get("js_code") or arguments.get("code") or "").strip()
    if not js_code:
        return ToolResult(ok=False, output="", error="Falta js_code.")
    raw = _bridge_browser("browserDoAction", uid=uid, js_code=js_code)
    if not raw.get("ok"):
        return _err(raw, "do_action_failed")
    result = raw.get("result", {})
    return ToolResult(
        ok=True,
        output=(
            f"JS ejecutado en sesión {uid} (url={raw.get('url')}). "
            f"Resultado: {result.get('value', result)}"
        ),
    )


def browser_close_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Cierra sesión de navegador y devuelve extracto estructurado: título, texto preview, links count, screenshot base64. Args: uid."""
    raw = _bridge_browser("browserCloseSessionExtract", uid=uid)
    if not raw.get("ok"):
        return _err(raw, "close_session_failed")
    _remove_session(uid)
    extract = raw.get("extract") or {}
    duration = raw.get("session_duration_ms", 0)
    lines = [
        f"Sesión {uid} cerrada (duración: {duration} ms).",
        f"Título: {extract.get('title', 'N/A')}",
        f"Links encontrados: {extract.get('links_count', 0)}",
        f"Texto preview ({len(str(extract.get('text_preview', '')))} chars): {str(extract.get('text_preview', ''))[:500]}",
    ]
    if extract.get("screenshot_base64"):
        lines.append(f"Screenshot: {len(str(extract['screenshot_base64']))} chars base64 PNG.")
    return ToolResult(ok=True, output="\n".join(lines))


# ---------------------------------------------------------------------------
# BR04 — FORM AUTOFILL AVANZADO: auto-detección de selectores por tipo
# ---------------------------------------------------------------------------

# Patrones comunes de selectores por tipo de campo
_FIELD_TYPE_PATTERNS: dict[str, list[str]] = {
    "text": [
        'input[id*="{name}" i]',
        'input[name*="{name}" i]',
        'input[placeholder*="{name}" i]',
        'input[type="text"][id*="{name}" i]',
        'input[type="text"][name*="{name}" i]',
        'textarea[id*="{name}" i]',
        'textarea[name*="{name}" i]',
    ],
    "email": [
        'input[type="email"]',
        'input[id*="email" i]',
        'input[name*="email" i]',
        'input[placeholder*="email" i]',
        'input[placeholder*="correo" i]',
    ],
    "password": [
        'input[type="password"]',
        'input[id*="password" i]',
        'input[id*="pass" i]',
        'input[name*="password" i]',
        'input[name*="pass" i]',
    ],
    "number": [
        'input[type="number"][id*="{name}" i]',
        'input[type="number"][name*="{name}" i]',
        'input[type="tel"][id*="{name}" i]',
        'input[type="tel"][name*="{name}" i]',
        'input[id*="{name}" i]',
        'input[name*="{name}" i]',
    ],
    "phone": [
        'input[type="tel"]',
        'input[id*="phone" i]',
        'input[id*="tel" i]',
        'input[id*="celular" i]',
        'input[id*="telefono" i]',
        'input[name*="phone" i]',
        'input[name*="tel" i]',
        'input[id*="{name}" i]',
    ],
    "select": [
        'select[id*="{name}" i]',
        'select[name*="{name}" i]',
        'select[class*="{name}" i]',
    ],
    "checkbox": [
        'input[type="checkbox"][id*="{name}" i]',
        'input[type="checkbox"][name*="{name}" i]',
    ],
    "date": [
        'input[type="date"][id*="{name}" i]',
        'input[type="date"][name*="{name}" i]',
        'input[id*="{name}" i]',
        'input[name*="{name}" i]',
    ],
    "textarea": [
        'textarea[id*="{name}" i]',
        'textarea[name*="{name}" i]',
        'textarea[placeholder*="{name}" i]',
    ],
}


def _generate_selectors(field_name: str, field_type: str) -> list[str]:
    """Genera una lista de selectores CSS candidatos para un campo según su tipo."""
    patterns = _FIELD_TYPE_PATTERNS.get(field_type, _FIELD_TYPE_PATTERNS["text"])
    selectors: list[str] = []
    for pattern in patterns:
        try:
            selectors.append(pattern.format(name=field_name))
        except KeyError:
            selectors.append(pattern)
    # Fallback genérico por label text
    if field_type not in ("checkbox",):
        selectors.append(f'[aria-label*="{field_name}" i]')
    return selectors


def browser_fill_form_advanced_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Rellena formulario con auto-detección de selectores por tipo de campo.

    Args:
        field_schema: dict mapeando nombre_de_campo → tipo (text, email, password, number,
                      phone, select, checkbox, date, textarea)
        field_values: dict mapeando nombre_de_campo → valor a escribir
        submit_selector: selector CSS opcional del botón de envío
    """
    field_schema = arguments.get("field_schema")
    field_values = arguments.get("field_values") or arguments.get("values") or {}

    if not field_schema or not isinstance(field_schema, dict):
        return ToolResult(
            ok=False, output="",
            error="Falta field_schema (dict: {\"nombre\": \"email\", \"pais\": \"select\", ...}).",
        )
    if not field_values or not isinstance(field_values, dict):
        return ToolResult(
            ok=False, output="",
            error="Falta field_values o values (dict: {\"nombre\": \"juan@mail.com\", \"pais\": \"Colombia\", ...}).",
        )

    submit_selector = str(arguments.get("submit_selector") or arguments.get("submit") or "").strip() or None

    filled: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    for field_name, field_type in field_schema.items():
        value = field_values.get(field_name)
        if value is None:
            errors.append({"field": field_name, "error": "sin valor en field_values"})
            continue

        candidates = _generate_selectors(field_name, str(field_type))
        raw = _bridge_browser(
            "browserFillFormAdvanced",
            field_name=field_name,
            field_type=str(field_type),
            selectors=candidates,
            value=str(value),
        )
        if raw.get("ok"):
            filled.append({
                "field": field_name,
                "type": str(field_type),
                "selector_used": str(raw.get("selector_used", candidates[0] if candidates else "N/A")),
            })
        else:
            error_msg = raw.get("error", "selector_no_encontrado")
            errors.append({"field": field_name, "error": error_msg})

    # Submit opcional
    submitted = False
    if submit_selector:
        raw_submit = _bridge_browser("browserClick", selector=submit_selector)
        submitted = raw_submit.get("ok", False)

    msg_parts = [f"Formulario avanzado: {len(filled)}/{len(field_schema)} campos rellenados."]
    if filled:
        details = ", ".join(f["field"] for f in filled)
        msg_parts.append(f"Rellenados: {details}.")
    if errors:
        err_details = "; ".join(f"{e['field']}: {e['error']}" for e in errors)
        msg_parts.append(f"Fallidos: {err_details}.")
    if submitted:
        msg_parts.append("Formulario enviado.")
    elif submit_selector:
        msg_parts.append("Envío fallido.")

    return ToolResult(ok=len(errors) == 0, output="\n".join(msg_parts))


# ---------------------------------------------------------------------------
# BR05 — SCREENSHOT ENHANCEMENT: captura por elemento y diff placeholder
# ---------------------------------------------------------------------------

def browser_screenshot_element_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Captura screenshot de un elemento específico vía CDP (selector → bounding box + clip).

    Args:
        selector: selector CSS del elemento a capturar
        format: png o jpeg (default png)
    """
    selector = str(arguments.get("selector") or "").strip()
    if not selector:
        return ToolResult(ok=False, output="", error="Falta selector (CSS del elemento a capturar).")
    format_ = str(arguments.get("format") or "png").strip().lower()
    raw = _bridge_browser(
        "browserScreenshotElement",
        selector=selector,
        format=format_,
    )
    if not raw.get("ok"):
        return _err(raw, "screenshot_element_failed")
    b64 = str(raw.get("screenshot_base64") or "")
    return ToolResult(
        ok=True,
        output=(
            f"Screenshot del elemento '{selector}' capturado ({format_.upper()}). "
            f"Tamaño: {raw.get('width', '?')}x{raw.get('height', '?')}px. "
            f"Base64: {len(b64)} chars. "
            f"URL: {raw.get('url', 'N/A')}"
        ),
    )


def browser_compare_screenshots_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    """Compara dos screenshots y detecta diferencias visuales (placeholder — futura implementación con pixelmatch/OpenCV).

    Args:
        baseline_selector: selector CSS o ruta de imagen de referencia
        current_selector: selector CSS o ruta de imagen actual
    """
    baseline = str(arguments.get("baseline_selector") or arguments.get("baseline") or "").strip()
    current = str(arguments.get("current_selector") or arguments.get("current") or "").strip()
    if not baseline or not current:
        return ToolResult(
            ok=False, output="",
            error="Faltan baseline_selector y/o current_selector.",
        )
    return ToolResult(
        ok=True,
        output=(
            "browser_compare_screenshots: funcionalidad de diff visual no implementada aún. "
            "Se planea usar pixelmatch/OpenCV para comparar dos screenshots y devolver "
            "porcentaje de diferencia + heatmap. "
            f"Baseline: {baseline}, Current: {current}."
        ),
    )


# ---------------------------------------------------------------------------
# TOOLS — REGISTRO DE HANDLERS
# ---------------------------------------------------------------------------

TOOLS = [
    # M1S1 (7)
    ("browser_navigate", browser_navigate_handler),
    ("browser_extract", browser_extract_handler),
    ("browser_click", browser_click_handler),
    ("browser_type", browser_type_handler),
    ("browser_wait", browser_wait_handler),
    ("browser_get_price", browser_get_price_handler),
    # BR02 — screenshot real CDP
    ("browser_screenshot", browser_screenshot_handler),
    # BR04 — fill single-field
    ("browser_fill", browser_fill_handler),
    # BR05/BR06 — session management
    ("browser_open", browser_open_handler),
    ("browser_do", browser_do_handler),
    ("browser_close", browser_close_handler),
    # BR03 — session management improvements
    ("browser_list_sessions", browser_list_sessions_handler),
    ("browser_close_all", browser_close_all_handler),
    # BR04 — form autofill avanzado
    ("browser_fill_form_advanced", browser_fill_form_advanced_handler),
    # BR05 — screenshot enhancement
    ("browser_screenshot_element", browser_screenshot_element_handler),
    ("browser_compare_screenshots", browser_compare_screenshots_handler),
    # M1S2-A — nuevas operaciones CDP (15)
    ("browser_pdf", browser_pdf_handler),
    ("browser_get_cookies", browser_get_cookies_handler),
    ("browser_set_cookies", browser_set_cookies_handler),
    ("browser_scroll", browser_scroll_handler),
    ("browser_network_intercept", browser_network_intercept_handler),
    ("browser_execute_js", browser_execute_js_handler),
    ("browser_fill_form", browser_fill_form_handler),
    ("browser_wait_for_navigation", browser_wait_for_navigation_handler),
    ("browser_get_page_title", browser_get_page_title_handler),
    ("browser_get_page_url", browser_get_page_url_handler),
    ("browser_select_option", browser_select_option_handler),
    ("browser_hover", browser_hover_handler),
    ("browser_press_key", browser_press_key_handler),
    ("browser_upload_file", browser_upload_file_handler),
    ("browser_stealth", browser_stealth_handler),
]

# ---------------------------------------------------------------------------
# TOOL_SPECS — ESQUEMAS DE PARÁMETROS
# ---------------------------------------------------------------------------

TOOL_SPECS = {
    # ---------- M1S1 (8) ----------
    "browser_navigate": {
        "description": "Entra a una URL y abre la página web para leer contenido (incluye JavaScript).",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL completa http/https a navegar"}
            },
            "required": ["url"],
        },
    },
    "browser_extract": {
        "description": "Lee el texto visible de la página web que ya está abierta.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Selector CSS opcional para limitar la extracción (dejar vacío para toda la página)"}
            },
        },
    },
    "browser_click": {
        "description": "Hace clic en un elemento de la página actual del navegador.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Selector CSS del elemento a clickear"},
                "text": {"type": "string", "description": "Texto visible del botón/enlace (alternativa a selector)"},
            },
        },
    },
    "browser_type": {
        "description": "Escribe texto en un campo de la página actual.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Selector CSS del campo de texto"},
                "value": {"type": "string", "description": "Texto a escribir en el campo"},
            },
            "required": ["selector", "value"],
        },
    },
    "browser_wait": {
        "description": "Espera a que aparezca un selector o texto en la página abierta.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Selector CSS a esperar"},
                "text_contains": {"type": "string", "description": "Texto que debe aparecer en la página"},
                "timeout_ms": {"type": "integer", "description": "Tiempo máximo de espera en milisegundos (default 15000)"},
            },
        },
    },
    "browser_get_price": {
        "description": "Busca y extrae el precio de un producto en la página actual usando heurísticas.",
        "parameters_schema": {
            "type": "object",
            "properties": {},
        },
    },
    "browser_screenshot": {
        "description": (
            "Toma una captura de la página web abierta y la guarda en ~/Desktop "
            "(nombre automático dot-captura-<sitio>-<fecha>.png). "
            "Usar tras browser_navigate para encadenar entrar → capturar."
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "full_page": {"type": "boolean", "description": "True para capturar la página completa, False solo visible (default: False)"},
                "format": {"type": "string", "description": "Formato de imagen: png o jpeg (default: png)"},
                "filepath": {"type": "string", "description": "Ruta opcional dentro del Escritorio, p. ej. Escritorio/mi-captura.png"},
            },
        },
    },
    "browser_close": {
        "description": "Cierra el navegador Chromium local de DOT y devuelve extracto estructurado (título, texto, links, screenshot).",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "uid": {"type": "string", "description": "ID de sesión activa a cerrar"},
            },
        },
    },
    "browser_fill": {
        "description": "Rellena un campo individual de formulario (set value + dispatch input/change events). Más ligero que browser_fill_form.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Selector CSS del campo a rellenar"},
                "value": {"type": "string", "description": "Valor a asignar al campo"},
            },
            "required": ["selector", "value"],
        },
    },
    "browser_open": {
        "description": "Abre una sesión de navegador multi-step. Similar a browser_navigate pero mantiene tracking de sesión por uid.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL a navegar"},
                "uid": {"type": "string", "description": "ID de sesión (default: uid del usuario)"},
            },
            "required": ["url"],
        },
    },
    "browser_do": {
        "description": "Ejecuta JavaScript en el contexto de la sesión activa vía CDP Runtime.evaluate.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "js_code": {"type": "string", "description": "Código JavaScript a ejecutar en la página"},
                "uid": {"type": "string", "description": "ID de sesión (default: uid del usuario)"},
            },
            "required": ["js_code"],
        },
    },

    # ---------- BR03 — Session Management ----------
    "browser_list_sessions": {
        "description": "Lista todas las sesiones activas de navegador para el usuario actual.",
        "parameters_schema": {
            "type": "object",
            "properties": {},
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_close_all": {
        "description": "Cierra todas las sesiones activas de navegador para el usuario actual.",
        "parameters_schema": {
            "type": "object",
            "properties": {},
        },
        "category": "browser",
        "capability": "B",
    },

    # ---------- BR04 — Form Autofill Avanzado ----------
    "browser_fill_form_advanced": {
        "description": "Rellena formularios con auto-detección de selectores por tipo de campo. Acepta un esquema JSON de tipos de campo y valores. Ideal para formularios donde no conoces los selectores exactos.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "field_schema": {
                    "type": "object",
                    "description": "Diccionario mapeando nombre de campo a tipo. Tipos: text, email, password, number, phone, select, checkbox, date, textarea. Ej: {\"nombre\": \"text\", \"correo\": \"email\", \"pais\": \"select\"}"
                },
                "field_values": {
                    "type": "object",
                    "description": "Diccionario mapeando nombre de campo a valor. Ej: {\"nombre\": \"Juan\", \"correo\": \"juan@mail.com\", \"pais\": \"Colombia\"}"
                },
                "submit_selector": {
                    "type": "string",
                    "description": "Selector CSS opcional del botón de envío (hace clic tras rellenar)"
                },
            },
            "required": ["field_schema", "field_values"],
        },
        "category": "browser",
        "capability": "B",
    },

    # ---------- BR05 — Screenshot Enhancement ----------
    "browser_screenshot_element": {
        "description": "Captura screenshot de un elemento específico de la página usando su selector CSS (bounding box + clip).",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Selector CSS del elemento a capturar"},
                "format": {"type": "string", "description": "Formato de imagen: png o jpeg (default: png)"},
            },
            "required": ["selector"],
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_compare_screenshots": {
        "description": "Compara dos screenshots y detecta diferencias visuales (placeholder — futura implementación con pixelmatch/OpenCV).",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "baseline_selector": {"type": "string", "description": "Selector CSS o ruta de la imagen de referencia"},
                "current_selector": {"type": "string", "description": "Selector CSS o ruta de la imagen actual a comparar"},
            },
            "required": ["baseline_selector", "current_selector"],
        },
        "category": "browser",
        "capability": "B",
    },

    # ---------- M1S2-A — NUEVAS OPERACIONES CDP (15) ----------
    "browser_pdf": {
        "description": (
            "Genera un PDF de la página web abierta y lo guarda en ~/Desktop "
            "(nombre automático dot-pdf-<sitio>-<fecha>.pdf). "
            "Puedes pasar url para navegar antes, o encadenar tras browser_navigate."
        ),
        "parameters_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL http/https opcional — navega antes de generar el PDF"},
                "filepath": {"type": "string", "description": "Ruta opcional en el Escritorio, p. ej. Escritorio/informe.pdf"},
                "landscape": {"type": "boolean", "description": "True para orientación horizontal, False vertical (default: False)"},
            },
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_get_cookies": {
        "description": "Obtiene todas las cookies de la página actual del navegador usando CDP (Network.getCookies).",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}, "description": "URLs para filtrar cookies (opcional, default: URL actual)"},
            },
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_set_cookies": {
        "description": "Establece cookies en la página actual del navegador usando CDP (Network.setCookie).",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "cookies": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Array de objetos cookie con name, value, y opcionalmente url/domain/path"
                },
            },
            "required": ["cookies"],
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_scroll": {
        "description": "Hace scroll vertical/horizontal en la página actual usando CDP (Input.dispatchMouseEvent mouseWheel).",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "delta_y": {"type": "integer", "description": "Píxeles de scroll vertical (positivo=abajo, negativo=arriba, default 500)"},
                "delta_x": {"type": "integer", "description": "Píxeles de scroll horizontal (default 0)"},
                "repeat": {"type": "integer", "description": "Número de repeticiones del scroll (default 1, max 30)"},
            },
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_network_intercept": {
        "description": "Intercepta requests de red del navegador usando CDP (Network.enable + requestWillBeSent). Permite capturar tráfico.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "snapshot", "stop"],
                    "description": "Acción: 'start' comienza captura, 'snapshot' devuelve capturas actuales, 'stop' detiene y devuelve todas"
                },
            },
            "required": ["action"],
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_execute_js": {
        "description": "Ejecuta código JavaScript arbitrario en la página actual usando CDP (Runtime.evaluate).",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Código JavaScript a ejecutar en la página"},
                "await_promise": {"type": "boolean", "description": "True para esperar promesas (default False)"},
            },
            "required": ["code"],
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_fill_form": {
        "description": "Rellena múltiples campos de un formulario de una sola vez. Acepta un diccionario selector→valor.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "object",
                    "description": 'Diccionario de campos a rellenar. Ej: {"#name": "Juan", "#email": "juan@mail.com"}'
                },
                "submit": {"type": "string", "description": "Selector CSS del botón de envío (opcional, hace clic tras rellenar)"},
            },
            "required": ["fields"],
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_wait_for_navigation": {
        "description": "Espera a que termine la navegación actual usando CDP (Page.frameStoppedLoading). Útil tras clicks que cambian de página.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "timeout_ms": {"type": "integer", "description": "Tiempo máximo de espera en ms (default 30000)"},
            },
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_get_page_title": {
        "description": "Obtiene el título de la página actual del navegador usando CDP (Runtime.evaluate document.title).",
        "parameters_schema": {
            "type": "object",
            "properties": {},
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_get_page_url": {
        "description": "Obtiene la URL actual de la página del navegador usando CDP (Runtime.evaluate window.location.href).",
        "parameters_schema": {
            "type": "object",
            "properties": {},
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_select_option": {
        "description": "Selecciona una opción en un elemento <select> por valor o texto visible.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Selector CSS del elemento <select>"},
                "value": {"type": "string", "description": "Valor (value) o texto visible de la opción a seleccionar"},
            },
            "required": ["selector", "value"],
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_hover": {
        "description": "Hace hover (mouseover) sobre un elemento usando CDP (DOM.getBoxModel + Input.dispatchMouseEvent mouseMoved).",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "Selector CSS del elemento sobre el que hacer hover"},
            },
            "required": ["selector"],
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_press_key": {
        "description": "Presiona una tecla especial en la página usando CDP (Input.dispatchKeyEvent). Soporta: enter, tab, escape, backspace, delete, arrowup/down/left/right, space, home, end, pageup, pagedown, f5, ctrl+a/c/v/x/z.",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Nombre de la tecla a presionar (enter, tab, escape, arrowdown, ctrl+c, etc.)"
                },
            },
            "required": ["key"],
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_upload_file": {
        "description": "Sube un archivo a un input[type=file] usando CDP (DOM.setFileInputFiles).",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Ruta del archivo a subir (absoluta o relativa al Escritorio)"},
                "selector": {"type": "string", "description": "Selector CSS del input[type=file] (default: input[type=\"file\"])"},
            },
            "required": ["filepath"],
        },
        "category": "browser",
        "capability": "B",
    },
    "browser_stealth": {
        "description": "Activa modo stealth anti-detección usando CDP (Page.addScriptToEvaluateOnNewDocument). Oculta que el navegador es Electron: navigator.webdriver=false, plugins y languages simulados, chrome.runtime presente.",
        "parameters_schema": {
            "type": "object",
            "properties": {},
        },
        "category": "browser",
        "capability": "B",
    },
}

TOOL_SCHEMAS = {
    name: spec.get("parameters_schema", {"type": "object", "properties": {}})
    for name, spec in TOOL_SPECS.items()
}
