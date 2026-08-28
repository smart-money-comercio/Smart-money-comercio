from typing import Any

from src.intelligence.news_evolution import (
    load_news_memory,
    theme_persistence,
)
from src.intelligence.news_live_sources import fetch_news_live_context


NEWS_ALERT_THEMES = {
    "Rates / Yields": {
        "trigger": "Macro alert: rates/yields pressure active.",
        "impact": "High-multiple growth and long-duration assets need confirmation.",
    },
    "Treasury / Debt": {
        "trigger": "Macro alert: Treasury/debt pressure active.",
        "impact": "Liquidity, duration, and valuation sensitivity are elevated.",
    },
    "Fed / Policy": {
        "trigger": "Macro alert: Fed/policy pressure active.",
        "impact": "Watch rate expectations, dollar pressure, and risk appetite.",
    },
    "Oil / Energy": {
        "trigger": "Macro alert: oil/energy pressure active.",
        "impact": "Inflation and consumer-margin pressure may rise.",
    },
    "Geopolitical Risk": {
        "trigger": "Macro alert: geopolitical risk active.",
        "impact": "Favor quality, defense, energy hedges, and risk controls.",
    },
    "China / Trade": {
        "trigger": "Macro alert: China/trade pressure active.",
        "impact": "Watch semis, mega-cap tech, industrials, and global cyclicals.",
    },
    "AI / Semiconductors": {
        "trigger": "Sector alert: AI/semiconductor headline cluster active.",
        "impact": "Leadership remains important, but validate momentum and valuation.",
    },
    "Mega-Cap Tech": {
        "trigger": "Sector alert: mega-cap tech headline cluster active.",
        "impact": "Index leadership may depend on large-cap growth confirmation.",
    },
    "Consumer / Retail": {
        "trigger": "Macro alert: consumer/retail divergence active.",
        "impact": "Favor earnings quality and resilient demand.",
    },
}


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def latest_news_record() -> dict:
    memory = load_news_memory()
    records = memory.get("records", [])

    if not isinstance(records, list) or not records:
        return {}

    latest = records[-1]

    return latest if isinstance(latest, dict) else {}


def get_recent_news_records(limit: int = 10) -> list[dict]:
    memory = load_news_memory()
    records = memory.get("records", [])

    if not isinstance(records, list):
        return []

    return [record for record in records[-limit:] if isinstance(record, dict)]


def classify_news_alert_level(record: dict, persistent_themes: dict[str, int]) -> str:
    risk_regime = str(record.get("risk_regime", "")).lower()
    news_regime = str(record.get("news_regime", "")).lower()

    top_themes = record.get("top_themes", []) or []

    macro_pressure_count = sum(
        1
        for theme in top_themes
        if theme in {
            "Rates / Yields",
            "Treasury / Debt",
            "Fed / Policy",
            "Oil / Energy",
            "Geopolitical Risk",
            "China / Trade",
        }
    )

    persistent_pressure_count = sum(
        1
        for theme, count in persistent_themes.items()
        if count >= 3
        and theme
        in {
            "Rates / Yields",
            "Treasury / Debt",
            "Fed / Policy",
            "Oil / Energy",
            "Geopolitical Risk",
            "China / Trade",
        }
    )

    if "risk-off" in risk_regime or macro_pressure_count >= 4 or persistent_pressure_count >= 3:
        return "High"

    if "cautious" in risk_regime or macro_pressure_count >= 2 or persistent_pressure_count >= 1:
        return "Medium"

    if "risk-on" in risk_regime:
        return "Low"

    if "rates" in news_regime or "treasury" in news_regime:
        return "Medium"

    return "Normal"


def build_theme_trigger_lines(record: dict, persistent_themes: dict[str, int]) -> list[str]:
    lines = []
    top_themes = record.get("top_themes", []) or []

    for theme in top_themes:
        config = NEWS_ALERT_THEMES.get(theme)

        if not config:
            continue

        persistence_count = safe_int(persistent_themes.get(theme, 0))

        if persistence_count >= 3:
            lines.append(f"{config['trigger']} Persistence: {persistence_count}/10 recent scans.")
        else:
            lines.append(config["trigger"])

    return lines[:8]


def build_theme_impact_lines(record: dict) -> list[str]:
    lines = []
    top_themes = record.get("top_themes", []) or []

    for theme in top_themes:
        config = NEWS_ALERT_THEMES.get(theme)

        if config:
            lines.append(f"{theme}: {config['impact']}")

    return lines[:8]


def build_ticker_pressure_lines(record: dict) -> list[str]:
    tickers = record.get("top_tickers", []) or []
    ticker_counts = record.get("ticker_counts", {}) or {}

    lines = []

    for ticker in tickers[:8]:
        count = safe_int(ticker_counts.get(ticker, 0))
        suffix = f" headline cluster count: {count}" if count else " headline cluster active"
        lines.append(f"{ticker}:{suffix}")

    return lines


def build_news_alert_context(force_refresh: bool = False) -> dict:
    records = get_recent_news_records(limit=10)
    latest = records[-1] if records else {}

    persistent_themes = theme_persistence(records, lookback=10) if records else {}

    live_context = {}

    if force_refresh:
        try:
            live_context = fetch_news_live_context(force_refresh=True)
        except Exception:
            live_context = {}

    if live_context:
        live_themes = live_context.get("themes", {}) or {}
        live_tickers = live_context.get("tickers", {}) or {}

        latest = {
            **latest,
            "news_regime": latest.get("news_regime", "Live news refresh"),
            "risk_regime": latest.get("risk_regime", "Refresh context"),
            "top_themes": list(live_themes.keys())[:10],
            "top_tickers": list(live_tickers.keys())[:10],
            "theme_counts": live_themes,
            "ticker_counts": live_tickers,
            "headline_count": len(live_context.get("items", []) or []),
        }

    alert_level = classify_news_alert_level(latest, persistent_themes) if latest else "Unknown"

    return {
        "latest": latest,
        "records": records,
        "persistent_themes": persistent_themes,
        "alert_level": alert_level,
        "theme_triggers": build_theme_trigger_lines(latest, persistent_themes) if latest else [],
        "theme_impacts": build_theme_impact_lines(latest) if latest else [],
        "ticker_pressure": build_ticker_pressure_lines(latest) if latest else [],
        "live_refreshed": bool(live_context),
    }


def bullet_lines(items: list[str], fallback: str = "• None detected.") -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]

    if not cleaned:
        return fallback

    return "\n".join(f"• {item}" for item in cleaned)


def build_alert_news_overlay(force_refresh: bool = False) -> str:
    context = build_news_alert_context(force_refresh=force_refresh)
    latest = context.get("latest", {})

    if not latest:
        return """
News Intelligence Overlay
Status: No news memory yet.

Run /newsintel first to start the evolving market-news memory.
""".strip()

    persistent_themes = context.get("persistent_themes", {}) or {}
    persistent_lines = [
        f"{theme}: {count}/10 recent scans"
        for theme, count in list(persistent_themes.items())[:8]
        if count >= 2
    ]

    return f"""
News Intelligence Overlay
News Alert Level: {context.get("alert_level", "Unknown")}
News Regime: {latest.get("news_regime", "unknown")}
Risk Regime: {latest.get("risk_regime", "unknown")}
Portfolio Impact: {latest.get("portfolio_impact", "unknown")}
Headlines Tracked: {latest.get("headline_count", 0)}
Live Refresh Used: {"yes" if context.get("live_refreshed") else "no"}

News Alert Triggers
{bullet_lines(context.get("theme_triggers", []), fallback="• No news-triggered alert pressure detected.")}

Persistent News Themes
{bullet_lines(persistent_lines, fallback="• No persistent news themes above threshold yet.")}

Ticker News Pressure
{bullet_lines(context.get("ticker_pressure", []), fallback="• No ticker headline clusters detected.")}

Alert Interpretation
{bullet_lines(context.get("theme_impacts", []), fallback="• No major news impact adjustment required.")}
""".strip()


def build_daily_alert_news_digest(force_refresh: bool = False) -> str:
    context = build_news_alert_context(force_refresh=force_refresh)
    latest = context.get("latest", {})

    if not latest:
        return """
News Overlay: No news memory yet. Run /newsintel to initialize.
""".strip()

    triggers = context.get("theme_triggers", [])[:4]
    tickers = context.get("ticker_pressure", [])[:4]

    return f"""
News Overlay
Level: {context.get("alert_level", "Unknown")}
Regime: {latest.get("news_regime", "unknown")}
Risk: {latest.get("risk_regime", "unknown")}
Impact: {latest.get("portfolio_impact", "unknown")}

News Triggers
{bullet_lines(triggers, fallback="• No major news trigger.")}

Ticker Pressure
{bullet_lines(tickers, fallback="• No ticker news pressure.")}
""".strip()


def build_alertstatus_news_summary() -> str:
    context = build_news_alert_context(force_refresh=False)
    latest = context.get("latest", {})

    if not latest:
        return "News Intelligence: no memory yet. Run /newsintel."

    return (
        f"News Intelligence: {context.get('alert_level')} | "
        f"{latest.get('news_regime', 'unknown')} | "
        f"{latest.get('risk_regime', 'unknown')}"
    )