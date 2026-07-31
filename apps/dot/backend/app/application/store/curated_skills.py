"""Catálogo curado de skills DOT (≥5) — instalables sin npm (BIBLIA §20)."""

from __future__ import annotations

from typing import Any

# Skills embebidas: fallback si Firestore store_skills está vacío (dev/demo).
CURATED_STORE_SKILLS: list[dict[str, Any]] = [
    {
        "id": "skill_alerta_dolar",
        "name": "Alerta dólar paralelo",
        "description": "Consulta diaria la tasa paralelo y notifica el valor.",
        "instruction": (
            "Consulta la tasa del dólar paralelo en Venezuela (Monitor Dólar / Binance P2P). "
            "Reporta el valor actual en 3–5 líneas y notifica."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "daily:09:00",
        "category": "Finanzas",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 5.0,
        "created_at": "2026-07-21T00:00:00Z",
    },
    {
        "id": "skill_resumen_gmail",
        "name": "Resumen Gmail mañana",
        "description": "Resume correos no leídos cada mañana.",
        "instruction": (
            "Revisa mis correos no leídos de Gmail. Agrupa por urgencia y dame hasta 10 ítems "
            "con remitente, asunto y acción sugerida. Notifica el resumen."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "daily:09:00",
        "category": "Productividad",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 5.0,
        "created_at": "2026-07-21T00:00:00Z",
    },
    {
        "id": "skill_agenda_dia",
        "name": "Agenda del día",
        "description": "Plan de reuniones de hoy desde Google Calendar.",
        "instruction": (
            "Revisa mi Google Calendar de hoy. Lista eventos con hora y título. "
            "Si no hay eventos, dilo claro. Notifica el plan."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "daily:09:00",
        "category": "Planificación",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 5.0,
        "created_at": "2026-07-21T00:00:00Z",
    },
    {
        "id": "skill_noticias_dolar",
        "name": "Alertas noticias dólar VE",
        "description": "Digest de noticias Venezuela/dólar.",
        "instruction": (
            "Busca noticias recientes sobre Venezuela dólar. Resume las 5 más relevantes "
            "con título y una frase. Notifica el digest."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "daily:18:00",
        "category": "Noticias",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 4.5,
        "created_at": "2026-07-21T00:00:00Z",
        "backend_provisioned": True,
        "backend_key": "newsapi",
        "requires_user_api_key": False,
    },
    {
        "id": "skill_computrabajo",
        "name": "Monitor ofertas Computrabajo",
        "description": "Ofertas de asistente administrativo en Caracas.",
        "instruction": (
            "Busca en Computrabajo Venezuela ofertas de asistente administrativo en Caracas. "
            "Lista hasta 5 con título y empresa. Notifica el resumen."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "weekly:mon:09:00",
        "category": "Empleo",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 4.5,
        "created_at": "2026-07-21T00:00:00Z",
    },
    {
        "id": "skill_cv_lunes",
        "name": "CV y empleo (lunes)",
        "description": (
            "Lee tu CV en PDF, resume habilidades y experiencia, y te avisa por WhatsApp. "
            "Caso estrella de DOT — sin terminal."
        ),
        "instruction": (
            "Cada ejecución:\n"
            "1) Busca el CV del usuario con file_search (nombre típico: cv, curriculum, hoja de vida) "
            "en Escritorio/Documentos/Descargas, o usa la ruta que el usuario haya indicado antes.\n"
            "2) Analiza el CV con analyze_cv (PDF/DOCX/TXT).\n"
            "3) Resume en español claro (máx 12 líneas): nombre, contacto, top habilidades, "
            "años/experiencia relevante y 1 sugerencia accionable (p. ej. actualizar sección X).\n"
            "4) Notifica el resumen por WhatsApp al dueño (notify_whatsapp_owner).\n"
            "Si no encuentras CV, dilo claro y sugiere guardarlo en ~/Desktop con nombre cv.pdf.\n"
            "No inventes datos; solo lo extraído del documento."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "weekly:mon:09:00",
        "category": "Empleo",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 5.0,
        "created_at": "2026-07-24T00:00:00Z",
    },
    {
        "id": "skill_citas_wa",
        "name": "Citas desde WhatsApp",
        "description": "Si confirman cita por WA, actúa (Calendar/aviso).",
        "instruction": (
            "Lee mensajes recientes de WhatsApp. Si alguien confirma fecha/hora de cita, "
            "crea el evento en Calendar y resume qué creaste. Si no hay confirmaciones, dilo."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "manual",
        "category": "WhatsApp",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 5.0,
        "created_at": "2026-07-21T00:00:00Z",
    },
    {
        "id": "skill_briefing_diario",
        "name": "Briefing de vida (mañana)",
        "description": (
            "Te dice qué pasó ayer, qué falta hoy y qué viene mañana — "
            "como un jefe de gabinete digital, sin terminal."
        ),
        "instruction": (
            "Eres el asistente de vida diaria del usuario. Genera un briefing corto y accionable:\n"
            "1) QUÉ HICISTE / QUÉ PASÓ: revisa Calendar de ayer y hoy, correos urgentes no leídos "
            "(Gmail si hay permiso), y notas relevantes si existen.\n"
            "2) QUÉ TE FALTA HOY: lista 3–7 pendientes claros (reuniones, respuestas, tareas "
            "implícitas en mails). Si no hay datos, dilo y sugiere 2 acciones concretas.\n"
            "3) MAÑANA: anticipa 1–3 cosas que no debe olvidar.\n"
            "4) AUTOMATIZACIONES: con auto_list_active, menciona si alguna falló o está pausada.\n"
            "Tono: claro, humano, sin jerga técnica. Máximo ~25 líneas. Notifica el resumen."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "daily:07:30",
        "category": "Productividad",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 5.0,
        "created_at": "2026-07-21T00:00:00Z",
    },
    {
        "id": "skill_atencion_cliente_dot",
        "name": "Atención al cliente DOT",
        "description": (
            "Responde dudas de producto DOT (precios, pendrive, WhatsApp, Google, límites) "
            "con tono amable — ideal para el día de apertura y soporte."
        ),
        "instruction": (
            "Eres el agente de atención al cliente de DOT (Nordik-IA), asistente de escritorio "
            "Windows con IA, WhatsApp, Gmail/Calendar y automatizaciones. Público: personas "
            "normales (profesores, emprendedores), NO desarrolladores.\n"
            "Reglas:\n"
            "- Responde en español claro, sin terminal ni jerga.\n"
            "- Si preguntan por OpenClaw/ChatGPT: DOT es un agente que actúa en su PC "
            "(automatiza, resume el día, responde WhatsApp), no solo un chat.\n"
            "- Capacidades: chat IA, WhatsApp local, Google, automatizaciones programadas, "
            "visión/imágenes según plan; límite de uso IA mensual; auth con cédula + pendrive.\n"
            "- Si no sabes un dato de precio/tienda exacto, di que lo confirmen en el canal "
            "oficial / tienda y ofrece pasos seguros (no inventes números).\n"
            "- Nunca pidas contraseñas ni seriales por chat. Nunca ejecutes acciones peligrosas.\n"
            "- Cierra ofreciendo: '¿Quieres que te cree una automatización para X?' y usa "
            "auto_create si el usuario confirma.\n"
            "Formato: respuesta corta (máx ~15 líneas) + 1 CTA claro."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "manual",
        "category": "Negocio",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 5.0,
        "created_at": "2026-07-21T00:00:00Z",
    },
    # ─── SK05 — Traductor instantáneo (gratis) ───
    {
        "id": "skill_translate_text",
        "name": "Traductor instantáneo EN↔ES",
        "description": "Traduce texto entre inglés y español usando el LLM de DOT. Ideal para correos, documentos y redes sociales.",
        "instruction": (
            "Eres un traductor bilingüe inglés-español. Traduce el texto de entrada al idioma "
            "opuesto con estas reglas:\n"
            "- Si el texto está en español, tradúcelo a inglés.\n"
            "- Si está en inglés, tradúcelo a español.\n"
            "- Si está en otro idioma, tradúcelo a español.\n"
            "- Mantén el tono, formalidad y estilo del original.\n"
            "- Para correos: conserva saludos y despedidas apropiados.\n"
            "- Para contenido técnico: traduce términos comunes, mantén siglas.\n"
            "- Entrega solo la traducción, sin explicaciones ni notas.\n"
            "Notifica el resultado."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "manual",
        "category": "Herramientas",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 5.0,
        "created_at": "2026-07-24T00:00:00Z",
    },
    # ─── SK06 — Resumir página web (gratis) ───
    {
        "id": "skill_resumir_web",
        "name": "Resumir página web",
        "description": "Extrae y resume el contenido de una URL. Ideal para artículos largos, noticias y documentación.",
        "instruction": (
            "Lee el contenido de la URL proporcionada y genera un resumen ejecutivo:\n"
            "1) TÍTULO: título o encabezado principal de la página.\n"
            "2) RESUMEN (3-5 líneas): idea central en lenguaje claro.\n"
            "3) PUNTOS CLAVE: 3-7 bullets con datos, cifras o conclusiones importantes.\n"
            "4) ACCIÓN SUGERIDA: una recomendación concreta (leer completo, guardar, compartir, ignorar).\n"
            "Si la URL no carga o no se puede leer, dilo claro y sugiere copiar/pegar el texto.\n"
            "Tono: neutral, informativo. Máximo ~15 líneas. Notifica el resumen."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "manual",
        "category": "Productividad",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 4.5,
        "created_at": "2026-07-24T00:00:00Z",
    },
    # ─── SK07 — Buscador MercadoLibre (AU-SK) ───
    {
        "id": "skill_mercadolibre_search",
        "name": "Buscador MercadoLibre",
        "description": "Busca productos en MercadoLibre Venezuela por nombre o URL, extrae precio, título, vendedor y calificación.",
        "instruction": (
            "Busca productos en MercadoLibre Venezuela (mercadolibre.com.ve) según el nombre o URL "
            "proporcionada por el usuario. Para cada producto encontrado, extrae:\n"
            "1) NOMBRE: título completo del producto.\n"
            "2) PRECIO: monto en Bs o USD (indicar moneda).\n"
            "3) VENDEDOR: nombre de la tienda o vendedor.\n"
            "4) CALIFICACIÓN: estrellas o rating si está disponible.\n"
            "5) ENLACE: URL directa al producto.\n"
            "Muestra hasta 5 resultados ordenados por precio (menor a mayor).\n"
            "Si la búsqueda no arroja resultados, sugiere términos alternativos.\n"
            "Tono: directo, útil para compras. Notifica el resultado."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "manual",
        "category": "Compras",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 4.0,
        "created_at": "2026-07-24T00:00:00Z",
    },
    # ─── SK08 — Asistente de viajes (AU-SK) ───
    {
        "id": "skill_travel_search",
        "name": "Asistente de viajes",
        "description": "Busca vuelos y hoteles usando la web, compara precios y sugiere itinerarios optimizados.",
        "instruction": (
            "Eres un asistente de viajes virtual. Usa búsqueda web para encontrar vuelos, hoteles "
            "y transporte según el destino y fechas del usuario.\n"
            "Reglas:\n"
            "1) VUELOS: busca en Google Flights, Skyscanner o Kayak. Lista 3-5 opciones con aerolínea, "
            "precio estimado, escalas y duración.\n"
            "2) HOTELES: busca en Booking o Google Hotels. Lista 3-5 opciones con nombre, precio "
            "por noche, ubicación y calificación.\n"
            "3) ITINERARIO: sugiere un plan día a día con actividades recomendadas y tiempos "
            "de traslado estimados.\n"
            "4) CONSEJOS: incluye datos útiles (clima, moneda, documentos necesarios, propinas).\n"
            "Si no encuentras disponibilidad, ofrece alternativas (fechas cercanas, destinos similares).\n"
            "Tono: entusiasta y práctico. Máximo ~25 líneas. Notifica el resultado."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "manual",
        "category": "Viajes",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 4.5,
        "created_at": "2026-07-24T00:00:00Z",
    },
    # ─── SK10 — Clima diario (backend OpenWeather, sin clave del usuario) ───
    {
        "id": "skill_clima_diario",
        "name": "Clima de tu ciudad",
        "description": (
            "Cada mañana te dice el clima actual de tu ciudad. "
            "DOT usa su propia conexión — tú no configuras nada."
        ),
        "instruction": (
            "Consulta el clima actual de la ciudad del usuario con web_get_weather. "
            "Si no conoces su ciudad, usa Caracas o la que figure en su memoria/perfil. "
            "Resume en 4–6 líneas: temperatura, sensación, condición, humedad y viento. "
            "Tono claro y humano. Notifica el resumen."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "daily:07:00",
        "category": "Clima",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 5.0,
        "created_at": "2026-07-24T00:00:00Z",
        "backend_provisioned": True,
        "backend_key": "openweather",
        "requires_user_api_key": False,
    },
    # ─── SK11 — Noticias del día (backend NewsAPI + RSS, sin clave del usuario) ───
    {
        "id": "skill_noticias_diarias",
        "name": "Noticias del día",
        "description": (
            "Un digest matutino con las noticias más relevantes de Venezuela. "
            "Listo al agregar — sin registrarte en ningún sitio."
        ),
        "instruction": (
            "Busca noticias recientes sobre Venezuela con monitor_news_keyword. "
            "Resume las 5 más relevantes con título, fuente y una frase cada una. "
            "Tono informativo, sin sensacionalismo. Notifica el digest."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "daily:08:00",
        "category": "Noticias",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 4.5,
        "created_at": "2026-07-24T00:00:00Z",
        "backend_provisioned": True,
        "backend_key": "newsapi",
        "requires_user_api_key": False,
    },
    # ─── SK09 — Monitor de redes sociales (AU-SK) ───
    {
        "id": "skill_social_monitor",
        "name": "Monitor de redes sociales",
        "description": "Monitorea menciones y novedades en Twitter/X e Instagram de cuentas o hashtags configurados por el usuario.",
        "instruction": (
            "Eres un monitor de redes sociales. Busca y resume actividad reciente en Twitter/X e "
            "Instagram según las cuentas o hashtags que el usuario configure.\n"
            "Reglas:\n"
            "1) TWITTER/X: busca tweets recientes de las cuentas indicadas o con los hashtags "
            "especificados. Resume los 5 más relevantes con autor, contenido y fecha.\n"
            "2) INSTAGRAM: busca posts recientes de las cuentas indicadas. Describe el contenido "
            "visual, hashtags usados y engagement si está disponible.\n"
            "3) TENDENCIAS: si se solicitan trending topics, lista los 5 más relevantes "
            "con breve contexto.\n"
            "4) ALERTAS: si detectas contenido negativo, crisis de reputación o noticias "
            "urgentes relacionadas con las cuentas monitoreadas, márcalo con ⚠️ ALERTA.\n"
            "Usa búsqueda web como fuente principal (Twitter/X e Instagram pueden limitar "
            "acceso sin API). Si no puedes acceder directamente, usa fuentes alternativas.\n"
            "Tono: profesional, tipo informe ejecutivo. Máximo ~20 líneas. Notifica el resultado."
        ),
        "integration_id": "third-option",
        "output_type": "notify",
        "schedule": "manual",
        "category": "Redes Sociales",
        "author_name": "DOT",
        "installs_count": 0,
        "rating": 4.0,
        "created_at": "2026-07-24T00:00:00Z",
    },
]


def get_curated_skill(skill_id: str) -> dict[str, Any] | None:
    for s in CURATED_STORE_SKILLS:
        if s["id"] == skill_id:
            return dict(s)
    return None


def list_curated_skills(
    *,
    category: str | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    q = (search or "").strip().lower()
    cat = (category or "").strip().lower()
    for s in CURATED_STORE_SKILLS:
        if cat and str(s.get("category", "")).lower() != cat:
            continue
        if q:
            blob = f"{s.get('name', '')} {s.get('description', '')}".lower()
            if q not in blob:
                continue
        out.append(dict(s))
    return out


def list_curated_skills_by_category() -> dict[str, list[dict[str, Any]]]:
    """Agrupa todas las skills curadas por categoría.

    Útil para mostrar el catálogo organizado en la UI del store o dashboard.

    Returns:
        Dict donde cada clave es una categoría y el valor es la lista de skills
        en esa categoría, ordenadas por rating descendente.
    """
    result: dict[str, list[dict[str, Any]]] = {}
    for s in CURATED_STORE_SKILLS:
        cat = str(s.get("category", "Sin categoría"))
        if cat not in result:
            result[cat] = []
        result[cat].append(dict(s))

    # Ordenar skills dentro de cada categoría por rating descendente
    for skills in result.values():
        skills.sort(key=lambda x: x.get("rating", 0.0), reverse=True)

    return result
