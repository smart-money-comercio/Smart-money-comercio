from typing import Any

from src.intelligence.ticker_evolution import (
    build_evolution_notes,
    build_memory_summary,
    build_record,
    record_ticker_read,
    safe_float,
)
from src.scoring.scoring_engine import get_stock_scores
from src.reports.tradeplan_snapshot_report import build_tradeplan_snapshot_section
from src.intelligence.stockanalysis_source import (
    build_stockanalysis_rating_section,
    fetch_stockanalysis_data,
)
from src.utils.score_display import (
    get_action_label,
    get_category,
    get_portfolio_fit,
    get_risk_label,
    get_score_story,
    get_signal_strength,
    get_smart_money_label,
    get_ticker,
)


try:
    from src.commands.watchlist_commands import fetch_quotes_for_symbols
except Exception:
    fetch_quotes_for_symbols = None


def clean_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("$", "").strip()


def normalize_score_items(raw_scores: Any) -> list[dict]:
    if isinstance(raw_scores, list):
        return [item for item in raw_scores if isinstance(item, dict)]

    if isinstance(raw_scores, dict):
        if "scores" in raw_scores and isinstance(raw_scores["scores"], list):
            return [item for item in raw_scores["scores"] if isinstance(item, dict)]

        items = []

        for key, value in raw_scores.items():
            if isinstance(value, dict):
                copy = dict(value)
                copy.setdefault("ticker", key)
                copy.setdefault("symbol", key)
                items.append(copy)

        return items

    return []


def get_score_value(score_data: dict) -> float | None:
    for key in [
        "final_score",
        "composite_score",
        "total_score",
        "smart_money_score",
        "overall_score",
        "score",
    ]:
        value = safe_float(score_data.get(key))

        if value is not None:
            return value

    return None


def find_score_data(symbol: str, scores: list[dict]) -> dict:
    symbol = clean_symbol(symbol)

    for item in scores:
        ticker = clean_symbol(get_ticker(item) or item.get("symbol") or item.get("ticker"))

        if ticker == symbol:
            return item

    return {"symbol": symbol, "ticker": symbol}


def get_quote_data(symbol: str) -> dict:
    if fetch_quotes_for_symbols is None:
        return {}

    try:
        quotes = fetch_quotes_for_symbols([symbol])

        if isinstance(quotes, dict):
            return quotes.get(symbol) or quotes.get(symbol.upper()) or {}

    except Exception:
        return {}

    return {}


def get_quote_value(quote: dict, *keys, default=None):
    for key in keys:
        if key in quote:
            return quote.get(key)

    return default


def format_score(score: float | None) -> str:
    if score is None:
        return "Not available"

    return f"{score:.0f} / 100"


def format_price(price: float | None) -> str:
    if price is None:
        return "Unavailable"

    return f"${price:,.2f}"


def format_change(change_percent: float | None) -> str:
    if change_percent is None:
        return "Unavailable"

    sign = "+" if change_percent > 0 else ""
    return f"{sign}{change_percent:.2f}%"


def bullet_lines(items: list[str]) -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]

    if not cleaned:
        return "• No clear signal yet."

    return "\n".join(f"• {item}" for item in cleaned)


def build_why_it_matters(symbol: str, score_data: dict, label: str, category: str) -> str:
    story = ""

    try:
        story = get_score_story(score_data)
    except Exception:
        story = ""

    story = str(story or "").strip()

    if story:
        return story

    if category and category.lower() not in {"unknown", "n/a", "none"}:
        return f"{symbol} is currently classified as {category}, with a {label.lower()} setup."

    return (
        f"{symbol} has enough signal to monitor, but the edge needs confirmation from "
        "score, volume, and catalyst behavior."
    )


def build_watch_items(symbol: str, score_data: dict, score: float | None, risk: str, action: str) -> list[str]:
    items = []

    if score is not None and score >= 80:
        items.append("Confirm the move with volume and leadership persistence.")
    elif score is not None and score >= 65:
        items.append("Watch for confirmation before treating this as high conviction.")
    else:
        items.append("Treat this as watchlist-only unless the score improves.")

    if risk:
        items.append(f"Respect the current risk read: {risk}.")

    if action:
        items.append(f"Current action bias: {action}.")

    items.append("Check earnings, volume, and sector rotation before acting.")

    return items[:4]


def build_action_read(score: float | None, label: str, risk: str, action: str) -> str:
    action_lower = str(action or "").lower()
    risk_lower = str(risk or "").lower()

    if score is not None and score >= 85 and "high" not in risk_lower:
        return "High-quality setup. Favor confirmation and disciplined entries over chasing."

    if score is not None and score >= 75:
        return "Constructive setup, but wait for confirmation from price action, volume, or catalyst support."

    if "avoid" in action_lower or "sell" in action_lower:
        return "Do not force the trade. The current read favors caution."

    if "high" in risk_lower:
        return "Risk is elevated. Use smaller sizing, tighter validation, or wait for a better setup."

    return "Keep it on watch. Demand a stronger catalyst or better technical confirmation before upgrading conviction."


def build_related_commands(symbol: str) -> str:
    return f"""
/tradeplan {symbol}
/tradeplans
/scorecard {symbol}
/volume {symbol}
/earnings {symbol}
/risk {symbol}
/stockdata {symbol}
/tickernews {symbol}
/brief
""".strip()


def build_stockanalysis_fundamentals_section(symbol: str) -> str:
    try:
        data = fetch_stockanalysis_data(symbol, force_refresh=False)
    except Exception:
        return (
            "StockAnalysis Fundamentals\n"
            "• Supplemental fundamentals unavailable."
        )

    metrics = data.get("metrics", {})

    if not data.get("available") or not metrics:
        return (
            "StockAnalysis Fundamentals\n"
            "• Supplemental fundamentals unavailable."
        )

    def line(key: str, label: str) -> str:
        value = metrics.get(key)

        if not value:
            return ""

        return f"• {label}: {value}"

    lines = [
        "StockAnalysis Fundamentals",
        line("market_cap", "Market Cap"),
        line("pe_ratio", "P/E"),
        line("forward_pe", "Forward P/E"),
        line("revenue", "Revenue"),
        line("net_income", "Net Income"),
        line("free_cash_flow", "Free Cash Flow"),
        line("total_debt", "Total Debt"),
        line("cash_and_equivalents", "Cash & Equivalents"),
    ]

    clean_lines = [item for item in lines if str(item or "").strip()]

    if len(clean_lines) <= 1:
        clean_lines.append("• Supplemental fundamentals unavailable.")

    return "\n".join(clean_lines)


def build_stockanalysis_rating_read(symbol: str) -> str:
    try:
        section = build_stockanalysis_rating_section(symbol, force_refresh=False)
    except Exception:
        return (
            "StockAnalysis Analyst Rating\n"
            "• External analyst consensus unavailable."
        )

    lines = section.splitlines()
    selected = []

    keep_headers = {
        "External Analyst Consensus",
        "Buy / Hold / Sell Mix",
        "Interpretation",
    }

    for line in lines:
        clean = line.strip()

        if clean in keep_headers:
            selected.append(line)
        elif clean.startswith("• Consensus:"):
            selected.append(line)
        elif clean.startswith("• Price Target:"):
            selected.append(line)
        elif clean.startswith("• Implied"):
            selected.append(line)
        elif clean.startswith("• Strong Buy:"):
            selected.append(line)
        elif clean.startswith("• Buy:"):
            selected.append(line)
        elif clean.startswith("• Hold:"):
            selected.append(line)
        elif clean.startswith("• Sell:"):
            selected.append(line)
        elif clean.startswith("• Strong Sell:"):
            selected.append(line)
        elif clean.startswith("• Analyst setup"):
            selected.append(line)

    if not selected:
        return (
            "StockAnalysis Analyst Rating\n"
            "• External analyst consensus unavailable."
        )

    return "StockAnalysis Analyst Rating\n" + "\n".join(selected)


def build_stock_intelligence_report(symbol: str) -> str:
    symbol = clean_symbol(symbol)

    if not symbol:
        return "Usage: /stock SYMBOL"

    try:
        raw_scores = get_stock_scores()
    except Exception:
        raw_scores = []

    scores = normalize_score_items(raw_scores)
    score_data = find_score_data(symbol, scores)

    score = get_score_value(score_data)

    try:
        label = get_smart_money_label(score_data)
    except Exception:
        label = "Signal developing"

    try:
        signal = get_signal_strength(score_data)
    except Exception:
        signal = label

    try:
        risk = get_risk_label(score_data)
    except Exception:
        risk = "Unknown"

    try:
        action = get_action_label(score_data)
    except Exception:
        action = "Watch"

    try:
        category = get_category(score_data)
    except Exception:
        category = "Uncategorized"

    try:
        fit = get_portfolio_fit(score_data)
    except Exception:
        fit = "Unknown"

    quote = get_quote_data(symbol)

    price = safe_float(
        get_quote_value(
            quote,
            "price",
            "current_price",
            "regularMarketPrice",
            "last",
            "close",
        )
    )

    change_percent = safe_float(
        get_quote_value(
            quote,
            "change_percent",
            "percent_change",
            "regularMarketChangePercent",
            "changePercent",
        )
    )

    record = build_record(
        symbol=symbol,
        score=score,
        label=label,
        risk=risk,
        action=action,
        category=category,
        signal=signal,
        price=price,
        change_percent=change_percent,
    )

    evolution = record_ticker_read(symbol, record)
    notes = build_evolution_notes(evolution.get("previous"), evolution.get("current"))

    why_it_matters = build_why_it_matters(symbol, score_data, label, category)
    watch_items = build_watch_items(symbol, score_data, score, risk, action)
    action_read = build_action_read(score, label, risk, action)
    memory_summary = build_memory_summary(symbol)

    stockanalysis_fundamentals = build_stockanalysis_fundamentals_section(symbol)
    stockanalysis_rating = build_stockanalysis_rating_read(symbol)
    tradeplan_snapshot = build_tradeplan_snapshot_section(symbol)

    return f"""
📈 {symbol} Stock Intelligence

Signal: {label}
Score: {format_score(score)}
Conviction: {signal}
Risk: {risk}
Action: {action}
Portfolio Fit: {fit}

Live Tape
Price: {format_price(price)}
Change: {format_change(change_percent)}

{stockanalysis_fundamentals}

{stockanalysis_rating}

Why It Matters
{why_it_matters}

What Changed
{bullet_lines(notes)}

Evolving Read
{memory_summary}

What Smart Money Should Watch
{bullet_lines(watch_items)}

Action Read
{action_read}

{tradeplan_snapshot}

Related Commands:
{build_related_commands(symbol)}

Research only. Not financial advice.
""".strip()