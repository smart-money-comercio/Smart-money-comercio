import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MEMORY_FILE = Path(
    os.getenv("EARNINGS_INTELLIGENCE_MEMORY_FILE", "data/earnings_intelligence_memory.json")
)

TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
MAX_RECORDS_PER_TICKER = int(os.getenv("EARNINGS_MEMORY_MAX_RECORDS", "30"))


def now() -> datetime:
    try:
        return datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        return datetime.now()


def now_text() -> str:
    return now().strftime("%Y-%m-%d %H:%M:%S")


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()

        return float(value)

    except Exception:
        return default


def load_earnings_memory() -> dict:
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


def save_earnings_memory(memory: dict) -> None:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = now_text()

        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(memory, file, indent=2, sort_keys=True)

    except Exception:
        return


def build_earnings_record(
    symbol: str,
    score: float | None = None,
    earnings_date: str = "",
    timing_bucket: str = "",
    catalyst_status: str = "",
    catalyst_risk: str = "",
    action: str = "",
    risk: str = "",
    signal: str = "",
    category: str = "",
) -> dict:
    return {
        "checked_at": now_text(),
        "symbol": str(symbol or "").upper().strip(),
        "score": score,
        "earnings_date": str(earnings_date or "").strip(),
        "timing_bucket": str(timing_bucket or "").strip(),
        "catalyst_status": str(catalyst_status or "").strip(),
        "catalyst_risk": str(catalyst_risk or "").strip(),
        "action": str(action or "").strip(),
        "risk": str(risk or "").strip(),
        "signal": str(signal or "").strip(),
        "category": str(category or "").strip(),
    }


def record_earnings_read(symbol: str, record: dict) -> dict:
    symbol = str(symbol or "").upper().strip()
    memory = load_earnings_memory()

    memory.setdefault("tickers", {})
    records = memory["tickers"].setdefault(symbol, [])

    if not isinstance(records, list):
        records = []
        memory["tickers"][symbol] = records

    previous = records[-1] if records else None

    records.append(record)
    memory["tickers"][symbol] = records[-MAX_RECORDS_PER_TICKER:]

    save_earnings_memory(memory)

    return {
        "previous": previous,
        "current": record,
        "records": memory["tickers"][symbol],
    }


def score_delta_note(previous: dict | None, current: dict) -> str:
    if not previous:
        return "First tracked earnings/catalyst read for this ticker."

    previous_score = safe_float(previous.get("score"))
    current_score = safe_float(current.get("score"))

    if previous_score is None or current_score is None:
        return "Score trend is not established yet."

    delta = current_score - previous_score

    if abs(delta) < 1:
        return "Score is broadly stable versus the prior catalyst read."

    direction = "improved" if delta > 0 else "weakened"

    return f"Score {direction} by {abs(delta):.1f} points versus the prior catalyst read."


def field_change_note(previous: dict | None, current: dict, field: str, label: str) -> str:
    if not previous:
        return ""

    previous_value = str(previous.get(field) or "").strip()
    current_value = str(current.get(field) or "").strip()

    if not previous_value or not current_value or previous_value == current_value:
        return ""

    return f"{label} changed from {previous_value} to {current_value}."


def build_earnings_evolution_notes(previous: dict | None, current: dict) -> list[str]:
    notes = [
        score_delta_note(previous, current),
        field_change_note(previous, current, "earnings_date", "Earnings date"),
        field_change_note(previous, current, "timing_bucket", "Timing"),
        field_change_note(previous, current, "catalyst_status", "Catalyst status"),
        field_change_note(previous, current, "catalyst_risk", "Catalyst risk"),
        field_change_note(previous, current, "action", "Action bias"),
        field_change_note(previous, current, "risk", "Risk"),
    ]

    return [note for note in notes if note][:5]


def build_earnings_memory_summary(symbol: str) -> str:
    memory = load_earnings_memory()
    records = memory.get("tickers", {}).get(str(symbol or "").upper().strip(), [])

    if not isinstance(records, list) or len(records) < 2:
        return "Not enough catalyst history yet. This read starts the earnings memory."

    first = records[0]
    latest = records[-1]

    first_score = safe_float(first.get("score"))
    latest_score = safe_float(latest.get("score"))

    if first_score is None or latest_score is None:
        return f"{len(records)} tracked catalyst reads. Score trend is still developing."

    delta = latest_score - first_score

    if abs(delta) < 1:
        trend = "stable"
    elif delta > 0:
        trend = "improving"
    else:
        trend = "weakening"

    return f"{len(records)} tracked catalyst reads. Longer-term catalyst score trend: {trend}."