#!/usr/bin/env bash
#
# Nightly MySQL backup with optional S3 upload.
#
# Usage:
#   ./scripts/backup_db.sh                # local-only, writes to ./backups/
#   ./scripts/backup_db.sh s3://my-bucket # also uploads to the given prefix
#
# Required env (from .env or process):
#   DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
#
# Optional env:
#   BACKUP_DIR        — local backup directory (default: ./backups)
#   BACKUP_RETAIN     — number of daily backups to keep locally (default: 14)
#   AWS_PROFILE       — passed through to `aws` if set
#
# Cron example (daily at 02:30 UTC, log to /var/log/erp-backup.log):
#
#   30 2 * * *  cd /opt/erp && ./scripts/backup_db.sh s3://my-bucket/erp-backups \
#                  >> /var/log/erp-backup.log 2>&1
#
set -euo pipefail

: "${DB_HOST:?DB_HOST is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"
: "${DB_NAME:?DB_NAME is required}"

DB_PORT="${DB_PORT:-3306}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_RETAIN="${BACKUP_RETAIN:-14}"
S3_PREFIX="${1:-}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
out="${BACKUP_DIR}/${DB_NAME}-${ts}.sql.gz"

mkdir -p "${BACKUP_DIR}"

echo "[$(date -u +%FT%TZ)] dumping ${DB_NAME} to ${out}"
mysqldump \
    --host="${DB_HOST}" \
    --port="${DB_PORT}" \
    --user="${DB_USER}" \
    --password="${DB_PASSWORD}" \
    --single-transaction \
    --routines \
    --triggers \
    --quick \
    --set-gtid-purged=OFF \
    "${DB_NAME}" \
  | gzip -9 > "${out}"

echo "[$(date -u +%FT%TZ)] dump size: $(du -h "${out}" | awk '{print $1}')"

if [[ -n "${S3_PREFIX}" ]]; then
    if ! command -v aws >/dev/null 2>&1; then
        echo "ERROR: aws CLI not installed; skipping S3 upload" >&2
        exit 2
    fi
    s3_target="${S3_PREFIX%/}/${DB_NAME}-${ts}.sql.gz"
    echo "[$(date -u +%FT%TZ)] uploading to ${s3_target}"
    aws s3 cp "${out}" "${s3_target}" --only-show-errors
fi

# Local rotation — keep the newest BACKUP_RETAIN files, delete the rest.
ls -1t "${BACKUP_DIR}/${DB_NAME}-"*.sql.gz 2>/dev/null \
    | tail -n +"$((BACKUP_RETAIN + 1))" \
    | xargs -r rm -f

echo "[$(date -u +%FT%TZ)] backup complete"
