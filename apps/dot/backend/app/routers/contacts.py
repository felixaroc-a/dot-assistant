"""Router de agenda local (phonebook) — UI Configuración."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth_deps import claims_uid, require_product_jwt
from app.services import contacts_store as store

router = APIRouter(prefix="/v1/contacts", tags=["contacts"])


class ContactCreateBody(BaseModel):
    name: str = Field(min_length=1)
    phone: str = ""
    email: str = ""
    notes: str = ""


def _serialize_contact(contact: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": contact.get("id"),
        "name": contact.get("name"),
        "phone": contact.get("phone"),
        "email": contact.get("email"),
        "tags": contact.get("tags") or [],
        "notes": contact.get("notes") or "",
        "source": contact.get("source") or "manual",
        "updated_at": contact.get("updated_at"),
    }


@router.get("")
def list_contacts(claims: dict = Depends(require_product_jwt)):
    _ = claims_uid(claims)
    contacts = store.read_contacts()
    return {
        "total": len(contacts),
        "contacts": [_serialize_contact(c) for c in contacts],
    }


@router.post("")
def create_contact(body: ContactCreateBody, claims: dict = Depends(require_product_jwt)):
    _ = claims_uid(claims)
    ok, contact, message = store.add_contact(
        name=body.name,
        phone=body.phone,
        email=body.email,
        notes=body.notes,
        source="manual",
    )
    if not ok:
        raise HTTPException(status_code=503, detail=message)
    return {"ok": True, "message": message, "contact": _serialize_contact(contact or {})}


@router.delete("/{contact_id}")
def remove_contact(contact_id: str, claims: dict = Depends(require_product_jwt)):
    _ = claims_uid(claims)
    ok, message = store.delete_contact(contact_id)
    if not ok:
        raise HTTPException(status_code=404 if "no encontrado" in message.lower() else 503, detail=message)
    return {"ok": True, "message": message}


@router.post("/import/gmail")
def import_gmail_contacts(claims: dict = Depends(require_product_jwt)):
    uid = claims_uid(claims)
    ok, message = store.import_from_gmail(uid)
    if not ok:
        raise HTTPException(status_code=503, detail=message)
    contacts = store.read_contacts()
    return {"ok": True, "message": message, "total": len(contacts)}


@router.post("/import/whatsapp")
def import_whatsapp_contacts(claims: dict = Depends(require_product_jwt)):
    uid = claims_uid(claims)
    ok, message = store.import_from_whatsapp(uid)
    if not ok:
        raise HTTPException(status_code=503, detail=message)
    contacts = store.read_contacts()
    return {"ok": True, "message": message, "total": len(contacts)}
