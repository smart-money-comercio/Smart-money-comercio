import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MEMORY_FILE = Path(
    os.getenv("TICKER_INTELLIGENCE_MEMORY_FILE", "data/ticker_intelligence_memory.json")
)

TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
MAX_RECORDS_PER_TICKER = int(os.getenv("TICKER_MEMORY_MAX_RECORDS", "25"))


def now_text() -> str:
    try:
        now = datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        now = datetime.now()

    return now.strftime("%Y-%m-%d %H:%M:%S")


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()

        return float(value)

    except Exception:
        return default


def load_ticker_memory() -> dict:
    try:
        if not MEMORY_FILE.exists():
            return {"tickers": {}, "updated_at": None}

        with MEMORY_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return {"tickers": {}, "updated_at": None}

        data.setdefault("tickers", {})
        return data

    except Exception:
        return {"tickers": {}, "updated_at": None}


def save_ticker_memory(memory: dict) -> None:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = now_text()

        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(memory, file, indent=2, sort_keys=True)

    except Exception:
        return


def get_recent_records(symbol: str, memory: dict | None = None) -> list[dict]:
    symbol = str(symbol or "").upper().strip()

    if not symbol:
        return []

    memory = memory or load_ticker_memory()
    records = memory.get("tickers", {}).get(symbol, [])

    if not isinstance(records, list):
        return []

    return records[-MAX_RECORDS_PER_TICKER:]


def build_record(
    symbol: str,
    score: float | None = None,
    label: str = "",
    risk: str = "",
    action: str = "",
    category: str = "",
    signal: str = "",
    price: float | None = None,
    change_percent: float | None = None,
) -> dict:
    return {
        "checked_at": now_text(),
        "symbol": str(symbol or "").upper().strip(),
        "score": score,
        "label": str(label or "").strip(),
        "risk": str(risk or "").strip(),
        "action": str(action or "").strip(),
        "category": str(category or "").strip(),
        "signal": str(signal or "").strip(),
        "price": price,
        "change_percent": change_percent,
    }


def record_ticker_read(symbol: str, record: dict) -> dict:
    symbol = str(symbol or "").upper().strip()
    memory = load_ticker_memory()

    memory.setdefault("tickers", {})
    records = memory["tickers"].setdefault(symbol, [])

    if not isinstance(records, list):
        records = []
        memory["tickers"][symbol] = records

    previous = records[-1] if records else None

    records.append(record)
    memory["tickers"][symbol] = records[-MAX_RECORDS_PER_TICKER:]

    save_ticker_memory(memory)

    return {
        "previous": previous,
        "current": record,
        "records": memory["tickers"][symbol],
    }


def score_delta_text(previous: dict | None, current: dict) -> str:
    if not previous:
        return "First tracked read for this ticker."

    previous_score = safe_float(previous.get("score"))
    current_score = safe_float(current.get("score"))

    if previous_score is None or current_score is None:
        return "Score trend is not established yet."

    delta = current_score - previous_score

    if abs(delta) < 1:
        return "Score is broadly stable versus the last read."

    direction = "improved" if delta > 0 else "weakened"
    return f"Score {direction} by {abs(delta):.1f} points versus the last read."


def field_change_text(previous: dict | None, current: dict, field: str, label: str) -> str:
    if not previous:
        return ""

    previous_value = str(previous.get(field) or "").strip()
    current_value = str(current.get(field) or "").strip()

    if not previous_value or not current_value or previous_value == current_value:
        return ""

    return f"{label} changed from {previous_value} to {current_value}."


def build_evolution_notes(previous: dict | None, current: dict) -> list[str]:
    notes = [score_delta_text(previous, current)]

    for field, label in [
        ("action", "Action"),
        ("risk", "Risk"),
        ("label", "Signal"),
        ("category", "Category"),
    ]:
        change = field_change_text(previous, current, field, label)

        if change:
            notes.append(change)

    return notes[:4]


def build_memory_summary(symbol: str) -> str:
    records = get_recent_records(symbol)

    if len(records) < 2:
        return "Not enough history yet. This read starts the ticker memory."

    first = records[0]
    latest = records[-1]

    first_score = safe_float(first.get("score"))
    latest_score = safe_float(latest.get("score"))

    if first_score is None or latest_score is None:
        return f"{len(records)} tracked reads. Score trend is still developing."

    delta = latest_score - first_score

    if abs(delta) < 1:
        trend = "stable"
    elif delta > 0:
        trend = "improving"
    else:
        trend = "weakening"

    return f"{len(records)} tracked reads. Longer-term score trend: {trend}."