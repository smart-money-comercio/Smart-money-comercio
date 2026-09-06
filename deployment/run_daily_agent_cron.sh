#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/smart-money-comercio"
LOG_FILE="$APP_DIR/data/daily_agent_cron.log"
LOCK_FILE="/tmp/smart-money-daily-agent.lock"

cd "$APP_DIR"

mkdir -p data

{
  echo ""
  echo "============================================================"
  echo "Smart Money Daily Agent started: $(date -Is)"
  echo "============================================================"

  if [ -f ".env" ]; then
    set -a
    source ".env"
    set +a
  fi

  export DAILY_REPORT_LIVE_QUOTES="${DAILY_REPORT_LIVE_QUOTES:-1}"

  flock -n "$LOCK_FILE" "$APP_DIR/.venv/bin/python" scripts/run_daily_agent.py --send-telegram

  echo "Smart Money Daily Agent finished: $(date -Is)"
} >> "$LOG_FILE" 2>&1
