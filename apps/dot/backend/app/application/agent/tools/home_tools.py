"""Tools de hogar y vida cotidiana — P2."""
from __future__ import annotations
import logging
from typing import Any
from app.application.agent.ports import ToolResult

log = logging.getLogger("dot.agent.tools.home")


def home_meal_planner_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        from app.services.provider_router import route_chat
        diet = str(arguments.get("diet") or "normal").strip()
        people = int(arguments.get("people") or 2)
        days = min(int(arguments.get("days") or 7), 14)
        result = route_chat(f"Menu semanal para {people} personas, dieta {diet}, {days} dias. Incluye desayuno, almuerzo, cena y lista de compras organizada.", provider_id="deepseek", system_prompt="Menu y lista de compras en espanol. Practico.")
        return ToolResult(ok=True, output=result.strip()[:1500])
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def home_shopping_list_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        items_text = str(arguments.get("items") or "").strip()
        if items_text:
            items = [i.strip() for i in items_text.split(",")]
        else:
            items = ["leche", "huevos", "pan", "frutas", "verduras"]
        cats = {"lacteos": [], "carnes": [], "frutas_verduras": [], "despensa": [], "limpieza": [], "otros": []}
        keyword_map = {"leche": "lacteos", "queso": "lacteos", "yogur": "lacteos", "huevos": "lacteos", "mantequilla": "lacteos", "pollo": "carnes", "carne": "carnes", "pescado": "carnes", "cerdo": "carnes", "manzana": "frutas_verduras", "tomate": "frutas_verduras", "cebolla": "frutas_verduras", "lechuga": "frutas_verduras", "zanahoria": "frutas_verduras", "arroz": "despensa", "pasta": "despensa", "aceite": "despensa", "sal": "despensa", "azucar": "despensa", "jabon": "limpieza", "detergente": "limpieza", "cloro": "limpieza"}
        for item in items:
            found = False
            for kw, cat in keyword_map.items():
                if kw in item.lower():
                    cats[cat].append(item)
                    found = True
                    break
            if not found:
                cats["otros"].append(item)
        lines = ["Lista de compras organizada:"]
        for cat, its in cats.items():
            if its:
                lines.append(f"\n{cat.replace('_',' ').title()}:")
                lines.extend(f"  - {i}" for i in its)
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def home_bill_tracker_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        service = str(arguments.get("service") or "").strip()
        amount = float(arguments.get("amount") or 0)
        due_date = str(arguments.get("due_date") or "").strip()
        if not service or amount <= 0:
            return ToolResult(ok=False, output="", error="Falta servicio y monto.")
        from datetime import datetime
        msg = f"Servicio: {service} | Monto: {amount:.2f} | Vence: {due_date or 'no especificado'}"
        return ToolResult(ok=True, output=f"Gasto registrado: {msg}. Usa schedule_reminder para alerta de vencimiento.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def home_chore_scheduler_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        members = arguments.get("members") or ["Persona 1", "Persona 2"]
        if isinstance(members, str):
            members = [m.strip() for m in members.split(",")]
        chores = arguments.get("chores") or ["cocina", "limpieza", "basura", "lavanderia", "compra"]
        if isinstance(chores, str):
            chores = [c.strip() for c in chores.split(",")]
        import random
        schedule = {}
        for i, chore in enumerate(chores):
            schedule[chore] = members[i % len(members)]
        lines = ["Asignacion de tareas:"]
        for chore, member in schedule.items():
            lines.append(f"  {chore}: {member}")
        lines.append("\nUsa schedule_reminder para recordatorios diarios.")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def home_pet_care_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    try:
        pet = str(arguments.get("pet") or "perro").strip()
        age = int(arguments.get("age") or 1)
        result = f"Calendario de cuidados para {pet} de {age} anios:\n- Vacunas anuales\n- Desparasitacion cada 3 meses\n- Bano cada 2-4 semanas\n- Alimento diario segun peso\n- Visita veterinaria anual\n\nUsa schedule_reminder para recordatorios."
        return ToolResult(ok=True, output=result)
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


TOOLS = [
    ("home_meal_planner", home_meal_planner_handler),
    ("home_shopping_list", home_shopping_list_handler),
    ("home_bill_tracker", home_bill_tracker_handler),
    ("home_chore_scheduler", home_chore_scheduler_handler),
    ("home_pet_care", home_pet_care_handler),
]
