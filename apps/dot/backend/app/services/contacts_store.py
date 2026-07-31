"""Agenda local de contactos (phonebook) — CRM en ~/Desktop/DOT Trabajos/CRM/contacts.json."""
from __future__ import annotations

import json
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.infrastructure.whatsapp.phone_resolver import to_e164

log = logging.getLogger("dot.contacts_store")

CONTACTS_JSON = "~/Desktop/DOT Trabajos/CRM/contacts.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _norm_text(value: str) -> str:
    return _strip_accents(str(value or "").strip().lower())


def names_match(a: str, b: str) -> bool:
    return _norm_text(a) == _norm_text(b)


def _norm_phone(value: str) -> str:
    return to_e164(value) or str(value or "").strip()


def _contact_key(contact: dict[str, Any]) -> str:
    phone = _norm_phone(str(contact.get("phone") or ""))
    if phone:
        return f"phone:{phone}"
    email = _norm_text(str(contact.get("email") or ""))
    if email:
        return f"email:{email}"
    return f"name:{_norm_text(str(contact.get('name') or ''))}"


def _ensure_contact_shape(raw: dict[str, Any]) -> dict[str, Any]:
    contact = dict(raw)
    if not contact.get("id"):
        contact["id"] = str(uuid.uuid4())
    name = str(contact.get("name") or "").strip()
    phone = _norm_phone(str(contact.get("phone") or ""))
    email = str(contact.get("email") or "").strip()
    tags = contact.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    contact.update(
        {
            "name": name,
            "phone": phone,
            "email": email,
            "tags": tags if isinstance(tags, list) else [],
            "notes": str(contact.get("notes") or "").strip(),
            "source": str(contact.get("source") or "manual").strip() or "manual",
            "created_at": contact.get("created_at") or _now_iso(),
            "updated_at": contact.get("updated_at") or contact.get("created_at") or _now_iso(),
        }
    )
    return contact


def _default_bridge_reader() -> Callable[..., dict[str, Any]]:
    from app.application.agent.tools.local_files import execute_local_tool_via_bridge

    return execute_local_tool_via_bridge


def read_contacts(*, bridge_reader: Callable[..., dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    reader = bridge_reader or _default_bridge_reader()
    try:
        raw = reader("readFile", path=str(Path(CONTACTS_JSON).expanduser()))
        if not raw.get("ok"):
            return []
        payload = json.loads(raw.get("content") or "[]")
        if not isinstance(payload, list):
            return []
        return [_ensure_contact_shape(c) for c in payload if isinstance(c, dict) and c.get("name")]
    except Exception:
        log.debug("read_contacts falló", exc_info=True)
        return []


def write_contacts(
    contacts: list[dict[str, Any]],
    *,
    bridge_reader: Callable[..., dict[str, Any]] | None = None,
) -> bool:
    reader = bridge_reader or _default_bridge_reader()
    try:
        normalized = [_ensure_contact_shape(c) for c in contacts]
        path = str(Path(CONTACTS_JSON).expanduser())
        res = reader(
            "writeFile",
            path=path,
            content=json.dumps(normalized, indent=2, ensure_ascii=False),
        )
        return bool(res.get("ok"))
    except Exception:
        log.warning("write_contacts falló", exc_info=True)
        return False


def parse_email_sender(raw: str) -> tuple[str, str]:
    value = str(raw or "").strip()
    if not value:
        return "", ""
    if "<" in value and ">" in value:
        name = value.split("<")[0].strip().strip('"').strip("'")
        email = value.split("<")[-1].rstrip(">").strip()
        if not name and email:
            name = email.split("@")[0].replace(".", " ").title()
        return name, email
    if "@" in value:
        local = value.split("@")[0].replace(".", " ").replace("_", " ").title()
        return local, value
    return value, ""


def score_contact_match(contact: dict[str, Any], query: str) -> int:
    q = _norm_text(query)
    if not q:
        return 0

    name = _norm_text(str(contact.get("name") or ""))
    phone = re.sub(r"\D", "", str(contact.get("phone") or ""))
    email = _norm_text(str(contact.get("email") or ""))
    tags = _norm_text(" ".join(contact.get("tags") or []))

    q_digits = re.sub(r"\D", "", query)
    if q_digits and q_digits in phone:
        return 120
    if q == name:
        return 110
    if name.startswith(q):
        return 95
    if q in name.split():
        return 90
    if q in name:
        return 75
    if q in email:
        return 70
    if q in tags:
        return 55

    q_tokens = [t for t in q.split() if len(t) >= 2]
    name_tokens = name.split()
    overlap = sum(1 for t in q_tokens if any(t in nt or nt.startswith(t) for nt in name_tokens))
    if overlap:
        return 40 + overlap * 10
    return 0


def search_contacts(
    query: str,
    contacts: list[dict[str, Any]] | None = None,
    *,
    min_score: int = 40,
    limit: int = 10,
) -> list[tuple[int, dict[str, Any]]]:
    items = contacts if contacts is not None else read_contacts()
    scored: list[tuple[int, dict[str, Any]]] = []
    for contact in items:
        score = score_contact_match(contact, query)
        if score >= min_score:
            scored.append((score, contact))
    scored.sort(key=lambda item: (-item[0], _norm_text(item[1].get("name", ""))))
    return scored[:limit]


def format_contact_line(contact: dict[str, Any], *, include_whatsapp_hint: bool = False) -> str:
    parts = [str(contact.get("name") or "Sin nombre")]
    phone = str(contact.get("phone") or "").strip()
    email = str(contact.get("email") or "").strip()
    if phone:
        label = "WhatsApp" if include_whatsapp_hint else "Tel"
        parts.append(f"{label}: {phone}")
    if email:
        parts.append(f"Email: {email}")
    tags = contact.get("tags") or []
    if tags:
        parts.append(f"[{', '.join(tags)}]")
    notes = str(contact.get("notes") or "").strip()
    if notes:
        parts.append(notes[:80])
    return " | ".join(parts)


def format_find_result(
    query: str,
    matches: list[tuple[int, dict[str, Any]]],
    *,
    for_whatsapp: bool = False,
) -> str:
    if not matches:
        return (
            f"No encontré contactos con «{query}». "
            "Pide al usuario importar contactos (Configuración → Contactos) o crear uno con contact_create."
        )

    with_phone = [(score, c) for score, c in matches if str(c.get("phone") or "").strip()]
    if for_whatsapp and not with_phone:
        lines = [f"Encontré {len(matches)} coincidencia(s) para «{query}», pero ninguna tiene teléfono:"]
        for _, contact in matches:
            lines.append(f"  - {format_contact_line(contact)}")
        lines.append("Pide al usuario el número o que complete el contacto en Configuración → Contactos.")
        return "\n".join(lines)

    display = with_phone if for_whatsapp else matches
    lines = [f"Contactos ({len(display)}) para «{query}»:"]
    for idx, (_, contact) in enumerate(display, start=1):
        lines.append(f"  {idx}. {format_contact_line(contact, include_whatsapp_hint=for_whatsapp)}")

    if len(display) == 1 and str(display[0][1].get("phone") or "").strip():
        phone = str(display[0][1]["phone"]).strip()
        lines.append(f"Teléfono listo para WhatsApp: {phone}")
        if for_whatsapp:
            lines.append(f"Siguiente paso: send_whatsapp_message con to=\"{phone}\" y el texto pedido.")
    elif len(display) > 1:
        lines.append("Hay varios candidatos: pregunta al usuario cuál es antes de enviar WhatsApp.")

    return "\n".join(lines)


def merge_contacts(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    by_key: dict[str, dict[str, Any]] = {}
    for contact in existing:
        by_key[_contact_key(contact)] = _ensure_contact_shape(contact)

    added = 0
    updated = 0
    for raw in incoming:
        contact = _ensure_contact_shape(raw)
        if not contact.get("name"):
            continue
        key = _contact_key(contact)
        current = by_key.get(key)
        if not current:
            by_key[key] = contact
            added += 1
            continue
        changed = False
        if not current.get("phone") and contact.get("phone"):
            current["phone"] = contact["phone"]
            changed = True
        if not current.get("email") and contact.get("email"):
            current["email"] = contact["email"]
            changed = True
        if len(contact.get("name", "")) > len(current.get("name", "")):
            current["name"] = contact["name"]
            changed = True
        for tag in contact.get("tags") or []:
            if tag not in (current.get("tags") or []):
                current.setdefault("tags", []).append(tag)
                changed = True
        if changed:
            current["updated_at"] = _now_iso()
            updated += 1

    merged = sorted(by_key.values(), key=lambda c: _norm_text(c.get("name", "")))
    return merged, added, updated


def add_contact(
    *,
    name: str,
    phone: str = "",
    email: str = "",
    tags: list[str] | None = None,
    notes: str = "",
    source: str = "manual",
) -> tuple[bool, dict[str, Any] | None, str]:
    clean_name = str(name or "").strip()
    if not clean_name:
        return False, None, "Falta el nombre del contacto."

    contact = _ensure_contact_shape(
        {
            "name": clean_name,
            "phone": _norm_phone(phone),
            "email": str(email or "").strip(),
            "tags": tags or [],
            "notes": str(notes or "").strip(),
            "source": source,
        }
    )
    contacts = read_contacts()
    merged, added, _ = merge_contacts(contacts, [contact])
    if added == 0:
        return True, contact, f"El contacto «{clean_name}» ya existía; no se duplicó."
    if write_contacts(merged):
        return True, contact, f"Contacto «{clean_name}» guardado."
    return False, None, "No se pudo guardar el contacto (¿bridge local activo?)."


def delete_contact(contact_id: str) -> tuple[bool, str]:
    cid = str(contact_id or "").strip()
    if not cid:
        return False, "Falta id del contacto."
    contacts = read_contacts()
    remaining = [c for c in contacts if str(c.get("id")) != cid]
    if len(remaining) == len(contacts):
        return False, "Contacto no encontrado."
    if write_contacts(remaining):
        return True, "Contacto eliminado."
    return False, "No se pudo eliminar el contacto."


def import_from_gmail(uid: str) -> tuple[bool, str]:
    try:
        from app.services import gmail_service

        messages = gmail_service.list_messages(uid, max_results=80)
        if not messages:
            return True, "No hay correos recientes para importar contactos."

        incoming: list[dict[str, Any]] = []
        seen_emails: set[str] = set()
        for msg in messages:
            sender = str(msg.get("from") or "").strip()
            name, email = parse_email_sender(sender)
            if not email or email in seen_emails:
                continue
            seen_emails.add(email)
            incoming.append(
                {
                    "name": name or email.split("@")[0],
                    "email": email,
                    "source": "gmail",
                    "tags": ["gmail"],
                }
            )

        if not incoming:
            return True, "No se encontraron remitentes nuevos en Gmail."

        merged, added, updated = merge_contacts(read_contacts(), incoming)
        if not write_contacts(merged):
            return False, "No se pudo guardar la agenda (¿bridge local activo?)."
        return True, f"Importados desde Gmail: {added} nuevos, {updated} actualizados (total {len(merged)})."
    except Exception as e:
        log.warning("import_from_gmail error uid=%s: %s", uid[:8], e)
        return False, "No pude importar desde Gmail. ¿Tienes Gmail conectado?"


def import_from_whatsapp(uid: str) -> tuple[bool, str]:
    try:
        from app.application.whatsapp.inbound_service import get_message_store

        store = get_message_store()
        messages = store.list_for_uid(uid, limit=300)
        if not messages:
            return True, "No hay conversaciones de WhatsApp para importar."

        incoming: list[dict[str, Any]] = []
        seen_phones: set[str] = set()
        for msg in messages:
            for raw_phone in (msg.from_phone, msg.to_phone):
                phone = _norm_phone(raw_phone)
                if not phone or phone in seen_phones:
                    continue
                seen_phones.add(phone)
                incoming.append(
                    {
                        "name": f"Contacto WA {phone[-4:]}",
                        "phone": phone,
                        "source": "whatsapp",
                        "tags": ["whatsapp"],
                    }
                )

        if not incoming:
            return True, "No se encontraron números en WhatsApp."

        merged, added, updated = merge_contacts(read_contacts(), incoming)
        if not write_contacts(merged):
            return False, "No se pudo guardar la agenda (¿bridge local activo?)."
        return True, f"Importados desde WhatsApp: {added} nuevos, {updated} actualizados (total {len(merged)})."
    except Exception as e:
        log.warning("import_from_whatsapp error uid=%s: %s", uid[:8], e)
        return False, "No pude importar desde WhatsApp."
