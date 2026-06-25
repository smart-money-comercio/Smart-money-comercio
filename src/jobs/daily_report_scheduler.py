import os
import asyncio
import traceback
from datetime import time
from zoneinfo import ZoneInfo

from telegram.error import TelegramError

from src.reports.daily_report import build_daily_report


TELEGRAM_MESSAGE_LIMIT = 3900
DEFAULT_DAILY_REPORT_TIME = "08:30"
DEFAULT_TIMEZONE = "America/Lima"


def split_long_message(message: str) -> list[str]:
    if len(message) <= TELEGRAM_MESSAGE_LIMIT:
        return [message]

    chunks = []
    current_chunk = ""

    for line in message.splitlines():
        candidate = f"{current_chunk}\n{line}" if current_chunk else line

        if len(candidate) > TELEGRAM_MESSAGE_LIMIT:
            if current_chunk:
                chunks.append(current_chunk)

            current_chunk = line
        else:
            current_chunk = candidate

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def parse_chat_destinations(raw_value: str | None) -> list[int | str]:
    """
    Supports:
    TELEGRAM_DAILY_REPORT_CHAT_ID=-1001234567890
    TELEGRAM_DAILY_REPORT_CHAT_ID=@SmartMoneyAIAlerts
    TELEGRAM_DAILY_REPORT_CHAT_ID=-1001234567890,@AnotherChannel
    """
    if not raw_value:
        return []

    destinations = []

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
            print(f"Skipping invalid Telegram chat destination: {cleaned}")

    return destinations


def get_daily_report_chat_ids() -> list[int | str]:
    daily_report_ids = parse_chat_destinations(os.getenv("TELEGRAM_DAILY_REPORT_CHAT_ID"))

    if daily_report_ids:
        return daily_report_ids

    return parse_chat_destinations(os.getenv("TELEGRAM_ADMIN_CHAT_ID"))


def get_daily_report_time() -> time:
    raw_time = os.getenv("TELEGRAM_DAILY_REPORT_TIME", DEFAULT_DAILY_REPORT_TIME).strip()

    try:
        hour_text, minute_text = raw_time.split(":")
        hour = int(hour_text)
        minute = int(minute_text)

        if not 0 <= hour <= 23:
            raise ValueError

        if not 0 <= minute <= 59:
            raise ValueError

    except ValueError:
        print(
            f"Invalid TELEGRAM_DAILY_REPORT_TIME value: {raw_time}. "
            f"Using default {DEFAULT_DAILY_REPORT_TIME}."
        )
        hour = 8
        minute = 30

    timezone_name = os.getenv("TELEGRAM_DAILY_REPORT_TIMEZONE", DEFAULT_TIMEZONE).strip()

    try:
        timezone = ZoneInfo(timezone_name)
    except Exception:
        print(
            f"Invalid TELEGRAM_DAILY_REPORT_TIMEZONE value: {timezone_name}. "
            f"Using default {DEFAULT_TIMEZONE}."
        )
        timezone = ZoneInfo(DEFAULT_TIMEZONE)

    return time(hour=hour, minute=minute, tzinfo=timezone)


def daily_report_enabled() -> bool:
    raw_value = os.getenv("TELEGRAM_DAILY_REPORT_ENABLED", "true").strip().lower()

    return raw_value in {"1", "true", "yes", "y", "on"}


async def build_daily_report_safe() -> str:
    return await asyncio.to_thread(build_daily_report)


async def send_daily_report_to_chat(bot, chat_id: int | str) -> bool:
    try:
        await bot.send_message(
            chat_id=chat_id,
            text="🗞 Building your Smart Money AI Daily Report..."
        )

        report = await build_daily_report_safe()

        for chunk in split_long_message(report):
            await bot.send_message(
                chat_id=chat_id,
                text=chunk
            )

        return True

    except TelegramError as error:
        print(f"Telegram error sending daily report to {chat_id}: {error}")
        return False

    except Exception as error:
        traceback_text = traceback.format_exc()
        print(f"Daily report job failed for {chat_id}:")
        print(traceback_text)

        error_message = (
            "Daily report automation failed.\n\n"
            f"Error type: {type(error).__name__}\n"
            f"Error detail: {error}"
        )

        try:
            await bot.send_message(
                chat_id=chat_id,
                text=error_message[:TELEGRAM_MESSAGE_LIMIT]
            )
        except Exception:
            pass

        return False


async def daily_report_job(context) -> None:
    chat_ids = get_daily_report_chat_ids()

    if not chat_ids:
        print(
            "Daily report job skipped. "
            "No TELEGRAM_DAILY_REPORT_CHAT_ID or TELEGRAM_ADMIN_CHAT_ID configured."
        )
        return

    for chat_id in chat_ids:
        await send_daily_report_to_chat(context.bot, chat_id)


def schedule_daily_report(app) -> None:
    if not daily_report_enabled():
        print("Daily report automation disabled by TELEGRAM_DAILY_REPORT_ENABLED.")
        return

    chat_ids = get_daily_report_chat_ids()

    if not chat_ids:
        print(
            "Daily report automation not scheduled. "
            "No TELEGRAM_DAILY_REPORT_CHAT_ID or TELEGRAM_ADMIN_CHAT_ID found."
        )
        return

    if app.job_queue is None:
        print(
            "Daily report automation not scheduled. "
            "JobQueue is unavailable. Install it with:\n"
            'pip install "python-telegram-bot[job-queue]"'
        )
        return

    report_time = get_daily_report_time()

    app.job_queue.run_daily(
        callback=daily_report_job,
        time=report_time,
        name="smart_money_daily_report",
    )

    destinations = ", ".join(str(chat_id) for chat_id in chat_ids)

    print(
        "Daily report automation scheduled.\n"
        f"Time: {report_time.strftime('%H:%M')} {report_time.tzinfo}\n"
        f"Recipient count: {len(chat_ids)}\n"
        f"Recipients: {destinations}"
    )