#!/usr/bin/env python3
"""
Resetea el onboarding de un usuario en Firestore para pruebas E2E (DOTTEST).

Uso:
  python scripts/reset_firestore_onboarding.py --uid <UUID>
  python scripts/reset_firestore_onboarding.py --cedula V-12345678

Requiere FIREBASE_SERVICE_ACCOUNT_PATH en .env (o firebase-service-account.json local).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def _resolve_uid(cedula: str) -> str | None:
    from sqlalchemy import create_engine, text

    url = os.getenv("DATABASE_URL", "sqlite+pysqlite:///./data/dot_dev.db")
    with create_engine(url).connect() as conn:
        row = conn.execute(
            text("SELECT id FROM clientes_suscripcion WHERE cedula = :cedula"),
            {"cedula": cedula},
        ).fetchone()
    return str(row[0]) if row else None


def reset_onboarding(uid: str) -> None:
    from firebase_admin import firestore

    from app.firebase_db import delete_user_google_tokens, get_db, init_firebase, merge_user_profile

    init_firebase()
    db = get_db()

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

    wa_ref = (
        db.collection("users")
        .document(uid)
        .collection("whatsapp_channel")
        .document("data")
    )
    if wa_ref.get().exists:
        wa_ref.delete()
        print(f"  Borrado: users/{uid}/whatsapp_channel/data")

    try:
        delete_user_google_tokens(uid)
        print(f"  Borrado: user_google_tokens/{uid}")
    except Exception as exc:
        print(f"  Aviso: user_google_tokens/{uid} — {exc}")

    print(f"Onboarding reseteado para uid={uid}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resetea onboarding Firestore para DOTTEST")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--uid", help="UUID del cliente (clientes_suscripcion.id)")
    group.add_argument("--cedula", help="Cédula del cliente (ej. V-12345678)")
    args = parser.parse_args()

    uid = args.uid
    if args.cedula:
        uid = _resolve_uid(args.cedula.strip())
        if not uid:
            print(f"No se encontró cliente con cédula {args.cedula}", file=sys.stderr)
            return 1

    try:
        reset_onboarding(uid)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Configura FIREBASE_SERVICE_ACCOUNT_PATH en apps/dot/backend/.env", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error al resetear Firestore: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
