"""Tools de entretenimiento y utilidades — F6."""
from __future__ import annotations

import logging
from typing import Any

from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.entertainment")


def entertainment_movie_info_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        title = str(arguments.get("title") or arguments.get("query") or "").strip()
        if not title:
            return ToolResult(ok=False, output="", error="Falta titulo de pelicula.")
        result = route_chat(
            f"Informacion de la pelicula '{title}': reparto principal, director, año, genero, rating IMDb, sinopsis breve.",
            provider_id="deepseek",
            system_prompt="Responde en espanol con datos concisos.",
        )
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def entertainment_book_recommend_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        genre = str(arguments.get("genre") or "").strip()
        author = str(arguments.get("author") or "").strip()
        prompt = "Recomienda 3 libros"
        if genre: prompt += f" del genero {genre}"
        if author: prompt += f" similares a {author}"
        result = route_chat(prompt, provider_id="deepseek", system_prompt="Responde en espanol, titulo + autor + 1 frase de por que. Lista numerada.")
        return ToolResult(ok=True, output=result.strip()[:600])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def entertainment_recipe_find_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        ingredients = str(arguments.get("ingredients") or arguments.get("query") or "").strip()
        if not ingredients:
            return ToolResult(ok=False, output="", error="Falta ingredientes disponibles.")
        result = route_chat(
            f"Receta que use: {ingredients}. Incluye ingredientes, pasos (5 max) y tiempo.",
            provider_id="deepseek",
            system_prompt="Recetas en espanol, practicas, con ingredientes y pasos. Se breve.",
        )
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def entertainment_trivia_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        topic = str(arguments.get("topic") or "cultura general").strip()
        count = min(int(arguments.get("count") or 5), 10)
        result = route_chat(
            f"Genera {count} preguntas de trivia sobre {topic}. Con 4 opciones (A,B,C,D) y respuesta correcta al final.",
            provider_id="deepseek",
            system_prompt="Trivia en espanol. Formato: pregunta + 4 opciones + respuesta correcta. Se breve.",
        )
        return ToolResult(ok=True, output=result.strip()[:1000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def entertainment_lyrics_find_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        query = str(arguments.get("query") or arguments.get("song") or "").strip()
        if not query:
            return ToolResult(ok=False, output="", error="Falta cancion o artista.")
        result = route_chat(
            f"Letra completa (o fragmento principal) de: {query}",
            provider_id="deepseek",
            system_prompt="Comparte la letra en espanol o idioma original. Fragmentos representativos si no tienes la letra completa.",
        )
        return ToolResult(ok=True, output=result.strip()[:1500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def util_random_picker_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        import random
        items = arguments.get("items") or arguments.get("options") or []
        if isinstance(items, str):
            items = [i.strip() for i in items.split(",") if i.strip()]
        if not items:
            return ToolResult(ok=False, output="", error="Falta lista de items.")
        picked = random.choice(items)
        return ToolResult(ok=True, output=f"Elegido: {picked}")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def util_countdown_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from datetime import datetime, timezone
        date_str = str(arguments.get("date") or "").strip()
        event = str(arguments.get("event") or "el evento").strip()
        if not date_str:
            return ToolResult(ok=False, output="", error="Falta fecha (ISO o DD/MM/YYYY).")
        target = datetime.fromisoformat(date_str[:19])
        now = datetime.now(timezone.utc)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        diff = target - now
        if diff.total_seconds() <= 0:
            return ToolResult(ok=True, output=f"{event} ya paso.")
        days = diff.days
        hours, rem = divmod(diff.seconds, 3600)
        mins = rem // 60
        return ToolResult(ok=True, output=f"Faltan {days} dias, {hours} horas y {mins} minutos para {event}.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def util_unit_convert_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        value = float(arguments.get("value") or 0)
        from_unit = str(arguments.get("from") or "").strip().lower()
        to_unit = str(arguments.get("to") or "").strip().lower()
        if not from_unit or not to_unit:
            return ToolResult(ok=False, output="", error="Falta from/to unidades.")

        conversions = {
            ("km", "mi"): value * 0.621371,
            ("mi", "km"): value * 1.60934,
            ("kg", "lb"): value * 2.20462,
            ("lb", "kg"): value * 0.453592,
            ("c", "f"): value * 9/5 + 32,
            ("f", "c"): (value - 32) * 5/9,
            ("cm", "in"): value * 0.393701,
            ("in", "cm"): value * 2.54,
            ("m", "ft"): value * 3.28084,
            ("ft", "m"): value * 0.3048,
        }
        result = conversions.get((from_unit, to_unit))
        if result is None:
            return ToolResult(ok=False, output="", error=f"Conversion {from_unit}->{to_unit} no soportada.")
        return ToolResult(ok=True, output=f"{value} {from_unit} = {result:.2f} {to_unit}")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def util_barcode_info_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        barcode = str(arguments.get("barcode") or arguments.get("code") or "").strip()
        if not barcode:
            return ToolResult(ok=False, output="", error="Falta codigo de barras.")
        result = route_chat(
            f"Informacion del producto con codigo de barras {barcode}. Nombre, marca, categoria, precio estimado si es conocido.",
            provider_id="deepseek",
            system_prompt="Responde con datos del producto en espanol. Si no conoces el codigo, dilo honestamente."
        )
        return ToolResult(ok=True, output=result.strip()[:500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def util_color_palette_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        theme = str(arguments.get("theme") or arguments.get("description") or "moderno").strip()
        result = route_chat(
            f"Genera una paleta de 5 colores con tema '{theme}'. Da hex codes y nombres descriptivos.",
            provider_id="deepseek",
            system_prompt="Responde con 5 colores hex + nombre. Se breve."
        )
        return ToolResult(ok=True, output=result.strip()[:400])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


TOOLS = [
    # ⚠️ FAKE: entertainment_movie_info alucina datos de películas sin API real (route_chat)
    # ("entertainment_movie_info", entertainment_movie_info_handler),
    # ⚠️ FAKE: entertainment_book_recommend alucina recomendaciones sin API de libros (route_chat)
    # ("entertainment_book_recommend", entertainment_book_recommend_handler),
    # ⚠️ FAKE: entertainment_recipe_find alucina recetas sin API culinaria (route_chat)
    # ("entertainment_recipe_find", entertainment_recipe_find_handler),
    # ⚠️ FAKE: entertainment_trivia alucina preguntas sin API de trivia (route_chat)
    # ("entertainment_trivia", entertainment_trivia_handler),
    # ⚠️ FAKE: entertainment_lyrics_find alucina letras sin API de música (route_chat)
    # ("entertainment_lyrics_find", entertainment_lyrics_find_handler),
    ("util_random_picker", util_random_picker_handler),
    ("util_countdown", util_countdown_handler),
    ("util_unit_convert", util_unit_convert_handler),
    # ⚠️ FAKE: util_barcode_info alucina información de códigos de barras sin API real (route_chat)
    # ("util_barcode_info", util_barcode_info_handler),
    # ⚠️ FAKE: util_color_palette alucina paletas sin API de color real (route_chat)
    # ("util_color_palette", util_color_palette_handler),
]
