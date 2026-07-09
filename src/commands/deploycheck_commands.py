import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from src.commands.admin_commands import get_current_chat_id, is_admin
from src.utils.telegram_messages import edit_or_reply_long_message
from src.utils.watchlist_store import get_watchlist_file_path, load_watchlist


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEZONE = "America/Lima"
DEFAULT_SERVICE_NAME = "smart-money-ai-bot"


def run_command(command: list[str], timeout: int = 5) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        output = (result.stdout or result.stderr or "").strip()

        if not output:
            return "Unavailable"

        return output

    except FileNotFoundError:
        return "Unavailable"
    except subprocess.TimeoutExpired:
        return "Timed out"
    except Exception as exc:
        return f"Error: {exc}"


def status_icon(value: bool) -> str:
    return "✅" if value else "❌"


def env_configured(name: str) -> bool:
    value = os.getenv(name)
    return bool(value and value.strip())


def env_enabled(name: str, default: str = "true") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value not in {"false", "0", "no", "off"}


def get_git_status() -> str:
    status = run_command(["git", "status", "--short"])

    if status == "Unavailable":
        return "Unavailable"

    if not status:
        return "Clean"

    return "Local changes present"


def get_watchlist_status() -> str:
    try:
        watchlist_file = Path(get_watchlist_file_path())
        symbols = load_watchlist()

        if watchlist_file.exists():
            return f"Found — {len(symbols)} symbols"

        return f"Missing file — {len(symbols)} symbols loaded from defaults"

    except Exception as exc:
        return f"Error: {exc}"


def build_deploycheck_report() -> str:
    timezone_name = os.getenv("TELEGRAM_DAILY_REPORT_TIMEZONE", DEFAULT_TIMEZONE)

    try:
        now = datetime.now(ZoneInfo(timezone_name))
    except Exception:
        timezone_name = DEFAULT_TIMEZONE
        now = datetime.now(ZoneInfo(timezone_name))

    service_name = os.getenv("SYSTEMD_SERVICE_NAME", DEFAULT_SERVICE_NAME)

    service_active = run_command(["systemctl", "is-active", service_name])
    service_enabled = run_command(["systemctl", "is-enabled", service_name])

    git_branch = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    git_commit = run_command(["git", "log", "-1", "--pretty=%h - %s"])
    git_status = get_git_status()

    bot_token_ok = env_configured("TELEGRAM_BOT_TOKEN")
    admin_chat_ok = env_configured("TELEGRAM_ADMIN_CHAT_ID")
    daily_report_enabled = env_enabled("TELEGRAM_DAILY_REPORT_ENABLED", "true")
    startup_alert_enabled = env_enabled("TELEGRAM_STARTUP_ALERT_ENABLED", "true")
    openai_key_ok = env_configured("OPENAI_API_KEY")

    hostname = platform.node() or "Unknown"
    python_version = platform.python_version()
    environment = os.getenv("APP_ENV", "production")

    daily_report_time = os.getenv("TELEGRAM_DAILY_REPORT_TIME", "08:30")
    watchlist_status = get_watchlist_status()

    return f"""
🛠 Smart Money AI Deploy Check

Server
Hostname: {hostname}
Environment: {environment}
Time: {now.strftime("%Y-%m-%d %H:%M:%S")} {timezone_name}
Python: {python_version}

Service
Name: {service_name}
Active: {service_active}
Enabled: {service_enabled}

Git
Branch: {git_branch}
Latest commit: {git_commit}
Working tree: {git_status}

Configuration
{status_icon(bot_token_ok)} Telegram bot token configured
{status_icon(admin_chat_ok)} Admin chat ID configured
{status_icon(openai_key_ok)} OpenAI API key configured
{status_icon(daily_report_enabled)} Daily report enabled
{status_icon(startup_alert_enabled)} Startup alert enabled

Daily Report
Time: {daily_report_time} {timezone_name}

Watchlist
{watchlist_status}

Status: ✅ Deploy check complete
""".strip()


async def deploycheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    current_chat_id = get_current_chat_id(update)

    if not is_admin(update):
        await update.message.reply_text(
            "Unauthorized: admin only\n\n"
            f"Current chat ID:\n{current_chat_id}",
            parse_mode=None,
        )
        return

    loading_message = await update.message.reply_text(
        "🧪 Running deployment health check...",
        parse_mode=None,
    )

    try:
        import importlib
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[2]

        required_files = [
            "src/bot.py",
            "src/commands/register_commands.py",
            "src/commands/daily_report_send_commands.py",
            "src/jobs/daily_report_scheduler.py",
            "src/reports/daily_report.py",
            "src/reports/ai_summary.py",
            "src/reports/action_checklist.py",
            "src/utils/telegram_messages.py",
            "deployment/update_bot.sh",
            "deployment/preflight_check.sh",
        ]

        missing_files = [
            file_path
            for file_path in required_files
            if not (project_root / file_path).exists()
        ]

        critical_modules = [
            "src.commands.register_commands",
            "src.commands.daily_report_send_commands",
            "src.jobs.daily_report_scheduler",
            "src.reports.daily_report",
            "src.reports.ai_summary",
            "src.reports.action_checklist",
            "src.utils.telegram_messages",
            "src.scoring.scoring_engine",
            "src.utils.watchlist_store",
        ]

        failed_imports = []

        for module_name in critical_modules:
            try:
                importlib.import_module(module_name)
            except Exception as error:
                failed_imports.append(
                    f"{module_name}: {type(error).__name__}: {error}"
                )

        report_status = "Not checked"
        report_length = 0
        report_parts = 0
        missing_sections = []
        destination_count = 0

        try:
            from src.jobs.daily_report_scheduler import get_daily_report_chat_ids
            from src.reports.daily_report import build_daily_report
            from src.utils.telegram_messages import split_long_message

            required_sections = [
                "Smart Money AI Daily Report",
                "Market Snapshot",
                "Watchlist Movers",
                "Smart Money Score Summary",
                "Top Opportunities",
                "Risk Notes",
                "AI Summary",
                "Action Checklist",
                "Next Commands",
                "Notes",
            ]

            destinations = get_daily_report_chat_ids()
            destination_count = len(destinations)

            report = build_daily_report()
            report_length = len(report)
            report_parts = len(split_long_message(report))

            missing_sections = [
                section
                for section in required_sections
                if section not in report
            ]

            if missing_sections:
                report_status = "⚠️ Built with missing section(s)"
            elif report_length < 100:
                report_status = "⚠️ Built but unusually short"
            else:
                report_status = "✅ Built successfully"

        except Exception as error:
            report_status = f"❌ Failed: {type(error).__name__}: {error}"

        overall_pass = (
            not missing_files
            and not failed_imports
            and report_status.startswith("✅")
        )

        status = "✅ PASS" if overall_pass else "⚠️ NEEDS REVIEW"

        missing_files_text = (
            "None"
            if not missing_files
            else "\n".join(f"• {file_path}" for file_path in missing_files)
        )

        failed_imports_text = (
            "None"
            if not failed_imports
            else "\n".join(f"• {item}" for item in failed_imports)
        )

        missing_sections_text = (
            "None"
            if not missing_sections
            else "\n".join(f"• {section}" for section in missing_sections)
        )

        message = f"""
🧪 Smart Money AI Deploy Check

Status: {status}

Required Files:
{missing_files_text}

Critical Imports:
{failed_imports_text}

Daily Report:
Status: {report_status}
Length: {report_length:,} characters
Telegram Parts: {report_parts}
Daily Destinations: {destination_count}

Missing Report Sections:
{missing_sections_text}

Protected By:
✅ deployment/preflight_check.sh
✅ daily report runtime smoke test
✅ Telegram-safe message splitting

Recommended Tests:
/ping
/dailycheck
/report
/testdaily
""".strip()

        await edit_or_reply_long_message(
    update=update,
    loading_message=loading_message,
    text=message,
    title="🧪 Deploy Check",
    parse_mode=None,
)

    except Exception as error:
        await loading_message.edit_text(
            "❌ Deploy check failed unexpectedly.\n\n"
            f"Error:\n{type(error).__name__}: {error}",
            parse_mode=None,
        )