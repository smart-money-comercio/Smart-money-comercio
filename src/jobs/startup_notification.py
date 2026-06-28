import os
import platform
from datetime import datetime
from zoneinfo import ZoneInfo

from src.utils.watchlist_store import load_watchlist


DEFAULT_TIMEZONE = "America/Lima"
DEFAULT_STARTUP_ALERT_ENABLED = "true"


def parse_chat_destinations(raw_value: str | None) -> list[int | str]:
    if not raw_value:
        return []

    destinations: list[int | str] = []

    for item in raw_value.split(","):
        cleaned = item.strip()

        if not cleaned:
            continue

        if cleaned.startswith("@"):
            destinations.append(cleaned)
            continue

        try:
            destinations.append(int(cleaned))
        except ValueError:
            print(f"Skipping invalid startup alert chat destination: {cleaned}")

    return destinations


def startup_alert_enabled() -> bool:
    value = os.getenv(
        "TELEGRAM_STARTUP_ALERT_ENABLED",
        DEFAULT_STARTUP_ALERT_ENABLED,
    ).strip().lower()

    return value not in {"false", "0", "no", "off"}


def get_startup_alert_chat_ids() -> list[int | str]:
    startup_alert_chat_id = os.getenv("TELEGRAM_STARTUP_ALERT_CHAT_ID")

    if startup_alert_chat_id:
        return parse_chat_destinations(startup_alert_chat_id)

    return parse_chat_destinations(os.getenv("TELEGRAM_ADMIN_CHAT_ID"))


def build_startup_message() -> str:
    timezone_name = os.getenv("TELEGRAM_DAILY_REPORT_TIMEZONE", DEFAULT_TIMEZONE)
    daily_report_time = os.getenv("TELEGRAM_DAILY_REPORT_TIME", "08:30")
    daily_report_enabled = os.getenv("TELEGRAM_DAILY_REPORT_ENABLED", "true")

    try:
        now = datetime.now(ZoneInfo(timezone_name))
    except Exception:
        timezone_name = DEFAULT_TIMEZONE
        now = datetime.now(ZoneInfo(timezone_name))

    try:
        watchlist_count = len(load_watchlist())
    except Exception:
        watchlist_count = "Unavailable"

    environment = os.getenv("APP_ENV", "production")
    hostname = platform.node() or "DigitalOcean Droplet"

    return f"""
✅ Smart Money AI bot started

Server: {hostname}
Environment: {environment}
Time: {now.strftime("%Y-%m-%d %H:%M:%S")} {timezone_name}

Daily report: {daily_report_enabled}
Daily report time: {daily_report_time} {timezone_name}
Watchlist symbols: {watchlist_count}

Service: smart-money-ai-bot
Status: online
""".strip()


async def startup_notification_job(context) -> None:
    if not startup_alert_enabled():
        print("Startup alert is disabled.")
        return

    chat_ids = get_startup_alert_chat_ids()

    if not chat_ids:
        print("Startup alert skipped: no chat destinations configured.")
        return

    message = build_startup_message()

    for chat_id in chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
            print(f"Startup alert sent to {chat_id}.")
        except Exception as exc:
            print(f"Failed to send startup alert to {chat_id}: {exc}")


def schedule_startup_notification(app) -> None:
    if not startup_alert_enabled():
        print("Startup alert disabled.")
        return

    if not app.job_queue:
        print("Startup alert not scheduled: JobQueue is unavailable.")
        return

    app.job_queue.run_once(startup_notification_job, when=5)
    print("Startup alert scheduled.")