import json
import time
from pathlib import Path
from typing import Any

from src.config.theme_watchlist_universe import (
    CORE_PORTFOLIO_TICKERS,
    THEME_TICKERS,
    normalize_symbol,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WATCHLIST_EVOLUTION_FILE = PROJECT_ROOT / "data" / "watchlist_evolution_memory.json"

MAX_MEMORY_DAYS = 30
MAX_RESEARCH_UNIVERSE = 20


def read_json(path: Path, default: Any):
    try:
        if not path.exists():
            return default

        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, sort_keys=True)
    except Exception:
        return


def load_watchlist_evolution_memory() -> dict:
    data = read_json(WATCHLIST_EVOLUTION_FILE, {"days": []})

    if not isinstance(data, dict):
        return {"days": []}

    if not isinstance(data.get("days"), list):
        data["days"] = []

    return data


def save_watchlist_evolution_memory(memory: dict) -> None:
    memory["days"] = memory.get("days", [])[-MAX_MEMORY_DAYS:]
    write_json(WATCHLIST_EVOLUTION_FILE, memory)


def extract_active_themes(context: dict | None) -> list[str]:
    if not isinstance(context, dict):
        return []

    themes = []

    for theme in context.get("headline_themes") or []:
        text = str(theme or "").strip()

        if text and text not in themes:
            themes.append(text)

    return themes


def safe_score(value: Any) -> float:
    try:
        if value is None:
            return 0.0

        return float(value)
    except Exception:
        return 0.0


def get_score_for_symbol(scores: list[dict], symbol: str) -> float:
    wanted = normalize_symbol(symbol)

    for item in scores or []:
        ticker = normalize_symbol(
            item.get("ticker")
            or item.get("symbol")
            or item.get("name")
        )

        if ticker == wanted:
            return safe_score(
                item.get("final_score")
                or item.get("score")
                or item.get("smart_money_score")
                or item.get("total_score")
            )

    return 0.0


def get_recent_symbol_frequency(memory: dict, symbol: str) -> int:
    wanted = normalize_symbol(symbol)
    count = 0

    for day in memory.get("days", [])[-10:]:
        for item in day.get("selected_symbols", []) or []:
            if normalize_symbol(item) == wanted:
                count += 1

    return count


def get_recent_theme_frequency(memory: dict, theme: str) -> int:
    wanted = str(theme or "").strip()
    count = 0

    for day in memory.get("days", [])[-10:]:
        if wanted in (day.get("themes") or []):
            count += 1

    return count


def score_candidate_symbol(
    symbol: str,
    active_themes: list[str],
    manual_symbols: list[str],
    scores: list[dict],
    memory: dict,
) -> float:
    clean_symbol = normalize_symbol(symbol)

    if not clean_symbol:
        return -999

    score = 0.0

    if clean_symbol in [normalize_symbol(item) for item in manual_symbols]:
        score += 100

    if clean_symbol in CORE_PORTFOLIO_TICKERS:
        score += 35

    smart_money_score = get_score_for_symbol(scores, clean_symbol)

    if smart_money_score:
        score += min(smart_money_score, 100) * 0.55

    for theme in active_themes:
        theme_symbols = [normalize_symbol(item) for item in THEME_TICKERS.get(theme, [])]

        if clean_symbol in theme_symbols:
            score += 30
            score += min(get_recent_theme_frequency(memory, theme), 5) * 4

    recent_symbol_frequency = get_recent_symbol_frequency(memory, clean_symbol)

    if recent_symbol_frequency >= 5:
        score += 8
    elif recent_symbol_frequency == 0 and clean_symbol not in [normalize_symbol(item) for item in manual_symbols]:
        score -= 4

    return score


def build_candidate_pool(
    manual_symbols: list[str],
    active_themes: list[str],
) -> list[str]:
    candidates = []

    for symbol in manual_symbols or []:
        clean_symbol = normalize_symbol(symbol)

        if clean_symbol and clean_symbol not in candidates:
            candidates.append(clean_symbol)

    for theme in active_themes:
        for symbol in THEME_TICKERS.get(theme, []):
            clean_symbol = normalize_symbol(symbol)

            if clean_symbol and clean_symbol not in candidates:
                candidates.append(clean_symbol)

    for symbol in CORE_PORTFOLIO_TICKERS:
        clean_symbol = normalize_symbol(symbol)

        if clean_symbol and clean_symbol not in candidates:
            candidates.append(clean_symbol)

    return candidates


def build_evolved_watchlist_universe(
    manual_symbols: list[str] | None = None,
    context: dict | None = None,
    scores: list[dict] | None = None,
    max_symbols: int = MAX_RESEARCH_UNIVERSE,
) -> list[str]:
    manual_symbols = manual_symbols or []
    scores = scores or []
    active_themes = extract_active_themes(context)
    memory = load_watchlist_evolution_memory()

    candidates = build_candidate_pool(manual_symbols, active_themes)

    ranked = sorted(
        candidates,
        key=lambda symbol: score_candidate_symbol(
            symbol=symbol,
            active_themes=active_themes,
            manual_symbols=manual_symbols,
            scores=scores,
            memory=memory,
        ),
        reverse=True,
    )

    selected = []

    for symbol in ranked:
        clean_symbol = normalize_symbol(symbol)

        if clean_symbol and clean_symbol not in selected:
            selected.append(clean_symbol)

        if len(selected) >= max_symbols:
            break

    return selected[:max_symbols]


def record_watchlist_evolution_day(
    selected_symbols: list[str],
    context: dict | None = None,
) -> None:
    memory = load_watchlist_evolution_memory()
    active_themes = extract_active_themes(context)

    today_key = time.strftime("%Y-%m-%d")

    days = [
        day
        for day in memory.get("days", [])
        if day.get("date") != today_key
    ]

    days.append(
        {
            "date": today_key,
            "themes": active_themes,
            "selected_symbols": [
                normalize_symbol(symbol)
                for symbol in selected_symbols
                if normalize_symbol(symbol)
            ][:MAX_RESEARCH_UNIVERSE],
        }
    )

    memory["days"] = days[-MAX_MEMORY_DAYS:]

    save_watchlist_evolution_memory(memory)