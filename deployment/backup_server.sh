#!/bin/bash

set -euo pipefail

APP_DIR="/opt/smart-money-comercio"
BACKUP_DIR="/opt/smart-money-backups"
SERVICE_NAME="smart-money-ai-bot"

if [ "$EUID" -ne 0 ]; then
    echo "Please run this script with sudo."
    echo "Example: sudo bash deployment/backup_server.sh"
    exit 1
fi

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_NAME="smart-money-backup-$TIMESTAMP"
STAGING_DIR="/tmp/$BACKUP_NAME"
BACKUP_FILE="$BACKUP_DIR/$BACKUP_NAME.tar.gz"

echo "======================================"
echo "Smart Money AI Bot Backup"
echo "======================================"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

echo "Creating backup staging folder..."

cat > "$STAGING_DIR/manifest.txt" <<EOF
Smart Money AI Bot Backup
Created: $(date)
Hostname: $(hostname)
App directory: $APP_DIR
Service name: $SERVICE_NAME
Git branch: $(cd "$APP_DIR" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "Unavailable")
Git commit: $(cd "$APP_DIR" && git log -1 --pretty="%h - %s" 2>/dev/null || echo "Unavailable")
Service status: $(systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo "Unavailable")
EOF

if [ -f "$APP_DIR/.env" ]; then
    echo "Backing up .env..."
    cp "$APP_DIR/.env" "$STAGING_DIR/.env"
else
    echo "No .env file found. Skipping."
fi

if [ -d "$APP_DIR/data" ]; then
    echo "Backing up data folder..."
    cp -r "$APP_DIR/data" "$STAGING_DIR/data"
else
    echo "No data folder found. Skipping."
fi

if [ -f "/etc/systemd/system/$SERVICE_NAME.service" ]; then
    echo "Backing up systemd service file..."
    mkdir -p "$STAGING_DIR/systemd"
    cp "/etc/systemd/system/$SERVICE_NAME.service" "$STAGING_DIR/systemd/$SERVICE_NAME.service"
fi

echo "Creating compressed backup..."
tar -czf "$BACKUP_FILE" -C "$STAGING_DIR" .

chmod 600 "$BACKUP_FILE"
rm -rf "$STAGING_DIR"

echo "Cleaning old backups, keeping latest 10..."
ls -1t "$BACKUP_DIR"/smart-money-backup-*.tar.gz 2>/dev/null | tail -n +11 | xargs -r rm -f

echo "Backup created:"
echo "$BACKUP_FILE"

echo "======================================"
echo "Backup complete."
echo "======================================"