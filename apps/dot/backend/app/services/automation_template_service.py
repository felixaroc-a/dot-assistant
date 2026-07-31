"""Servicio de plantillas reutilizables de automatizaciones (C3).

Gestiona plantillas públicas de pipelines/automatizaciones en Firestore
colección raíz `templates`. Los usuarios pueden guardar sus automatizaciones
como templates públicos y clonar templates de otros.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from firebase_admin import firestore as firestore_admin
from app.firebase_db import get_db

log = logging.getLogger("dot.automation_templates")

FIRESTORE_COLLECTION = "templates"

DEFAULT_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "Revisar Gmail diario",
        "description": "Cada mañana revisa tu bandeja de Gmail, busca correos importantes y te notifica por WhatsApp con un resumen.",
        "category": "Productividad",
        "schedule": "daily:08:00",
        "workflow_def": {
            "name": "Revisar Gmail diario",
            "description": "Revisa Gmail cada mañana y notifica por WhatsApp",
            "schedule": "daily:08:00",
            "active": True,
            "steps": [
                {
                    "id": "step_1", "type": "action", "integration": "gmail",
                    "instruction": "Buscar correos no leídos de las últimas 24 horas",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": [], "on_failure": "log", "timeout_seconds": 30
                },
                {
                    "id": "step_2", "type": "action", "integration": "chat",
                    "instruction": "Resumir los correos encontrados en 2-3 frases destacando los más importantes",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": ["step_1"], "on_failure": "log", "timeout_seconds": 30
                },
                {
                    "id": "step_3", "type": "output", "integration": "whatsapp",
                    "instruction": "Enviar el resumen al usuario por WhatsApp",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": ["step_2"], "on_failure": "log", "timeout_seconds": 30
                }
            ],
            "source_nl": "Cada mañana revisa mi Gmail, busca correos importantes y avísame por WhatsApp con un resumen"
        }
    },
    {
        "name": "Resumen semanal por WhatsApp",
        "description": "Cada viernes revisa tu calendario de Google, resume la próxima semana y te lo envía por WhatsApp.",
        "category": "Planificación",
        "schedule": "weekly:fri:17:00",
        "workflow_def": {
            "name": "Resumen semanal por WhatsApp",
            "description": "Resumen semanal de calendario enviado por WhatsApp",
            "schedule": "weekly:fri:17:00",
            "active": True,
            "steps": [
                {
                    "id": "step_1", "type": "action", "integration": "google-calendar",
                    "instruction": "Consultar eventos de la próxima semana (lunes a domingo)",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": [], "on_failure": "log", "timeout_seconds": 30
                },
                {
                    "id": "step_2", "type": "action", "integration": "chat",
                    "instruction": "Generar un resumen organizado por día con los eventos importantes de la próxima semana",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": ["step_1"], "on_failure": "log", "timeout_seconds": 30
                },
                {
                    "id": "step_3", "type": "output", "integration": "whatsapp",
                    "instruction": "Enviar el resumen semanal al usuario por WhatsApp",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": ["step_2"], "on_failure": "log", "timeout_seconds": 30
                }
            ],
            "source_nl": "Cada viernes revisa mi calendario de Google, resume la próxima semana y envíamelo por WhatsApp"
        }
    },
    {
        "name": "Backup de documentos a carpeta",
        "description": "Busca PDFs y documentos en tu Gmail y los guarda automáticamente en tu carpeta DOT Trabajos.",
        "category": "Archivos",
        "schedule": "manual",
        "workflow_def": {
            "name": "Backup de documentos a carpeta",
            "description": "Descarga adjuntos de Gmail a carpeta local",
            "schedule": "manual",
            "active": True,
            "steps": [
                {
                    "id": "step_1", "type": "action", "integration": "gmail",
                    "instruction": "Buscar correos con archivos adjuntos (PDF, DOCX, XLSX) de los últimos 7 días",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": [], "on_failure": "log", "timeout_seconds": 30
                },
                {
                    "id": "step_2", "type": "condition", "integration": "condition",
                    "instruction": "Verificar si se encontraron archivos adjuntos",
                    "condition_operator": "if_result_contains", "condition_value": ".pdf",
                    "depends_on": ["step_1"], "on_failure": "skip", "timeout_seconds": 10
                },
                {
                    "id": "step_3", "type": "action", "integration": "file",
                    "instruction": "Guardar los archivos encontrados en la carpeta DOT Trabajos",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": ["step_2"], "on_failure": "log", "timeout_seconds": 30
                },
                {
                    "id": "step_4", "type": "output", "integration": "whatsapp",
                    "instruction": "Notificar al usuario con la lista de archivos guardados",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": ["step_3"], "on_failure": "log", "timeout_seconds": 30
                }
            ],
            "source_nl": "Busca PDFs y documentos en mi Gmail y guárdalos en mi carpeta DOT Trabajos, avísame por WhatsApp"
        }
    },
    {
        "name": "Búsqueda de trabajo semanal",
        "description": "Cada lunes busca ofertas de trabajo según tu perfil y te envía las mejores por WhatsApp.",
        "category": "Empleo",
        "schedule": "weekly:mon:09:00",
        "workflow_def": {
            "name": "Búsqueda de trabajo semanal",
            "description": "Busca ofertas de trabajo y notifica por WhatsApp",
            "schedule": "weekly:mon:09:00",
            "active": True,
            "steps": [
                {
                    "id": "step_1", "type": "action", "integration": "web_search",
                    "instruction": "Buscar ofertas de trabajo recientes según el perfil del usuario (cargo, industria, ubicación)",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": [], "on_failure": "log", "timeout_seconds": 30
                },
                {
                    "id": "step_2", "type": "action", "integration": "chat",
                    "instruction": "Filtrar y ordenar las 5 mejores ofertas con enlaces, salario si está disponible y fecha de publicación",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": ["step_1"], "on_failure": "log", "timeout_seconds": 30
                },
                {
                    "id": "step_3", "type": "output", "integration": "whatsapp",
                    "instruction": "Enviar las mejores ofertas de trabajo al usuario por WhatsApp",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": ["step_2"], "on_failure": "log", "timeout_seconds": 30
                }
            ],
            "source_nl": "Cada lunes busca ofertas de trabajo según mi perfil y envíame las mejores por WhatsApp"
        }
    },
    {
        "name": "Recordatorio de reuniones diarias",
        "description": "Cada mañana revisa tu calendario de Google y te recuerda por WhatsApp las reuniones del día.",
        "category": "Productividad",
        "schedule": "daily:07:00",
        "workflow_def": {
            "name": "Recordatorio de reuniones diarias",
            "description": "Recordatorio matutino de reuniones del día",
            "schedule": "daily:07:00",
            "active": True,
            "steps": [
                {
                    "id": "step_1", "type": "action", "integration": "google-calendar",
                    "instruction": "Consultar todos los eventos del día de hoy",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": [], "on_failure": "log", "timeout_seconds": 30
                },
                {
                    "id": "step_2", "type": "condition", "integration": "condition",
                    "instruction": "Verificar si hay eventos hoy",
                    "condition_operator": "if_result_contains", "condition_value": "summary",
                    "depends_on": ["step_1"], "on_failure": "skip", "timeout_seconds": 10
                },
                {
                    "id": "step_3", "type": "output", "integration": "whatsapp",
                    "instruction": "Enviar resumen de reuniones del día con horas y enlaces",
                    "condition_operator": "always", "condition_value": "",
                    "depends_on": ["step_2"], "on_failure": "log", "timeout_seconds": 30
                }
            ],
            "source_nl": "Cada mañana revisa mi calendario y recuérdame por WhatsApp las reuniones del día"
        }
    },
]


class AutomationTemplateService:
    """Gestiona plantillas reutilizables de automatizaciones en Firestore."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def _ensure_enabled(self) -> None:
        if not self.enabled:
            raise RuntimeError("Plantillas de automatización no disponibles: Firebase no inicializado.")

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def seed_default_templates(self) -> int:
        """Inserta las plantillas por defecto si no existen. Retorna cuántas se insertaron."""
        self._ensure_enabled()
        db = get_db()
        existing = list(db.collection(FIRESTORE_COLLECTION).limit(1).stream())
        if existing:
            log.info("Seed de plantillas: ya existen plantillas, omitiendo.")
            return 0

        count = 0
        batch = db.batch()
        for template in DEFAULT_TEMPLATES:
            doc_ref = db.collection(FIRESTORE_COLLECTION).document()
            batch.set(doc_ref, {
                "name": template["name"],
                "description": template["description"],
                "category": template["category"],
                "schedule": template.get("schedule", "manual"),
                "workflow_def": template["workflow_def"],
                "author_uid": "system",
                "usage_count": 0,
                "created_at": self._now_iso(),
            })
            count += 1

        batch.commit()
        log.info("Seed de plantillas: %d plantillas insertadas.", count)
        return count

    def save_as_template(
        self, uid: str, name: str, description: str, category: str,
        workflow_def: dict[str, Any], schedule: str = "manual",
    ) -> dict[str, Any]:
        """Guarda una automatización o pipeline como plantilla pública.

        Args:
            uid: UID del autor
            name: Nombre descriptivo de la plantilla
            description: Qué hace la plantilla
            category: Categoría (Productividad, Planificación, Archivos, Empleo, etc.)
            workflow_def: Definición completa del pipeline/automatización (dict)
            schedule: Schedule string asociado
        """
        self._ensure_enabled()
        safe_name = (name or "").strip()
        if not safe_name or len(safe_name) > 120:
            raise ValueError("El nombre de la plantilla es obligatorio (máx. 120 caracteres).")
        if not workflow_def or not isinstance(workflow_def, dict):
            raise ValueError("La definición del workflow es obligatoria.")

        db = get_db()
        doc_ref = db.collection(FIRESTORE_COLLECTION).document()
        payload = {
            "name": safe_name,
            "description": (description or "").strip(),
            "category": (category or "General").strip(),
            "schedule": schedule or "manual",
            "workflow_def": workflow_def,
            "author_uid": uid,
            "usage_count": 0,
            "created_at": self._now_iso(),
        }
        doc_ref.set(payload)
        log.info("Plantilla guardada: %s por uid=%s", safe_name, uid[:8])
        return {"id": doc_ref.id, **payload}

    def list_templates(self, category: str | None = None) -> list[dict[str, Any]]:
        """Lista todas las plantillas públicas, opcionalmente filtradas por categoría."""
        self._ensure_enabled()
        db = get_db()
        query = db.collection(FIRESTORE_COLLECTION).order_by("created_at", direction="DESCENDING")
        if category:
            query = query.where("category", "==", category)

        templates: list[dict[str, Any]] = []
        for doc in query.stream():
            data = doc.to_dict() or {}
            data["id"] = doc.id
            templates.append(data)
        return templates

    def get_template(self, template_id: str) -> dict[str, Any] | None:
        """Obtiene una plantilla por ID."""
        self._ensure_enabled()
        db = get_db()
        doc = db.collection(FIRESTORE_COLLECTION).document(template_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        data["id"] = doc.id
        return data

    def clone_template(self, uid: str, template_id: str) -> dict[str, Any] | None:
        """Clona una plantilla y la asigna al usuario. Retorna el workflow_def clonado.

        Incrementa usage_count en la plantilla original.
        """
        self._ensure_enabled()
        template = self.get_template(template_id)
        if not template:
            return None

        # Incrementar contador de uso
        db = get_db()
        db.collection(FIRESTORE_COLLECTION).document(template_id).update({
            "usage_count": firestore_admin.Increment(1)
        })

        # Retornar el workflow_def para que el caller lo cree en el perfil del usuario
        workflow_def = template.get("workflow_def", {})
        if isinstance(workflow_def, dict):
            workflow_def["source_nl"] = workflow_def.get(
                "source_nl",
                f"Clonado de plantilla: {template.get('name', '')}"
            )

        log.info("Plantilla %s clonada por uid=%s", template_id, uid[:8])
        return {
            "template_id": template_id,
            "template_name": template.get("name", ""),
            "schedule": template.get("schedule", "manual"),
            "workflow_def": workflow_def,
        }
