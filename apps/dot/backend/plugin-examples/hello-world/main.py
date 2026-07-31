"""Hello World Plugin — ejemplo mínimo del SDK de plugins Nordik-IA.

Demuestra:
  - Decorador @plugin_tool
  - Registro automático en ToolRegistry
  - Manejo de argumentos
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Asegurar que el SDK del backend esté en el path
_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.plugin_sdk import plugin_tool


@plugin_tool(
    name="hello_world",
    description="Saluda al usuario por su nombre. Plugin de ejemplo del SDK Nordik-IA.",
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Nombre de la persona a saludar. Si no se provee, saluda al mundo.",
            },
            "language": {
                "type": "string",
                "description": "Idioma del saludo (es, en, fr, de, it, pt). Default: es.",
            },
        },
    },
)
def hello_world(uid: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Handler de la tool hello_world."""
    name = arguments.get("name", "Mundo")
    language = arguments.get("language", "es").lower()

    greetings = {
        "es": f"¡Hola, {name}! Bienvenido a Nordik-IA.",
        "en": f"Hello, {name}! Welcome to Nordik-IA.",
        "fr": f"Bonjour, {name}! Bienvenue sur Nordik-IA.",
        "de": f"Hallo, {name}! Willkommen bei Nordik-IA.",
        "it": f"Ciao, {name}! Benvenuto su Nordik-IA.",
        "pt": f"Olá, {name}! Bem-vindo ao Nordik-IA.",
    }

    message = greetings.get(language, greetings["es"])
    return {
        "ok": True,
        "output": message,
        "error": None,
        "artifacts": [],
    }
