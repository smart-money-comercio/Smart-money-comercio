"""Build the Daily Brief's research watchlist and save its selection reasons."""

from contextlib import suppress
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from threading import RLock

from src.config.special_alerts import settings
from src.config.theme_watchlist_universe import (
    CORE_DEFENSE_RESEARCH, CORE_PORTFOLIO_TICKERS, THEME_TICKERS, normalize_symbol,
)
from src.intelligence.company_focus import issuer
from src.intelligence.special_alert_sources import NY, company_url, timestamp
from src.intelligence.special_alert_universe import SYMBOL
from src.utils.yahoo_quote import finite_number


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WATCHLIST_EVOLUTION_FILE = PROJECT_ROOT / "data" / "watchlist_evolution_memory.json"
MAX_MEMORY_DAYS = 30
MAX_RESEARCH_UNIVERSE = 20
MAX_EARNINGS_ADDITIONS = 2
RANKED_ADDITIONS = 2
MAX_MEMORY_BYTES = 500_000
LOCK = RLock()


def memory_path() -> Path:
    return Path(os.getenv("WATCHLIST_EVOLUTION_MEMORY_FILE") or WATCHLIST_EVOLUTION_FILE)


def load_watchlist_evolution_memory() -> dict:
    try:
        with memory_path().open("rb") as file:
            raw = file.read(MAX_MEMORY_BYTES + 1)
        if len(raw) <= MAX_MEMORY_BYTES:
            data = json.loads(raw)
            days = data.get("days", []) if isinstance(data, dict) else []
            if isinstance(days, list):
                return {"days": [day for day in days if isinstance(day, dict) and isinstance(day.get("date"), str)]}
    except (OSError, ValueError):
        pass
    return {"days": []}


def save_watchlist_evolution_memory(memory: dict) -> None:
    path = memory_path()
    pending = None
    try:
        body = json.dumps({"days": memory.get("days", [])[-MAX_MEMORY_DAYS:]}, indent=2, sort_keys=True)
        if len(body.encode()) > MAX_MEMORY_BYTES:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
            pending = Path(out.name)
            out.write(body)
        os.replace(pending, path)
        pending = None
    except OSError:
        pass
    finally:
        if pending is not None:
            with suppress(OSError):
                pending.unlink(missing_ok=True)


def extract_active_themes(context: dict | None) -> list[str]:
    themes = context.get("headline_themes", []) if isinstance(context, dict) else []
    return list(dict.fromkeys(theme for theme in themes or [] if isinstance(theme, str) and theme in THEME_TICKERS))


def ranked_scores(scores: list[dict] | None) -> dict[str, float]:
    values = {}
    for row in scores or []:
        if not isinstance(row, dict):
            continue
        symbol = normalize_symbol(row.get("ticker") or row.get("symbol") or row.get("name"))
        if symbol == "UNKNOWN" or not SYMBOL.fullmatch(symbol):
            continue
        for field in ("final_score", "score", "smart_money_score", "total_score"):
            value = finite_number(row.get(field))
            if value is not None and 0 <= value <= 100:
                values[symbol] = max(value, values.get(symbol, value))
                break
    return dict(sorted(values.items(), key=lambda item: (-item[1], item[0])))


def confirmed_earnings(now: datetime, symbols: list[str]) -> dict:
    from src.intelligence.company_schedule import cached_notices

    try:
        notices = cached_notices(now, symbols)
    except (OSError, ValueError, TypeError, KeyError):
        return {}
    due = []
    allowed = set(symbols)
    for notice in notices:
        at = timestamp(notice["event_at"])
        if notice["symbol"] in allowed and at is not None and now <= at <= now + timedelta(days=4):
            due.append((at, notice["symbol"], notice))
    result = {}
    for _, symbol, notice in sorted(due, key=lambda item: (item[0], item[1])):
        result.setdefault(issuer(symbol), {
            "symbol": symbol,
            "date": notice["event_date"],
            "event": notice["event"],
            "url": notice["source"]["url"],
        })
    return result


def build_watchlist_selection(
    manual_symbols: list[str] | None = None, context: dict | None = None,
    scores: list[dict] | None = None, max_symbols: int = MAX_RESEARCH_UNIVERSE,
    *, now: datetime | None = None,
) -> list[dict]:
    """Prioritize explicit symbols, coverage, dated issuer events, and model leaders."""
    if max_symbols <= 0:
        return []
    now = now or datetime.now(timezone.utc)
    manual = list(dict.fromkeys(normalize_symbol(symbol) for symbol in manual_symbols or [] if isinstance(symbol, str)))
    manual = [symbol for symbol in manual if symbol]
    coverage = {**CORE_DEFENSE_RESEARCH}
    for symbol in settings()["symbols"]:
        coverage.setdefault(symbol, "Core company coverage")
    themes = extract_active_themes(context)
    ranked = ranked_scores(scores)
    theme_symbols = [symbol for theme in themes for symbol in THEME_TICKERS[theme]]
    candidates = list(dict.fromkeys([*manual, *coverage, *ranked, *CORE_PORTFOLIO_TICKERS, *theme_symbols]))
    earnings = confirmed_earnings(now, candidates)
    rows, selected, represented = [], set(), set()

    def add(symbol, reason, *, pinned=False):
        company = issuer(symbol)
        if len(rows) >= max_symbols or symbol in selected or (company in represented and not pinned):
            return False
        row = {"symbol": symbol, "reason": reason}
        if company in earnings:
            row["earnings"] = earnings[company]
        rows.append(row)
        selected.add(symbol)
        represented.add(company)
        return True

    for symbol in manual:
        add(symbol, "Saved symbol", pinned=True)
    for symbol, reason in coverage.items():
        add(symbol, reason)

    added = 0
    for event in earnings.values():
        if added == MAX_EARNINGS_ADDITIONS or len(rows) == max_symbols:
            break
        if add(event["symbol"], "Upcoming issuer-confirmed earnings"):
            added += 1

    added = 0
    for symbol, value in ranked.items():
        if added == RANKED_ADDITIONS or len(rows) == max_symbols:
            break
        if add(symbol, f"Model score {value:.1f}/100"):
            added += 1

    for theme in themes:
        options = sorted(THEME_TICKERS[theme], key=lambda symbol: -ranked.get(symbol, -1))
        for symbol in options:
            if add(symbol, f"Active theme · {theme}"):
                break
    for symbol in CORE_PORTFOLIO_TICKERS:
        add(symbol, "Core research coverage")
    for symbol, value in ranked.items():
        add(symbol, f"Model score {value:.1f}/100")

    return rows


def build_evolved_watchlist_universe(
    manual_symbols: list[str] | None = None, context: dict | None = None,
    scores: list[dict] | None = None, max_symbols: int = MAX_RESEARCH_UNIVERSE,
) -> list[str]:
    return [row["symbol"] for row in build_watchlist_selection(manual_symbols, context, scores, max_symbols)]


def record_watchlist_evolution_day(
    selected_symbols: list[str], context: dict | None = None, *, now: datetime | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(NY).date().isoformat()
    symbols = [normalize_symbol(symbol) for symbol in selected_symbols][:MAX_RESEARCH_UNIVERSE]
    row = {"date": today, "built_at": now.astimezone(timezone.utc).isoformat(),
           "themes": extract_active_themes(context), "selected_symbols": symbols}
    selection = context.get("_watchlist_selection", []) if isinstance(context, dict) else []
    if selection and [entry["symbol"] for entry in selection] == symbols:
        row["selection"] = selection
    with LOCK:
        days = load_watchlist_evolution_memory()["days"]
        for old in days:
            if old["date"] == today and (built := timestamp(old.get("built_at"))) and built > now:
                return
        history = [day for day in days if day["date"] != today] + [row]
        save_watchlist_evolution_memory({"days": sorted(history, key=lambda day: day["date"])})


def build_watchlist_focus_report() -> str:
    days = load_watchlist_evolution_memory()["days"]
    snapshots = [(at, day) for day in days if (at := timestamp(day.get("built_at"))) is not None]
    if not snapshots:
        return "Research watchlist\n\nRun /brief to build the current research watchlist."
    built, latest = max(snapshots, key=lambda snapshot: snapshot[0])
    rows = latest.get("selection")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_RESEARCH_UNIVERSE:
        return "Research watchlist\n\nRun /brief to build the current research watchlist."
    lines = ["Research watchlist", f"Built {built.astimezone(NY):%Y-%m-%d %H:%M %Z} · {len(rows)} symbols", ""]
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) for key in ("symbol", "reason")):
            return "Research watchlist\n\nRun /brief to refresh the watchlist selection."
        line = f"• {row['symbol']} — {row['reason']}"
        if isinstance(event := row.get("earnings"), dict) and all(
            isinstance(event.get(key), str) for key in ("symbol", "date", "event", "url")
        ) and company_url(event["symbol"], event["url"]):
            line += f" · {event['date']} {event['event']}"
            line += "\n  " + event["url"]
        lines.append(line)
    return "\n".join(lines)
