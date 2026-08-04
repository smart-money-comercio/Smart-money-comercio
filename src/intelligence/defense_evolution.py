import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MEMORY_FILE = Path(
    os.getenv("DEFENSE_INTELLIGENCE_MEMORY_FILE", "data/defense_intelligence_memory.json")
)

TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
MAX_RECORDS = int(os.getenv("DEFENSE_MEMORY_MAX_RECORDS", "40"))


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


def load_defense_memory() -> dict:
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


def save_defense_memory(memory: dict) -> None:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = now_text()

        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(memory, file, indent=2, sort_keys=True)

    except Exception:
        return


def build_defense_record(
    top_symbols: list[str],
    high_risk_symbols: list[str],
    confirmation_symbols: list[str],
    top_theme: str,
    defense_stance: str,
    average_score: float | None,
    source_item_count: int,
    source_error_count: int,
    portfolio_impact: str,
) -> dict:
    return {
        "checked_at": now_text(),
        "top_symbols": top_symbols[:8],
        "high_risk_symbols": high_risk_symbols[:8],
        "confirmation_symbols": confirmation_symbols[:8],
        "top_theme": str(top_theme or "").strip(),
        "defense_stance": str(defense_stance or "").strip(),
        "average_score": average_score,
        "source_item_count": source_item_count,
        "source_error_count": source_error_count,
        "portfolio_impact": str(portfolio_impact or "").strip(),
    }


def record_defense_read(record: dict) -> dict:
    memory = load_defense_memory()
    records = memory.setdefault("records", [])

    if not isinstance(records, list):
        records = []
        memory["records"] = records

    previous = records[-1] if records else None

    records.append(record)
    memory["records"] = records[-MAX_RECORDS:]

    save_defense_memory(memory)

    return {
        "previous": previous,
        "current": record,
        "records": memory["records"],
    }


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
        return "First tracked defense / AI warfare portfolio read."

    previous_score = safe_float(previous.get("average_score"))
    current_score = safe_float(current.get("average_score"))

    if previous_score is None or current_score is None:
        return "Average defense score trend is still developing."

    delta = current_score - previous_score

    if abs(delta) < 1:
        return "Average defense score is broadly stable versus the prior read."

    direction = "improved" if delta > 0 else "weakened"

    return f"Average defense score {direction} by {abs(delta):.1f} points versus the prior read."


def source_delta_note(previous: dict | None, current: dict) -> str:
    if not previous:
        return ""

    previous_count = safe_float(previous.get("source_item_count"), 0) or 0
    current_count = safe_float(current.get("source_item_count"), 0) or 0

    delta = current_count - previous_count

    if abs(delta) < 1:
        return "Official-source defense signal count is stable versus the prior read."

    direction = "increased" if delta > 0 else "decreased"

    return f"Official-source defense signal count {direction} by {abs(delta):.0f} items."


def field_change_note(previous: dict | None, current: dict, field: str, label: str) -> str:
    if not previous:
        return ""

    previous_value = str(previous.get(field) or "").strip()
    current_value = str(current.get(field) or "").strip()

    if not previous_value or not current_value or previous_value == current_value:
        return ""

    return f"{label} changed from {previous_value} to {current_value}."


def build_defense_evolution_notes(previous: dict | None, current: dict) -> list[str]:
    notes = [
        score_delta_note(previous, current),
        source_delta_note(previous, current),
        list_delta_note(previous, current, "top_symbols", "Top defense names changed"),
        list_delta_note(previous, current, "high_risk_symbols", "High-risk defense names changed"),
        list_delta_note(previous, current, "confirmation_symbols", "Confirmation queue changed"),
        field_change_note(previous, current, "top_theme", "Top defense theme"),
        field_change_note(previous, current, "defense_stance", "Defense stance"),
        field_change_note(previous, current, "portfolio_impact", "Portfolio impact"),
    ]

    return [note for note in notes if note][:7]


def build_defense_memory_summary() -> str:
    memory = load_defense_memory()
    records = memory.get("records", [])

    if not isinstance(records, list) or len(records) < 2:
        return "Not enough defense history yet. This read starts the defense portfolio memory."

    first = records[0]
    latest = records[-1]

    first_score = safe_float(first.get("average_score"))
    latest_score = safe_float(latest.get("average_score"))

    if first_score is None or latest_score is None:
        return f"{len(records)} tracked defense reads. Defense trend is still developing."

    delta = latest_score - first_score

    if abs(delta) < 1:
        trend = "stable"
    elif delta > 0:
        trend = "improving"
    else:
        trend = "weakening"

    return (
        f"{len(records)} tracked defense reads. "
        f"Longer-term defense score trend: {trend}. "
        f"Latest stance: {latest.get('defense_stance', 'developing')}. "
        f"Portfolio impact: {latest.get('portfolio_impact', 'developing')}."
    )