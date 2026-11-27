import os
import asyncio
import logging
import traceback
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram.error import TelegramError

from src.intelligence.news_editor_store import confirm_watchlist_delivery
from src.reports import weekend_telegram
from src.jobs.daily_agent_job import run_daily_agent
from src.utils.telegram_messages import send_long_message_to_chat


TELEGRAM_MESSAGE_LIMIT = 3900
DEFAULT_DAILY_REPORT_TIME = "08:30"
DEFAULT_EVENING_TIME = "17:30"
DEFAULT_TIMEZONE = "America/New_York"
MARKET_TIMEZONE = ZoneInfo("America/New_York")
LOG = logging.getLogger(__name__)


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

    return list(dict.fromkeys(destinations))


def get_daily_report_chat_ids() -> list[int | str]:
    daily_report_ids = parse_chat_destinations(os.getenv("TELEGRAM_DAILY_REPORT_CHAT_ID"))

    if daily_report_ids:
        return daily_report_ids

    return parse_chat_destinations(os.getenv("TELEGRAM_ADMIN_CHAT_ID"))


def get_daily_report_time(setting="TELEGRAM_DAILY_REPORT_TIME", default=DEFAULT_DAILY_REPORT_TIME) -> time:
    raw_time = os.getenv(setting, default).strip()

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
            f"Invalid {setting} value: {raw_time}. Using default {default}."
        )
        hour, minute = map(int, default.split(":"))

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


def report_times() -> list[time]:
    morning = time(8, 30, tzinfo=MARKET_TIMEZONE)
    evening = get_daily_report_time("TELEGRAM_DAILY_REPORT_EVENING_TIME", DEFAULT_EVENING_TIME)
    if evening.hour < 12:
        LOG.warning("Ignoring a second morning Daily Brief slot; using the evening default.")
        evening = time(17, 30, tzinfo=MARKET_TIMEZONE)
    return [morning, evening]


def daily_report_enabled() -> bool:
    raw_value = os.getenv("TELEGRAM_DAILY_REPORT_ENABLED", "true").strip().lower()

    return raw_value in {"1", "true", "yes", "y", "on"}


async def build_daily_report_safe() -> str:
    result = await asyncio.to_thread(run_daily_agent, False)
    if not result.get("success") or not (result.get("report") or "").strip():
        raise RuntimeError("Scheduled daily agent failed. See /agentstatus for the workflow results.")
    return result["report"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def weekend_outlook_due(now: datetime) -> bool:
    return now.astimezone(MARKET_TIMEZONE).weekday() >= 5


def build_weekend_delivery_report(now: datetime, *, refresh=False) -> str:
    from src.intelligence import calendar_sources, news_live_sources, weekend_inputs, weekend_store
    from src.reports import weekend_outlook

    window = weekend_inputs.window(now)
    previous = weekend_store.latest()
    if previous is not None and not refresh:
        try:
            weekend_outlook.checked(previous, now, require_publishable=True)
        except ValueError:
            pass
        else:
            return weekend_telegram.render(previous, now)

    monday = date.fromisoformat(window["next_start"])
    dates = [monday + timedelta(days=index) for index in range(5)]
    try:
        calendar_sources.collect_schedules(dates)
    except (OSError, ValueError, RuntimeError) as error:
        LOG.warning("Weekend publisher calendar refresh failed: %s", error)
    try:
        news_live_sources.fetch_news_live_context()
    except (OSError, ValueError, RuntimeError) as error:
        LOG.warning("Weekend publisher lead refresh failed: %s", error)

    record = weekend_outlook.build(now=utc_now(), force=True) if refresh else weekend_outlook.build(now=utc_now())
    weekend_outlook.checked(record, utc_now(), require_publishable=True)
    return weekend_telegram.render(record, now)


async def send_daily_report_to_chat(bot, chat_id: int | str, *, report_builder=None, report: str | None = None) -> bool:
    try:
        if report is None:
            await bot.send_message(chat_id=chat_id, text="🗞 Building your Smart Money AI Daily Report...")
            report = await (report_builder or build_daily_report_safe)()

        for chunk in split_long_message(report):
            await bot.send_message(
                chat_id=chat_id,
                text=chunk
            )

        await asyncio.to_thread(confirm_watchlist_delivery, report)
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

    now = utc_now()
    LOG.info("Scheduled report run starting at %s", now.astimezone(MARKET_TIMEZONE).isoformat(timespec="minutes"))
    if not weekend_outlook_due(now):
        try:
            report = await build_daily_report_safe()
        except Exception:
            LOG.exception("Scheduled daily agent did not produce a publishable brief")
            for chat_id in chat_ids:
                try:
                    await context.bot.send_message(chat_id=chat_id, text="The Daily Brief is unavailable for this scheduled run.")
                except TelegramError:
                    LOG.warning("Scheduled Daily Brief status delivery to %s was unconfirmed", chat_id)
            return

        for chat_id in chat_ids:
            sent = await send_daily_report_to_chat(context.bot, chat_id, report=report)
            LOG.info("Scheduled Daily Brief delivery to %s: %s", chat_id, "sent" if sent else "unconfirmed")
        return

    edition = weekend_telegram.edition_name(now)
    try:
        if getattr(getattr(context, "job", None), "name", "") == "smart_money_daily_report_evening":
            report = await asyncio.to_thread(build_weekend_delivery_report, now, refresh=True)
        else:
            report = await asyncio.to_thread(build_weekend_delivery_report, now)
    except Exception:
        LOG.exception("Scheduled %s build failed", edition)
        report = f"The {edition} is unavailable for this scheduled run."

    for chat_id in chat_ids:
        try:
            await send_long_message_to_chat(
                context.bot, chat_id, report,
                title=f"Smart Money {edition}", limit=TELEGRAM_MESSAGE_LIMIT,
            )
        except TelegramError as error:
            LOG.warning("Telegram error sending %s to %s: %s", edition, chat_id, error)


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

    times = report_times()
    names = ("smart_money_daily_report", "smart_money_daily_report_evening")
    for name, slot in zip(names, times):
        app.job_queue.run_daily(
            callback=daily_report_job, time=slot, name=name,
            job_kwargs={"id": name, "replace_existing": True, "max_instances": 1,
                        "coalesce": True, "misfire_grace_time": 300},
        )

    schedule_label = (", ".join(slot.strftime("%H:%M") for slot in times) + f" {times[0].tzinfo}"
                      if times[0].tzinfo == times[-1].tzinfo else
                      ", ".join(f"{slot:%H:%M} {slot.tzinfo}" for slot in times))
    print("Daily report automation scheduled.\n"
          + f"Times: {schedule_label} every day\nRecipient count: {len(chat_ids)}", flush=True)
