#!/usr/bin/env python3
"""create_all + columnas IA en SQLite/Postgres si la BD es anterior al selector de IA."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.billing_db import get_engine  # noqa: E402
from app.services.db_schema_bootstrap import ensure_backend_schema  # noqa: E402
from app.services.db_schema_checklist import (  # noqa: E402
    BACKEND_ALL_TABLES,
    format_missing_tables_hint,
)


def main() -> int:
    engine = get_engine()
    schema, applied = ensure_backend_schema(engine)
    if applied:
        print("Columnas añadidas:", ", ".join(applied))

    if schema.ok_all:
        print(
            "Esquema al día (billing + chat):",
            ", ".join(BACKEND_ALL_TABLES),
        )
        return 0

    hint = format_missing_tables_hint(schema, enable_chat=True)
    print("ADVERTENCIA:", hint)
    if not schema.ok_billing_minimum:
        return 1
    if not schema.ok_chat:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
