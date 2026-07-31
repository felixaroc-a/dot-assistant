"""Tools de CRM ligero y contactos — F6 / Phonebook MVP."""
from __future__ import annotations

import logging
from typing import Any

from app.application.agent.ports import ToolResult
from app.services import contacts_store as store

log = logging.getLogger("dot.agent.tools.crm")


def contact_create_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    _ = uid
    try:
        tags = arguments.get("tags") or arguments.get("label") or ""
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        ok, _contact, message = store.add_contact(
            name=str(arguments.get("name") or ""),
            phone=str(arguments.get("phone") or ""),
            email=str(arguments.get("email") or ""),
            tags=tags if isinstance(tags, list) else [],
            notes=str(arguments.get("notes") or ""),
            source="manual",
        )
        if ok:
            return ToolResult(ok=True, output=message)
        return ToolResult(ok=False, output="", error=message)
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def contact_find_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    _ = uid
    try:
        query = str(
            arguments.get("query")
            or arguments.get("name")
            or arguments.get("phone")
            or ""
        ).strip()
        if not query:
            return ToolResult(ok=False, output="", error="Falta query de búsqueda (nombre o teléfono).")

        for_whatsapp = arguments.get("for_whatsapp")
        if for_whatsapp is None:
            for_whatsapp = arguments.get("whatsapp")
        if for_whatsapp is None:
            for_whatsapp = True
        for_whatsapp = bool(for_whatsapp)
        matches = store.search_contacts(query)
        output = store.format_find_result(query, matches, for_whatsapp=for_whatsapp)
        return ToolResult(ok=True, output=output)
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def contact_add_note_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    _ = uid
    try:
        from datetime import datetime, timezone

        name = str(arguments.get("name") or "").strip()
        note = str(arguments.get("note") or arguments.get("notes") or "").strip()
        if not name or not note:
            return ToolResult(ok=False, output="", error="Falta name y note.")

        contacts = store.read_contacts()
        for contact in contacts:
            if store.names_match(str(contact.get("name") or ""), name):
                stamp = datetime.now(timezone.utc).strftime("%d/%m/%Y")
                contact["notes"] = f"{contact.get('notes', '')}\n[{stamp}] {note}".strip()
                contact["updated_at"] = datetime.now(timezone.utc).isoformat()
                if store.write_contacts(contacts):
                    return ToolResult(ok=True, output=f"Nota añadida a «{name}».")
                return ToolResult(ok=False, output="", error="No se pudo guardar la nota.")
        return ToolResult(ok=False, output="", error=f"Contacto «{name}» no encontrado.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def contact_tag_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    _ = uid
    try:
        from datetime import datetime, timezone

        name = str(arguments.get("name") or "").strip()
        tag = str(arguments.get("tag") or arguments.get("label") or "").strip()
        if not name or not tag:
            return ToolResult(ok=False, output="", error="Falta name y tag.")

        contacts = store.read_contacts()
        for contact in contacts:
            if store.names_match(str(contact.get("name") or ""), name):
                tags = contact.setdefault("tags", [])
                if tag not in tags:
                    tags.append(tag)
                contact["updated_at"] = datetime.now(timezone.utc).isoformat()
                if store.write_contacts(contacts):
                    return ToolResult(ok=True, output=f"Etiqueta «{tag}» añadida a «{name}».")
                return ToolResult(ok=False, output="", error="No se pudo guardar la etiqueta.")
        return ToolResult(ok=False, output="", error=f"Contacto «{name}» no encontrado.")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def contact_list_all_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    _ = uid
    try:
        only_with_phone = bool(arguments.get("with_phone") or arguments.get("whatsapp_only"))
        contacts = store.read_contacts()
        if only_with_phone:
            contacts = [c for c in contacts if str(c.get("phone") or "").strip()]
        if not contacts:
            return ToolResult(
                ok=True,
                output="No hay contactos guardados. Importa desde Configuración → Contactos o usa contact_import_gmail.",
            )
        lines = [f"Contactos ({len(contacts)}):"]
        for contact in contacts:
            lines.append(f"  - {store.format_contact_line(contact, include_whatsapp_hint=only_with_phone)}")
        return ToolResult(ok=True, output="\n".join(lines))
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def contact_import_gmail_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    ok, message = store.import_from_gmail(uid)
    if ok:
        return ToolResult(ok=True, output=message)
    return ToolResult(ok=False, output="", error=message)


def contact_import_whatsapp_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    ok, message = store.import_from_whatsapp(uid)
    if ok:
        return ToolResult(ok=True, output=message)
    return ToolResult(ok=False, output="", error=message)


def contact_remind_followup_handler(uid: str, arguments: dict[str, Any]) -> ToolResult:
    _ = uid
    try:
        name = str(arguments.get("name") or "").strip()
        days = int(arguments.get("days") or 3)
        message = str(arguments.get("message") or f"Hacer seguimiento a {name}").strip()
        if not name:
            return ToolResult(ok=False, output="", error="Falta name del contacto.")
        return ToolResult(
            ok=True,
            output=(
                f"Seguimiento para «{name}» en {days} días: {message}. "
                "Usa schedule_reminder para programar el aviso."
            ),
        )
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


def contact_export_vcf_handler(uid: str, _arguments: dict[str, Any]) -> ToolResult:
    _ = uid
    try:
        from pathlib import Path

        from app.application.agent.tools.local_files import execute_local_tool_via_bridge

        contacts = store.read_contacts()
        if not contacts:
            return ToolResult(ok=True, output="No hay contactos para exportar.")

        lines: list[str] = []
        for contact in contacts:
            lines.extend(
                [
                    "BEGIN:VCARD",
                    "VERSION:3.0",
                    f"FN:{contact.get('name', '')}",
                ]
            )
            if contact.get("phone"):
                lines.append(f"TEL:{contact['phone']}")
            if contact.get("email"):
                lines.append(f"EMAIL:{contact['email']}")
            if contact.get("notes"):
                lines.append(f"NOTE:{str(contact['notes'])[:100]}")
            lines.append("END:VCARD")

        path = str(Path("~/Desktop/DOT Trabajos/CRM/contacts.vcf").expanduser())
        res = execute_local_tool_via_bridge("writeFile", path=path, content="\n".join(lines))
        if res.get("ok"):
            return ToolResult(ok=True, output=f"Exportado: {path} ({len(contacts)} contactos).")
        return ToolResult(ok=False, output="", error=f"Error: {res.get('error')}")
    except Exception as e:
        return ToolResult(ok=False, output="", error=str(e))


TOOLS = [
    ("contact_create", contact_create_handler),
    ("contact_find", contact_find_handler),
    ("contact_add_note", contact_add_note_handler),
    ("contact_tag", contact_tag_handler),
    ("contact_list", contact_list_all_handler),
    ("contact_import_gmail", contact_import_gmail_handler),
    ("contact_import_whatsapp", contact_import_whatsapp_handler),
    ("contact_remind_followup", contact_remind_followup_handler),
    ("contact_export_vcf", contact_export_vcf_handler),
]

TOOL_SCHEMAS = {
    "contact_create": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "phone": {"type": "string"},
            "email": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "string"},
        },
        "required": ["name"],
    },
    "contact_find": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Nombre o teléfono a buscar"},
            "name": {"type": "string"},
            "for_whatsapp": {"type": "boolean", "description": "True si vas a enviar WhatsApp"},
        },
    },
    "contact_list": {
        "type": "object",
        "properties": {
            "with_phone": {"type": "boolean", "description": "Solo contactos con teléfono"},
        },
    },
    "contact_import_gmail": {"type": "object", "properties": {}},
    "contact_import_whatsapp": {"type": "object", "properties": {}},
}

TOOL_SPECS = {
    "contact_find": {
        "description": (
            "Busca contactos locales por nombre o teléfono. "
            "Úsala antes de send_whatsapp_message cuando el usuario diga «escríbele a X»."
        ),
    },
    "contact_list": {
        "description": "Lista la agenda local de contactos (CRM en Escritorio).",
    },
    "contact_import_gmail": {
        "description": "Importa remitentes frecuentes de Gmail a la agenda local.",
    },
    "contact_import_whatsapp": {
        "description": "Importa números de conversaciones WhatsApp a la agenda local.",
    },
}
