#!/usr/bin/env python3
"""Crea tablas de billing (ORM) según DATABASE_URL en backend/.env."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

from ensure_billing_schema import main as ensure_main  # noqa: E402


def main() -> int:
    return ensure_main()


if __name__ == "__main__":
    raise SystemExit(main())
