import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


MEMORY_FILE = Path(os.getenv("NEWS_INTELLIGENCE_MEMORY_FILE", "data/news_intelligence_memory.json"))
TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
MAX_RECORDS = int(os.getenv("NEWS_INTELLIGENCE_MAX_RECORDS", "120"))


def now_text() -> str:
    try:
        current = datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        current = datetime.now()

    return current.strftime("%Y-%m-%d %H:%M:%S")


def load_news_memory() -> dict:
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


def save_news_memory(memory: dict) -> None:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        memory["updated_at"] = now_text()

        with MEMORY_FILE.open("w", encoding="utf-8") as file:
            json.dump(memory, file, indent=2, sort_keys=True)

    except Exception:
        return


def top_keys(counts: dict[str, int], limit: int = 8) -> list[str]:
    if not isinstance(counts, dict):
        return []

    return [
        key
        for key, _value in sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:limit]
    ]


def build_news_record(
    context: dict,
    news_regime: str,
    risk_regime: str,
    portfolio_impact: str,
    alert_triggers: list[str],
    mode: str = "all",
    symbol: str = "",
) -> dict:
    themes = context.get("themes", {}) if isinstance(context, dict) else {}
    tickers = context.get("tickers", {}) if isinstance(context, dict) else {}

    return {
        "checked_at": now_text(),
        "mode": mode,
        "symbol": symbol,
        "fingerprint": context.get("fingerprint", ""),
        "news_regime": news_regime,
        "risk_regime": risk_regime,
        "portfolio_impact": portfolio_impact,
        "top_themes": top_keys(themes, 10),
        "top_tickers": top_keys(tickers, 10),
        "theme_counts": themes,
        "ticker_counts": tickers,
        "alert_triggers": alert_triggers[:10],
        "headline_count": len(context.get("items", []) or []),
    }


def record_news_scan(record: dict) -> dict:
    memory = load_news_memory()
    records = memory.setdefault("records", [])

    if not isinstance(records, list):
        records = []
        memory["records"] = records

    previous = records[-1] if records else None

    # Avoid duplicate learning when /headlines and /newsintel run
    # against the same headline set.
    if previous and previous.get("fingerprint") == record.get("fingerprint") and previous.get("mode") == record.get("mode"):
        return {
            "previous": previous,
            "current": previous,
            "records": records,
            "deduped": True,
        }

    records.append(record)
    memory["records"] = records[-MAX_RECORDS:]
    save_news_memory(memory)

    return {
        "previous": previous,
        "current": record,
        "records": memory["records"],
        "deduped": False,
    }


def list_delta(previous_items: list[str], current_items: list[str]) -> tuple[list[str], list[str], list[str]]:
    previous_set = set(previous_items or [])
    current_set = set(current_items or [])

    new_items = [item for item in current_items if item not in previous_set]
    fading_items = [item for item in previous_items if item not in current_set]
    persistent_items = [item for item in current_items if item in previous_set]

    return new_items, fading_items, persistent_items


def build_news_change_notes(previous: dict | None, current: dict) -> list[str]:
    if not previous:
        return ["First tracked news intelligence scan."]

    notes = []

    if previous.get("news_regime") != current.get("news_regime"):
        notes.append(
            f"News regime changed from {previous.get('news_regime', 'unknown')} to {current.get('news_regime', 'unknown')}."
        )

    if previous.get("risk_regime") != current.get("risk_regime"):
        notes.append(
            f"Risk regime changed from {previous.get('risk_regime', 'unknown')} to {current.get('risk_regime', 'unknown')}."
        )

    new_themes, fading_themes, persistent_themes = list_delta(
        previous.get("top_themes", []),
        current.get("top_themes", []),
    )

    if new_themes:
        notes.append("New themes: " + ", ".join(new_themes[:5]) + ".")

    if fading_themes:
        notes.append("Fading themes: " + ", ".join(fading_themes[:5]) + ".")

    if persistent_themes:
        notes.append("Persistent themes: " + ", ".join(persistent_themes[:5]) + ".")

    new_tickers, fading_tickers, persistent_tickers = list_delta(
        previous.get("top_tickers", []),
        current.get("top_tickers", []),
    )

    if new_tickers:
        notes.append("New ticker clusters: " + ", ".join(new_tickers[:6]) + ".")

    if persistent_tickers:
        notes.append("Persistent ticker clusters: " + ", ".join(persistent_tickers[:6]) + ".")

    if previous.get("alert_triggers") != current.get("alert_triggers"):
        notes.append("Alert triggers changed.")

    return notes[:9] or ["No major memory change from the prior scan."]


def theme_persistence(records: list[dict], lookback: int = 10) -> dict[str, int]:
    counts = {}

    for record in records[-lookback:]:
        for theme in record.get("top_themes", []) or []:
            counts[theme] = counts.get(theme, 0) + 1

    return dict(sorted(counts.items(), key=lambda pair: pair[1], reverse=True))


def build_news_memory_summary() -> str:
    memory = load_news_memory()
    records = memory.get("records", [])

    if not isinstance(records, list) or not records:
        return "No news memory yet. Run /newsintel to start the evolving record."

    latest = records[-1]
    persistence = theme_persistence(records, lookback=10)
    persistent = [theme for theme, count in persistence.items() if count >= 3]

    lines = [
        f"Tracked Scans: {len(records)}",
        f"Latest News Regime: {latest.get('news_regime', 'unknown')}",
        f"Latest Risk Regime: {latest.get('risk_regime', 'unknown')}",
        f"Latest Portfolio Impact: {latest.get('portfolio_impact', 'unknown')}",
        "Persistent Themes: " + (", ".join(persistent[:8]) if persistent else "None yet"),
    ]

    return "\n".join(lines)


def build_news_memory_report() -> str:
    memory = load_news_memory()
    records = memory.get("records", [])

    if not isinstance(records, list) or not records:
        return """
🧠 News Memory

Status: No news memory yet.

Run:
/newsintel
/macronews
/headlines

Research only. Not financial advice.
""".strip()

    latest = records[-1]
    persistence = theme_persistence(records, lookback=10)
    persistent_lines = [
        f"• {theme}: {count}/10 recent scans"
        for theme, count in list(persistence.items())[:10]
    ]

    if not persistent_lines:
        persistent_lines = ["• No persistent themes yet."]

    return f"""
🧠 News Memory

Summary
{build_news_memory_summary()}

Latest Scan
Checked: {latest.get("checked_at", "unknown")}
Mode: {latest.get("mode", "all")}
News Regime: {latest.get("news_regime", "unknown")}
Risk Regime: {latest.get("risk_regime", "unknown")}
Headlines: {latest.get("headline_count", 0)}

Latest Themes
{chr(10).join("• " + theme for theme in latest.get("top_themes", [])[:10])}

Latest Ticker Clusters
{chr(10).join("• " + ticker for ticker in latest.get("top_tickers", [])[:10])}

Persistence
{chr(10).join(persistent_lines)}

Alert Triggers
{chr(10).join("• " + trigger for trigger in latest.get("alert_triggers", [])[:10]) or "• None"}

Research only. Not financial advice.
""".strip()