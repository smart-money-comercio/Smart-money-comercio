import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MEMORY_FILE = Path(
    os.getenv("TOP10_EVOLUTION_MEMORY_FILE", "data/top10_evolution_memory.json")
)

TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
MAX_HISTORY = int(os.getenv("TOP10_EVOLUTION_MAX_HISTORY", "30"))


def now_text() -> str:
    try:
        now = datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        now = datetime.now()

    return now.strftime("%Y-%m-%d %H:%M:%S")


def normalize_symbol(value: Any) -> str:
    return str(value or "").upper().replace("$", "").strip()


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()

        return float(value)

    except Exception:
        return default


def load_top10_memory() -> dict:
    try:
        if not MEMORY_FILE.exists():
            return {"history": [], "updated_at": None}

        with MEMORY_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return {"history": [], "updated_at": None}

        data.setdefault("history", [])
        return data

    except Exception:
        return {"history": [], "updated_at": None}


def save_top10_memory(memory: dict) -> None:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = now_text()

        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(memory, file, indent=2, sort_keys=True)

    except Exception:
        return


def build_ranking_record(ranked_items: list[dict], limit: int = 20) -> dict:
    names = []

    for index, item in enumerate(ranked_items[:limit], start=1):
        symbol = normalize_symbol(item.get("symbol") or item.get("ticker"))

        if not symbol:
            continue

        names.append(
            {
                "rank": index,
                "symbol": symbol,
                "score": safe_float(item.get("score")),
                "label": str(item.get("label") or "").strip(),
                "risk": str(item.get("risk") or "").strip(),
                "action": str(item.get("action") or "").strip(),
            }
        )

    return {
        "checked_at": now_text(),
        "limit": limit,
        "rankings": names,
    }


def get_previous_record(memory: dict | None = None) -> dict | None:
    memory = memory or load_top10_memory()
    history = memory.get("history") or []

    if not history:
        return None

    if not isinstance(history, list):
        return None

    return history[-1] if history else None


def record_top10_ranking(ranked_items: list[dict], limit: int = 20) -> dict:
    memory = load_top10_memory()
    previous = get_previous_record(memory)

    current = build_ranking_record(ranked_items, limit=limit)

    history = memory.setdefault("history", [])

    if not isinstance(history, list):
        history = []
        memory["history"] = history

    history.append(current)
    memory["history"] = history[-MAX_HISTORY:]

    save_top10_memory(memory)

    return {
        "previous": previous,
        "current": current,
        "history": memory["history"],
    }


def ranking_map(record: dict | None) -> dict[str, dict]:
    if not record:
        return {}

    output = {}

    for item in record.get("rankings") or []:
        symbol = normalize_symbol(item.get("symbol"))

        if symbol:
            output[symbol] = item

    return output


def build_top10_change_summary(previous: dict | None, current: dict | None) -> dict:
    previous_map = ranking_map(previous)
    current_map = ranking_map(current)

    previous_symbols = set(previous_map)
    current_symbols = set(current_map)

    new_entrants = sorted(current_symbols - previous_symbols)
    fell_out = sorted(previous_symbols - current_symbols)

    rising = []
    falling = []

    for symbol in sorted(current_symbols & previous_symbols):
        previous_rank = previous_map[symbol].get("rank")
        current_rank = current_map[symbol].get("rank")

        try:
            move = int(previous_rank) - int(current_rank)
        except Exception:
            continue

        if move > 0:
            rising.append(
                {
                    "symbol": symbol,
                    "move": move,
                    "from": previous_rank,
                    "to": current_rank,
                }
            )

        elif move < 0:
            falling.append(
                {
                    "symbol": symbol,
                    "move": abs(move),
                    "from": previous_rank,
                    "to": current_rank,
                }
            )

    rising.sort(key=lambda item: item["move"], reverse=True)
    falling.sort(key=lambda item: item["move"], reverse=True)

    return {
        "has_previous": bool(previous),
        "new_entrants": new_entrants[:5],
        "fell_out": fell_out[:5],
        "rising": rising[:5],
        "falling": falling[:5],
    }


def format_change_summary(summary: dict) -> str:
    if not summary.get("has_previous"):
        return "First tracked Top 20 ranking. Future runs will show new entrants, risers, and fallers."

    sections = []

    new_entrants = summary.get("new_entrants") or []
    rising = summary.get("rising") or []
    falling = summary.get("falling") or []
    fell_out = summary.get("fell_out") or []

    if new_entrants:
        sections.append(
            "New Entrants\n"
            + "\n".join(f"• {symbol} entered the Top 20" for symbol in new_entrants)
        )

    if rising:
        sections.append(
            "Rising\n"
            + "\n".join(
                f"• {item['symbol']} moved up {item['move']} spots "
                f"#{item['from']} → #{item['to']}"
                for item in rising
            )
        )

    if falling:
        sections.append(
            "Falling\n"
            + "\n".join(
                f"• {item['symbol']} moved down {item['move']} spots "
                f"#{item['from']} → #{item['to']}"
                for item in falling
            )
        )

    if fell_out:
        sections.append(
            "Fell Out\n"
            + "\n".join(f"• {symbol} fell out of the Top 20" for symbol in fell_out)
        )

    if not sections:
        return "Ranking is stable versus the prior run."

    return "\n\n".join(sections)