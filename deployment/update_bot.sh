#!/bin/bash

set -e

APP_DIR="/opt/smart-money-comercio"
SERVICE_NAME="smart-money-ai-bot"
PYTHON_BIN="$APP_DIR/.venv/bin/python"
PIP_BIN="$APP_DIR/.venv/bin/pip"
BACKUP_SCRIPT="$APP_DIR/deployment/backup_server.sh"

if [ "$EUID" -ne 0 ]; then
    echo "Please run this script with sudo."
    echo "Example: sudo bash deployment/update_bot.sh"
    exit 1
fi

echo "======================================"
echo "Smart Money AI Bot Update"
echo "======================================"

cd "$APP_DIR"

echo "Adding Git safe.directory exception..."
git config --global --add safe.directory "$APP_DIR" || true

if [ -f "$BACKUP_SCRIPT" ]; then
    echo "Creating pre-update backup..."
    bash "$BACKUP_SCRIPT"
else
    echo "Backup script not found. Skipping pre-update backup."
fi

if [ -d ".git" ]; then
    echo "Pulling latest code from GitHub..."
    git pull origin main
else
    echo "No Git repository found. Skipping git pull."
    echo "This project folder must be cloned from GitHub for automatic updates."
fi

echo "Installing/updating requirements..."
"$PIP_BIN" install --upgrade pip
"$PIP_BIN" install -r requirements.txt

echo "Checking Python syntax..."
"$PYTHON_BIN" -m compileall src

echo "Restarting service..."
systemctl restart "$SERVICE_NAME"

echo "Checking service status..."
systemctl status "$SERVICE_NAME" --no-pager

echo "======================================"
echo "Update complete."
echo "======================================"