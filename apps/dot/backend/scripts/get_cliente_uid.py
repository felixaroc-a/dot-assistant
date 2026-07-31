#!/usr/bin/env python3
"""Imprime el UUID de un cliente por cedula (para reset_dev.ps1)."""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cedula", nargs="?", default="V-12345678")
    args = parser.parse_args()

    from sqlalchemy import create_engine, text

    url = os.getenv("DATABASE_URL", "sqlite+pysqlite:///./data/dot_dev.db")
    with create_engine(url).connect() as conn:
        row = conn.execute(
            text("SELECT id FROM clientes_suscripcion WHERE cedula = :cedula"),
            {"cedula": args.cedula.strip()},
        ).fetchone()

    if not row:
        return 1

    print(row[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
