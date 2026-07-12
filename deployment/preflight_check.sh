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
  "src/insiders/insider_data.py"
  "src/insiders/insider_scoring.py"
  "src/reports/insider_report.py"
  "src/reports/ai_summary.py"
  "src/reports/action_checklist.py"
  "src/commands/volume_commands.py"
  "src/reports/global_market_report.py"
  "src/commands/global_commands.py"
  "src/reports/headlines_report.py"
  "src/reports/portfolio_headline_impact.py"
  "src/commands/headlines_commands.py"
  "src/commands/analyst_commands.py"
  
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
    "src.commands.volume_commands",
    "src.commands.market_commands",
    "src.commands.watchlist_commands",
    "src.commands.intelligence_commands",
    "src.jobs.daily_report_scheduler",
    "src.reports.daily_report",
    "src.reports.ai_summary",
    "src.reports.action_checklist",
    "src.scoring.scoring_engine",
    "src.reports.global_market_report",
    "src.reports.headlines_report",
    "src.reports.portfolio_headline_impact",
    "src.commands.headlines_commands",
    "src.commands.global_commands",
    "src.utils.watchlist_store",
    "src.commands.analyst_commands",
    "src.agents.analyst_agent",
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
    ("src.insiders.insider_data", "get_insider_trades"),
    ("src.insiders.insider_data", "get_insider_trades_for_symbol"),
    ("src.insiders.insider_scoring", "get_insider_score"),
    ("src.insiders.insider_scoring", "build_insider_score_details"),
    ("src.reports.insider_report", "build_insider_report"),
    ("src.commands.volume_commands", "volume"),
    ("src.commands.analyst_commands", "analyst_command"),
    ("src.reports.global_market_report", "build_global_market_report"),
    ("src.commands.global_commands", "global_market"),
    ("src.reports.headlines_report", "build_headlines_report"),
    ("src.reports.portfolio_headline_impact", "build_headline_impact_summary"),
    ("src.commands.headlines_commands", "headlines"),
    ("src.agents.analyst_agent", "run_analyst_agent"),
    ("src.agents.analyst_agent", "analyze_ticker"),
]

print("\nChecking daily report runtime build...")

try:
    from src.reports.daily_report import build_daily_report

    report = build_daily_report()

    if not isinstance(report, str):
        print("ERROR: build_daily_report() did not return a string")
        sys.exit(1)

    if len(report.strip()) < 100:
        print("ERROR: build_daily_report() returned an unexpectedly short report")
        sys.exit(1)

    required_sections = [
        "Smart Money AI Daily Report",
        "Market Snapshot",
        "Top Opportunities",
        "Risk Notes",
        "AI Summary",
        "Action Checklist",
    ]

    missing_sections = [
        section for section in required_sections
        if section not in report
    ]

    if missing_sections:
        print("ERROR: Daily report is missing required section(s):")
        for section in missing_sections:
            print(f"- {section}")
        sys.exit(1)

    print(f"OK: build_daily_report() generated {len(report)} characters")

except Exception as exc:
    print(f"ERROR: build_daily_report() failed: {type(exc).__name__}: {exc}")
    sys.exit(1)

for module_name, function_name in function_checks:
    module = importlib.import_module(module_name)

    if not hasattr(module, function_name):
        print(f"ERROR: {module_name} is missing function {function_name}")
        sys.exit(1)

    print(f"OK: {module_name}.{function_name}")

print("\nPreflight checks passed.")
PY

echo "Smart Money AI preflight passed."