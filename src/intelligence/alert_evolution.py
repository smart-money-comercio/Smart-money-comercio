import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MEMORY_FILE = Path(
    os.getenv("ALERT_MONITOR_MEMORY_FILE", "data/alert_monitor_memory.json")
)

TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
MAX_RECORDS = int(os.getenv("ALERT_MONITOR_MAX_RECORDS", "80"))


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


def load_alert_memory() -> dict:
    try:
        if not MEMORY_FILE.exists():
            return {"records": [], "updated_at": None, "latest_symbol_state": {}}

        with MEMORY_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return {"records": [], "updated_at": None, "latest_symbol_state": {}}

        data.setdefault("records", [])
        data.setdefault("latest_symbol_state", {})
        return data

    except Exception:
        return {"records": [], "updated_at": None, "latest_symbol_state": {}}


def save_alert_memory(memory: dict) -> None:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = now_text()

        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(memory, file, indent=2, sort_keys=True)

    except Exception:
        return


def get_latest_symbol_state() -> dict[str, dict]:
    memory = load_alert_memory()
    state = memory.get("latest_symbol_state", {})

    if isinstance(state, dict):
        return state

    return {}


def build_alert_record(
    alert_regime: str,
    macro_regime: str,
    risk_regime: str,
    highest_priority_symbols: list[str],
    new_priority_symbols: list[str],
    deteriorating_symbols: list[str],
    validation_symbols: list[str],
    risk_symbols: list[str],
    alert_count: int,
    critical_count: int,
    warning_count: int,
) -> dict:
    return {
        "checked_at": now_text(),
        "alert_regime": str(alert_regime or "").strip(),
        "macro_regime": str(macro_regime or "").strip(),
        "risk_regime": str(risk_regime or "").strip(),
        "highest_priority_symbols": highest_priority_symbols[:12],
        "new_priority_symbols": new_priority_symbols[:12],
        "deteriorating_symbols": deteriorating_symbols[:12],
        "validation_symbols": validation_symbols[:12],
        "risk_symbols": risk_symbols[:12],
        "alert_count": alert_count,
        "critical_count": critical_count,
        "warning_count": warning_count,
    }


def record_alert_scan(record: dict, symbol_state: dict[str, dict]) -> dict:
    memory = load_alert_memory()
    records = memory.setdefault("records", [])

    if not isinstance(records, list):
        records = []
        memory["records"] = records

    previous = records[-1] if records else None
    previous_symbol_state = memory.get("latest_symbol_state", {})

    records.append(record)
    memory["records"] = records[-MAX_RECORDS:]
    memory["latest_symbol_state"] = symbol_state

    save_alert_memory(memory)

    return {
        "previous": previous,
        "current": record,
        "records": memory["records"],
        "previous_symbol_state": previous_symbol_state,
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
        pieces.append("new " + ", ".join(new_items[:5]))

    if removed_items:
        pieces.append("removed " + ", ".join(removed_items[:5]))

    return f"{label}: {'; '.join(pieces)}."


def count_delta_note(previous: dict | None, current: dict, field: str, label: str) -> str:
    if not previous:
        return ""

    previous_value = safe_float(previous.get(field), 0) or 0
    current_value = safe_float(current.get(field), 0) or 0
    delta = current_value - previous_value

    if abs(delta) < 1:
        return ""

    direction = "increased" if delta > 0 else "decreased"

    return f"{label} {direction} by {abs(delta):.0f}."


def build_alert_evolution_notes(previous: dict | None, current: dict) -> list[str]:
    notes = [
        "First tracked alert monitor scan." if not previous else "",
        field_change_note(previous, current, "alert_regime", "Alert regime"),
        field_change_note(previous, current, "macro_regime", "Macro regime"),
        field_change_note(previous, current, "risk_regime", "Risk regime"),
        count_delta_note(previous, current, "alert_count", "Alert count"),
        count_delta_note(previous, current, "critical_count", "Critical alert count"),
        count_delta_note(previous, current, "warning_count", "Warning alert count"),
        list_delta_note(
            previous,
            current,
            "highest_priority_symbols",
            "Highest-priority symbols changed",
        ),
        list_delta_note(
            previous,
            current,
            "new_priority_symbols",
            "New-priority symbols changed",
        ),
        list_delta_note(
            previous,
            current,
            "deteriorating_symbols",
            "Deteriorating symbols changed",
        ),
        list_delta_note(
            previous,
            current,
            "validation_symbols",
            "Validation queue changed",
        ),
        list_delta_note(
            previous,
            current,
            "risk_symbols",
            "Risk-control queue changed",
        ),
    ]

    return [note for note in notes if note][:9]


def build_alert_memory_summary() -> str:
    memory = load_alert_memory()
    records = memory.get("records", [])

    if not isinstance(records, list) or len(records) < 2:
        return "Not enough alert history yet. This scan starts the alert memory."

    latest = records[-1]

    regimes = [
        str(record.get("alert_regime") or "")
        for record in records[-10:]
        if str(record.get("alert_regime") or "")
    ]

    dominant = max(set(regimes), key=regimes.count) if regimes else "developing"

    return (
        f"{len(records)} tracked alert scans. "
        f"Recent dominant alert regime: {dominant}. "
        f"Latest alerts: {latest.get('alert_count', 0)} total, "
        f"{latest.get('critical_count', 0)} critical, "
        f"{latest.get('warning_count', 0)} warning."
    )