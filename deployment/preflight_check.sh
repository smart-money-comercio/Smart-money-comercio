#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/smart-money-comercio"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"

cd "$PROJECT_DIR"

echo "Running Smart Money AI preflight checks..."

if [ ! -x "$PYTHON_BIN" ]; then
  echo "ERROR: Python virtual environment not found at $PYTHON_BIN"
  exit 1
fi

echo "1/3 Checking required files..."

required_files=(
  "src/bot.py"
  "src/commands/register_commands.py"
  "src/commands/daily_report_send_commands.py"
  "src/jobs/daily_report_scheduler.py"
  "src/reports/daily_report.py"
  "src/reports/ai_summary.py"
  "src/reports/action_checklist.py"
)

for file in "${required_files[@]}"; do
  if [ ! -f "$file" ]; then
    echo "ERROR: Missing required file: $file"
    exit 1
  fi
done

echo "2/3 Compiling Python files..."

"$PYTHON_BIN" -m compileall src scripts

echo "3/3 Checking critical imports..."

PYTHONPATH="$PROJECT_DIR" "$PYTHON_BIN" - <<'PY'
import importlib
import sys

modules = [
    "src.bot",
    "src.commands.register_commands",
    "src.commands.daily_report_send_commands",
    "src.commands.market_commands",
    "src.commands.watchlist_commands",
    "src.commands.intelligence_commands",
    "src.jobs.daily_report_scheduler",
    "src.reports.daily_report",
    "src.reports.ai_summary",
    "src.reports.action_checklist",
    "src.scoring.scoring_engine",
    "src.utils.watchlist_store",
]

failed = []

for module_name in modules:
    try:
        importlib.import_module(module_name)
        print(f"OK: {module_name}")
    except Exception as exc:
        failed.append((module_name, type(exc).__name__, str(exc)))

if failed:
    print("\nERROR: Critical import check failed.\n")
    for module_name, error_type, message in failed:
        print(f"- {module_name}: {error_type}: {message}")
    sys.exit(1)

function_checks = [
    ("src.reports.daily_report", "build_daily_report"),
    ("src.reports.ai_summary", "build_ai_summary"),
    ("src.reports.action_checklist", "build_action_checklist"),
]

for module_name, function_name in function_checks:
    module = importlib.import_module(module_name)

    if not hasattr(module, function_name):
        print(f"ERROR: {module_name} is missing function {function_name}")
        sys.exit(1)

    print(f"OK: {module_name}.{function_name}")

print("\nPreflight checks passed.")
PY

echo "Smart Money AI preflight passed."