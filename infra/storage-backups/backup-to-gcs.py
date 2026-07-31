#!/usr/bin/env python3
"""
Nordik-IA — PostgreSQL Backup to GCS

Dumps the Nordik-IA PostgreSQL database and uploads the dump to a GCS bucket
with date-stamped filenames, optional compression, and lifecycle support.

Requires:
    pip install google-cloud-storage psycopg2-binary

Usage:
    python backup-to-gcs.py \\
        --db-host 127.0.0.1 \\
        --db-user nordik_admin \\
        --db-pass "..." \\
        --db-name nordikdb \\
        --bucket nordik-prod-db-backups \\
        [--compress] \\
        [--retention-days 30] \\
        [--dry-run]
"""

import argparse
import gzip
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Command-line interface ───────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backup Nordik-IA PostgreSQL to GCS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db-host", required=True, help="PostgreSQL host")
    parser.add_argument("--db-port", default="5432", help="PostgreSQL port")
    parser.add_argument("--db-user", required=True, help="PostgreSQL user")
    parser.add_argument("--db-pass", required=True, help="PostgreSQL password")
    parser.add_argument("--db-name", required=True, help="Database name")
    parser.add_argument(
        "--bucket",
        required=True,
        help="GCS bucket name (e.g., nordik-prod-db-backups)",
    )
    parser.add_argument(
        "--compress",
        action="store_true",
        help="Gzip the dump before uploading",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=30,
        help="Days to retain daily backups (default: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Create dump but do not upload to GCS",
    )
    parser.add_argument(
        "--dump-dir",
        default=None,
        help="Directory for temporary dump files (default: system temp)",
    )
    return parser.parse_args()


# ── Database dump ────────────────────────────────────────────────────────────


def run_pg_dump(args: argparse.Namespace, dump_path: Path) -> None:
    """Execute pg_dump and write to the given path."""
    cmd = [
        "pg_dump",
        "-h", args.db_host,
        "-p", args.db_port,
        "-U", args.db_user,
        "-d", args.db_name,
        "-Fc",                # custom format (compressed, parallel restore)
        "--no-owner",
        "--no-acl",
        "-f", str(dump_path),
    ]

    env = os.environ.copy()
    env["PGPASSWORD"] = args.db_pass

    logger.info("Running pg_dump: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.error("pg_dump stderr:\n%s", result.stderr)
            raise RuntimeError(f"pg_dump failed with exit code {result.returncode}")
    except FileNotFoundError:
        logger.error("pg_dump not found. Install PostgreSQL client tools.")
        raise

    if not dump_path.is_file() or dump_path.stat().st_size == 0:
        raise RuntimeError(f"Dump file is empty or missing: {dump_path}")

    size_mb = dump_path.stat().st_size / (1024 * 1024)
    logger.info("pg_dump complete — %s (%.2f MB)", dump_path.name, size_mb)


# ── Compression ──────────────────────────────────────────────────────────────


def compress_dump(dump_path: Path) -> Path:
    """Gzip the dump file and return the path to the compressed file."""
    compressed_path = Path(str(dump_path) + ".gz")
    logger.info("Compressing %s → %s", dump_path.name, compressed_path.name)

    with dump_path.open("rb") as src:
        with gzip.open(compressed_path, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)

    size_mb = compressed_path.stat().st_size / (1024 * 1024)
    logger.info("Compressed to %.2f MB", size_mb)
    return compressed_path


# ── GCS upload ───────────────────────────────────────────────────────────────


def upload_to_gcs(
    local_path: Path,
    bucket_name: str,
    blob_name: str,
    dry_run: bool = False,
) -> None:
    """Upload a file to Google Cloud Storage."""
    if dry_run:
        logger.info("[DRY RUN] Would upload %s → gs://%s/%s", local_path, bucket_name, blob_name)
        return

    try:
        from google.cloud import storage
    except ImportError:
        logger.error(
            "google-cloud-storage not installed. Run: pip install google-cloud-storage"
        )
        raise

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    logger.info("Uploading to gs://%s/%s", bucket_name, blob_name)
    blob.upload_from_filename(str(local_path))
    logger.info("Upload complete — %s", blob_name)


# ── Retention cleanup ────────────────────────────────────────────────────────


def cleanup_old_backups(
    bucket_name: str,
    prefix: str,
    retention_days: int,
    dry_run: bool = False,
) -> None:
    """Delete backups older than retention_days from GCS."""
    try:
        from google.cloud import storage
    except ImportError:
        logger.error(
            "google-cloud-storage not installed. Run: pip install google-cloud-storage"
        )
        raise

    client = storage.Client()
    blobs = list(client.list_blobs(bucket_name, prefix=prefix))

    cutoff = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
    expired = [b for b in blobs if b.time_created and b.time_created.timestamp() < cutoff]

    if not expired:
        logger.info("No expired backups to clean up (retention=%d days)", retention_days)
        return

    logger.info("Cleaning up %d expired backup(s)", len(expired))
    for blob in expired:
        if dry_run:
            logger.info("[DRY RUN] Would delete gs://%s/%s", bucket_name, blob.name)
        else:
            blob.delete()
            logger.info("Deleted gs://%s/%s", bucket_name, blob.name)


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dump_dir = Path(args.dump_dir) if args.dump_dir else Path(tempfile.mkdtemp())
    dump_dir.mkdir(parents=True, exist_ok=True)

    suffix = ".dump.gz" if args.compress else ".dump"
    dump_filename = f"nordik_{args.db_name}_{timestamp}{suffix}"
    dump_path = dump_dir / dump_filename.replace(".gz", "")

    try:
        # Step 1 — Dump
        logger.info("=== PostgreSQL Backup to GCS ===")
        logger.info("DB: %s@%s:%s/%s", args.db_user, args.db_host, args.db_port, args.db_name)
        logger.info("Bucket: gs://%s", args.bucket)
        logger.info("Retention: %d days", args.retention_days)

        run_pg_dump(args, dump_path)

        # Step 2 — Compress (optional)
        upload_path = dump_path
        if args.compress:
            upload_path = compress_dump(dump_path)

        # Step 3 — Upload
        upload_to_gcs(
            local_path=upload_path,
            bucket_name=args.bucket,
            blob_name=upload_path.name,
            dry_run=args.dry_run,
        )

        # Step 4 — Cleanup old backups
        cleanup_old_backups(
            bucket_name=args.bucket,
            prefix="nordik_",
            retention_days=args.retention_days,
            dry_run=args.dry_run,
        )

        logger.info("=== Backup completed successfully ===")

    except Exception:
        logger.exception("Backup failed")
        sys.exit(1)
    finally:
        # Clean up local temp files
        if not args.dry_run and not args.dump_dir:
            for f in dump_dir.glob("nordik_*"):
                try:
                    f.unlink()
                    logger.debug("Cleaned up local file: %s", f)
                except OSError:
                    pass
            try:
                dump_dir.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    main()
