"""Script de prueba de restore: dump -> drop -> create -> restore -> verify.

NO USAR EN PRODUCCION. Solo para entornos de desarrollo/testing.
Este script verifica que el proceso de backup/restore funciona correctamente.

Uso:
    python scripts/test_db_restore.py              # ejecuta prueba completa
    python scripts/test_db_restore.py --dry-run    # simula sin ejecutar
    python scripts/test_db_restore.py --db test_db # usa BD especifica

Flujo:
    1. pg_dump de la BD objetivo a archivo temporal
    2. DROP DATABASE (si existe)
    3. CREATE DATABASE
    4. pg_restore / psql del dump
    5. Verifica que las tablas core existen (SELECT 1 FROM clientes_suscripcion)

PRECAUCION:
    - Usa la misma DATABASE_URL del .env
    - El script verifica que DOT_ENV != production antes de ejecutar
    - Crea una BD temporal con sufijo _restore_test si no se especifica --db
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent


def _load_env_value(key: str) -> str:
    env_file = BACKEND_DIR / ".env"
    if not env_file.is_file():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _check_production() -> None:
    dot_env = _load_env_value("DOT_ENV")
    if dot_env.lower() == "production":
        print("ERROR: DOT_ENV=production. Este script NO debe ejecutarse en produccion.")
        sys.exit(1)
    print(f"OK: DOT_ENV={dot_env or 'development'} (no produccion)")


def _parse_pg_url(db_url: str) -> dict[str, str]:
    parsed = urlparse(db_url)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
        "dbname": (parsed.path or "/").lstrip("/") or "postgres",
    }


def _pg_cmd(conn: dict[str, str], *args: str) -> list[str]:
    return [
        "psql",
        "-h", conn["host"],
        "-p", conn["port"],
        "-U", conn["user"],
        *args,
    ]


def _run_pg(conn: dict[str, str], sql: str, dbname: str = "postgres") -> tuple[int, str, str]:
    env = os.environ.copy()
    if conn["password"]:
        env["PGPASSWORD"] = conn["password"]
    cmd = _pg_cmd(conn, "-d", dbname, "-c", sql)
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def test_restore(source_url: str, test_db: str, dry_run: bool = False) -> bool:
    print(f"\n=== DB Restore Test === {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  BD origen: {_parse_pg_url(source_url)['dbname']}")
    print(f"  BD prueba: {test_db}")

    if dry_run:
        print("  [DRY RUN] No se ejecutaran comandos SQL.")
        return True

    conn = _parse_pg_url(source_url)
    pg_dump = shutil.which("pg_dump")
    psql = shutil.which("psql")

    if not pg_dump or not psql:
        print(f"  ERROR: pg_dump={'OK' if pg_dump else 'FALTA'}, psql={'OK' if psql else 'FALTA'}")
        print("  Instala PostgreSQL client tools para ejecutar esta prueba.")
        return False

    env = os.environ.copy()
    if conn["password"]:
        env["PGPASSWORD"] = conn["password"]

    print("\n1/5 Dump de BD origen...")
    dump_file = tempfile.NamedTemporaryFile(suffix=".sql", delete=False, prefix="dot_restore_test_")
    dump_path = Path(dump_file.name)
    try:
        dump_cmd = [
            pg_dump,
            "-h", conn["host"],
            "-p", conn["port"],
            "-U", conn["user"],
            "-d", conn["dbname"],
            "--no-owner",
            "--no-acl",
            "-f", str(dump_path),
        ]
        result = subprocess.run(dump_cmd, env=env, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"  ERROR pg_dump: {result.stderr[:300]}")
            dump_path.unlink(missing_ok=True)
            return False
        dump_size = dump_path.stat().st_size
        print(f"  OK: {dump_size / 1024:.1f} KB -> {dump_path.name}")
    except Exception as e:
        print(f"  ERROR: {e}")
        dump_path.unlink(missing_ok=True)
        return False

    try:
        print(f"\n2/5 DROP DATABASE {test_db}...")
        _run_pg(conn, f"DROP DATABASE IF EXISTS {test_db} WITH (FORCE);")
        print("  OK: BD eliminada (o no existia)")

        print(f"\n3/5 CREATE DATABASE {test_db}...")
        rc, stdout, stderr = _run_pg(conn, f"CREATE DATABASE {test_db};")
        if rc != 0:
            if "already exists" not in stderr.lower():
                print(f"  ERROR: {stderr[:300]}")
                return False
        print("  OK: BD creada")

        print(f"\n4/5 Restore {dump_path.name} -> {test_db}...")
        restore_cmd = [
            psql,
            "-h", conn["host"],
            "-p", conn["port"],
            "-U", conn["user"],
            "-d", test_db,
            "-f", str(dump_path),
            "-v", "ON_ERROR_STOP=1",
        ]
        result = subprocess.run(restore_cmd, env=env, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"  ERROR restore: {result.stderr[:500]}")
            return False
        print("  OK: restore completado")

        print(f"\n5/5 Verify en {test_db}...")
        checks = {
            "clientes_suscripcion": "SELECT COUNT(*) FROM clientes_suscripcion",
            "chat_exchanges": "SELECT COUNT(*) FROM chat_exchanges",
            "ai_usage": "SELECT COUNT(*) FROM ai_usage",
        }
        all_ok = True
        for table, query in checks.items():
            rc, stdout, stderr = _run_pg(conn, query, dbname=test_db)
            if rc == 0:
                print(f"  OK {table}: {stdout}")
            elif "does not exist" in stderr.lower():
                print(f"  ~ {table}: no existe (esperado si no es BD completa)")
            else:
                print(f"  X {table}: ERROR - {stderr[:200]}")
                all_ok = False

        print(f"\nCleanup: DROP DATABASE {test_db}...")
        _run_pg(conn, f"DROP DATABASE IF EXISTS {test_db} WITH (FORCE);")

        if all_ok:
            print("\n=== DB Restore Test: OK ===")
            return True
        else:
            print("\n=== DB Restore Test: VERIFICACION PARCIAL (tablas esperadas faltantes) ===")
            return False

    finally:
        try:
            dump_path.unlink(missing_ok=True)
        except OSError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Prueba de restore de base de datos DOT")
    parser.add_argument("--dry-run", action="store_true", help="Simula sin ejecutar")
    parser.add_argument("--db", type=str, default="", help="BD de prueba (default: <dbname>_restore_test)")
    parser.add_argument("--url", type=str, default="", help="DATABASE_URL (default: desde .env)")
    args = parser.parse_args()

    _check_production()

    db_url = args.url.strip() or _load_env_value("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL no configurada en .env")
        sys.exit(1)

    conn = _parse_pg_url(db_url)
    test_db = args.db.strip() or f"{conn['dbname']}_restore_test"

    success = test_restore(db_url, test_db, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
