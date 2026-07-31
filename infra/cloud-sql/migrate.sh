#!/usr/bin/env bash
#
# Nordik-IA — Cloud SQL Migration Script
# Migrates a PostgreSQL database to Cloud SQL with validation.
#
# Usage:
#   SOURCE_DB_HOST=... SOURCE_DB_USER=... SOURCE_DB_PASS=... SOURCE_DB_NAME=... \
#   TARGET_DB_HOST=... TARGET_DB_USER=... TARGET_DB_PASS=... TARGET_DB_NAME=... \
#   bash migrate.sh
#
# Required env vars:
#   SOURCE_DB_HOST   — source PostgreSQL host[:port]
#   SOURCE_DB_USER   — source PostgreSQL user
#   SOURCE_DB_PASS   — source PostgreSQL password
#   SOURCE_DB_NAME   — source database name
#   TARGET_DB_HOST   — target Cloud SQL host[:port] (use Cloud SQL Proxy)
#   TARGET_DB_USER   — target Cloud SQL user
#   TARGET_DB_PASS   — target Cloud SQL password
#   TARGET_DB_NAME   — target Cloud SQL database name
#
# Optional env vars:
#   DUMP_DIR          — directory to store dump file (default: ./dumps)
#   PGDump_EXTRA_OPTS — extra flags for pg_dump
#   PGRESTORE_JOBS    — number of parallel restore jobs (default: 4)

set -euo pipefail

# ── helpers ──────────────────────────────────────────────────────────────────

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

die() {
  log "ERROR: $*"
  exit 1
}

check_var() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    die "Missing required env var: ${name}"
  fi
}

# ── validation ───────────────────────────────────────────────────────────────

for var in SOURCE_DB_HOST SOURCE_DB_USER SOURCE_DB_PASS SOURCE_DB_NAME \
           TARGET_DB_HOST TARGET_DB_USER TARGET_DB_PASS TARGET_DB_NAME; do
  check_var "$var"
done

DUMP_DIR="${DUMP_DIR:-./dumps}"
PGRESTORE_JOBS="${PGRESTORE_JOBS:-4}"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
DUMP_FILE="${DUMP_DIR}/migration_${SOURCE_DB_NAME}_${TIMESTAMP}.dump"

mkdir -p "${DUMP_DIR}"

export PGPASSWORD

# ── Step 1: Dump source database ─────────────────────────────────────────────

log "STEP 1/5 — Dumping source database ${SOURCE_DB_NAME} from ${SOURCE_DB_HOST}"

PGPASSWORD="${SOURCE_DB_PASS}" \
  pg_dump \
    -h "${SOURCE_DB_HOST}" \
    -U "${SOURCE_DB_USER}" \
    -d "${SOURCE_DB_NAME}" \
    -Fc \
    --no-owner \
    --no-acl \
    ${PGDump_EXTRA_OPTS:-} \
    -f "${DUMP_FILE}"

log "Dump written to ${DUMP_FILE} ($(du -h "${DUMP_FILE}" | cut -f1))"

# ── Step 2: Validate dump ────────────────────────────────────────────────────

log "STEP 2/5 — Validating dump file"

if [ ! -s "${DUMP_FILE}" ]; then
  die "Dump file is empty or does not exist: ${DUMP_FILE}"
fi

# pg_restore --list validates the archive is readable
PGPASSWORD="${SOURCE_DB_PASS}" \
  pg_restore --list "${DUMP_FILE}" > /dev/null

log "Dump file is valid (pg_restore --list succeeded)"

# ── Step 3: Restore to Cloud SQL ─────────────────────────────────────────────

log "STEP 3/5 — Restoring to target Cloud SQL ${TARGET_DB_NAME} on ${TARGET_DB_HOST}"

PGPASSWORD="${TARGET_DB_PASS}" \
  pg_restore \
    -h "${TARGET_DB_HOST}" \
    -U "${TARGET_DB_USER}" \
    -d "${TARGET_DB_NAME}" \
    -j "${PGRESTORE_JOBS}" \
    --no-owner \
    --no-acl \
    --clean \
    --if-exists \
    "${DUMP_FILE}"

log "Restore completed successfully"

# ── Step 4: Verify row counts ────────────────────────────────────────────────

log "STEP 4/5 — Verifying row counts for key tables"

KEY_TABLES=("clientes_suscripcion" "subscription_tokens")

verify_table() {
  local table="$1"

  log "Verifying table: ${table}"

  local source_count
  source_count=$(PGPASSWORD="${SOURCE_DB_PASS}" \
    psql -h "${SOURCE_DB_HOST}" -U "${SOURCE_DB_USER}" -d "${SOURCE_DB_NAME}" \
      -t -A -c "SELECT COUNT(*) FROM ${table};")

  local target_count
  target_count=$(PGPASSWORD="${TARGET_DB_PASS}" \
    psql -h "${TARGET_DB_HOST}" -U "${TARGET_DB_USER}" -d "${TARGET_DB_NAME}" \
      -t -A -c "SELECT COUNT(*) FROM ${table};")

  if [ "${source_count}" != "${target_count}" ]; then
    log "MISMATCH — ${table}: source=${source_count} target=${target_count}"
    return 1
  fi

  log "OK — ${table}: ${source_count} rows match"
}

MISMATCHES=0
for table in "${KEY_TABLES[@]}"; do
  if ! verify_table "${table}"; then
    MISMATCHES=$((MISMATCHES + 1))
  fi
done

if [ "${MISMATCHES}" -gt 0 ]; then
  die "Row count verification FAILED for ${MISMATCHES} table(s)"
fi

# ── Step 5: Final report ─────────────────────────────────────────────────────

log "STEP 5/5 — Migration complete"
log "═══════════════════════════════════════════════════════════════"
log "Migration finished successfully at $(date '+%Y-%m-%d %H:%M:%S')"
log "Source:  ${SOURCE_DB_HOST}/${SOURCE_DB_NAME}"
log "Target:  ${TARGET_DB_HOST}/${TARGET_DB_NAME}"
log "Dump:    ${DUMP_FILE}"
log "All key table row counts verified."
log "═══════════════════════════════════════════════════════════════"
