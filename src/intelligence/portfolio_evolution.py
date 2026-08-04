import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MEMORY_FILE = Path(
    os.getenv("PORTFOLIO_INTELLIGENCE_MEMORY_FILE", "data/portfolio_intelligence_memory.json")
)

TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
MAX_RECORDS = int(os.getenv("PORTFOLIO_MEMORY_MAX_RECORDS", "40"))


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


def load_portfolio_memory() -> dict:
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


def save_portfolio_memory(memory: dict) -> None:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = now_text()

        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(memory, file, indent=2, sort_keys=True)

    except Exception:
        return


def build_portfolio_record(
    top_symbols: list[str],
    high_risk_symbols: list[str],
    confirmation_symbols: list[str],
    top_theme: str,
    portfolio_stance: str,
    average_score: float | None,
    high_conviction_count: int,
    elevated_risk_count: int,
    action_bias: str,
) -> dict:
    return {
        "checked_at": now_text(),
        "top_symbols": top_symbols[:8],
        "high_risk_symbols": high_risk_symbols[:8],
        "confirmation_symbols": confirmation_symbols[:8],
        "top_theme": str(top_theme or "").strip(),
        "portfolio_stance": str(portfolio_stance or "").strip(),
        "average_score": average_score,
        "high_conviction_count": high_conviction_count,
        "elevated_risk_count": elevated_risk_count,
        "action_bias": str(action_bias or "").strip(),
    }


def record_portfolio_read(record: dict) -> dict:
    memory = load_portfolio_memory()
    records = memory.setdefault("records", [])

    if not isinstance(records, list):
        records = []
        memory["records"] = records

    previous = records[-1] if records else None

    records.append(record)
    memory["records"] = records[-MAX_RECORDS:]

    save_portfolio_memory(memory)

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
        return "First tracked portfolio intelligence read."

    previous_score = safe_float(previous.get("average_score"))
    current_score = safe_float(current.get("average_score"))

    if previous_score is None or current_score is None:
        return "Average score trend is still developing."

    delta = current_score - previous_score

    if abs(delta) < 1:
        return "Average portfolio score is broadly stable versus the prior read."

    direction = "improved" if delta > 0 else "weakened"

    return f"Average portfolio score {direction} by {abs(delta):.1f} points versus the prior read."


def field_change_note(previous: dict | None, current: dict, field: str, label: str) -> str:
    if not previous:
        return ""

    previous_value = str(previous.get(field) or "").strip()
    current_value = str(current.get(field) or "").strip()

    if not previous_value or not current_value or previous_value == current_value:
        return ""

    return f"{label} changed from {previous_value} to {current_value}."


def build_portfolio_evolution_notes(previous: dict | None, current: dict) -> list[str]:
    notes = [
        score_delta_note(previous, current),
        list_delta_note(previous, current, "top_symbols", "Top ideas changed"),
        list_delta_note(previous, current, "high_risk_symbols", "High-risk names changed"),
        list_delta_note(previous, current, "confirmation_symbols", "Confirmation queue changed"),
        field_change_note(previous, current, "top_theme", "Top theme"),
        field_change_note(previous, current, "portfolio_stance", "Portfolio stance"),
        field_change_note(previous, current, "action_bias", "Action bias"),
    ]

    return [note for note in notes if note][:6]


def build_portfolio_memory_summary() -> str:
    memory = load_portfolio_memory()
    records = memory.get("records", [])

    if not isinstance(records, list) or len(records) < 2:
        return "Not enough portfolio history yet. This read starts the portfolio memory."

    first = records[0]
    latest = records[-1]

    first_score = safe_float(first.get("average_score"))
    latest_score = safe_float(latest.get("average_score"))

    if first_score is None or latest_score is None:
        return f"{len(records)} tracked portfolio reads. Portfolio trend is still developing."

    delta = latest_score - first_score

    if abs(delta) < 1:
        trend = "stable"
    elif delta > 0:
        trend = "improving"
    else:
        trend = "weakening"

    return (
        f"{len(records)} tracked portfolio reads. "
        f"Longer-term score trend: {trend}. "
        f"Latest stance: {latest.get('portfolio_stance', 'developing')}."
    )