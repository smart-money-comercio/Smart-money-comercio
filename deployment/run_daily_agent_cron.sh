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

  # Older installations may still have this cron entry alongside the bot service.
  if systemctl is-active --quiet smart-money-ai-bot.service && "$APP_DIR/.venv/bin/python" -c \
      'import os
from src.jobs.daily_report_scheduler import daily_report_enabled, get_daily_report_chat_ids
target = next((os.getenv(key) for key in ("TELEGRAM_CHANNEL_ID", "TELEGRAM_CHAT_ID", "TELEGRAM_COMMAND_CHAT_ID") if os.getenv(key)), "")
destinations = {str(chat).casefold() for chat in get_daily_report_chat_ids()}
raise SystemExit(0 if daily_report_enabled() and target.casefold() in destinations else 1)'; then
    echo "The active bot service owns scheduled report delivery."
    exit 0
  fi

  export DAILY_REPORT_LIVE_QUOTES="${DAILY_REPORT_LIVE_QUOTES:-1}"

  flock -n "$LOCK_FILE" "$APP_DIR/.venv/bin/python" scripts/run_daily_agent.py --send-telegram

  echo "Smart Money Daily Agent finished: $(date -Is)"
} >> "$LOG_FILE" 2>&1
