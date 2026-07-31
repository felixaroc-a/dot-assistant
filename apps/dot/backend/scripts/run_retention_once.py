#!/usr/bin/env python3
"""Ejecuta un ciclo manual de retención D5 (T11) para verificación / ops.

Uso (desde apps/dot/backend):
  python -m scripts.run_retention_once
  python -m scripts.run_retention_once --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan + purge retención D5")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo listar candidatos elegibles sin borrar datos",
    )
    args = parser.parse_args()

    from app.billing_db import get_session_factory
    from app.billing_models import ClienteORM
    from app.firebase_db import get_user_profile, init_firebase
    from app.services.data_retention import evaluate_cliente_for_purge, run_retention_scan

    try:
        init_firebase()
    except Exception as exc:
        print(f"Firebase no disponible: {exc}")
        return 1

    session = get_session_factory()()
    try:
        if args.dry_run:
            candidates = []
            for cliente in session.query(ClienteORM).all():
                uid = str(cliente.id)
                profile = get_user_profile(uid) or {}
                decision = evaluate_cliente_for_purge(
                    uid=uid,
                    fecha_vencimiento=cliente.fecha_vencimiento,
                    profile=profile,
                )
                if decision.should_purge or decision.reason == "already_purged":
                    candidates.append(
                        {
                            "uid": uid,
                            "cedula": cliente.cedula,
                            "fecha_vencimiento": cliente.fecha_vencimiento.isoformat(),
                            "decision": decision.reason,
                            "reasons": decision.reasons,
                            "last_active_at": profile.get("last_active_at"),
                            "retention_purged_at": profile.get("retention_purged_at"),
                        }
                    )
            print(json.dumps({"dry_run": True, "candidates": candidates}, indent=2, default=str))
            return 0

        summary = run_retention_scan(session)
        print(json.dumps(summary, indent=2, default=str))
        return 0 if summary.get("errors", 0) == 0 else 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
