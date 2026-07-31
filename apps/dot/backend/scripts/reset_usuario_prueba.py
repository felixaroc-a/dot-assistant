#!/usr/bin/env python3
"""
Resetea el onboarding del usuario de prueba (V-12345678) para probar el flujo E2E desde cero.

Limpia:
  - Firestore users/{cliente_id}: onboarding, perfil, integraciones
  - Firestore users/{cliente_id}/whatsapp_channel/data
  - Firestore user_google_tokens/{cliente_id} (revoca OAuth en Google si aplica)

Uso:
  python scripts/reset_usuario_prueba.py
  python scripts/reset_usuario_prueba.py --cedula V-12345678
  python scripts/reset_usuario_prueba.py --uid 3d234035-5029-40d6-ab0b-02101105eecc

Requiere FIREBASE_SERVICE_ACCOUNT_PATH en .env (firebase-service-account.json local).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

DEFAULT_CEDULA = "V-12345678"


def _resolve_cliente_by_cedula(cedula: str) -> tuple[str, str] | None:
    from sqlalchemy import create_engine, text

    url = os.getenv("DATABASE_URL", "sqlite+pysqlite:///./data/dot_dev.db")
    with create_engine(url).connect() as conn:
        row = conn.execute(
            text("SELECT id, nombre FROM clientes_suscripcion WHERE cedula = :cedula"),
            {"cedula": cedula},
        ).fetchone()
    if not row:
        return None
    return str(row[0]), str(row[1] or "")


def _resolve_cliente_by_uid(uid: str) -> tuple[str, str] | None:
    from sqlalchemy import create_engine, text

    url = os.getenv("DATABASE_URL", "sqlite+pysqlite:///./data/dot_dev.db")
    with create_engine(url).connect() as conn:
        row = conn.execute(
            text("SELECT cedula, nombre FROM clientes_suscripcion WHERE id = :uid"),
            {"uid": uid},
        ).fetchone()
    if not row:
        return None
    return str(row[0]), str(row[1] or "")


def _snapshot(uid: str) -> dict:
    from app.firebase_db import get_db, get_user_google_tokens_doc_data, get_user_profile, init_firebase

    init_firebase()
    db = get_db()
    profile = get_user_profile(uid) or {}
    wa_ref = (
        db.collection("users")
        .document(uid)
        .collection("whatsapp_channel")
        .document("data")
    )
    wa_snap = wa_ref.get()
    google_doc = get_user_google_tokens_doc_data(uid)
    return {
        "profile": profile,
        "whatsapp_exists": wa_snap.exists,
        "whatsapp": wa_snap.to_dict() if wa_snap.exists else None,
        "google_tokens_exists": google_doc is not None,
    }


def reset_usuario_prueba(uid: str, cedula: str, nombre: str) -> dict[str, object]:
    from firebase_admin import firestore

    from app.firebase_db import delete_user_google_tokens, init_firebase, merge_user_profile
    from app.services import oauth_service
    from app.services.whatsapp_link import clear_channel_state

    before = _snapshot(uid)

    init_firebase()

    merge_user_profile(
        uid,
        {
            "onboarding_completed": False,
            "display_name": firestore.DELETE_FIELD,
            "channel_id": firestore.DELETE_FIELD,
            "ai_provider_id": firestore.DELETE_FIELD,
            "integrations": [],
            "automation_summary": firestore.DELETE_FIELD,
        },
    )

    whatsapp_cleared = before["whatsapp_exists"]
    clear_channel_state(uid)

    google_revoked_remotely = False
    google_had_tokens = before["google_tokens_exists"]
    if google_had_tokens:
        try:
            result = oauth_service.revoke_google_access(uid)
            google_revoked_remotely = bool(result.get("revoked_remotely"))
        except Exception:
            delete_user_google_tokens(uid)

    after = _snapshot(uid)
    profile_after = after["profile"]

    return {
        "cedula": cedula,
        "nombre": nombre,
        "uid": uid,
        "before": before,
        "after": after,
        "actions": {
            "profile_reset": True,
            "whatsapp_cleared": whatsapp_cleared,
            "google_tokens_removed": google_had_tokens,
            "google_revoked_remotely": google_revoked_remotely,
        },
        "verified": {
            "onboarding_completed": profile_after.get("onboarding_completed") is False,
            "display_name_cleared": "display_name" not in profile_after,
            "channel_id_cleared": "channel_id" not in profile_after,
            "integrations_empty": profile_after.get("integrations") == [],
            "automation_summary_cleared": "automation_summary" not in profile_after,
            "whatsapp_deleted": not after["whatsapp_exists"],
            "google_tokens_deleted": not after["google_tokens_exists"],
        },
    }


def _print_report(report: dict[str, object]) -> None:
    before = report["before"]
    profile = before["profile"]
    actions = report["actions"]
    verified = report["verified"]

    print("=" * 60)
    print("RESET USUARIO DE PRUEBA — Nordik-IA")
    print("=" * 60)
    print(f"Cédula:  {report['cedula']}")
    print(f"Nombre:  {report['nombre']}")
    print(f"UID:     {report['uid']}")
    print()
    print("Estado ANTES:")
    print(f"  onboarding_completed: {profile.get('onboarding_completed')!r}")
    print(f"  display_name:         {profile.get('display_name')!r}")
    print(f"  channel_id:           {profile.get('channel_id')!r}")
    print(f"  integrations:         {profile.get('integrations')!r}")
    print(f"  automation_summary:   {profile.get('automation_summary')!r}")
    print(f"  whatsapp_channel:     {'presente' if before['whatsapp_exists'] else 'ausente'}")
    if before["whatsapp"]:
        wa = before["whatsapp"]
        print(f"    linked={wa.get('linked')!r} status={wa.get('status')!r}")
    print(f"  google_tokens:        {'presente' if before['google_tokens_exists'] else 'ausente'}")
    print()
    print("Acciones ejecutadas:")
    print("  [OK] Perfil Firestore reseteado (onboarding_completed=false)")
    if actions["whatsapp_cleared"]:
        print("  [OK] WhatsApp channel eliminado (users/{uid}/whatsapp_channel/data)")
    else:
        print("  [--] WhatsApp channel no existía")
    if actions["google_tokens_removed"]:
        remote = "sí" if actions["google_revoked_remotely"] else "no"
        print(f"  [OK] Tokens Google OAuth eliminados (revocado en Google: {remote})")
    else:
        print("  [--] Tokens Google OAuth no existían")
    print()
    print("Verificación DESPUÉS:")
    for key, ok in verified.items():
        mark = "OK" if ok else "FALLO"
        print(f"  [{mark}] {key}")
    print()
    print("Frontend — limpiar sessionStorage antes de probar:")
    print("  dot_onboarding_step")
    print("  dot_onboarding_channel")
    print("  dot_onboarding_integrations")
    print("  dot_onboarding_display_name")
    print("  dot_onboarding_back_step")
    print()
    print("Flujo esperado: login -> paso channel -> WhatsApp QR -> Google OAuth -> dashboard")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resetea onboarding del usuario de prueba para Nordik-IA",
    )
    parser.add_argument("--uid", help="UUID del cliente (clientes_suscripcion.id)")
    parser.add_argument(
        "--cedula",
        default=DEFAULT_CEDULA,
        help=f"Cédula del cliente (default: {DEFAULT_CEDULA})",
    )
    args = parser.parse_args()

    if args.uid:
        uid = args.uid.strip()
        resolved = _resolve_cliente_by_uid(uid)
        cedula, nombre = resolved if resolved else (args.cedula, "")
    else:
        cedula = args.cedula.strip()
        resolved = _resolve_cliente_by_cedula(cedula)
        if not resolved:
            print(f"No se encontró cliente con cédula {cedula}", file=sys.stderr)
            return 1
        uid, nombre = resolved

    try:
        report = reset_usuario_prueba(uid, cedula, nombre)
        _print_report(report)
        if not all(report["verified"].values()):
            return 1
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Configura FIREBASE_SERVICE_ACCOUNT_PATH en apps/dot/backend/.env", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error al resetear usuario de prueba: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
