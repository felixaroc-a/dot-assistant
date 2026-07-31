"""Gestión de plantillas reutilizables de documentos en Firestore."""
from __future__ import annotations

from datetime import datetime, timezone

from app.firebase_db import get_db
from app.services.provider_router import route_chat

ALLOWED_TEMPLATE_TYPES = frozenset({"docx", "xlsx", "txt"})

TEMPLATE_RENDER_SYSTEM_PROMPT = (
    "Eres asistente de redacción para documentos empresariales en español. "
    "Genera contenido final listo para exportar, claro y accionable, sin explicaciones meta."
)


class TemplateServiceDisabledError(RuntimeError):
    """Servicio deshabilitado por falta de Firebase."""


class TemplateNotFoundError(KeyError):
    """Plantilla no encontrada."""


class TemplateService:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def _ensure_enabled(self) -> None:
        if not self.enabled:
            raise TemplateServiceDisabledError(
                "Plantillas no disponibles: Firebase no está inicializado."
            )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _sanitize_type(document_type: str) -> str:
        clean = (document_type or "").strip().lower()
        if clean not in ALLOWED_TEMPLATE_TYPES:
            raise ValueError(
                "Tipo de plantilla no soportado. Usa: docx, xlsx o txt."
            )
        return clean

    @staticmethod
    def _sanitize_name(name: str) -> str:
        clean = (name or "").strip()
        if not clean:
            raise ValueError("El nombre de la plantilla es obligatorio.")
        if len(clean) > 120:
            raise ValueError("El nombre de la plantilla no puede superar 120 caracteres.")
        return clean

    @staticmethod
    def _sanitize_structure(structure: str) -> str:
        clean = (structure or "").strip()
        if not clean:
            raise ValueError("La estructura de la plantilla es obligatoria.")
        if len(clean) > 8_000:
            raise ValueError("La estructura de la plantilla excede 8000 caracteres.")
        return clean

    @staticmethod
    def _template_collection(uid: str):
        db = get_db()
        return db.collection("users").document(uid).collection("document_templates")

    def list_templates(self, uid: str) -> list[dict]:
        self._ensure_enabled()
        docs = self._template_collection(uid).order_by(
            "updated_at", direction="DESCENDING"
        ).stream()

        templates: list[dict] = []
        for doc in docs:
            data = doc.to_dict() or {}
            name = str(data.get("name") or "").strip()
            structure = str(data.get("structure") or "").strip()
            document_type = str(data.get("document_type") or "").strip().lower()
            if not name or not structure or document_type not in ALLOWED_TEMPLATE_TYPES:
                continue
            templates.append(
                {
                    "id": doc.id,
                    "name": name,
                    "document_type": document_type,
                    "structure": structure,
                    "created_at": str(data.get("created_at") or ""),
                    "updated_at": str(data.get("updated_at") or ""),
                }
            )
        return templates

    def create_template(
        self,
        uid: str,
        name: str,
        document_type: str,
        structure: str,
    ) -> dict:
        self._ensure_enabled()
        safe_name = self._sanitize_name(name)
        safe_type = self._sanitize_type(document_type)
        safe_structure = self._sanitize_structure(structure)
        now = self._now_iso()
        payload = {
            "name": safe_name,
            "document_type": safe_type,
            "structure": safe_structure,
            "created_at": now,
            "updated_at": now,
        }
        ref = self._template_collection(uid).document()
        ref.set(payload)
        return {"id": ref.id, **payload}

    def delete_template(self, uid: str, template_id: str) -> bool:
        self._ensure_enabled()
        clean_id = (template_id or "").strip()
        if not clean_id:
            raise ValueError("Id de plantilla inválido.")
        ref = self._template_collection(uid).document(clean_id)
        snap = ref.get()
        if not snap.exists:
            raise TemplateNotFoundError("Plantilla no encontrada.")
        ref.delete()
        return True

    def render_template(
        self,
        uid: str,
        template_id: str,
        user_input: str,
        provider_id: str | None = None,
    ) -> dict:
        self._ensure_enabled()
        clean_id = (template_id or "").strip()
        clean_input = (user_input or "").strip()
        if not clean_id:
            raise ValueError("Id de plantilla inválido.")
        if not clean_input:
            raise ValueError("Debes indicar los datos para completar la plantilla.")

        ref = self._template_collection(uid).document(clean_id)
        snap = ref.get()
        if not snap.exists:
            raise TemplateNotFoundError("Plantilla no encontrada.")

        raw = snap.to_dict() or {}
        template_name = self._sanitize_name(str(raw.get("name") or "Plantilla"))
        document_type = self._sanitize_type(str(raw.get("document_type") or "docx"))
        structure = self._sanitize_structure(str(raw.get("structure") or ""))

        prompt = (
            f'Usa esta plantilla "{template_name}" para generar un documento final.\n\n'
            "Estructura base de plantilla:\n"
            f"{structure}\n\n"
            "Datos y contexto provistos por el usuario:\n"
            f"{clean_input}\n\n"
            "Reglas:\n"
            "1) Entrega solo el contenido final del documento.\n"
            "2) No incluyas introducciones meta ni etiquetas JSON.\n"
            "3) Mantén un tono profesional y coherente con el contexto.\n"
        )
        content = route_chat(
            prompt,
            provider_id or "deepseek",
            system_prompt=TEMPLATE_RENDER_SYSTEM_PROMPT,
            include_document_action_prompt=False,
        ).strip()
        if not content:
            raise RuntimeError("No se pudo generar contenido desde la plantilla.")

        short_date = datetime.now().strftime("%Y%m%d")
        title = f"{template_name} {short_date}"
        ref.set({"updated_at": self._now_iso()}, merge=True)
        return {
            "template_id": clean_id,
            "template_name": template_name,
            "document_type": document_type,
            "title": title,
            "content": content,
        }
