from src.intelligence.news_evolution import (
    build_news_change_notes,
    build_news_memory_report,
    build_news_memory_summary,
    build_news_record,
    record_news_scan,
)
from src.intelligence.news_live_sources import (
    clean_symbol,
    fetch_news_live_context,
    filter_items_for_symbol,
    format_source_status,
)


MACRO_THEMES = {
    "Rates / Yields",
    "Fed / Policy",
    "Treasury / Debt",
    "Oil / Energy",
    "Geopolitical Risk",
    "China / Trade",
    "Crypto / Liquidity",
}


def bullet_lines(items: list[str], fallback: str = "• No detail available.") -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]

    if not cleaned:
        return fallback

    return "\n".join(f"• {item}" for item in cleaned)


def top_theme_lines(themes: dict[str, int], limit: int = 8) -> str:
    if not themes:
        return "• No themes detected."

    return "\n".join(
        f"• {theme}: {count}"
        for theme, count in list(themes.items())[:limit]
    )


def headline_lines(items: list[dict], limit: int = 8) -> str:
    if not items:
        return "• No headlines available."

    lines = []

    for item in items[:limit]:
        themes = ", ".join(item.get("themes", [])[:3]) or "untagged"
        source = item.get("source", "Unknown")
        title = item.get("title", "Untitled")
        lines.append(f"• {title} — {source} [{themes}]")

    return "\n".join(lines)


def ticker_lines(tickers: dict[str, int], limit: int = 8) -> str:
    if not tickers:
        return "• No ticker clusters detected."

    return "\n".join(
        f"• {ticker}: {count}"
        for ticker, count in list(tickers.items())[:limit]
    )


def determine_news_regime(themes: dict[str, int]) -> str:
    if not themes:
        return "Quiet / low signal"

    if themes.get("Rates / Yields", 0) + themes.get("Treasury / Debt", 0) >= 3:
        return "Rates / Treasury pressure"

    if themes.get("Fed / Policy", 0) >= 3:
        return "Fed / policy pressure"

    if themes.get("Oil / Energy", 0) + themes.get("Geopolitical Risk", 0) >= 3:
        return "Oil / geopolitical pressure"

    if themes.get("China / Trade", 0) >= 2:
        return "China / trade pressure"

    if themes.get("AI / Semiconductors", 0) + themes.get("Mega-Cap Tech", 0) >= 3:
        return "Growth / AI leadership"

    if themes.get("Consumer / Retail", 0) >= 2:
        return "Consumer watch"

    return list(themes.keys())[0]


def determine_risk_regime(themes: dict[str, int]) -> str:
    risk_score = 0

    risk_score += themes.get("Rates / Yields", 0)
    risk_score += themes.get("Treasury / Debt", 0)
    risk_score += themes.get("Oil / Energy", 0)
    risk_score += themes.get("Geopolitical Risk", 0)
    risk_score += themes.get("China / Trade", 0)

    growth_score = themes.get("AI / Semiconductors", 0) + themes.get("Mega-Cap Tech", 0)

    if risk_score >= 6:
        return "Risk-off / macro pressure"

    if risk_score >= 3:
        return "Cautious"

    if growth_score >= 3 and risk_score <= 2:
        return "Risk-on / growth leadership"

    return "Balanced / mixed"


def determine_portfolio_impact(news_regime: str, risk_regime: str, themes: dict[str, int]) -> str:
    regime = f"{news_regime} {risk_regime}".lower()

    if "risk-off" in regime or "rates" in regime or "treasury" in regime:
        return "Risk-control watch; require confirmation for high-multiple growth."

    if "oil" in regime or "geopolitical" in regime:
        return "Macro hedge watch; energy, defense, and quality balance matter."

    if "growth" in regime or themes.get("AI / Semiconductors", 0) >= 3:
        return "Growth leadership constructive, but validate valuation and volume."

    if themes.get("Consumer / Retail", 0) >= 2:
        return "Consumer divergence watch; favor quality earnings and resilient demand."

    return "Balanced posture; use /portfolio and /alerts for positioning confirmation."


def build_alert_triggers(themes: dict[str, int], tickers: dict[str, int], risk_regime: str) -> list[str]:
    triggers = []

    if "risk-off" in risk_regime.lower() or "cautious" in risk_regime.lower():
        triggers.append("Macro alert: risk regime is cautious or risk-off.")

    if themes.get("Rates / Yields", 0) >= 2:
        triggers.append("Theme alert: rates/yields pressure active.")

    if themes.get("Treasury / Debt", 0) >= 2:
        triggers.append("Theme alert: Treasury/debt pressure active.")

    if themes.get("Oil / Energy", 0) >= 2 or themes.get("Geopolitical Risk", 0) >= 2:
        triggers.append("Theme alert: oil/geopolitical pressure active.")

    if themes.get("China / Trade", 0) >= 2:
        triggers.append("Theme alert: China/trade pressure active.")

    if themes.get("AI / Semiconductors", 0) >= 2:
        triggers.append("Sector alert: AI/semiconductor cluster active.")

    for ticker, count in list(tickers.items())[:5]:
        if count >= 2:
            triggers.append(f"Ticker alert: {ticker} headline cluster active.")

    return triggers[:10]


def macro_filtered_context(context: dict) -> dict:
    items = []

    for item in context.get("items", []) or []:
        item_themes = set(item.get("themes", []) or [])

        if item_themes & MACRO_THEMES:
            items.append(item)

    themes = {}

    for item in items:
        for theme in item.get("themes", []) or []:
            if theme in MACRO_THEMES:
                themes[theme] = themes.get(theme, 0) + 1

    tickers = {}

    for item in items:
        for ticker in item.get("tickers", []) or []:
            tickers[ticker] = tickers.get(ticker, 0) + 1

    copy = dict(context)
    copy["items"] = items
    copy["top_items"] = items[:20]
    copy["themes"] = dict(sorted(themes.items(), key=lambda pair: pair[1], reverse=True))
    copy["tickers"] = dict(sorted(tickers.items(), key=lambda pair: pair[1], reverse=True))
    return copy


def ticker_filtered_context(context: dict, symbol: str) -> dict:
    items = filter_items_for_symbol(context.get("items", []) or [], symbol)

    themes = {}
    tickers = {}

    for item in items:
        for theme in item.get("themes", []) or []:
            themes[theme] = themes.get(theme, 0) + 1

        for ticker in item.get("tickers", []) or []:
            tickers[ticker] = tickers.get(ticker, 0) + 1

    copy = dict(context)
    copy["items"] = items
    copy["top_items"] = items[:20]
    copy["themes"] = dict(sorted(themes.items(), key=lambda pair: pair[1], reverse=True))
    copy["tickers"] = dict(sorted(tickers.items(), key=lambda pair: pair[1], reverse=True))
    return copy


def build_headlines_report(force_refresh: bool = False) -> str:
    context = fetch_news_live_context(force_refresh=force_refresh)
    themes = context.get("themes", {})
    tickers = context.get("tickers", {})

    return f"""
📰 Market Headlines

Top Headlines
{headline_lines(context.get("top_items", []), limit=10)}

Theme Snapshot
{top_theme_lines(themes, limit=8)}

Ticker Clusters
{ticker_lines(tickers, limit=8)}

Sources
{format_source_status(context)}

Next Commands
• /newsintel
• /macronews
• /alerts
• /dailyalerts
• /portfolio

Research only. Not financial advice.
""".strip()


def build_news_intelligence_report(
    force_refresh: bool = False,
    mode: str = "all",
    symbol: str = "",
    record_memory: bool = True,
) -> str:
    context = fetch_news_live_context(force_refresh=force_refresh)

    mode = str(mode or "all").lower().strip()
    symbol = clean_symbol(symbol)

    if mode == "macro":
        context = macro_filtered_context(context)

    elif mode == "ticker":
        context = ticker_filtered_context(context, symbol)

    themes = context.get("themes", {})
    tickers = context.get("tickers", {})

    news_regime = determine_news_regime(themes)
    risk_regime = determine_risk_regime(themes)
    portfolio_impact = determine_portfolio_impact(news_regime, risk_regime, themes)
    alert_triggers = build_alert_triggers(themes, tickers, risk_regime)

    evolution = {"previous": None, "current": None, "deduped": False}

    if record_memory:
        record = build_news_record(
            context=context,
            news_regime=news_regime,
            risk_regime=risk_regime,
            portfolio_impact=portfolio_impact,
            alert_triggers=alert_triggers,
            mode=mode,
            symbol=symbol,
        )
        evolution = record_news_scan(record)

    change_notes = build_news_change_notes(
        evolution.get("previous"),
        evolution.get("current") or {},
    )

    title = "Market News Intelligence"

    if mode == "macro":
        title = "Macro News Intelligence"

    elif mode == "ticker":
        title = f"{symbol} Ticker News Intelligence"

    return f"""
🧠 {title}

Executive Read
News Regime: {news_regime}
Risk Regime: {risk_regime}
Portfolio Impact: {portfolio_impact}
Headlines Reviewed: {len(context.get("items", []) or [])}
Memory Update: {"deduped" if evolution.get("deduped") else "recorded"}

Top News Signals
{top_theme_lines(themes, limit=8)}

Top Headlines
{headline_lines(context.get("top_items", []), limit=8)}

Ticker Clusters
{ticker_lines(tickers, limit=8)}

What Changed
{bullet_lines(change_notes)}

Evolving Read
{build_news_memory_summary()}

Portfolio Impact
• {portfolio_impact}

Alert Triggers
{bullet_lines(alert_triggers, fallback="• No major alert triggers detected.")}

Sources
{format_source_status(context)}

Next Commands
• /headlines
• /global
• /alerts
• /dailyalerts
• /portfolio
{f"• /stock {symbol}" if symbol else "• /tickernews NVDA"}
{f"• /stockdata {symbol}" if symbol else "• /stockdata NVDA"}

Research only. Not financial advice.
""".strip()


def build_macro_news_report(force_refresh: bool = False) -> str:
    return build_news_intelligence_report(
        force_refresh=force_refresh,
        mode="macro",
        symbol="",
        record_memory=True,
    )


def build_ticker_news_report(symbol: str, force_refresh: bool = False) -> str:
    symbol = clean_symbol(symbol)

    if not symbol:
        return "Usage: /tickernews SYMBOL"

    return build_news_intelligence_report(
        force_refresh=force_refresh,
        mode="ticker",
        symbol=symbol,
        record_memory=True,
    )


def build_newsmemory_report() -> str:
    return build_news_memory_report()