from typing import Any

from src.intelligence.volume_evolution import (
    build_volume_evolution_notes,
    build_volume_memory_summary,
    build_volume_record,
    record_volume_read,
    safe_float,
)
from src.scoring.scoring_engine import get_stock_scores
from src.utils.score_display import (
    get_action_label,
    get_category,
    get_risk_label,
    get_signal_strength,
    get_smart_money_label,
    get_ticker,
    get_volume_label,
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
        "score",
        "total_score",
        "smart_money_score",
        "overall_score",
        "final_score",
        "composite_score",
    ]:
        value = safe_float(score_data.get(key))

        if value is not None:
            return value

    return None


def find_score_data(symbol: str, scores: list[dict]) -> dict:
    symbol = clean_symbol(symbol)

    for item in scores:
        ticker = clean_symbol(
            get_ticker(item) or item.get("symbol") or item.get("ticker")
        )

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
        return "N/A"

    return f"{score:.0f}/100"


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
        return "• No clear volume signal yet."

    return "\n".join(f"• {item}" for item in cleaned)


def is_positive_volume_label(volume_label: str) -> bool:
    text = str(volume_label or "").lower()

    return any(
        term in text
        for term in [
            "strong",
            "high",
            "positive",
            "confirm",
            "accumulation",
            "above",
            "bullish",
            "support",
        ]
    )


def is_weak_volume_label(volume_label: str) -> bool:
    text = str(volume_label or "").lower()

    return any(
        term in text
        for term in [
            "weak",
            "low",
            "thin",
            "unconfirmed",
            "fade",
            "fading",
            "below",
            "poor",
        ]
    )


def build_confirmation_read(
    score: float | None,
    change_percent: float | None,
    volume_label: str,
    risk: str,
    action: str,
) -> str:
    positive_volume = is_positive_volume_label(volume_label)
    weak_volume = is_weak_volume_label(volume_label)
    risk_lower = str(risk or "").lower()

    if (
        positive_volume
        and score is not None
        and score >= 80
        and change_percent is not None
        and change_percent >= 0
    ):
        return "Confirmed / constructive"

    if positive_volume and score is not None and score >= 70:
        return "Partially confirming"

    if weak_volume and change_percent is not None and change_percent > 1:
        return "Price move not fully confirmed"

    if weak_volume:
        return "Weak / unconfirmed"

    if change_percent is not None and change_percent < -1:
        return "Distribution risk"

    if "high" in risk_lower:
        return "Needs confirmation"

    return "Developing / watch"


def build_money_flow_read(
    symbol: str,
    score: float | None,
    change_percent: float | None,
    volume_label: str,
    confirmation: str,
) -> str:
    confirmation_lower = confirmation.lower()

    if "confirmed" in confirmation_lower or "constructive" in confirmation_lower:
        return (
            f"{symbol} has a constructive money-flow read. "
            "The move is more credible if price and volume keep confirming together."
        )

    if "partially" in confirmation_lower:
        return (
            f"{symbol} is showing partial confirmation. "
            "Treat it as promising, but not proven."
        )

    if "not fully confirmed" in confirmation_lower:
        return (
            f"{symbol} may be moving faster than volume support. "
            "Avoid chasing without stronger confirmation."
        )

    if "distribution" in confirmation_lower:
        return f"{symbol} has downside confirmation risk. Weak price action needs extra caution."

    if "weak" in confirmation_lower:
        return f"{symbol} does not have strong money-flow confirmation yet."

    return (
        f"{symbol} has a developing money-flow read. "
        "Use this as confirmation, not a standalone buy/sell signal."
    )


def build_watch_items(
    score: float | None,
    change_percent: float | None,
    volume_label: str,
    risk: str,
    action: str,
    category: str,
) -> list[str]:
    items = []

    if score is not None and score >= 80:
        items.append("Watch whether strong score is backed by volume, not just ranking quality.")
    elif score is not None and score >= 70:
        items.append("Watch for volume confirmation before upgrading conviction.")
    else:
        items.append("Watch for score improvement before treating volume as actionable.")

    if change_percent is not None:
        if change_percent > 1:
            items.append("Price is already moving; avoid chasing if volume confirmation is weak.")
        elif change_percent < -1:
            items.append("Price is under pressure; look for stabilization before acting.")

    if volume_label:
        items.append(f"Volume read: {volume_label}.")

    if risk:
        items.append(f"Risk overlay: {risk}.")

    category_lower = str(category or "").lower()

    if any(term in category_lower for term in ["ai", "chip", "semiconductor", "technology", "growth"]):
        items.append("For AI/growth names, confirm Nasdaq breadth and rate sensitivity.")

    if any(term in category_lower for term in ["defense", "warfare", "aerospace", "military", "munition"]):
        items.append("For defense names, confirm contract/backlog/budget follow-through.")

    if action:
        items.append(f"Current action bias: {action}.")

    return items[:5]


def build_volume_action(
    symbol: str,
    score: float | None,
    confirmation: str,
    risk: str,
    action: str,
) -> str:
    confirmation_lower = confirmation.lower()
    risk_lower = str(risk or "").lower()

    if (
        "confirmed" in confirmation_lower
        and score is not None
        and score >= 80
        and "high" not in risk_lower
    ):
        return (
            f"Volume supports the thesis. Review /stock {symbol} and look for "
            "disciplined entries, not blind chasing."
        )

    if "partially" in confirmation_lower:
        return f"Volume is helping but not decisive. Use /scorecard {symbol} and wait for stronger confirmation."

    if "not fully confirmed" in confirmation_lower:
        return "Do not chase the move. Wait for volume-backed continuation or a cleaner pullback."

    if "distribution" in confirmation_lower or "weak" in confirmation_lower:
        return "Money flow is not confirming. Treat as watchlist-only until price and volume improve."

    return f"Keep monitoring. Current action bias: {action or 'Watch'}."


def build_related_commands(symbol: str) -> str:
    return f"""
/stock {symbol}
/scorecard {symbol}
/risk {symbol}
/earnings {symbol}
/top10
""".strip()


def build_volume_intelligence_report(symbol: str) -> str:
    symbol = clean_symbol(symbol)

    if not symbol:
        return "Usage: /volume SYMBOL"

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
        volume_label = get_volume_label(score_data)
    except Exception:
        volume_label = "Volume confirmation unavailable"

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

    confirmation = build_confirmation_read(
        score=score,
        change_percent=change_percent,
        volume_label=volume_label,
        risk=risk,
        action=action,
    )

    record = build_volume_record(
        symbol=symbol,
        score=score,
        price=price,
        change_percent=change_percent,
        volume_label=volume_label,
        action=action,
        risk=risk,
        signal=signal,
        confirmation=confirmation,
    )

    evolution = record_volume_read(symbol, record)

    evolution_notes = build_volume_evolution_notes(
        evolution.get("previous"),
        evolution.get("current"),
    )

    watch_items = build_watch_items(
        score=score,
        change_percent=change_percent,
        volume_label=volume_label,
        risk=risk,
        action=action,
        category=category,
    )

    return f"""
📊 {symbol} Volume Intelligence

Headline
Confirmation: {confirmation}
Score: {format_score(score)}
Signal: {label}
Conviction: {signal}
Risk: {risk}
Action: {action}
Category: {category}

Live Tape
Price: {format_price(price)}
Change: {format_change(change_percent)}
Volume Read: {volume_label}

Money-Flow Read
{build_money_flow_read(symbol, score, change_percent, volume_label, confirmation)}

What Changed
{bullet_lines(evolution_notes)}

Evolving Analysis
{build_volume_memory_summary(symbol)}

What To Watch
{bullet_lines(watch_items)}

Volume Action
{build_volume_action(symbol, score, confirmation, risk, action)}

Related Commands:
{build_related_commands(symbol)}

Research only. Not financial advice.
""".strip()