"""Choose monitored companies from the core list and dated, cached rankings."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo


RANKING_PATH = Path(__file__).resolve().parents[2] / "data/opportunity_score_memory.json"
SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}\Z")


def company_universe(config: dict, now: datetime | None = None, path: Path | None = None) -> dict:
    """Read the existing ranking snapshot; never fetch, rescore, or write memory."""
    now = now or datetime.now(timezone.utc)
    core = list(dict.fromkeys(s for s in config["symbols"] if SYMBOL.fullmatch(s)))[:20]
    count = config.get("top_count", 0)
    result = {"symbols": core.copy(), "core": core, "ranked": [],
              "ranking_status": "Cached top opportunities disabled"}
    if not count:
        return result
    try:
        with (path or RANKING_PATH).open("rb") as handle:
            raw = handle.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("ranking snapshot too large")
        payload = json.loads(raw)
        day = date.fromisoformat(payload["current_date"])
        age = (now.astimezone(ZoneInfo("America/New_York")).date() - day).days
        if not 0 <= age <= 4:
            raise ValueError("ranking snapshot stale or future-dated")
        current = payload["current"]
        if not isinstance(current, dict):
            raise ValueError("ranking snapshot invalid")
        ranked = []
        for symbol, values in current.items():
            if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol) or not isinstance(values, dict):
                continue
            score = values.get("opportunity_score")
            structural = values.get("structural_score", 0)
            if any(type(v) not in (int, float) or not 0 <= v <= 100 or not math.isfinite(v)
                   for v in (score, structural)):
                continue
            ranked.append((score, structural, symbol))
        ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
        if not ranked:
            raise ValueError("no valid cached opportunities")
        result["ranked"] = [row[2] for row in ranked[:count]]
        result["symbols"] = list(dict.fromkeys(core + result["ranked"]))
        result["ranking_status"] = f"Top {len(result['ranked'])} from rankings dated {day.isoformat()} (cache only)"
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        result["ranking_status"] = "Cached rankings unavailable, invalid, or stale; core companies only"
    return result
