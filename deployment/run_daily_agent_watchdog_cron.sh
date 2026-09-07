#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/smart-money-comercio"
LOG_FILE="$APP_DIR/data/daily_agent_watchdog_cron.log"
LOCK_FILE="/tmp/smart-money-daily-agent-watchdog.lock"

cd "$APP_DIR"

mkdir -p data

{
  echo ""
  echo "============================================================"
  echo "Smart Money Daily Agent Watchdog started: $(date -Is)"
  echo "============================================================"

  if [ -f ".env" ]; then
    set -a
    source ".env"
    set +a
  fi

  flock -n "$LOCK_FILE" "$APP_DIR/.venv/bin/python" scripts/run_watchdog.py --send-telegram

  echo "Smart Money Daily Agent Watchdog finished: $(date -Is)"
} >> "$LOG_FILE" 2>&1
