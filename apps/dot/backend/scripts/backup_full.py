"""Backup unificado — Postgres + Firestore + GCS con programación automática.

Billing-Ops: Backup completo del sistema Nordik-IA.

Soporta:
  1. PostgreSQL (pg_dump) — heredado de backup_db.py
  2. Firestore (export JSON) — colecciones principales de usuarios
  3. GCS (Google Cloud Storage) — rotación si GOOGLE_APPLICATION_CREDENTIALS existe
  4. Rotación local + remota con retención configurable

Uso:
    python scripts/backup_full.py                    # backup completo
    python scripts/backup_full.py --pg-only           # solo Postgres
    python scripts/backup_full.py --firestore-only    # solo Firestore
    python scripts/backup_full.py --dry-run           # simula sin ejecutar
    python scripts/backup_full.py --keep 14           # retención 14 días

Requisitos:
    - pg_dump instalado y en PATH (solo para --pg-only / backup completo)
    - Firestore: firebase-service-account.json configurado
    - GCS: GOOGLE_APPLICATION_CREDENTIALS configurado (opcional)
    - Python 3.11+
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

# ─── Configuración  ───────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
BACKUP_DIR = BACKEND_DIR / "backups"
LOG_FORMAT = "[%(asctime)s] %(levelname)s — %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=DATE_FORMAT, stream=sys.stdout)
log = logging.getLogger("backup_full")


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════

def _load_database_url() -> str:
    """Carga DATABASE_URL desde .env del backend."""
    env_file = BACKEND_DIR / ".env"
    if not env_file.is_file():
        log.error(".env no encontrado en %s", env_file)
        sys.exit(1)
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        if line.startswith("DATABASE_URL="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value:
                return value
    log.error("DATABASE_URL no configurada en .env")
    sys.exit(1)


def _check_pg_dump() -> str:
    """Verifica que pg_dump esté disponible. Devuelve el path."""
    pg_dump = shutil.which("pg_dump")
    if pg_dump:
        return pg_dump
    log.error(
        "pg_dump no encontrado en PATH. Instala PostgreSQL client tools:\n"
        "  Linux: sudo apt install postgresql-client\n"
        "  Windows: https://www.postgresql.org/download/"
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


def _gcs_client():
    """Retorna cliente GCS si GOOGLE_APPLICATION_CREDENTIALS está configurado."""
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not creds or not Path(creds).is_file():
        return None
    try:
        from google.cloud import storage
        return storage.Client()
    except ImportError:
        log.warning("google-cloud-storage no instalado. GCS no disponible.")
        return None
    except Exception as e:
        log.warning("Error al conectar con GCS: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════════
#  POSTGRES BACKUP
# ═══════════════════════════════════════════════════════════════════

def backup_postgres(dry_run: bool = False) -> Path | None:
    """Ejecuta pg_dump y devuelve la ruta del archivo comprimido."""
    db_url = _load_database_url()
    pg_dump = _check_pg_dump()
    conn = _parse_pg_url(db_url)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_file = BACKUP_DIR / f"dot_backup_{timestamp}.sql"
    compressed_file = BACKUP_DIR / f"dot_backup_{timestamp}.sql.gz"

    log.info("PostgreSQL: %s@%s:%s", conn["dbname"], conn["host"], conn["port"])

    if dry_run:
        log.info("[DRY RUN] pg_dump no ejecutado. Sería: %s", compressed_file)
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if conn["password"]:
        env["PGPASSWORD"] = conn["password"]

    cmd = [
        pg_dump, "-h", conn["host"], "-p", conn["port"],
        "-U", conn["user"], "-d", conn["dbname"],
        "--no-owner", "--no-acl", "-f", str(backup_file),
    ]

    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            error_msg = result.stderr.strip().split("\n")[-1] if result.stderr else "error desconocido"
            log.error("pg_dump falló (código %d): %s", result.returncode, error_msg)
            if backup_file.exists():
                backup_file.unlink()
            return None
    except subprocess.TimeoutExpired:
        log.error("pg_dump timeout (>300s)")
        if backup_file.exists():
            backup_file.unlink()
        return None

    size_before = backup_file.stat().st_size
    with open(backup_file, "rb") as f_in:
        with gzip.open(str(compressed_file), "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
    size_after = compressed_file.stat().st_size
    backup_file.unlink()

    ratio = (1 - size_after / size_before) * 100 if size_before > 0 else 0
    log.info(
        "PostgreSQL backup: %s (%.1f KB → %.1f KB, %d%% comprimido)",
        compressed_file.name, size_before / 1024, size_after / 1024, int(ratio),
    )
    return compressed_file


# ═══════════════════════════════════════════════════════════════════
#  FIRESTORE BACKUP
# ═══════════════════════════════════════════════════════════════════

# Colecciones principales de Firestore a respaldar
FIRESTORE_COLLECTIONS = [
    "users",
    "user_google_tokens",
    "automation_templates",
    "pendrive_recovery",
]


def backup_firestore(dry_run: bool = False) -> Path | None:
    """Exporta colecciones principales de Firestore a JSON comprimido."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    firestore_file = BACKUP_DIR / f"firestore_backup_{timestamp}.json"
    compressed_file = BACKUP_DIR / f"firestore_backup_{timestamp}.json.gz"

    log.info("Firestore: exportando %d colecciones", len(FIRESTORE_COLLECTIONS))

    if dry_run:
        log.info("[DRY RUN] Firestore no exportado. Sería: %s", compressed_file)
        return None

    try:
        # Intentar inicializar Firebase
        sys.path.insert(0, str(BACKEND_DIR))
        from app.firebase_db import get_db

        db = get_db()
        if db is None:
            log.warning("Firestore no disponible. Omitiendo backup Firestore.")
            return None

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

        export_data: dict[str, list[dict]] = {
            "metadata": {
                "backup_type": "firestore_export",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "collections": FIRESTORE_COLLECTIONS,
            }
        }

        total_docs = 0
        for collection_name in FIRESTORE_COLLECTIONS:
            try:
                docs = list(db.collection(collection_name).stream())
                export_data[collection_name] = [doc.to_dict() for doc in docs]
                log.info(
                    "  Colección '%s': %d documentos exportados",
                    collection_name, len(docs),
                )
                total_docs += len(docs)
            except Exception as e:
                log.warning(
                    "  Error exportando colección '%s': %s. Continuando...",
                    collection_name, e,
                )
                export_data[collection_name] = [{"_export_error": str(e)}]

        # Escribir JSON y comprimir
        with open(firestore_file, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, default=str)

        with open(firestore_file, "rb") as f_in:
            with gzip.open(str(compressed_file), "wb", compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)
        firestore_file.unlink()

        size_kb = compressed_file.stat().st_size / 1024
        log.info(
            "Firestore backup: %s (%.1f KB, %d documentos totales)",
            compressed_file.name, size_kb, total_docs,
        )
        return compressed_file

    except Exception as e:
        log.error("Error exportando Firestore: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════════
#  GCS UPLOAD + ROTATION
# ═══════════════════════════════════════════════════════════════════

GCS_BACKUP_PREFIX = "nordik-backups"


def upload_to_gcs(
    local_path: Path,
    bucket_name: str | None = None,
    dry_run: bool = False,
) -> bool:
    """Sube un archivo de backup a GCS si está configurado."""
    if dry_run:
        log.info("[DRY RUN] No se subiría %s a GCS", local_path.name)
        return True

    gcs = _gcs_client()
    if gcs is None:
        log.info("GCS no configurado. Backup local solamente.")
        return False

    bucket_name = bucket_name or os.environ.get("GCS_BACKUP_BUCKET", "")
    if not bucket_name:
        log.warning("GCS_BACKUP_BUCKET no configurada. Omitiendo subida.")
        return False

    try:
        bucket = gcs.bucket(bucket_name)
        blob_name = f"{GCS_BACKUP_PREFIX}/{local_path.name}"
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(str(local_path))
        log.info("GCS: subido gs://%s/%s", bucket_name, blob_name)
        return True
    except Exception as e:
        log.error("Error subiendo a GCS: %s", e)
        return False


def cleanup_gcs(
    bucket_name: str | None = None,
    prefix: str = GCS_BACKUP_PREFIX,
    keep_days: int = 7,
    dry_run: bool = False,
) -> int:
    """Elimina backups GCS más viejos que keep_days."""
    gcs = _gcs_client()
    if gcs is None:
        return 0

    bucket_name = bucket_name or os.environ.get("GCS_BACKUP_BUCKET", "")
    if not bucket_name:
        return 0

    try:
        bucket = gcs.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=prefix))
        cutoff = datetime.now(timezone.utc).timestamp() - (keep_days * 86400)

        removed = 0
        for blob in blobs:
            if blob.time_created and blob.time_created.timestamp() < cutoff:
                if dry_run:
                    log.info("[DRY RUN] GCS: eliminaría gs://%s/%s", bucket_name, blob.name)
                else:
                    blob.delete()
                    log.info("GCS: eliminado gs://%s/%s", bucket_name, blob.name)
                removed += 1

        if removed:
            log.info("GCS rotación: %d backups eliminados (keep=%d días)", removed, keep_days)
        return removed
    except Exception as e:
        log.warning("Error en rotación GCS: %s", e)
        return 0


# ═══════════════════════════════════════════════════════════════════
#  LOCAL ROTATION
# ═══════════════════════════════════════════════════════════════════

def cleanup_local(directory: Path, pattern: str = "*.gz", keep_days: int = 7) -> int:
    """Elimina backups locales más viejos que keep_days."""
    if not directory.is_dir():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    removed = 0
    for f in sorted(directory.glob(pattern)):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                f.unlink()
                removed += 1
                log.info("  [rotación] eliminado: %s", f.name)
        except OSError as e:
            log.warning("  [rotación] error eliminando %s: %s", f.name, e)
    return removed


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

def run_full_backup(
    pg: bool = True,
    firestore: bool = True,
    gcs: bool = True,
    keep_days: int = 7,
    dry_run: bool = False,
) -> dict:
    """Ejecuta backup completo. Devuelve resumen."""
    timestamp = datetime.now().isoformat()
    result: dict = {
        "timestamp": timestamp,
        "dry_run": dry_run,
        "postgres": None,
        "firestore": None,
        "gcs_uploaded": [],
        "cleanup_local": 0,
        "cleanup_gcs": 0,
        "success": False,
        "errors": [],
    }

    log.info("=== Backup Completo Nordik-IA === %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("Modo: %s", "DRY RUN" if dry_run else "LIVE")
    if pg:
        log.info("Componentes: PostgreSQL%s%s%s",
                 " + Firestore" if firestore else "",
                 " + GCS" if gcs else "",
                 f" (retención: {keep_days}d)")
    else:
        log.info("Componentes: %s", "Firestore" if firestore else "ninguno")

    # 1. PostgreSQL
    if pg:
        try:
            result["postgres"] = backup_postgres(dry_run=dry_run)
            if result["postgres"] and gcs:
                gcs_ok = upload_to_gcs(result["postgres"], dry_run=dry_run)
                if gcs_ok:
                    result["gcs_uploaded"].append(str(result["postgres"].name))
        except Exception as e:
            log.error("Backup PostgreSQL falló: %s", e)
            result["errors"].append(f"PostgreSQL: {e}")

    # 2. Firestore
    if firestore:
        try:
            result["firestore"] = backup_firestore(dry_run=dry_run)
            if result["firestore"] and gcs:
                gcs_ok = upload_to_gcs(result["firestore"], dry_run=dry_run)
                if gcs_ok:
                    result["gcs_uploaded"].append(str(result["firestore"].name))
        except Exception as e:
            log.error("Backup Firestore falló: %s", e)
            result["errors"].append(f"Firestore: {e}")

    # 3. Rotación local
    result["cleanup_local"] = cleanup_local(BACKUP_DIR, keep_days=keep_days)

    # 4. Rotación GCS
    if gcs:
        result["cleanup_gcs"] = cleanup_gcs(keep_days=keep_days, dry_run=dry_run)

    # 5. Resumen final
    backups = sorted(BACKUP_DIR.glob("*.gz")) if BACKUP_DIR.is_dir() else []
    log.info("Backups locales actuales: %d", len(backups))
    for b in backups[-5:]:
        size_kb = b.stat().st_size / 1024
        age = datetime.now() - datetime.fromtimestamp(b.stat().st_mtime)
        log.info("  %s  (%.0f KB, %dd atrás)", b.name, size_kb, age.days)

    result["success"] = result["errors"] == []
    if result["success"]:
        log.info("=== Backup completado OK ===")
    else:
        log.error("=== Backup completado con errores ===")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup completo Nordik-IA (Postgres + Firestore + GCS)")
    parser.add_argument("--pg-only", action="store_true", help="Solo backup de PostgreSQL")
    parser.add_argument("--firestore-only", action="store_true", help="Solo backup de Firestore")
    parser.add_argument("--no-gcs", action="store_true", help="No subir a GCS aunque esté configurado")
    parser.add_argument("--dry-run", action="store_true", help="Simula sin ejecutar")
    parser.add_argument("--keep", type=int, default=7, help="Días de retención (default: 7)")
    args = parser.parse_args()

    pg = not args.firestore_only
    firestore = not args.pg_only
    gcs = not args.no_gcs

    result = run_full_backup(
        pg=pg,
        firestore=firestore,
        gcs=gcs,
        keep_days=args.keep,
        dry_run=args.dry_run,
    )
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
