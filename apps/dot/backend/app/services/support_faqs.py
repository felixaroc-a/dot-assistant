"""Base de datos de FAQs y motor de busqueda para soporte de Nordik-IA.

Provee respuestas automaticas a preguntas frecuentes de los usuarios,
reduciendo la carga de tickets de soporte.
"""

from __future__ import annotations

import re
from typing import Optional

# ─── FAQ Database ─────────────────────────────────────────────────────
# Cada entrada tiene:
#   q: Pregunta (texto de busqueda)
#   a: Respuesta (texto formateado para mostrar al usuario)
#   keywords: Palabras clave adicionales para mejorar el matching
#   category: Categoria para agrupacion

FAQ_DATABASE: list[dict] = [
    # ── Precios y Planes ──────────────────────────────────────────
    {
        "q": "¿Cuánto cuesta Nordik IA?",
        "a": (
            "Nordik IA ofrece planes **mensual ($X)**, **trimestral ($Y)** y **anual ($Z)**. "
            "Todos los planes incluyen las mismas capacidades: chat IA, WhatsApp, Google (Gmail/Calendar), "
            "automatizaciones, visión, generación de imágenes, búsqueda web y herramientas de archivos. "
            "La única diferencia es la duración de la suscripción. "
            "Visita tu tienda Nordik más cercana para conocer los precios actualizados."
        ),
        "keywords": ["precio", "costo", "plan", "mensual", "trimestral", "anual", "pagar", "cuanto", "valor"],
        "category": "billing",
    },
    {
        "q": "¿Cuál es el límite de consumo de IA?",
        "a": (
            "El límite de consumo de IA es de **$7.50 USD por mes** por usuario. "
            "Este límite cubre TODO el consumo de IA: chat con DeepSeek, análisis de imágenes con "
            "Vision (Vertex AI) y generación de imágenes con Vertex Imagen. "
            "Cuando alcances el 100% del límite, el uso de IA se bloqueará automáticamente. "
            "Puedes verificar tu consumo actual en cualquier momento desde la aplicación."
        ),
        "keywords": ["limite", "consumo", "ia", "7.50", "dolares", "bloqueo", "tope", "maximo"],
        "category": "billing",
    },
    {
        "q": "¿Cómo puedo recargar mi crédito de IA?",
        "a": (
            "Para recargar tu crédito de IA, debes **visitar la tienda Nordik más cercana** "
            "donde adquiriste tu suscripción. El personal de la tienda procesará tu recarga "
            "a través del panel administrativo. El crédito se acredita de inmediato: "
            "el 75% del monto pagado se convierte en crédito IA, y el 25% restante "
            "es el margen de servicio de Nordik."
        ),
        "keywords": ["recargar", "recarga", "credito", "tienda", "pagar", "saldo"],
        "category": "billing",
    },
    {
        "q": "¿Qué planes hay disponibles?",
        "a": (
            "Nordik IA ofrece tres planes de suscripción:\n\n"
            "1. **Mensual** — 1 mes de acceso completo\n"
            "2. **Trimestral** — 3 meses de acceso completo (mejor valor)\n"
            "3. **Anual** — 12 meses de acceso completo (mejor ahorro)\n\n"
            "Todos los planes incluyen las mismas capacidades sin restricciones. "
            "La única diferencia es la duración. Consulta en tu tienda Nordik los precios vigentes."
        ),
        "keywords": ["planes", "suscripcion", "mensual", "trimestral", "anual", "tipos"],
        "category": "billing",
    },
    {
        "q": "¿Cómo verifico mi fecha de vencimiento?",
        "a": (
            "Puedes verificar tu fecha de vencimiento desde la aplicación Nordik IA:\n"
            "1. Ve a **Perfil** o **Configuración**\n"
            "2. Busca la sección **Suscripción**\n"
            "3. Allí verás tu plan actual y la **fecha de vencimiento**\n\n"
            "También recibirás recordatorios automáticos cuando tu suscripción esté por vencer."
        ),
        "keywords": ["vencimiento", "fecha", "expira", "cuando", "renovar"],
        "category": "billing",
    },

    # ── Pendrive y Seguridad ──────────────────────────────────────
    {
        "q": "¿Qué hago si perdí mi pendrive?",
        "a": (
            "Si perdiste tu pendrive Nordik, sigue estos pasos:\n"
            "1. **Ve a la tienda Nordik más cercana** inmediatamente\n"
            "2. Presenta tu cédula de identidad\n"
            "3. El personal desvinculará el pendrive perdido de tu cuenta\n"
            "4. Te entregarán un nuevo pendrive vinculado a tu cuenta\n\n"
            "**Importante:** El pendrive perdido quedará inutilizable para Nordik IA. "
            "Nadie podrá usar tu cuenta con ese dispositivo. "
            "Tus datos y conversaciones están seguros."
        ),
        "keywords": ["perdi", "perdido", "pendrive", "usb", "robo", "robado", "recuperar", "reemplazo"],
        "category": "pendrive",
    },
    {
        "q": "Mi pendrive no es detectado por la aplicación",
        "a": (
            "Si tu pendrive no es detectado, intenta lo siguiente:\n\n"
            "1. **Reconecta el pendrive** en otro puerto USB\n"
            "2. **Reinicia la aplicación** Nordik IA completamente\n"
            "3. **Verifica en Windows:** Abre 'Este PC' y confirma que el pendrive aparece\n"
            "4. **Prueba en otro puerto USB** (preferiblemente USB 2.0 o 3.0 directamente en la PC)\n"
            "5. Si usas un hub USB, conéctalo directamente a la computadora\n\n"
            "Si después de estos pasos sigue sin funcionar, visita tu tienda Nordik para revisión."
        ),
        "keywords": ["pendrive", "detecta", "no funciona", "usb", "reconocer", "error"],
        "category": "pendrive",
    },

    # ── Errores Comunes ───────────────────────────────────────────
    {
        "q": "Error al iniciar sesión: credenciales inválidas",
        "a": (
            "Si recibes un error de credenciales inválidas al iniciar sesión:\n\n"
            "1. **Verifica tu cédula:** Asegúrate de escribirla sin puntos ni espacios\n"
            "2. **Verifica tu contraseña:** Las mayúsculas y minúsculas importan\n"
            "3. **Confirma que tu suscripción está activa:** Las suscripciones vencidas no permiten acceso\n"
            "4. **Asegúrate de tener el pendrive conectado:** Es necesario para autenticación\n\n"
            "Si el problema persiste, visita tu tienda Nordik para verificar tu cuenta."
        ),
        "keywords": ["login", "iniciar sesion", "error", "credenciales", "invalidas", "no entra", "acceso"],
        "category": "account",
    },
    {
        "q": "La IA está bloqueada — alcancé el límite de consumo",
        "a": (
            "Has alcanzado el límite de consumo de IA de **$7.50 USD** para este mes. "
            "Mientras esté bloqueada, no podrás usar el chat, visión ni generación de imágenes.\n\n"
            "**¿Qué puedes hacer?**\n"
            "- Visitar tu **tienda Nordik más cercana** para recargar crédito IA\n"
            "- El límite se reinicia automáticamente el **primer día de cada mes**\n"
            "- Puedes seguir usando otras funciones: WhatsApp, Google, automatizaciones, archivos\n\n"
            "El personal de la tienda procesará tu recarga y el crédito se acreditará de inmediato."
        ),
        "keywords": ["bloqueado", "ia bloqueada", "limite", "consumo", "no puedo", "recargar"],
        "category": "billing",
    },
    {
        "q": "La aplicación se cierra inesperadamente",
        "a": (
            "Si la aplicación se cierra sola:\n\n"
            "1. **Reinicia tu computadora**\n"
            "2. **Asegúrate de tener Windows actualizado** (Windows 10 o superior)\n"
            "3. **Verifica que tienes suficiente espacio en disco** (mínimo 500 MB libres)\n"
            "4. **Desactiva temporalmente el antivirus** para descartar conflictos\n"
            "5. **Reinstala la aplicación** desde tu pendrive Nordik\n\n"
            "Si el problema persiste, contacta a soporte técnico en tu tienda Nordik."
        ),
        "keywords": ["cierra", "crash", "error", "no abre", "falla", "se cae"],
        "category": "technical",
    },

    # ── WhatsApp ──────────────────────────────────────────────────
    {
        "q": "¿Cómo configuro WhatsApp en Nordik IA?",
        "a": (
            "Para conectar WhatsApp con Nordik IA:\n\n"
            "1. Abre Nordik IA y ve a **WhatsApp** en el menú lateral\n"
            "2. Haz clic en **Conectar WhatsApp**\n"
            "3. Escanea el **código QR** que aparece con tu teléfono\n"
            "   (WhatsApp > Ajustes > Dispositivos vinculados > Vincular dispositivo)\n"
            "4. Una vez vinculado, podrás enviar y recibir mensajes desde Nordik IA\n\n"
            "**Nota:** Necesitas tener WhatsApp instalado en tu teléfono y conexión a internet."
        ),
        "keywords": ["whatsapp", "configurar", "vincular", "qr", "conectar", "wasap"],
        "category": "whatsapp",
    },
    {
        "q": "No recibo mensajes de WhatsApp en Nordik IA",
        "a": (
            "Si no recibes mensajes de WhatsApp:\n\n"
            "1. **Verifica la conexión:** Tu teléfono debe tener internet activo\n"
            "2. **Revisa la vinculación:** En WhatsApp del teléfono > Dispositivos vinculados, "
            "confirma que Nordik IA aparece\n"
            "3. **Reconecta:** Desvincula y vuelve a escanear el código QR\n"
            "4. **Reinicia la aplicación** Nordik IA\n\n"
            "Si el problema persiste, prueba cerrando y abriendo WhatsApp en tu teléfono primero."
        ),
        "keywords": ["whatsapp", "no recibo", "mensajes", "whatsapp no funciona", "vincular"],
        "category": "whatsapp",
    },

    # ── Google (Gmail / Calendar) ─────────────────────────────────
    {
        "q": "¿Cómo conecto mi cuenta de Google (Gmail/Calendar)?",
        "a": (
            "Para conectar tu cuenta de Google:\n\n"
            "1. Ve a **Configuración** o **Integraciones** en Nordik IA\n"
            "2. Selecciona **Conectar Google**\n"
            "3. Se abrirá una ventana de Google donde debes iniciar sesión\n"
            "4. **Acepta los permisos** solicitados (Gmail, Calendar)\n"
            "5. Una vez autorizado, Nordik IA podrá leer tus correos y gestionar tu calendario\n\n"
            "Puedes desconectar Google en cualquier momento desde la misma sección."
        ),
        "keywords": ["google", "gmail", "calendar", "conectar", "integracion", "correo"],
        "category": "google",
    },
    {
        "q": "Error al conectar Google: permiso denegado",
        "a": (
            "Si recibes un error de permisos al conectar Google:\n\n"
            "1. Asegúrate de **aceptar todos los permisos** que solicita Google\n"
            "2. Si usas una cuenta de Google Workspace (empresarial), "
            "tu administrador debe habilitar el acceso a apps de terceros\n"
            "3. **Revoca el acceso anterior** desde tu cuenta de Google: "
            "myaccount.google.com > Seguridad > Apps de terceros\n"
            "4. Intenta la conexión nuevamente desde Nordik IA\n\n"
            "Nordik IA solo accede a Gmail y Calendar con los permisos mínimos necesarios."
        ),
        "keywords": ["google", "permiso", "denegado", "error", "no conecta", "oauth"],
        "category": "google",
    },

    # ── Automatizaciones ──────────────────────────────────────────
    {
        "q": "¿Cómo creo una automatización?",
        "a": (
            "Para crear una automatización en Nordik IA:\n\n"
            "1. Ve a la sección **Automatizaciones** en el menú lateral\n"
            "2. Haz clic en **Nueva Automatización**\n"
            "3. Elige un **activador** (horario, evento de WhatsApp, nuevo correo, etc.)\n"
            "4. Configura la **acción** (enviar mensaje, generar reporte, crear recordatorio, etc.)\n"
            "5. **Guarda y activa** la automatización\n\n"
            "Puedes pausar, editar o eliminar automatizaciones en cualquier momento."
        ),
        "keywords": ["automatizacion", "crear", "configurar", "automatizar", "tarea automatica", "bot"],
        "category": "automations",
    },

    # ── Soporte y Contacto ────────────────────────────────────────
    {
        "q": "¿Cómo contacto a soporte técnico?",
        "a": (
            "Tienes varias formas de contactar a soporte Nordik:\n\n"
            "1. **Crear un ticket de soporte** desde la aplicación (Menú > Soporte > Nuevo ticket)\n"
            "2. **Visitar tu tienda Nordik** más cercana para atención presencial\n"
            "3. **Consultar las FAQs** desde la sección de Ayuda en la aplicación\n\n"
            "Recomendamos crear un ticket desde la app para un seguimiento más rápido. "
            "Nuestro equipo responde en un plazo de 24 horas hábiles."
        ),
        "keywords": ["contacto", "soporte", "ayuda", "tecnico", "atencion", "contactar", "hablar"],
        "category": "support",
    },
    {
        "q": "¿Tienen número de teléfono de soporte?",
        "a": (
            "Nordik IA no ofrece soporte telefónico directo. Nuestros canales de soporte son:\n\n"
            "- **Tickets de soporte** desde la aplicación (recomendado)\n"
            "- **Atención presencial** en tu tienda Nordik más cercana\n"
            "- **FAQs y ayuda integrada** en la aplicación\n\n"
            "El sistema de tickets nos permite dar seguimiento detallado a tu caso "
            "y mantener un historial de soluciones."
        ),
        "keywords": ["telefono", "numero", "llamar", "whatsapp soporte", "contacto directo"],
        "category": "support",
    },
]


# ─── Search Engine ────────────────────────────────────────────────────

_STOP_WORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "en",
    "con", "por", "para", "es", "son", "mi", "tu", "su", "me", "se", "no",
    "si", "que", "como", "cuando", "donde", "cual", "cuales", "quien", "hay",
    "tengo", "tiene", "puedo", "puede", "hacer", "hago", "hace", "esta", "estoy",
    "the", "a", "an", "is", "are", "do", "does", "can", "i", "my", "to",
}


def _tokenize(text: str) -> set[str]:
    """Tokeniza texto en palabras clave normalizadas (sin stop words, sin acentos)."""
    # Normalizar: minusculas, sin acentos
    normalized = text.lower()
    # Remover acentos simples (suficiente para FAQ)
    accent_map = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ü": "u", "ñ": "n",
    }
    for accented, plain in accent_map.items():
        normalized = normalized.replace(accented, plain)

    # Extraer palabras (alfanumericas + guiones)
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    # Remover stop words
    return tokens - _STOP_WORDS


def _score_match(query_tokens: set[str], faq_entry: dict) -> float:
    """
    Calcula un puntaje de coincidencia entre la query y una entrada FAQ.

    Factores:
    - Coincidencia exacta de tokens en la pregunta (peso 3)
    - Coincidencia exacta de tokens en keywords (peso 1)
    - Coincidencia parcial (substring) en la pregunta (peso 0.5)
    - Bonus por coincidencia en el campo "q" (peso 2 si >60% tokens coinciden)
    """
    score = 0.0

    q_text = faq_entry["q"].lower()
    keywords = faq_entry.get("keywords", [])

    # Coincidencias exactas en la pregunta
    q_tokens = _tokenize(q_text)
    exact_q_matches = query_tokens & q_tokens
    score += len(exact_q_matches) * 3.0

    # Coincidencias exactas en keywords
    kw_token_set = set()
    for kw in keywords:
        kw_token_set.update(_tokenize(kw))
    exact_kw_matches = query_tokens & kw_token_set
    score += len(exact_kw_matches) * 1.5

    # Coincidencias parciales (substring) en la pregunta
    for qt in query_tokens:
        if len(qt) >= 4 and qt in q_text:
            score += 0.5

    # Coincidencias parciales en keywords
    for qt in query_tokens:
        if len(qt) >= 4:
            for kw in keywords:
                if qt in kw.lower():
                    score += 0.3
                    break

    # Bonus: si mas del 60% de los tokens de la query coinciden en la pregunta
    if query_tokens and len(exact_q_matches) / len(query_tokens) >= 0.6:
        score += 2.0

    return score


def find_best_match(query: str, min_score: float = 1.0) -> Optional[dict]:
    """
    Encuentra la mejor coincidencia FAQ para una consulta.

    Args:
        query: Texto de la consulta del usuario
        min_score: Puntaje minimo para considerar una coincidencia valida

    Returns:
        Dict con la FAQ coincidente {"q", "a", "category", "score"} o None.
    """
    if not query or not query.strip():
        return None

    query_tokens = _tokenize(query)
    if not query_tokens:
        return None

    best_entry = None
    best_score = 0.0

    for entry in FAQ_DATABASE:
        score = _score_match(query_tokens, entry)
        if score > best_score:
            best_score = score
            best_entry = entry

    if best_entry and best_score >= min_score:
        return {
            "q": best_entry["q"],
            "a": best_entry["a"],
            "category": best_entry.get("category", "other"),
            "score": round(best_score, 2),
        }

    return None


def get_faq_response(query: str) -> dict:
    """
    Obtiene la respuesta FAQ para una consulta, con fallback si no hay match.

    Args:
        query: Texto de la consulta del usuario

    Returns:
        Dict con {"found": bool, "response": str, "category": str, "score": float}
    """
    match = find_best_match(query)

    if match:
        return {
            "found": True,
            "response": match["a"],
            "category": match["category"],
            "score": match["score"],
        }
    else:
        return {
            "found": False,
            "response": (
                "No encontré una respuesta automática para tu consulta. "
                "Puedes **crear un ticket de soporte** desde la aplicación "
                "para que nuestro equipo te ayude personalmente. "
                "Ve a Menú > Soporte > Nuevo ticket.\n\n"
                "También puedes visitar tu **tienda Nordik más cercana** para atención presencial."
            ),
            "category": "fallback",
            "score": 0,
        }


def suggest_related_faqs(query: str, limit: int = 3) -> list[dict]:
    """
    Sugiere FAQs relacionadas a una consulta.

    Args:
        query: Texto de la consulta
        limit: Maximo de sugerencias

    Returns:
        Lista de FAQs relacionadas (excluyendo la mejor coincidencia).
    """
    if not query or not query.strip():
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    scored = []
    best_q = None

    # Encontrar la mejor coincidencia primero para excluirla
    best_match = find_best_match(query, min_score=0)
    if best_match:
        best_q = best_match["q"]

    for entry in FAQ_DATABASE:
        score = _score_match(query_tokens, entry)
        if score > 0:
            scored.append({
                "q": entry["q"],
                "category": entry.get("category", "other"),
                "score": round(score, 2),
            })

    # Ordenar por score descendente
    scored.sort(key=lambda x: x["score"], reverse=True)

    # Excluir la mejor coincidencia
    if best_q:
        scored = [s for s in scored if s["q"] != best_q]

    return scored[:limit]
