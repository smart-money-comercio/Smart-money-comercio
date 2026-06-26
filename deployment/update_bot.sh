#!/bin/bash

set -e

APP_DIR="/opt/smart-money-comercio"
SERVICE_NAME="smart-money-ai-bot"
PYTHON_BIN="$APP_DIR/.venv/bin/python"
PIP_BIN="$APP_DIR/.venv/bin/pip"

echo "======================================"
echo "Smart Money AI Bot Update"
echo "======================================"

cd "$APP_DIR"

echo "Adding Git safe.directory exception..."
git config --global --add safe.directory "$APP_DIR" || true

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