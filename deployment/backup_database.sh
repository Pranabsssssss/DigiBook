#!/usr/bin/env bash
# DigiBook Daily Database Backup Script
set -e

BACKUP_DIR="/home/pi/DigiBook/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
FILENAME="$BACKUP_DIR/digibook_backup_$TIMESTAMP.sql.gz"

mkdir -p "$BACKUP_DIR"

# Source environment variables if present
if [ -f "/home/pi/DigiBook/.env" ]; then
    export $(grep -v '^#' /home/pi/DigiBook/.env | xargs)
fi

DB_USER="${DB_USER:-digibook}"
DB_PASS="${DB_PASSWORD:-digibook_secure_pass_2026}"
DB_NAME="${DB_NAME:-digibook}"

echo "[DigiBook Backup] Dumping database $DB_NAME..."
mysqldump -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" | gzip > "$FILENAME"

echo "[DigiBook Backup] Successfully saved backup to: $FILENAME"

# Retain backups for 14 days, delete older
find "$BACKUP_DIR" -type f -name "digibook_backup_*.sql.gz" -mtime +14 -delete
echo "[DigiBook Backup] Retained backups newer than 14 days."
