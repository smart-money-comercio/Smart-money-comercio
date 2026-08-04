import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MEMORY_FILE = Path(
    os.getenv("ANALYST_INTELLIGENCE_MEMORY_FILE", "data/analyst_intelligence_memory.json")
)

TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
MAX_RECORDS_PER_TICKER = int(os.getenv("ANALYST_MEMORY_MAX_RECORDS", "30"))


def now_text() -> str:
    try:
        current = datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        current = datetime.now()

    return current.strftime("%Y-%m-%d %H:%M:%S")


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.replace("%", "").replace("$", "").replace(",", "").strip()

        return float(value)

    except Exception:
        return default


def load_analyst_memory() -> dict:
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


def save_analyst_memory(memory: dict) -> None:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = now_text()

        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(memory, file, indent=2, sort_keys=True)

    except Exception:
        return


def build_analyst_record(
    symbol: str,
    score: float | None = None,
    consensus: str = "",
    alignment: str = "",
    analyst_risk: str = "",
    price_target: float | None = None,
    upside_percent: float | None = None,
    action: str = "",
    risk: str = "",
    signal: str = "",
) -> dict:
    return {
        "checked_at": now_text(),
        "symbol": str(symbol or "").upper().strip(),
        "score": score,
        "consensus": str(consensus or "").strip(),
        "alignment": str(alignment or "").strip(),
        "analyst_risk": str(analyst_risk or "").strip(),
        "price_target": price_target,
        "upside_percent": upside_percent,
        "action": str(action or "").strip(),
        "risk": str(risk or "").strip(),
        "signal": str(signal or "").strip(),
    }


def record_analyst_read(symbol: str, record: dict) -> dict:
    symbol = str(symbol or "").upper().strip()
    memory = load_analyst_memory()

    memory.setdefault("tickers", {})
    records = memory["tickers"].setdefault(symbol, [])

    if not isinstance(records, list):
        records = []
        memory["tickers"][symbol] = records

    previous = records[-1] if records else None

    records.append(record)
    memory["tickers"][symbol] = records[-MAX_RECORDS_PER_TICKER:]

    save_analyst_memory(memory)

    return {
        "previous": previous,
        "current": record,
        "records": memory["tickers"][symbol],
    }


def score_delta_note(previous: dict | None, current: dict) -> str:
    if not previous:
        return "First tracked analyst consensus read for this ticker."

    previous_score = safe_float(previous.get("score"))
    current_score = safe_float(current.get("score"))

    if previous_score is None or current_score is None:
        return "Score trend is not established yet."

    delta = current_score - previous_score

    if abs(delta) < 1:
        return "Smart Money score is broadly stable versus the prior analyst read."

    direction = "improved" if delta > 0 else "weakened"

    return f"Smart Money score {direction} by {abs(delta):.1f} points versus the prior analyst read."


def upside_delta_note(previous: dict | None, current: dict) -> str:
    if not previous:
        return ""

    previous_upside = safe_float(previous.get("upside_percent"))
    current_upside = safe_float(current.get("upside_percent"))

    if previous_upside is None or current_upside is None:
        return ""

    delta = current_upside - previous_upside

    if abs(delta) < 1:
        return "Analyst upside/downside is broadly stable versus the prior read."

    direction = "improved" if delta > 0 else "weakened"

    return f"Analyst implied upside {direction} by {abs(delta):.1f} percentage points."


def field_change_note(previous: dict | None, current: dict, field: str, label: str) -> str:
    if not previous:
        return ""

    previous_value = str(previous.get(field) or "").strip()
    current_value = str(current.get(field) or "").strip()

    if not previous_value or not current_value or previous_value == current_value:
        return ""

    return f"{label} changed from {previous_value} to {current_value}."


def build_analyst_evolution_notes(previous: dict | None, current: dict) -> list[str]:
    notes = [
        score_delta_note(previous, current),
        upside_delta_note(previous, current),
        field_change_note(previous, current, "consensus", "Consensus"),
        field_change_note(previous, current, "alignment", "Alignment"),
        field_change_note(previous, current, "analyst_risk", "Analyst risk"),
        field_change_note(previous, current, "action", "Action bias"),
        field_change_note(previous, current, "risk", "Risk"),
    ]

    return [note for note in notes if note][:5]


def build_analyst_memory_summary(symbol: str) -> str:
    memory = load_analyst_memory()
    records = memory.get("tickers", {}).get(str(symbol or "").upper().strip(), [])

    if not isinstance(records, list) or len(records) < 2:
        return "Not enough analyst history yet. This read starts the consensus memory."

    first = records[0]
    latest = records[-1]

    first_score = safe_float(first.get("score"))
    latest_score = safe_float(latest.get("score"))

    if first_score is None or latest_score is None:
        return f"{len(records)} tracked analyst reads. Alignment trend is still developing."

    delta = latest_score - first_score

    if abs(delta) < 1:
        trend = "stable"
    elif delta > 0:
        trend = "improving"
    else:
        trend = "weakening"

    latest_alignment = latest.get("alignment") or "alignment developing"

    return f"{len(records)} tracked analyst reads. Smart Money trend: {trend}. Latest alignment: {latest_alignment}."