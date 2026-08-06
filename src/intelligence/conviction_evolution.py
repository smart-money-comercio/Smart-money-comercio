import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MEMORY_FILE = Path(
    os.getenv("CONVICTION_INTELLIGENCE_MEMORY_FILE", "data/conviction_intelligence_memory.json")
)

TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
MAX_RECORDS = int(os.getenv("CONVICTION_MEMORY_MAX_RECORDS", "50"))


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


def load_conviction_memory() -> dict:
    try:
        if not MEMORY_FILE.exists():
            return {"records": [], "updated_at": None}

        with MEMORY_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return {"records": [], "updated_at": None}

        data.setdefault("records", [])
        return data

    except Exception:
        return {"records": [], "updated_at": None}


def save_conviction_memory(memory: dict) -> None:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = now_text()

        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(memory, file, indent=2, sort_keys=True)

    except Exception:
        return


def build_conviction_record(
    conviction_regime: str,
    macro_regime: str,
    risk_regime: str,
    top_symbols: list[str],
    confirmed_symbols: list[str],
    validation_symbols: list[str],
    risk_symbols: list[str],
    average_conviction_score: float | None,
    top_conviction_score: float | None,
    action: str,
) -> dict:
    return {
        "checked_at": now_text(),
        "conviction_regime": str(conviction_regime or "").strip(),
        "macro_regime": str(macro_regime or "").strip(),
        "risk_regime": str(risk_regime or "").strip(),
        "top_symbols": top_symbols[:10],
        "confirmed_symbols": confirmed_symbols[:10],
        "validation_symbols": validation_symbols[:10],
        "risk_symbols": risk_symbols[:10],
        "average_conviction_score": average_conviction_score,
        "top_conviction_score": top_conviction_score,
        "action": str(action or "").strip(),
    }


def record_conviction_read(record: dict) -> dict:
    memory = load_conviction_memory()
    records = memory.setdefault("records", [])

    if not isinstance(records, list):
        records = []
        memory["records"] = records

    previous = records[-1] if records else None

    records.append(record)
    memory["records"] = records[-MAX_RECORDS:]

    save_conviction_memory(memory)

    return {
        "previous": previous,
        "current": record,
        "records": memory["records"],
    }


def field_change_note(previous: dict | None, current: dict, field: str, label: str) -> str:
    if not previous:
        return ""

    previous_value = str(previous.get(field) or "").strip()
    current_value = str(current.get(field) or "").strip()

    if not previous_value or not current_value or previous_value == current_value:
        return ""

    return f"{label} changed from {previous_value} to {current_value}."


def list_delta_note(previous: dict | None, current: dict, field: str, label: str) -> str:
    if not previous:
        return ""

    previous_items = [str(item).upper() for item in previous.get(field, []) or []]
    current_items = [str(item).upper() for item in current.get(field, []) or []]

    new_items = [item for item in current_items if item not in previous_items]
    removed_items = [item for item in previous_items if item not in current_items]

    if not new_items and not removed_items:
        return ""

    pieces = []

    if new_items:
        pieces.append("new " + ", ".join(new_items[:4]))

    if removed_items:
        pieces.append("removed " + ", ".join(removed_items[:4]))

    return f"{label}: {'; '.join(pieces)}."


def number_delta_note(
    previous: dict | None,
    current: dict,
    field: str,
    label: str,
    threshold: float = 1.0,
) -> str:
    if not previous:
        return ""

    previous_value = safe_float(previous.get(field))
    current_value = safe_float(current.get(field))

    if previous_value is None or current_value is None:
        return ""

    delta = current_value - previous_value

    if abs(delta) < threshold:
        return ""

    direction = "improved" if delta > 0 else "weakened"

    return f"{label} {direction} by {abs(delta):.1f} points versus the prior conviction read."


def build_conviction_evolution_notes(previous: dict | None, current: dict) -> list[str]:
    notes = [
        "First tracked Conviction Command Center read." if not previous else "",
        field_change_note(previous, current, "conviction_regime", "Conviction regime"),
        field_change_note(previous, current, "macro_regime", "Macro regime"),
        field_change_note(previous, current, "risk_regime", "Risk regime"),
        number_delta_note(previous, current, "average_conviction_score", "Average conviction score"),
        number_delta_note(previous, current, "top_conviction_score", "Top conviction score"),
        list_delta_note(previous, current, "top_symbols", "Top conviction names changed"),
        list_delta_note(previous, current, "confirmed_symbols", "Confirmed names changed"),
        list_delta_note(previous, current, "validation_symbols", "Validation queue changed"),
        list_delta_note(previous, current, "risk_symbols", "Risk-control names changed"),
        field_change_note(previous, current, "action", "Conviction action"),
    ]

    return [note for note in notes if note][:8]


def build_conviction_memory_summary() -> str:
    memory = load_conviction_memory()
    records = memory.get("records", [])

    if not isinstance(records, list) or len(records) < 2:
        return "Not enough conviction history yet. This read starts the conviction memory."

    latest = records[-1]

    recent_regimes = [
        str(record.get("conviction_regime") or "")
        for record in records[-8:]
        if str(record.get("conviction_regime") or "")
    ]

    dominant = max(set(recent_regimes), key=recent_regimes.count) if recent_regimes else "developing"

    return (
        f"{len(records)} tracked conviction reads. "
        f"Recent dominant conviction regime: {dominant}. "
        f"Latest action: {latest.get('action', 'developing')}."
    )