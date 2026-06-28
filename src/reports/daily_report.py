from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.agents.analyst_agent import generate_ai_summary
from src.commands.watchlist_commands import fetch_quotes_for_symbols
from src.scoring.scoring_engine import get_stock_scores
from src.utils.watchlist_store import load_watchlist


REPORT_TIMEZONE = "America/Lima"
MAX_TOP_OPPORTUNITIES = 10
MAX_WATCHLIST_MOVERS = 8


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def get_value(data: dict, keys: list[str], default=None):
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def normalize_score_item(item: Any) -> dict:
    if isinstance(item, dict):
        symbol = (
            item.get("symbol")
            or item.get("ticker")
            or item.get("name")
            or "UNKNOWN"
        )

        score = get_value(
            item,
            ["score", "total_score", "smart_money_score", "rating_score"],
            None,
        )

        rating = get_value(
            item,
            ["rating", "grade", "signal", "recommendation"],
            "N/A",
        )

        reason = get_value(
            item,
            ["reason", "summary", "thesis", "note", "explanation"],
            "",
        )

        return {
            "symbol": str(symbol).upper(),
            "score": safe_float(score),
            "rating": str(rating),
            "reason": str(reason),
            "raw": item,
        }

    if isinstance(item, (list, tuple)) and item:
        symbol = str(item[0]).upper()
        score = safe_float(item[1]) if len(item) > 1 else None

        return {
            "symbol": symbol,
            "score": score,
            "rating": "N/A",
            "reason": "",
            "raw": item,
        }

    return {
        "symbol": str(item).upper(),
        "score": None,
        "rating": "N/A",
        "reason": "",
        "raw": item,
    }


def normalize_scores(scores: Any) -> list[dict]:
    if scores is None:
        return []

    if isinstance(scores, dict):
        normalized = []

        for symbol, value in scores.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("symbol", symbol)
                normalized.append(normalize_score_item(item))
            else:
                normalized.append(
                    {
                        "symbol": str(symbol).upper(),
                        "score": safe_float(value),
                        "rating": "N/A",
                        "reason": "",
                        "raw": value,
                    }
                )

        return sort_scores(normalized)

    if isinstance(scores, list):
        return sort_scores(normalize_score_item(item) for item in scores)

    return []


def sort_scores(scores: Any) -> list[dict]:
    normalized = list(scores)

    return sorted(
        normalized,
        key=lambda item: item["score"] if item["score"] is not None else -999,
        reverse=True,
    )


def format_score(score: float | None) -> str:
    if score is None:
        return "N/A"

    if score.is_integer():
        return str(int(score))

    return f"{score:.1f}"


def classify_score(score: float | None) -> str:
    if score is None:
        return "Unrated"
    if score >= 85:
        return "High conviction"
    if score >= 75:
        return "Strong watch"
    if score >= 65:
        return "Moderate watch"
    if score >= 50:
        return "Neutral"
    return "Weak"


def format_opportunity_line(index: int, item: dict) -> str:
    symbol = item["symbol"]
    score = format_score(item["score"])
    rating = item["rating"]

    signal = classify_score(item["score"])

    if rating and rating != "N/A":
        return f"{index}. {symbol} — Score: {score} | {signal} | {rating}"

    return f"{index}. {symbol} — Score: {score} | {signal}"


def get_quote_value(quote: dict, keys: list[str]):
    for key in keys:
        value = quote.get(key)

        if value is not None:
            return value

    return None


def get_quote_price(quote: dict | None) -> float | None:
    if not quote:
        return None

    return safe_float(
        get_quote_value(
            quote,
            [
                "price",
                "regularMarketPrice",
                "regular_market_price",
                "current_price",
                "last_price",
            ],
        )
    )


def get_quote_change_percent(quote: dict | None) -> float | None:
    if not quote:
        return None

    return safe_float(
        get_quote_value(
            quote,
            [
                "change_percent",
                "percent_change",
                "regularMarketChangePercent",
                "regular_market_change_percent",
                "changePercent",
            ],
        )
    )


def format_price(price: float | None) -> str:
    if price is None:
        return "N/A"

    return f"${price:,.2f}"


def format_percent(value: float | None) -> str:
    if value is None:
        return "N/A"

    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def fetch_watchlist_quotes() -> tuple[list[str], dict]:
    try:
        symbols = load_watchlist()
    except Exception:
        return [], {}

    if not symbols:
        return [], {}

    try:
        quotes = fetch_quotes_for_symbols(symbols)
    except Exception:
        return symbols, {}

    if not isinstance(quotes, dict):
        return symbols, {}

    return symbols, quotes


def build_watchlist_snapshot(symbols: list[str], quotes: dict) -> str:
    if not symbols:
        return "Watchlist unavailable."

    if not quotes:
        return f"{len(symbols)} symbols loaded, but quote data is unavailable."

    movers = []

    for symbol in symbols:
        quote = quotes.get(symbol) or quotes.get(symbol.upper())

        if not isinstance(quote, dict):
            continue

        change_percent = get_quote_change_percent(quote)
        price = get_quote_price(quote)

        if change_percent is None:
            continue

        movers.append(
            {
                "symbol": symbol.upper(),
                "price": price,
                "change_percent": change_percent,
            }
        )

    if not movers:
        return f"{len(symbols)} symbols loaded, but no movement data available."

    movers.sort(key=lambda item: abs(item["change_percent"]), reverse=True)

    lines = []

    for item in movers[:MAX_WATCHLIST_MOVERS]:
        lines.append(
            f"• {item['symbol']}: {format_price(item['price'])} "
            f"({format_percent(item['change_percent'])})"
        )

    return "\n".join(lines)


def build_market_tone_from_watchlist(quotes: dict) -> str:
    if not quotes:
        return "Data unavailable"

    changes = []

    for quote in quotes.values():
        if not isinstance(quote, dict):
            continue

        change = get_quote_change_percent(quote)

        if change is not None:
            changes.append(change)

    if not changes:
        return "Data unavailable"

    positive = sum(1 for item in changes if item > 0)
    negative = sum(1 for item in changes if item < 0)
    average_change = sum(changes) / len(changes)

    if average_change >= 1.0 and positive > negative:
        return "Risk-on / bullish"
    if average_change <= -1.0 and negative > positive:
        return "Risk-off / bearish"
    if positive > negative:
        return "Constructive / mildly bullish"
    if negative > positive:
        return "Defensive / mildly bearish"

    return "Mixed / neutral"


def build_risk_notes(top_scores: list[dict], watchlist_quotes: dict) -> str:
    notes = []

    high_conviction_count = sum(
        1 for item in top_scores if item["score"] is not None and item["score"] >= 85
    )

    weak_count = sum(
        1 for item in top_scores if item["score"] is not None and item["score"] < 50
    )

    if high_conviction_count:
        notes.append(
            f"{high_conviction_count} high-conviction name(s) are present in the current scoring output."
        )

    if weak_count:
        notes.append(
            f"{weak_count} low-score name(s) appear in the ranking and should be treated cautiously."
        )

    if watchlist_quotes:
        large_movers = []

        for quote in watchlist_quotes.values():
            if not isinstance(quote, dict):
                continue

            symbol = str(quote.get("symbol") or quote.get("ticker") or "").upper()
            change = get_quote_change_percent(quote)

            if symbol and change is not None and abs(change) >= 2:
                large_movers.append(symbol)

        if large_movers:
            notes.append(
                "Large watchlist moves detected: "
                + ", ".join(sorted(set(large_movers))[:8])
                + "."
            )

    if not notes:
        return "No major report-level risk flags detected from current data."

    return "\n".join(f"• {note}" for note in notes)


def build_action_checklist(market_tone: str) -> str:
    if "Risk-on" in market_tone or "bullish" in market_tone.lower():
        return "\n".join(
            [
                "• Review top-ranked names for continuation setups.",
                "• Confirm volume, earnings dates, and sector strength before entering.",
                "• Avoid chasing extended moves without a defined stop.",
            ]
        )

    if "Risk-off" in market_tone or "bearish" in market_tone.lower():
        return "\n".join(
            [
                "• Prioritize capital protection and position sizing.",
                "• Review stop-loss levels and avoid weak relative-strength names.",
                "• Watch defensive sectors, bonds, gold, and volatility.",
            ]
        )

    return "\n".join(
        [
            "• Wait for confirmation before adding new risk.",
            "• Focus on the strongest names with clean setups.",
            "• Keep position sizing disciplined until market tone improves.",
        ]
    )


def build_ai_summary(scores: Any) -> str:
    try:
        summary = generate_ai_summary(scores)
    except Exception as exc:
        return f"AI summary unavailable: {exc}"

    if not summary:
        return "AI summary unavailable."

    return str(summary).strip()


def build_daily_report() -> str:
    now = datetime.now(ZoneInfo(REPORT_TIMEZONE))
    today = now.strftime("%B %d, %Y")
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    try:
        raw_scores = get_stock_scores()
    except Exception as exc:
        raw_scores = []
        scoring_error = str(exc)
    else:
        scoring_error = ""

    normalized_scores = normalize_scores(raw_scores)
    top_scores = normalized_scores[:MAX_TOP_OPPORTUNITIES]

    watchlist_symbols, watchlist_quotes = fetch_watchlist_quotes()
    market_tone = build_market_tone_from_watchlist(watchlist_quotes)

    if top_scores:
        top_opportunities = "\n".join(
            format_opportunity_line(index, item)
            for index, item in enumerate(top_scores, start=1)
        )
    elif scoring_error:
        top_opportunities = f"Scoring unavailable: {scoring_error}"
    else:
        top_opportunities = "No scoring opportunities available."

    watchlist_snapshot = build_watchlist_snapshot(
        watchlist_symbols,
        watchlist_quotes,
    )

    risk_notes = build_risk_notes(top_scores, watchlist_quotes)
    action_checklist = build_action_checklist(market_tone)
    ai_summary = build_ai_summary(raw_scores)

    return f"""
📊 Smart Money AI Report
Date: {today}
Generated: {timestamp} {REPORT_TIMEZONE}

Market Snapshot
Market tone: {market_tone}
Watchlist symbols: {len(watchlist_symbols)}

Watchlist Movers
{watchlist_snapshot}

Top Opportunities
{top_opportunities}

Risk Notes
{risk_notes}

AI Summary
{ai_summary}

Action Checklist
{action_checklist}

Notes
This report is informational only and is not financial advice.
Use /marketbrief for a quick market snapshot.
Use /watchlist report for your full custom watchlist.
""".strip()