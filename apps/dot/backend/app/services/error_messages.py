"""Capa de traducción de errores técnicos → mensajes de usuario en español (Life-OS G4)."""

from __future__ import annotations

import re

from app.services.usage_service import USAGE_LIMIT_EXCEEDED_MESSAGE

GENERIC = "Algo salió mal. Intenta de nuevo en unos momentos."
GENERIC_NOTIFY = (
    "Algo salió mal. El equipo ya fue notificado. Intenta de nuevo en unos minutos."
)

ERROR_MAP = {
    "DATABASE_URL no configurada": "El servicio no está disponible. Intenta de nuevo en unos minutos.",
    "Connection refused": "No pude conectar con el servicio. Revisa tu conexión a internet.",
    "ConnectionError": "No pude conectar con el servicio. Intenta de nuevo.",
    "ECONNREFUSED": "No pude conectar con el servicio. Revisa tu conexión a internet.",
    "TimeoutError": "La operación tardó demasiado. Intenta con una consulta más corta.",
    "RateLimitExceeded": "Has enviado muchos mensajes. Espera unos segundos e inténtalo de nuevo.",
    "Firebase credentials": "Error de configuración del servidor. El equipo ya fue notificado.",
    "token expirado": "Tu sesión expiró. Vuelve a iniciar sesión.",
    "invalid token": "Tu sesión no es válida. Vuelve a iniciar sesión.",
    "Quota exceeded": USAGE_LIMIT_EXCEEDED_MESSAGE,
    "ai_usage_limit_exceeded": USAGE_LIMIT_EXCEEDED_MESSAGE,
    "usage limit": USAGE_LIMIT_EXCEEDED_MESSAGE,
    "image_generation_unavailable": "La generación de imágenes no está disponible ahora.",
    "ProviderNotAvailable": "El servicio de IA no está disponible. Intenta de nuevo en un momento.",
    "browser_permission_denied": (
        "No tengo permiso para abrir páginas web. "
        "Actívalo en Configuración → Privacidad → 'DOT puede usar webs'."
    ),
    "browser_permission_required": (
        "Para entrar en páginas web necesito tu permiso. "
        "Ve a Configuración → Privacidad y activa 'DOT puede usar webs'."
    ),
    "browser_web_disabled": (
        "Para que DOT entre en páginas web, actívalo en Configuración → Privacidad → "
        "'DOT puede usar webs'."
    ),
    "browser_timeout": "La página tardó demasiado en cargar. Intenta con otra URL o más tarde.",
    "browser_not_navigated": "Primero necesito abrir la página web. Indica la URL o pide que entre al sitio.",
    "host_blocked": "Por seguridad no puedo abrir esa dirección.",
    "invalid_url": "La dirección web no es válida. Debe empezar con http:// o https://.",
    "gmail_not_connected": "Gmail no está vinculado. Conéctalo en Sesiones.",
    "calendar_not_connected": "Calendar no está vinculado. Conéctalo en Sesiones.",
    "bridge_unreachable": "WhatsApp no está disponible. Abre la aplicación DOT e intenta de nuevo.",
    "bridge_secret_not_configured": "WhatsApp no está configurado. Escanea el QR para vincularlo.",
    "bridge_unauthorized": "No pude conectar WhatsApp. Escanea el código de nuevo.",
    "bridge_send_failed": "No se pudo enviar el mensaje por WhatsApp. Intenta de nuevo.",
    "stt_failed": "No pude escuchar el audio, ¿me lo escribes?",
    "openclaw": "No pude completar la operación. Intenta de nuevo.",
    "baileys": "No pude conectar WhatsApp. Escanea el código de nuevo.",
    "sandbox deny": "Esta acción no está permitida en tu equipo.",
    "Traceback": GENERIC,
    # Documentos / CV
    "read_document necesita": "Indica la ruta del documento (por ejemplo ~/Desktop/archivo.pdf).",
    "read_spreadsheet necesita": "Indica la ruta del Excel (por ejemplo ~/Desktop/ventas.xlsx).",
    "analyze_cv necesita": "Indica la ruta de tu CV (por ejemplo ~/Desktop/mi_cv.pdf).",
    "Tipo de archivo no soportado": "Ese formato no se puede leer. Usa PDF, DOCX, TXT o Excel (.xlsx/.xls).",
    "Formato no soportado": "Ese formato no se puede leer. Usa archivos Excel .xlsx o .xls.",
    "No pude abrir el Excel": "No pude abrir el Excel. Revisa que no esté corrupto, protegido con contraseña o abierto en otra app.",
    "no se encontró texto extraíble": "No pude leer texto del documento. ¿Es un PDF escaneado?",
    "Bridge de herramientas locales no disponible": "Abre la app DOT en tu PC para leer archivos.",
    "No se pudo leer el documento": "No pude abrir el documento. Revisa la ruta y que DOT esté abierto.",
    "No se pudo analizar el CV": "No pude analizar el CV. Verifica que sea PDF/DOCX con texto seleccionable.",
    "Indica el idioma destino": "Dime a qué idioma quieres traducir (por ejemplo: inglés, francés, portugués).",
    "Indica el texto a procesar": "Pega el texto o indica la ruta del documento (~/Desktop/archivo.pdf).",
    "Traducción no disponible": "La traducción no está disponible ahora. Intenta más tarde.",
    "Resumen no disponible": "No pude generar el resumen ahora. Intenta con un texto más corto.",
}

WHATSAPP_BRIDGE_ERRORS = {
    "bridge_unreachable": ERROR_MAP["bridge_unreachable"],
    "bridge_secret_not_configured": ERROR_MAP["bridge_secret_not_configured"],
    "bridge_unauthorized": ERROR_MAP["bridge_unauthorized"],
    "bridge_send_failed": ERROR_MAP["bridge_send_failed"],
}

_TECHNICAL_PATTERNS = (
    re.compile(r"open\s*claw", re.I),
    re.compile(r"openclaw", re.I),
    re.compile(r"baileys", re.I),
    re.compile(r"\bnpm\b", re.I),
    re.compile(r"\bdocker\b", re.I),
    re.compile(r"sandbox\s*deny", re.I),
    re.compile(r"econnrefused", re.I),
    re.compile(r"traceback", re.I),
    re.compile(r"stack\s*trace", re.I),
    re.compile(r"node_modules", re.I),
    re.compile(r"bridge_", re.I),
    re.compile(r"\bhttp\s*\d{3}\b", re.I),
    re.compile(r"httpx", re.I),
    re.compile(r"sqlalchemy", re.I),
    re.compile(r"pydantic", re.I),
    re.compile(r"fastapi", re.I),
)


def is_technical_message(message: str) -> bool:
    msg = str(message or "").strip()
    if not msg:
        return False
    return any(pattern.search(msg) for pattern in _TECHNICAL_PATTERNS)


def _looks_like_friendly_spanish(message: str) -> bool:
    if len(message) > 240:
        return False
    if is_technical_message(message):
        return False
    if re.search(r"[áéíóúñ¿¡]", message, re.I):
        return True
    return bool(
        re.match(
            r"^(no se pudo|no pude|revisa|intenta|escanea|conecta|vuelve|espera|abre|cierra)",
            message,
            re.I,
        )
    )


def translate_error(error_message: str) -> str:
    """Traduce un error técnico a un mensaje amigable en español."""
    return sanitize_user_message(error_message)


def sanitize_user_message(error_message: str, fallback: str = GENERIC_NOTIFY) -> str:
    """Sanitiza cualquier string visible al usuario final."""
    msg = str(error_message or "").strip()
    if not msg:
        return GENERIC

    for key, translation in ERROR_MAP.items():
        if key.lower() in msg.lower():
            return translation

    if _looks_like_friendly_spanish(msg):
        return msg

    if is_technical_message(msg):
        return fallback

    if re.fullmatch(r"[a-z0-9_:\s.\-/\\()[\]{}'\"]+", msg, re.I) and not re.search(
        r"[áéíóúñ]", msg, re.I
    ):
        return fallback

    return msg


def translate_whatsapp_error(code: str) -> str:
    """Traduce códigos del bridge WhatsApp a mensajes amigables."""
    key = str(code or "").strip()
    if key in WHATSAPP_BRIDGE_ERRORS:
        return WHATSAPP_BRIDGE_ERRORS[key]
    return sanitize_user_message(
        key,
        "No se pudo enviar el mensaje por WhatsApp. Intenta de nuevo.",
    )


def translate_http_exception(status_code: int, detail: str = "") -> str:
    """Traduce un status code HTTP + detail a mensaje de usuario."""
    generic = {
        400: "La solicitud no es válida. Revisa los datos enviados.",
        401: "No tienes acceso. Inicia sesión de nuevo.",
        403: "No tienes permiso para esta acción.",
        404: "No encontré lo que buscas.",
        409: "Conflicto con otro mensaje. Intenta de nuevo.",
        429: "Demasiadas solicitudes. Espera un momento.",
        500: "Error interno del servidor. Intenta más tarde.",
        502: "Servicio externo no disponible. Intenta más tarde.",
        503: "Servicio en mantenimiento. Vuelve en unos minutos.",
    }
    if detail:
        translated = sanitize_user_message(detail, fallback="__unmapped__")
        if translated != "__unmapped__":
            return translated
    return generic.get(status_code, GENERIC)
