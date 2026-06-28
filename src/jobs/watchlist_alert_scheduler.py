import asyncio
import json
import os
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from src.commands.watchlist_commands import fetch_quotes_for_symbols
from src.utils.watchlist_store import load_watchlist


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
STATE_FILE = DATA_DIR / "watchlist_alert_state.json"

DEFAULT_ALERT_ENABLED = "true"
DEFAULT_ALERT_THRESHOLD_PERCENT = 2.0
DEFAULT_ALERT_TIMES = "10:00,12:30,15:30"
DEFAULT_ALERT_TIMEZONE = "America/New_York"


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
            print(f"Skipping invalid watchlist alert chat destination: {cleaned}")

    return destinations


def watchlist_alerts_enabled() -> bool:
    value = os.getenv(
        "TELEGRAM_WATCHLIST_ALERTS_ENABLED",
        DEFAULT_ALERT_ENABLED,
    ).strip().lower()

    return value not in {"false", "0", "no", "off"}


def get_watchlist_alert_chat_ids() -> list[int | str]:
    alert_chat_id = os.getenv("TELEGRAM_WATCHLIST_ALERT_CHAT_ID")

    if alert_chat_id:
        return parse_chat_destinations(alert_chat_id)

    daily_report_chat_id = os.getenv("TELEGRAM_DAILY_REPORT_CHAT_ID")

    if daily_report_chat_id:
        return parse_chat_destinations(daily_report_chat_id)

    return parse_chat_destinations(os.getenv("TELEGRAM_ADMIN_CHAT_ID"))


def get_alert_threshold() -> float:
    raw_value = os.getenv(
        "WATCHLIST_ALERT_THRESHOLD_PERCENT",
        str(DEFAULT_ALERT_THRESHOLD_PERCENT),
    )

    try:
        threshold = float(raw_value)
    except ValueError:
        threshold = DEFAULT_ALERT_THRESHOLD_PERCENT

    if threshold <= 0:
        threshold = DEFAULT_ALERT_THRESHOLD_PERCENT

    return threshold


def get_alert_timezone() -> ZoneInfo:
    timezone_name = os.getenv(
        "WATCHLIST_ALERT_TIMEZONE",
        DEFAULT_ALERT_TIMEZONE,
    )

    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo(DEFAULT_ALERT_TIMEZONE)


def parse_alert_times() -> list[time]:
    raw_times = os.getenv("WATCHLIST_ALERT_SCAN_TIMES", DEFAULT_ALERT_TIMES)
    timezone = get_alert_timezone()

    parsed_times: list[time] = []

    for raw_item in raw_times.split(","):
        item = raw_item.strip()

        if not item:
            continue

        try:
            hour_text, minute_text = item.split(":", 1)
            hour = int(hour_text)
            minute = int(minute_text)

            if 0 <= hour <= 23 and 0 <= minute <= 59:
                parsed_times.append(time(hour=hour, minute=minute, tzinfo=timezone))
        except ValueError:
            print(f"Skipping invalid watchlist alert scan time: {item}")

    if parsed_times:
        return parsed_times

    return [
        time(hour=10, minute=0, tzinfo=timezone),
        time(hour=12, minute=30, tzinfo=timezone),
        time(hour=15, minute=30, tzinfo=timezone),
    ]


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_alert_state() -> dict:
    ensure_data_dir()

    if not STATE_FILE.exists():
        return {}

    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def save_alert_state(state: dict) -> None:
    ensure_data_dir()

    with STATE_FILE.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, sort_keys=True)


def get_quote_value(quote: dict, keys: list[str]):
    for key in keys:
        value = quote.get(key)

        if value is not None:
            return value

    return None


def get_change_percent(quote: dict) -> float | None:
    value = get_quote_value(
        quote,
        [
            "change_percent",
            "percent_change",
            "regularMarketChangePercent",
            "regular_market_change_percent",
            "changePercent",
        ],
    )

    if value is None:
        return None

    try:
        return float(value)
    except ValueError:
        return None


def get_price(quote: dict) -> float | None:
    value = get_quote_value(
        quote,
        [
            "price",
            "regularMarketPrice",
            "regular_market_price",
            "current_price",
            "last_price",
        ],
    )

    if value is None:
        return None

    try:
        return float(value)
    except ValueError:
        return None


def get_symbol(symbol: str, quote: dict) -> str:
    value = get_quote_value(
        quote,
        [
            "symbol",
            "ticker",
        ],
    )

    if value:
        return str(value).upper()

    return symbol.upper()


def build_triggered_alerts(quotes: dict, threshold: float) -> list[dict]:
    triggered: list[dict] = []

    for symbol, quote in quotes.items():
        if not isinstance(quote, dict):
            continue

        change_percent = get_change_percent(quote)

        if change_percent is None:
            continue

        if abs(change_percent) < threshold:
            continue

        price = get_price(quote)
        clean_symbol = get_symbol(symbol, quote)

        direction = "up" if change_percent >= threshold else "down"

        triggered.append(
            {
                "symbol": clean_symbol,
                "price": price,
                "change_percent": change_percent,
                "direction": direction,
            }
        )

    triggered.sort(key=lambda item: abs(item["change_percent"]), reverse=True)

    return triggered


def filter_new_alerts(triggered_alerts: list[dict], threshold: float, now: datetime) -> list[dict]:
    state = load_alert_state()

    today_key = now.strftime("%Y-%m-%d")
    threshold_key = f"{threshold:.2f}"

    state.setdefault(today_key, {})
    state[today_key].setdefault(threshold_key, [])

    already_sent = set(state[today_key][threshold_key])
    new_alerts: list[dict] = []

    for alert in triggered_alerts:
        alert_key = f"{alert['symbol']}:{alert['direction']}"

        if alert_key in already_sent:
            continue

        new_alerts.append(alert)
        already_sent.add(alert_key)

    state[today_key][threshold_key] = sorted(already_sent)

    # Keep only recent alert-state days so the file stays small.
    sorted_days = sorted(state.keys(), reverse=True)
    for old_day in sorted_days[10:]:
        state.pop(old_day, None)

    save_alert_state(state)

    return new_alerts


def format_alert_line(alert: dict) -> str:
    symbol = alert["symbol"]
    price = alert["price"]
    change_percent = alert["change_percent"]

    sign = "+" if change_percent >= 0 else ""

    if price is None:
        return f"• {symbol}: {sign}{change_percent:.2f}%"

    return f"• {symbol}: ${price:,.2f} ({sign}{change_percent:.2f}%)"


def build_alert_message(alerts: list[dict], threshold: float, now: datetime) -> str:
    alert_lines = "\n".join(format_alert_line(alert) for alert in alerts)

    timezone_name = os.getenv(
        "WATCHLIST_ALERT_TIMEZONE",
        DEFAULT_ALERT_TIMEZONE,
    )

    return f"""
🚨 Smart Money AI Watchlist Alerts

Scan time: {now.strftime("%Y-%m-%d %H:%M:%S")} {timezone_name}
Threshold: ±{threshold:.2f}%

Triggered:
{alert_lines}

Use /watchlist report for the full watchlist.
""".strip()


async def watchlist_alert_job(context) -> None:
    if not watchlist_alerts_enabled():
        print("Watchlist alerts disabled.")
        return

    timezone = get_alert_timezone()
    now = datetime.now(timezone)

    # Monday = 0, Sunday = 6.
    if now.weekday() >= 5:
        print("Watchlist alert scan skipped: weekend.")
        return

    chat_ids = get_watchlist_alert_chat_ids()

    if not chat_ids:
        print("Watchlist alert scan skipped: no chat destinations configured.")
        return

    threshold = get_alert_threshold()

    try:
        symbols = load_watchlist()
    except Exception as exc:
        print(f"Watchlist alert scan failed loading symbols: {exc}")
        return

    if not symbols:
        print("Watchlist alert scan skipped: empty watchlist.")
        return

    try:
        quotes = await asyncio.to_thread(fetch_quotes_for_symbols, symbols)
    except Exception as exc:
        print(f"Watchlist alert scan failed fetching quotes: {exc}")
        return

    triggered_alerts = build_triggered_alerts(quotes, threshold)

    if not triggered_alerts:
        print("Watchlist alert scan complete: no triggered alerts.")
        return

    new_alerts = filter_new_alerts(triggered_alerts, threshold, now)

    if not new_alerts:
        print("Watchlist alert scan complete: alerts already sent today.")
        return

    message = build_alert_message(new_alerts, threshold, now)

    for chat_id in chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
            print(f"Watchlist alert sent to {chat_id}.")
        except Exception as exc:
            print(f"Failed to send watchlist alert to {chat_id}: {exc}")


def schedule_watchlist_alerts(app) -> None:
    if not watchlist_alerts_enabled():
        print("Watchlist alerts disabled.")
        return

    if not app.job_queue:
        print("Watchlist alerts not scheduled: JobQueue is unavailable.")
        return

    scan_times = parse_alert_times()

    for scan_time in scan_times:
        app.job_queue.run_daily(
            watchlist_alert_job,
            time=scan_time,
            name=f"watchlist-alert-{scan_time.hour:02d}{scan_time.minute:02d}",
        )

    formatted_times = ", ".join(item.strftime("%H:%M") for item in scan_times)
    timezone_name = os.getenv(
        "WATCHLIST_ALERT_TIMEZONE",
        DEFAULT_ALERT_TIMEZONE,
    )

    print(f"Watchlist alerts scheduled at {formatted_times} {timezone_name}.")