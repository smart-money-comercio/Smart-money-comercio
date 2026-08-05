import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MEMORY_FILE = Path(
    os.getenv("SMARTMONEY_INTELLIGENCE_MEMORY_FILE", "data/smartmoney_intelligence_memory.json")
)

TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
MAX_RECORDS = int(os.getenv("SMARTMONEY_MEMORY_MAX_RECORDS", "50"))


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


def load_smartmoney_memory() -> dict:
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


def save_smartmoney_memory(memory: dict) -> None:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = now_text()

        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(memory, file, indent=2, sort_keys=True)

    except Exception:
        return


def build_smartmoney_record(
    command_stance: str,
    macro_regime: str,
    risk_regime: str,
    top_theme: str,
    defense_theme: str,
    top_symbols: list[str],
    high_risk_symbols: list[str],
    confirmation_symbols: list[str],
    average_score: float | None,
    smartmoney_action: str,
) -> dict:
    return {
        "checked_at": now_text(),
        "command_stance": str(command_stance or "").strip(),
        "macro_regime": str(macro_regime or "").strip(),
        "risk_regime": str(risk_regime or "").strip(),
        "top_theme": str(top_theme or "").strip(),
        "defense_theme": str(defense_theme or "").strip(),
        "top_symbols": top_symbols[:10],
        "high_risk_symbols": high_risk_symbols[:10],
        "confirmation_symbols": confirmation_symbols[:10],
        "average_score": average_score,
        "smartmoney_action": str(smartmoney_action or "").strip(),
    }


def record_smartmoney_read(record: dict) -> dict:
    memory = load_smartmoney_memory()
    records = memory.setdefault("records", [])

    if not isinstance(records, list):
        records = []
        memory["records"] = records

    previous = records[-1] if records else None

    records.append(record)
    memory["records"] = records[-MAX_RECORDS:]

    save_smartmoney_memory(memory)

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


def score_delta_note(previous: dict | None, current: dict) -> str:
    if not previous:
        return "First tracked Smart Money Command Center read."

    previous_score = safe_float(previous.get("average_score"))
    current_score = safe_float(current.get("average_score"))

    if previous_score is None or current_score is None:
        return "Average Smart Money score trend is still developing."

    delta = current_score - previous_score

    if abs(delta) < 1:
        return "Average Smart Money score is broadly stable versus the prior read."

    direction = "improved" if delta > 0 else "weakened"

    return f"Average Smart Money score {direction} by {abs(delta):.1f} points versus the prior read."


def build_smartmoney_evolution_notes(previous: dict | None, current: dict) -> list[str]:
    notes = [
        score_delta_note(previous, current),
        field_change_note(previous, current, "command_stance", "Command stance"),
        field_change_note(previous, current, "macro_regime", "Macro regime"),
        field_change_note(previous, current, "risk_regime", "Risk regime"),
        field_change_note(previous, current, "top_theme", "Top theme"),
        field_change_note(previous, current, "defense_theme", "Defense theme"),
        list_delta_note(previous, current, "top_symbols", "Top Smart Money names changed"),
        list_delta_note(previous, current, "high_risk_symbols", "High-risk names changed"),
        list_delta_note(previous, current, "confirmation_symbols", "Confirmation queue changed"),
        field_change_note(previous, current, "smartmoney_action", "Smart Money action"),
    ]

    return [note for note in notes if note][:8]


def build_smartmoney_memory_summary() -> str:
    memory = load_smartmoney_memory()
    records = memory.get("records", [])

    if not isinstance(records, list) or len(records) < 2:
        return "Not enough Smart Money history yet. This read starts the command-center memory."

    latest = records[-1]

    recent_stances = [
        str(record.get("command_stance") or "")
        for record in records[-8:]
        if str(record.get("command_stance") or "")
    ]

    if recent_stances:
        dominant = max(set(recent_stances), key=recent_stances.count)
    else:
        dominant = "developing"

    return (
        f"{len(records)} tracked Smart Money Command Center reads. "
        f"Recent dominant stance: {dominant}. "
        f"Latest action: {latest.get('smartmoney_action', 'developing')}."
    )