import asyncio
import importlib
import os
import platform
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from src.utils.telegram_messages import edit_or_reply_long_message


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_TIMEZONE = "America/Lima"
SERVICE_NAME = "smart-money-ai-bot"

REPORT_TIMEOUT_SECONDS = 10
INSIDER_TIMEOUT_SECONDS = 6


REQUIRED_FILES = [
    "src/bot.py",
    "src/commands/register_commands.py",
    "src/commands/deploycheck_commands.py",
    "src/reports/daily_report.py",
    "src/reports/global_market_report.py",
    "src/reports/headlines_report.py",
    "src/reports/scorecard.py",
    "src/reports/portfolio_headline_impact.py",
    "src/insiders/insider_data.py",
    "src/insiders/insider_scoring.py",
    "src/reports/insider_report.py",
    "deployment/update_bot.sh",
    "deployment/preflight_check.sh",
]

CRITICAL_MODULES = [
    "src.bot",
    "src.commands.register_commands",
    "src.commands.deploycheck_commands",
    "src.reports.daily_report",
    "src.reports.global_market_report",
    "src.reports.headlines_report",
    "src.reports.scorecard",
    "src.reports.portfolio_headline_impact",
    "src.insiders.insider_data",
    "src.insiders.insider_scoring",
    "src.reports.insider_report",
    "src.scoring.scoring_engine",
]

FUNCTION_CHECKS = [
    ("src.reports.daily_report", "build_daily_report"),
    ("src.reports.global_market_report", "build_global_market_report"),
    ("src.reports.headlines_report", "build_headlines_report"),
    ("src.reports.scorecard", "build_scorecard"),
    ("src.reports.portfolio_headline_impact", "build_headline_impact_summary"),
    ("src.insiders.insider_data", "get_insider_trades"),
    ("src.insiders.insider_data", "get_insider_trades_for_symbol"),
    ("src.insiders.insider_scoring", "get_insider_score"),
    ("src.insiders.insider_scoring", "build_insider_score_details"),
    ("src.reports.insider_report", "build_insider_report"),
]

REQUIRED_REPORT_SECTIONS = [
    "Smart Money AI Daily Report",
    "Executive Summary",
    "Market Snapshot",
    "Top Opportunities",
    "Risk Notes",
    "Action Checklist",
]


def clean_text(value: Any, max_length: int = 300) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def status_icon(ok: bool) -> str:
    return "✅" if ok else "❌"


def warning_icon(ok: bool) -> str:
    return "✅" if ok else "⚠️"


def env_present(name: str) -> bool:
    return bool(str(os.getenv(name, "")).strip())

def env_any_present(names: list[str]) -> bool:
    return any(env_present(name) for name in names)

def get_admin_ids() -> set[str]:
    raw = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")

    return {
        item.strip()
        for item in raw.replace(";", ",").split(",")
        if item.strip()
    }


def is_admin(update: Update) -> bool:
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    admin_ids = get_admin_ids()

    return bool(chat_id and chat_id in admin_ids)


def run_command(command: list[str], timeout: int = 5) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = (result.stdout or result.stderr or "").strip()

        return result.returncode == 0, clean_text(output, 500)

    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


def check_service_status() -> dict:
    if platform.system().lower() != "linux":
        return {
            "active": "Skipped on local/dev machine",
            "enabled": "Skipped on local/dev machine",
            "ok": True,
        }

    active_ok, active_output = run_command(
        ["systemctl", "is-active", SERVICE_NAME],
        timeout=4,
    )

    enabled_ok, enabled_output = run_command(
        ["systemctl", "is-enabled", SERVICE_NAME],
        timeout=4,
    )

    active = active_output or "Unavailable"
    enabled = enabled_output or "Unavailable"

    return {
        "active": active,
        "enabled": enabled,
        "ok": active_ok and active == "active",
    }


def get_git_status() -> dict:
    branch_ok, branch = run_command(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        timeout=4,
    )

    commit_ok, commit = run_command(
        ["git", "log", "-1", "--pretty=%h - %s"],
        timeout=4,
    )

    tree_ok, tree = run_command(
        ["git", "status", "--short"],
        timeout=4,
    )

    if tree_ok:
        working_tree = "Clean" if not tree else "Local changes present"
    else:
        working_tree = f"Unavailable: {tree}"

    return {
        "branch": branch if branch_ok else f"Unavailable: {branch}",
        "commit": commit if commit_ok else f"Unavailable: {commit}",
        "working_tree": working_tree,
        "ok": branch_ok and commit_ok and tree_ok and not tree,
    }


def check_required_files() -> tuple[list[str], list[str]]:
    present = []
    missing = []

    for relative_path in REQUIRED_FILES:
        path = PROJECT_ROOT / relative_path

        if path.exists():
            present.append(relative_path)
        else:
            missing.append(relative_path)

    return present, missing


def check_imports() -> list[str]:
    errors = []

    for module_name in CRITICAL_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as error:
            errors.append(f"{module_name}: {type(error).__name__}: {error}")

    return errors


def check_functions() -> list[str]:
    errors = []

    for module_name, function_name in FUNCTION_CHECKS:
        try:
            module = importlib.import_module(module_name)

            if not hasattr(module, function_name):
                errors.append(f"{module_name}: missing {function_name}")

        except Exception as error:
            errors.append(f"{module_name}.{function_name}: {type(error).__name__}: {error}")

    return errors


def run_with_timeout(function, timeout_seconds: int):
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(function)
        return future.result(timeout=timeout_seconds)


def check_daily_report_runtime() -> dict:
    started = time.perf_counter()

    try:
        from src.reports.daily_report import build_daily_report

        report = run_with_timeout(
            build_daily_report,
            REPORT_TIMEOUT_SECONDS,
        )

        elapsed = time.perf_counter() - started

        missing_sections = [
            section
            for section in REQUIRED_REPORT_SECTIONS
            if section not in report
        ]

        return {
            "ok": not missing_sections,
            "elapsed": elapsed,
            "length": len(report),
            "missing_sections": missing_sections,
            "error": "",
        }

    except TimeoutError:
        return {
            "ok": False,
            "elapsed": REPORT_TIMEOUT_SECONDS,
            "length": 0,
            "missing_sections": [],
            "error": "Timed out. Daily report may still be doing live network work.",
        }

    except Exception as error:
        return {
            "ok": False,
            "elapsed": time.perf_counter() - started,
            "length": 0,
            "missing_sections": [],
            "error": f"{type(error).__name__}: {error}",
        }


def check_insider_fast_path() -> dict:
    started = time.perf_counter()

    try:
        from src.insiders.insider_scoring import build_insider_score_details

        details = run_with_timeout(
            lambda: build_insider_score_details("NVDA", force_refresh=False),
            INSIDER_TIMEOUT_SECONDS,
        )

        elapsed = time.perf_counter() - started
        breakdown = details.get("breakdown") or {}

        required_whale_fields = [
            "whale_label",
            "whale_purchases",
            "whale_buyers",
            "whale_purchase_value",
            "top_whales",
        ]

        missing_whale_fields = [
            field
            for field in required_whale_fields
            if field not in breakdown
        ]

        return {
            "ok": not missing_whale_fields,
            "elapsed": elapsed,
            "label": details.get("label", "Unknown"),
            "missing_whale_fields": missing_whale_fields,
            "error": "",
        }

    except TimeoutError:
        return {
            "ok": False,
            "elapsed": INSIDER_TIMEOUT_SECONDS,
            "label": "Unavailable",
            "missing_whale_fields": [],
            "error": "Timed out. Insider scoring may still be doing live SEC calls.",
        }

    except Exception as error:
        return {
            "ok": False,
            "elapsed": time.perf_counter() - started,
            "label": "Unavailable",
            "missing_whale_fields": [],
            "error": f"{type(error).__name__}: {error}",
        }


def get_cache_status() -> str:
    data_dir = PROJECT_ROOT / "data"

    files = [
        "watchlist.json",
        "volume_signal_cache.json",
        "insider_trades_cache.json",
        "sec_company_tickers_cache.json",
    ]

    lines = []

    for filename in files:
        path = data_dir / filename

        if not path.exists():
            lines.append(f"• {filename}: missing")
            continue

        age_seconds = time.time() - path.stat().st_mtime
        age_hours = age_seconds / 3600

        lines.append(f"• {filename}: present, age {age_hours:.1f}h")

    return "\n".join(lines)


def get_watchlist_count() -> str:
    try:
        from src.utils.watchlist_store import load_watchlist

        symbols = load_watchlist()

        return f"{len(symbols)} symbols"

    except Exception as error:
        return f"Unavailable: {type(error).__name__}"


def build_deploycheck_report() -> str:
    now = datetime.now(ZoneInfo(REPORT_TIMEZONE))
    current_time = now.strftime("%Y-%m-%d %H:%M:%S")

    service = check_service_status()
    git = get_git_status()
    present_files, missing_files = check_required_files()
    import_errors = check_imports()
    function_errors = check_functions()
    daily = check_daily_report_runtime()
    insider = check_insider_fast_path()

    env_checks = {
    "Telegram bot token": env_present("TELEGRAM_BOT_TOKEN"),
    "Admin chat ID": env_present("TELEGRAM_ADMIN_CHAT_ID"),
    "Channel ID": env_any_present(
        [
            "TELEGRAM_CHANNEL_ID",
            "TELEGRAM_CHANNEL_IDS",
            "TELEGRAM_REPORT_CHAT_ID",
            "TELEGRAM_REPORT_CHAT_IDS",
            "DAILY_REPORT_CHAT_ID",
            "DAILY_REPORT_CHAT_IDS",
            "TELEGRAM_DAILY_REPORT_CHAT_ID",
            "TELEGRAM_DAILY_REPORT_CHAT_IDS",
        ]
    ),
    "OpenAI API key": env_present("OPENAI_API_KEY"),
    "SEC User Agent": env_present("SEC_USER_AGENT"),
}

    issues = []

    if not service["ok"]:
        issues.append("Service status needs review.")

    if missing_files:
        issues.append(f"{len(missing_files)} required file(s) missing.")

    if import_errors:
        issues.append(f"{len(import_errors)} critical import error(s).")

    if function_errors:
        issues.append(f"{len(function_errors)} function check error(s).")

    if not daily["ok"]:
        issues.append("Daily report runtime needs review.")

    if not insider["ok"]:
        issues.append("Insider/whale fast path needs review.")

    missing_env = [
        name
        for name, ok in env_checks.items()
        if not ok and name != "OpenAI API key"
    ]

    if missing_env:
        issues.append("Required environment value(s) missing: " + ", ".join(missing_env) + ".")

    overall_ok = not issues

    env_text = "\n".join(
        f"{status_icon(ok)} {name} configured"
        for name, ok in env_checks.items()
    )

    missing_files_text = (
        "\n".join(f"• {item}" for item in missing_files)
        if missing_files
        else "None"
    )

    import_error_text = (
        "\n".join(f"• {clean_text(item, 350)}" for item in import_errors[:8])
        if import_errors
        else "None"
    )

    function_error_text = (
        "\n".join(f"• {clean_text(item, 350)}" for item in function_errors[:8])
        if function_errors
        else "None"
    )

    daily_error = daily.get("error") or "None"

    if daily.get("missing_sections"):
        daily_error += "\nMissing sections: " + ", ".join(daily["missing_sections"])

    insider_error = insider.get("error") or "None"

    if insider.get("missing_whale_fields"):
        insider_error += "\nMissing whale fields: " + ", ".join(insider["missing_whale_fields"])

    issue_text = (
        "\n".join(f"• {issue}" for issue in issues)
        if issues
        else "• No blocking issues detected."
    )

    return f"""
🛠 Smart Money AI Deploy Check

Overall Status:
{status_icon(overall_ok)} {'Healthy' if overall_ok else 'Needs Review'}

Server:
Hostname: {socket.gethostname()}
Environment: {os.getenv("ENVIRONMENT", "production")}
Time: {current_time} {REPORT_TIMEZONE}
Python: {sys.version.split()[0]}
Project: {PROJECT_ROOT}

Service:
Name: {SERVICE_NAME}
Active: {service['active']}
Enabled: {service['enabled']}

Git:
Branch: {git['branch']}
Latest Commit: {git['commit']}
Working Tree: {git['working_tree']}

Configuration:
{env_text}

Daily Report:
Status: {status_icon(daily['ok'])} {'OK' if daily['ok'] else 'Needs Review'}
Build Time: {daily['elapsed']:.2f}s
Length: {daily['length']} chars
Error: {daily_error}

Insider / Whale:
Status: {status_icon(insider['ok'])} {'OK' if insider['ok'] else 'Needs Review'}
Fast Path Time: {insider['elapsed']:.2f}s
Current NVDA Read: {insider['label']}
Error: {insider_error}

Watchlist:
{get_watchlist_count()}

Required Files:
Present: {len(present_files)}
Missing: {len(missing_files)}
{missing_files_text}

Critical Imports:
{import_error_text}

Function Checks:
{function_error_text}

Cache Status:
{get_cache_status()}

Review Notes:
{issue_text}

Next Commands:
/report
/global
/headlines
/insiders refresh
""".strip()


async def deploycheck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not is_admin(update):
        await update.message.reply_text("Unauthorized: admin only.")
        return

    loading_message = await update.message.reply_text("🛠 Running deploy check...")

    try:
        report = await asyncio.to_thread(build_deploycheck_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=report,
            title="🛠 Deploy Check",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Deploy check failed.\n\n"
            f"Error: {type(error).__name__}: {error}"
        )


deploycheck_command = deploycheck
deploy_check = deploycheck
deployment_check = deploycheck