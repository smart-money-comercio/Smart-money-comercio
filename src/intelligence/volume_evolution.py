import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MEMORY_FILE = Path(
    os.getenv("VOLUME_INTELLIGENCE_MEMORY_FILE", "data/volume_intelligence_memory.json")
)

TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
MAX_RECORDS_PER_TICKER = int(os.getenv("VOLUME_MEMORY_MAX_RECORDS", "30"))


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


def load_volume_memory() -> dict:
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


def save_volume_memory(memory: dict) -> None:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = now_text()

        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(memory, file, indent=2, sort_keys=True)

    except Exception:
        return


def build_volume_record(
    symbol: str,
    score: float | None = None,
    price: float | None = None,
    change_percent: float | None = None,
    volume_label: str = "",
    action: str = "",
    risk: str = "",
    signal: str = "",
    confirmation: str = "",
) -> dict:
    return {
        "checked_at": now_text(),
        "symbol": str(symbol or "").upper().strip(),
        "score": score,
        "price": price,
        "change_percent": change_percent,
        "volume_label": str(volume_label or "").strip(),
        "action": str(action or "").strip(),
        "risk": str(risk or "").strip(),
        "signal": str(signal or "").strip(),
        "confirmation": str(confirmation or "").strip(),
    }


def record_volume_read(symbol: str, record: dict) -> dict:
    symbol = str(symbol or "").upper().strip()
    memory = load_volume_memory()

    memory.setdefault("tickers", {})
    records = memory["tickers"].setdefault(symbol, [])

    if not isinstance(records, list):
        records = []
        memory["tickers"][symbol] = records

    previous = records[-1] if records else None

    records.append(record)
    memory["tickers"][symbol] = records[-MAX_RECORDS_PER_TICKER:]

    save_volume_memory(memory)

    return {
        "previous": previous,
        "current": record,
        "records": memory["tickers"][symbol],
    }


def score_delta_note(previous: dict | None, current: dict) -> str:
    if not previous:
        return "First tracked volume read for this ticker."

    previous_score = safe_float(previous.get("score"))
    current_score = safe_float(current.get("score"))

    if previous_score is None or current_score is None:
        return "Score trend is not established yet."

    delta = current_score - previous_score

    if abs(delta) < 1:
        return "Score is broadly stable versus the last volume read."

    direction = "improved" if delta > 0 else "weakened"

    return f"Score {direction} by {abs(delta):.1f} points versus the last volume read."


def change_percent_note(previous: dict | None, current: dict) -> str:
    if not previous:
        return ""

    previous_change = safe_float(previous.get("change_percent"))
    current_change = safe_float(current.get("change_percent"))

    if previous_change is None or current_change is None:
        return ""

    delta = current_change - previous_change

    if abs(delta) < 0.5:
        return "Price move is similar to the prior read."

    direction = "strengthened" if delta > 0 else "faded"

    return f"Price move {direction} by {abs(delta):.2f} percentage points versus the prior read."


def field_change_note(previous: dict | None, current: dict, field: str, label: str) -> str:
    if not previous:
        return ""

    previous_value = str(previous.get(field) or "").strip()
    current_value = str(current.get(field) or "").strip()

    if not previous_value or not current_value or previous_value == current_value:
        return ""

    return f"{label} changed from {previous_value} to {current_value}."


def build_volume_evolution_notes(previous: dict | None, current: dict) -> list[str]:
    notes = [
        score_delta_note(previous, current),
        change_percent_note(previous, current),
        field_change_note(previous, current, "volume_label", "Volume read"),
        field_change_note(previous, current, "confirmation", "Confirmation read"),
        field_change_note(previous, current, "action", "Action bias"),
        field_change_note(previous, current, "risk", "Risk"),
    ]

    return [note for note in notes if note][:5]


def build_volume_memory_summary(symbol: str) -> str:
    memory = load_volume_memory()
    records = memory.get("tickers", {}).get(str(symbol or "").upper().strip(), [])

    if not isinstance(records, list) or len(records) < 2:
        return "Not enough volume history yet. This read starts the money-flow memory."

    first = records[0]
    latest = records[-1]

    first_change = safe_float(first.get("change_percent"))
    latest_change = safe_float(latest.get("change_percent"))

    if first_change is None or latest_change is None:
        return f"{len(records)} tracked volume reads. Confirmation trend is still developing."

    delta = latest_change - first_change

    if abs(delta) < 0.5:
        trend = "stable"
    elif delta > 0:
        trend = "improving"
    else:
        trend = "fading"

    return f"{len(records)} tracked volume reads. Longer-term price/flow confirmation trend: {trend}."