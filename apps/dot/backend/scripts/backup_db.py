"""Backup diario de base de datos Postgres (pg_dump) con rotación de 7 días.

Uso:
    python scripts/backup_db.py                  # backup normal
    python scripts/backup_db.py --dry-run        # simula sin ejecutar
    python scripts/backup_db.py --keep 14        # guardar 14 días

Configuración:
    - Lee DATABASE_URL desde .env (apps/dot/backend/.env)
    - Backups se guardan en apps/dot/backend/backups/ (crea dir si no existe)
    - Nombres: dot_backup_YYYY-MM-DD_HHMMSS.sql
    - Rotación: elimina backups más viejos que KEEP_DAYS (default 7)

Requisitos:
    - pg_dump instalado y en PATH
    - Python 3.11+

Edge cases:
    - Si no hay DATABASE_URL configurada → sale con error claro
    - Si pg_dump no está en PATH → documenta cómo instalar
    - Si el dir de backups no tiene permisos → error claro
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# ─── Resolver rutas ────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
BACKUP_DIR = BACKEND_DIR / "backups"


def _load_database_url() -> str:
    """Carga DATABASE_URL desde .env del backend."""
    env_file = BACKEND_DIR / ".env"
    if not env_file.is_file():
        print(f"ERROR: .env no encontrado en {env_file}")
        sys.exit(1)

    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        if line.startswith("DATABASE_URL="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                return value

    print("ERROR: DATABASE_URL no configurada en .env")
    sys.exit(1)


def _check_pg_dump() -> str:
    """Verifica que pg_dump esté disponible. Devuelve el path."""
    pg_dump = shutil.which("pg_dump")
    if pg_dump:
        return pg_dump
    print(
        "ERROR: pg_dump no encontrado en PATH.\n"
        "Instala PostgreSQL client tools:\n"
        "  Windows: descarga desde https://www.postgresql.org/download/\n"
        "  Linux:   sudo apt install postgresql-client\n"
        "  macOS:   brew install libpq && echo 'export PATH=\"/opt/homebrew/opt/libpq/bin:$PATH\"' >> ~/.zshrc"
    )
    sys.exit(1)


def _parse_pg_url(db_url: str) -> dict[str, str]:
    """Extrae host, port, user, password, dbname de DATABASE_URL."""
    parsed = urlparse(db_url)
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    user = parsed.username or "postgres"
    password = parsed.password or ""
    dbname = (parsed.path or "/").lstrip("/") or "postgres"
    return {"host": host, "port": port, "user": user, "password": password, "dbname": dbname}


def _cleanup_old_backups(keep_days: int) -> int:
    """Elimina backups .sql.gz más viejos que keep_days. Devuelve cuántos eliminó."""
    if not BACKUP_DIR.is_dir():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    removed = 0
    for f in sorted(BACKUP_DIR.glob("dot_backup_*.sql.gz")):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                f.unlink()
                removed += 1
                print(f"  [rotación] eliminado: {f.name}")
        except OSError as e:
            print(f"  [rotación] error eliminando {f.name}: {e}")
    return removed


def run_backup(keep_days: int = 7, dry_run: bool = False) -> bool:
    """Ejecuta el backup completo. Retorna True si fue exitoso."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_file = BACKUP_DIR / f"dot_backup_{timestamp}.sql"
    compressed_file = BACKUP_DIR / f"dot_backup_{timestamp}.sql.gz"

    print(f"=== DOT DB Backup === {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. Cargar config
    db_url = _load_database_url()
    pg_dump = _check_pg_dump()
    conn = _parse_pg_url(db_url)
    print(f"  Base de datos: {conn['dbname']}@{conn['host']}:{conn['port']}")

    if dry_run:
        print("  [DRY RUN] No se ejecutará pg_dump.")
        print(f"  Backup sería: {compressed_file}")
        _cleanup_old_backups(keep_days)
        return True

    # 2. Crear directorio de backups
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # 3. Ejecutar pg_dump
    env = os.environ.copy()
    if conn["password"]:
        env["PGPASSWORD"] = conn["password"]

    cmd = [
        pg_dump,
        "-h", conn["host"],
        "-p", conn["port"],
        "-U", conn["user"],
        "-d", conn["dbname"],
        "--no-owner",
        "--no-acl",
        "-f", str(backup_file),
    ]

    print(f"  Ejecutando: pg_dump -h {conn['host']} -p {conn['port']} -U {conn['user']} -d {conn['dbname']} ...")
    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            error_msg = result.stderr.strip().split("\n")[-1] if result.stderr else "error desconocido"
            print(f"  ERROR: pg_dump falló (código {result.returncode}): {error_msg}")
            if backup_file.exists():
                backup_file.unlink()
            return False
    except subprocess.TimeoutExpired:
        print("  ERROR: pg_dump timeout (>300s). La BD puede ser muy grande.")
        if backup_file.exists():
            backup_file.unlink()
        return False
    except FileNotFoundError:
        print(f"  ERROR: pg_dump no encontrado en: {pg_dump}")
        return False

    # 4. Comprimir
    size_before = backup_file.stat().st_size
    with open(backup_file, "rb") as f_in:
        with gzip.open(str(compressed_file), "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
    size_after = compressed_file.stat().st_size
    backup_file.unlink()  # eliminar sin comprimir

    ratio = (1 - size_after / size_before) * 100 if size_before > 0 else 0
    print(f"  Backup: {compressed_file.name}")
    print(f"  Tamaño: {size_before / 1024:.1f} KB → {size_after / 1024:.1f} KB (comprimido {ratio:.0f}%)")

    # 5. Rotación: eliminar backups viejos
    removed = _cleanup_old_backups(keep_days)
    if removed:
        print(f"  Rotación: {removed} backup(s) antiguos eliminados (keep={keep_days}d)")
    else:
        print(f"  Rotación: sin backups antiguos para eliminar (keep={keep_days}d)")

    # 6. Listar backups actuales
    backups = sorted(BACKUP_DIR.glob("dot_backup_*.sql.gz"))
    print(f"  Backups actuales: {len(backups)}")
    for b in backups[-5:]:
        size_kb = b.stat().st_size / 1024
        age = datetime.now() - datetime.fromtimestamp(b.stat().st_mtime)
        print(f"    {b.name}  ({size_kb:.0f} KB, {age.days}d atrás)")

    print("=== Backup completado OK ===")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup diario de base de datos DOT")
    parser.add_argument("--dry-run", action="store_true", help="Simula sin ejecutar pg_dump")
    parser.add_argument("--keep", type=int, default=7, help="Días de retención (default: 7)")
    args = parser.parse_args()

    success = run_backup(keep_days=args.keep, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
