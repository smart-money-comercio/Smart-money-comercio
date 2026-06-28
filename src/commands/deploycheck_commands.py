import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from src.commands.admin_commands import is_admin
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


async def deploycheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unauthorized: admin only")
        return

    report = build_deploycheck_report()
    await update.message.reply_text(report)