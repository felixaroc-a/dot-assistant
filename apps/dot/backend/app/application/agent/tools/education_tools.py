"""Tools de educacion — P0-P1."""
from __future__ import annotations
import logging
from typing import Any
from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.education")


def edu_course_finder_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        topic = str(arguments.get("topic") or "").strip()
        level = str(arguments.get("level") or "principiante").strip()
        if not topic:
            return ToolResult(ok=False, output="", error="Falta topic.")
        result = route_chat(f"Busca 5 cursos online de {topic} nivel {level}. Incluye plataforma, duracion, costo y link si es conocido. Prioriza Coursera, Udemy, edX, YouTube.", provider_id="deepseek", system_prompt="Recomendaciones de cursos en espanol. Datos reales o indica si no puedes buscar en tiempo real.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def edu_study_plan_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        subject = str(arguments.get("subject") or "").strip()
        days = int(arguments.get("days") or 7)
        hours_per_day = int(arguments.get("hours_per_day") or 2)
        if not subject:
            return ToolResult(ok=False, output="", error="Falta subject.")
        result = route_chat(f"Plan de estudio de {days} dias para {subject}. {hours_per_day}h/dia. Incluye temas por dia, ejercicios y tecnicas (Pomodoro, spaced repetition).", provider_id="deepseek", system_prompt="Plan de estudio en espanol, practico y realista.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def edu_summarize_book_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        title = str(arguments.get("title") or "").strip()
        if not title:
            return ToolResult(ok=False, output="", error="Falta titulo del libro.")
        result = route_chat(f"Resumen estructurado del libro '{title}': ideas principales, personajes clave (si ficcion), lecciones, aplicaciones practicas. 3-5 parrafos.", provider_id="deepseek", system_prompt="Resumen de libro en espanol, util y directo.")
        return ToolResult(ok=True, output=result.strip()[:1000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def edu_flashcard_generator_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        topic = str(arguments.get("topic") or "").strip()
        count = min(int(arguments.get("count") or 20), 50)
        if not topic:
            return ToolResult(ok=False, output="", error="Falta topic.")
        result = route_chat(f"Genera {count} flashcards sobre {topic}. Formato: Q: pregunta | A: respuesta. Una por linea.", provider_id="deepseek", system_prompt="Flashcards en espanol. Formato Q: ... | A: ...")
        from app.application.agent.tools.local_files import execute_local_tool_via_bridge
        path = f"~/Desktop/Flashcards_{topic.replace(' ','_')[:20]}.txt"
        execute_local_tool_via_bridge("writeFile", path=path, content=result.strip())
        return ToolResult(ok=True, output=f"{count} flashcards generadas sobre {topic}.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def edu_exam_simulator_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        topic = str(arguments.get("topic") or "").strip()
        qty = min(int(arguments.get("questions") or 15), 30)
        if not topic:
            return ToolResult(ok=False, output="", error="Falta topic.")
        result = route_chat(f"Examen de practica de {qty} preguntas sobre {topic}. Incluye 70% opcion multiple (A,B,C,D) y 30% desarrollo. Con respuestas correctas y explicacion breve al final.", provider_id="deepseek", system_prompt="Examen en espanol con respuestas. Claro y didactico.")
        return ToolResult(ok=True, output=result.strip()[:2000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def edu_language_tutor_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        lang = str(arguments.get("language") or "ingles").strip()
        level = str(arguments.get("level") or "basico").strip()
        qty = min(int(arguments.get("exercises") or 5), 10)
        result = route_chat(f"Genera {qty} ejercicios de {lang} nivel {level}. Incluye vocabulario, gramatica y frases de conversacion practica.", provider_id="deepseek", system_prompt="Ejercicios de idiomas en espanol. Practicos y variados.")
        return ToolResult(ok=True, output=result.strip()[:1000])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def edu_certification_path_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        career = str(arguments.get("career") or "").strip()
        if not career:
            return ToolResult(ok=False, output="", error="Falta carrera o profesion objetivo.")
        result = route_chat(f"Roadmap de certificaciones para {career}. Orden recomendado, costo estimado, tiempo, ROI. 5-8 certificaciones clave.", provider_id="deepseek", system_prompt="Roadmap de certificaciones en espanol. Datos realistas.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def edu_kids_homeschool_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        age = int(arguments.get("age") or 7)
        subjects = str(arguments.get("subjects") or "matematicas, lenguaje, ciencias").strip()
        result = route_chat(f"Plan semanal de homeschool para nino de {age} anos. Materias: {subjects}. Incluye actividades, juegos y recursos gratuitos.", provider_id="deepseek", system_prompt="Plan educativo en espanol, divertido y practico para ninos.")
        return ToolResult(ok=True, output=result.strip()[:800])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


# ⚠️ MÓDULO 100% FAKE — tools solo generan texto con LLM, no ejecutan acciones reales. Deshabilitado hasta migrar a APIs reales.
TOOLS = [
    # ("edu_course_finder", edu_course_finder_handler),
    # ("edu_study_plan", edu_study_plan_handler),
    # ("edu_summarize_book", edu_summarize_book_handler),
    # ("edu_flashcard_generator", edu_flashcard_generator_handler),
    # ("edu_exam_simulator", edu_exam_simulator_handler),
    # ("edu_language_tutor", edu_language_tutor_handler),
    # ("edu_certification_path", edu_certification_path_handler),
    # ("edu_kids_homeschool", edu_kids_homeschool_handler),
]
