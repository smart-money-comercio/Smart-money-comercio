import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MARKET_MEMORY_FILE = PROJECT_ROOT / "data" / "daily_market_memory.json"

MEMORY_TIMEZONE = "America/Lima"
MAX_MEMORY_DAYS = 30


def read_json(path: Path, default: Any):
    try:
        if not path.exists():
            return default

        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, sort_keys=True)
    except Exception:
        return


def today_key() -> str:
    return datetime.now(ZoneInfo(MEMORY_TIMEZONE)).strftime("%Y-%m-%d")


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("$", "")


def clean_text(value: Any, max_length: int = 180) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def load_market_memory() -> dict:
    data = read_json(MARKET_MEMORY_FILE, {"days": []})

    if not isinstance(data, dict):
        return {"days": []}

    if not isinstance(data.get("days"), list):
        data["days"] = []

    return data


def save_market_memory(memory: dict) -> None:
    days = memory.get("days") or []

    if not isinstance(days, list):
        days = []

    memory["days"] = days[-MAX_MEMORY_DAYS:]

    write_json(MARKET_MEMORY_FILE, memory)


def get_ticker_from_item(item: dict | None) -> str:
    if not isinstance(item, dict):
        return ""

    return normalize_symbol(
        item.get("ticker")
        or item.get("symbol")
        or item.get("name")
    )


def build_market_day_record(
    context: dict,
    top_scores: list[dict],
    movers: list[dict],
    market_tone: str,
    watchlist_symbols: list[str],
) -> dict:
    themes = [
        str(theme).strip()
        for theme in context.get("headline_themes", []) or []
        if str(theme).strip()
    ]

    headline_examples = [
        clean_text(item, 160)
        for item in context.get("headline_examples", []) or []
        if clean_text(item, 160)
    ][:5]

    top_tickers = [
        get_ticker_from_item(item)
        for item in top_scores[:5]
        if get_ticker_from_item(item)
    ]

    mover_symbols = [
        normalize_symbol(item.get("symbol"))
        for item in movers[:5]
        if isinstance(item, dict) and normalize_symbol(item.get("symbol"))
    ]

    return {
        "date": today_key(),
        "themes": themes[:8],
        "headline_examples": headline_examples,
        "top_tickers": top_tickers,
        "mover_symbols": mover_symbols,
        "market_tone": market_tone,
        "watchlist_symbols": [
            normalize_symbol(symbol)
            for symbol in watchlist_symbols[:20]
            if normalize_symbol(symbol)
        ],
    }


def record_market_day(record: dict) -> None:
    memory = load_market_memory()
    current_date = record.get("date")

    days = [
        day
        for day in memory.get("days", [])
        if day.get("date") != current_date
    ]

    days.append(record)
    memory["days"] = days[-MAX_MEMORY_DAYS:]

    save_market_memory(memory)


def get_previous_day(memory: dict, current_date: str) -> dict:
    previous_days = [
        day
        for day in memory.get("days", [])
        if day.get("date") != current_date
    ]

    if not previous_days:
        return {}

    return previous_days[-1]


def count_theme_frequency(memory: dict, theme: str, lookback: int = 5) -> int:
    count = 0

    for day in memory.get("days", [])[-lookback:]:
        if theme in (day.get("themes") or []):
            count += 1

    return count


def build_theme_change_lines(current: dict, previous: dict, memory: dict) -> list[str]:
    current_themes = current.get("themes") or []
    previous_themes = previous.get("themes") or []

    lines = []

    new_themes = [
        theme
        for theme in current_themes
        if theme not in previous_themes
    ]

    faded_themes = [
        theme
        for theme in previous_themes
        if theme not in current_themes
    ]

    if new_themes:
        lines.append(
            "New theme: "
            + ", ".join(new_themes[:3])
            + " moved into today’s brief."
        )

    if faded_themes:
        lines.append(
            "Fading theme: "
            + ", ".join(faded_themes[:3])
            + " dropped out of today’s top read."
        )

    persistent = []

    for theme in current_themes:
        frequency = count_theme_frequency(memory, theme, lookback=5)

        if frequency >= 3:
            persistent.append(f"{theme} appeared {frequency} of the last 5 reports")

    if persistent:
        lines.append("Theme persistence: " + "; ".join(persistent[:2]) + ".")

    return lines


def build_watchlist_change_lines(current: dict, previous: dict) -> list[str]:
    lines = []

    current_top = (current.get("top_tickers") or [""])[0]
    previous_top = (previous.get("top_tickers") or [""])[0]

    if current_top and previous_top and current_top != previous_top:
        lines.append(
            f"Top watch changed: {current_top} moved ahead of {previous_top}."
        )
    elif current_top:
        lines.append(
            f"Top watch remains {current_top}; confirmation still matters more than chasing."
        )

    current_movers = current.get("mover_symbols") or []
    previous_movers = previous.get("mover_symbols") or []

    new_movers = [
        symbol
        for symbol in current_movers
        if symbol not in previous_movers
    ]

    if new_movers:
        lines.append(
            "New live-mover focus: "
            + ", ".join(new_movers[:3])
            + "."
        )

    return lines


def build_tone_change_lines(current: dict, previous: dict) -> list[str]:
    current_tone = current.get("market_tone", "")
    previous_tone = previous.get("market_tone", "")

    if current_tone and previous_tone and current_tone != previous_tone:
        return [
            f"Market tone changed from {previous_tone.lower()} to {current_tone.lower()}."
        ]

    if current_tone:
        return [f"Market tone is still {current_tone.lower()}."]

    return []


def build_what_changed_today(
    context: dict,
    top_scores: list[dict],
    movers: list[dict],
    market_tone: str,
    watchlist_symbols: list[str],
    record: bool = True,
) -> str:
    memory = load_market_memory()

    current = build_market_day_record(
        context=context,
        top_scores=top_scores,
        movers=movers,
        market_tone=market_tone,
        watchlist_symbols=watchlist_symbols,
    )

    previous = get_previous_day(memory, current.get("date", ""))

    if record:
        record_market_day(current)

    if not previous:
        return (
            "This is the first saved market-memory snapshot. Future reports will compare "
            "today against prior themes, top watches, movers, and market tone."
        )

    lines = []
    lines.extend(build_theme_change_lines(current, previous, memory))
    lines.extend(build_watchlist_change_lines(current, previous))
    lines.extend(build_tone_change_lines(current, previous))

    if not lines:
        return (
            "The setup is broadly similar to the prior report. That makes confirmation, "
            "position sizing, and avoiding repeated headline noise more important today."
        )

    return "\n".join(f"• {line}" for line in lines[:5])