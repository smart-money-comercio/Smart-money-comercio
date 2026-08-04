import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MEMORY_FILE = Path(
    os.getenv("GLOBAL_INTELLIGENCE_MEMORY_FILE", "data/global_intelligence_memory.json")
)

TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
MAX_RECORDS = int(os.getenv("GLOBAL_MEMORY_MAX_RECORDS", "40"))


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


def load_global_memory() -> dict:
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


def save_global_memory(memory: dict) -> None:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = now_text()

        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(memory, file, indent=2, sort_keys=True)

    except Exception:
        return


def build_global_record(
    macro_regime: str,
    risk_regime: str,
    portfolio_impact: str,
    top_theme: str,
    pressure_count: int,
    source_item_count: int,
    source_error_count: int,
    sp500_move: float | None,
    nasdaq_move: float | None,
    vix_move: float | None,
    oil_move: float | None,
    dollar_move: float | None,
    tlt_move: float | None,
) -> dict:
    return {
        "checked_at": now_text(),
        "macro_regime": str(macro_regime or "").strip(),
        "risk_regime": str(risk_regime or "").strip(),
        "portfolio_impact": str(portfolio_impact or "").strip(),
        "top_theme": str(top_theme or "").strip(),
        "pressure_count": pressure_count,
        "source_item_count": source_item_count,
        "source_error_count": source_error_count,
        "sp500_move": sp500_move,
        "nasdaq_move": nasdaq_move,
        "vix_move": vix_move,
        "oil_move": oil_move,
        "dollar_move": dollar_move,
        "tlt_move": tlt_move,
    }


def record_global_read(record: dict) -> dict:
    memory = load_global_memory()
    records = memory.setdefault("records", [])

    if not isinstance(records, list):
        records = []
        memory["records"] = records

    previous = records[-1] if records else None

    records.append(record)
    memory["records"] = records[-MAX_RECORDS:]

    save_global_memory(memory)

    return {
        "previous": previous,
        "current": record,
        "records": memory["records"],
    }


def number_delta_note(previous: dict | None, current: dict, field: str, label: str, threshold: float = 0.5) -> str:
    if not previous:
        return ""

    previous_value = safe_float(previous.get(field))
    current_value = safe_float(current.get(field))

    if previous_value is None or current_value is None:
        return ""

    delta = current_value - previous_value

    if abs(delta) < threshold:
        return ""

    direction = "increased" if delta > 0 else "decreased"

    return f"{label} {direction} by {abs(delta):.2f} points versus the prior macro read."


def field_change_note(previous: dict | None, current: dict, field: str, label: str) -> str:
    if not previous:
        return ""

    previous_value = str(previous.get(field) or "").strip()
    current_value = str(current.get(field) or "").strip()

    if not previous_value or not current_value or previous_value == current_value:
        return ""

    return f"{label} changed from {previous_value} to {current_value}."


def build_global_evolution_notes(previous: dict | None, current: dict) -> list[str]:
    notes = [
        "First tracked global macro intelligence read." if not previous else "",
        field_change_note(previous, current, "macro_regime", "Macro regime"),
        field_change_note(previous, current, "risk_regime", "Risk regime"),
        field_change_note(previous, current, "portfolio_impact", "Portfolio impact"),
        field_change_note(previous, current, "top_theme", "Top macro theme"),
        number_delta_note(previous, current, "sp500_move", "S&P move"),
        number_delta_note(previous, current, "nasdaq_move", "Nasdaq move"),
        number_delta_note(previous, current, "vix_move", "VIX move"),
        number_delta_note(previous, current, "oil_move", "Oil move"),
        number_delta_note(previous, current, "dollar_move", "Dollar move"),
        number_delta_note(previous, current, "tlt_move", "TLT move"),
    ]

    return [note for note in notes if note][:7]


def build_global_memory_summary() -> str:
    memory = load_global_memory()
    records = memory.get("records", [])

    if not isinstance(records, list) or len(records) < 2:
        return "Not enough global macro history yet. This read starts the macro memory."

    latest = records[-1]

    regimes = [
        str(record.get("risk_regime") or "")
        for record in records[-8:]
        if str(record.get("risk_regime") or "")
    ]

    if not regimes:
        trend = "developing"
    else:
        trend = max(set(regimes), key=regimes.count)

    return (
        f"{len(records)} tracked global macro reads. "
        f"Recent dominant risk regime: {trend}. "
        f"Latest portfolio impact: {latest.get('portfolio_impact', 'developing')}."
    )