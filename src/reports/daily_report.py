from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.agents.analyst_agent import generate_ai_summary
from src.commands.watchlist_commands import fetch_quotes_for_symbols
from src.scoring.scoring_engine import get_stock_scores
from src.utils.watchlist_store import load_watchlist


REPORT_TIMEZONE = "America/Lima"
MAX_TOP_OPPORTUNITIES = 5
MAX_WATCHLIST_MOVERS = 5
MAX_AI_SUMMARY_CHARS = 900


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_symbol(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper().replace("$", "")


def clean_text(value: Any, max_length: int = 120) -> str:
    if value is None:
        return ""

    text = " ".join(str(value).split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def get_value(data: dict, keys: list[str], default=None):
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def first_list_text(value: Any, fallback: str) -> str:
    if isinstance(value, list):
        for item in value:
            text = clean_text(item, 110)
            if text:
                return text
        return fallback

    if isinstance(value, tuple):
        return first_list_text(list(value), fallback)

    if isinstance(value, str) and value.strip():
        return clean_text(value, 110)

    return fallback


def format_score(value: Any) -> str:
    score = safe_float(value)

    if score is None:
        return "N/A"

    if score.is_integer():
        return str(int(score))

    return f"{score:.1f}"


def format_adjustment(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "0"

    if number > 0:
        return f"+{number:.0f}"

    return f"{number:.0f}"


def format_price(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    return f"${number:,.2f}"


def format_percent(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    sign = "+" if number >= 0 else ""
    return f"{sign}{number:.2f}%"


def classify_score(score: float | None) -> str:
    if score is None:
        return "Unrated"
    if score >= 90:
        return "Elite"
    if score >= 82:
        return "High conviction"
    if score >= 75:
        return "Strong watch"
    if score >= 68:
        return "Good watch"
    if score >= 60:
        return "Moderate watch"
    if score >= 50:
        return "Neutral"
    return "Weak"


def normalize_score_item(item: Any) -> dict:
    if isinstance(item, dict):
        score = get_value(
            item,
            ["final_score", "score", "smart_money_score", "total_score", "rating_score"],
            None,
        )

        return {
            "symbol": clean_symbol(
                get_value(item, ["ticker", "symbol", "name"], "UNKNOWN")
            ),
            "score": safe_float(score),
            "rating": str(
                get_value(item, ["rating", "grade", "signal"], "Unrated")
            ),
            "risk_label": str(
                get_value(item, ["risk_label", "risk_level", "risk"], "N/A")
            ),
            "category": str(
                get_value(item, ["category", "sector", "industry"], "N/A")
            ),
            "category_adjustment": safe_float(
                get_value(item, ["category_adjustment", "adjustment"], 0)
            ) or 0,
            "strength": first_list_text(
                get_value(item, ["strengths", "pros", "bull_case"], []),
                "No strength detail available.",
            ),
            "weakness": first_list_text(
                get_value(item, ["weaknesses", "cons", "bear_case"], []),
                "No weakness detail available.",
            ),
        }

    if isinstance(item, (list, tuple)) and item:
        return {
            "symbol": clean_symbol(item[0]),
            "score": safe_float(item[1]) if len(item) > 1 else None,
            "rating": "Unrated",
            "risk_label": "N/A",
            "category": "N/A",
            "category_adjustment": 0,
            "strength": "No strength detail available.",
            "weakness": "No weakness detail available.",
        }

    return {
        "symbol": clean_symbol(item),
        "score": None,
        "rating": "Unrated",
        "risk_label": "N/A",
        "category": "N/A",
        "category_adjustment": 0,
        "strength": "No strength detail available.",
        "weakness": "No weakness detail available.",
    }


def normalize_scores(scores: Any) -> list[dict]:
    if not scores:
        return []

    normalized = []

    if isinstance(scores, dict):
        for symbol, value in scores.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("symbol", symbol)
                normalized.append(normalize_score_item(item))
            else:
                normalized.append(
                    normalize_score_item(
                        {
                            "symbol": symbol,
                            "score": value,
                        }
                    )
                )

    elif isinstance(scores, list):
        normalized = [normalize_score_item(item) for item in scores]

    return sorted(
        normalized,
        key=lambda item: item["score"] if item["score"] is not None else -999,
        reverse=True,
    )


def build_score_summary(scores: list[dict]) -> str:
    values = [
        item["score"]
        for item in scores
        if item["score"] is not None
    ]

    if not values:
        return "No scored symbols available."

    return "\n".join(
        [
            f"Total Scored Symbols: {len(scores)}",
            f"High Conviction 82+: {len([score for score in values if score >= 82])}",
            f"Strong Watch 75+: {len([score for score in values if score >= 75])}",
            f"Highest Score: {format_score(max(values))}",
            f"Average Score: {format_score(sum(values) / len(values))}",
        ]
    )


def format_opportunity(index: int, item: dict) -> str:
    score = item["score"]
    signal = classify_score(score)

    return (
        f"{index}. {item['symbol']} — {format_score(score)}/100 | {signal}\n"
        f"   Rating: {item['rating']} | Risk: {item['risk_label']}\n"
        f"   Category: {item['category']} | Adj: {format_adjustment(item['category_adjustment'])}\n"
        f"   Strength: {clean_text(item['strength'], 100)}"
    )


def get_quote_value(quote: dict | None, keys: list[str]):
    if not isinstance(quote, dict):
        return None

    for key in keys:
        value = quote.get(key)
        if value is not None:
            return value

    return None


def get_quote_price(quote: dict | None):
    return get_quote_value(
        quote,
        [
            "price",
            "regularMarketPrice",
            "regular_market_price",
            "current_price",
            "last_price",
        ],
    )


def get_quote_change_percent(quote: dict | None):
    return get_quote_value(
        quote,
        [
            "change_percent",
            "percent_change",
            "regularMarketChangePercent",
            "regular_market_change_percent",
            "changePercent",
        ],
    )


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

        change_percent = safe_float(get_quote_change_percent(quote))
        price = safe_float(get_quote_price(quote))

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

    return "\n".join(
        f"• {item['symbol']}: {format_price(item['price'])} ({format_percent(item['change_percent'])})"
        for item in movers[:MAX_WATCHLIST_MOVERS]
    )


def build_market_tone_from_watchlist(quotes: dict) -> str:
    changes = []

    for quote in quotes.values():
        change = safe_float(get_quote_change_percent(quote))
        if change is not None:
            changes.append(change)

    if not changes:
        return "Data unavailable"

    positive = len([change for change in changes if change > 0])
    negative = len([change for change in changes if change < 0])
    average = sum(changes) / len(changes)

    if average >= 1 and positive > negative:
        return "Risk-on / bullish"
    if average <= -1 and negative > positive:
        return "Risk-off / bearish"
    if positive > negative:
        return "Constructive / mildly bullish"
    if negative > positive:
        return "Defensive / mildly bearish"

    return "Mixed / neutral"


def build_risk_notes(top_scores: list[dict], watchlist_quotes: dict) -> str:
    notes = []

    high_conviction = len(
        [
            item
            for item in top_scores
            if item["score"] is not None and item["score"] >= 82
        ]
    )

    high_risk = len(
        [
            item
            for item in top_scores
            if "high" in str(item.get("risk_label", "")).lower()
        ]
    )

    if high_conviction:
        notes.append(f"{high_conviction} high-conviction name(s) in the top ranking.")

    if high_risk:
        notes.append(f"{high_risk} top-ranked name(s) carry elevated risk labels.")

    large_movers = []

    for quote in watchlist_quotes.values():
        if not isinstance(quote, dict):
            continue

        symbol = clean_symbol(quote.get("symbol") or quote.get("ticker"))
        change = safe_float(get_quote_change_percent(quote))

        if symbol != "UNKNOWN" and change is not None and abs(change) >= 2:
            large_movers.append(symbol)

    if large_movers:
        notes.append(
            "Large watchlist moves detected: "
            + ", ".join(sorted(set(large_movers))[:5])
            + "."
        )

    if not notes:
        return "No major report-level risk flags detected."

    return "\n".join(f"• {note}" for note in notes)


def build_action_checklist(market_tone: str) -> str:
    if "bullish" in market_tone.lower():
        return "\n".join(
            [
                "• Review top-ranked names for clean continuation setups.",
                "• Confirm volume, earnings dates, and sector strength.",
                "• Avoid chasing extended moves without a defined stop.",
            ]
        )

    if "bearish" in market_tone.lower():
        return "\n".join(
            [
                "• Prioritize capital protection and position sizing.",
                "• Review stop-loss levels.",
                "• Avoid weak relative-strength names.",
            ]
        )

    return "\n".join(
        [
            "• Wait for confirmation before adding new risk.",
            "• Focus on the strongest names with clean setups.",
            "• Keep position sizing disciplined.",
        ]
    )


def build_ai_summary(scores: Any) -> str:
    try:
        summary = generate_ai_summary(scores)
    except Exception as exc:
        return f"AI summary unavailable: {type(exc).__name__}"

    if not summary:
        return "AI summary unavailable."

    return clean_text(summary, MAX_AI_SUMMARY_CHARS)


def build_daily_report() -> str:
    now = datetime.now(ZoneInfo(REPORT_TIMEZONE))
    today = now.strftime("%B %d, %Y")
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    try:
        raw_scores = get_stock_scores()
        scoring_error = ""
    except Exception as exc:
        raw_scores = []
        scoring_error = type(exc).__name__

    scores = normalize_scores(raw_scores)
    top_scores = scores[:MAX_TOP_OPPORTUNITIES]

    watchlist_symbols, watchlist_quotes = fetch_watchlist_quotes()
    market_tone = build_market_tone_from_watchlist(watchlist_quotes)

    if top_scores:
        top_opportunities = "\n\n".join(
            format_opportunity(index, item)
            for index, item in enumerate(top_scores, start=1)
        )
    elif scoring_error:
        top_opportunities = f"Scoring unavailable: {scoring_error}"
    else:
        top_opportunities = "No scoring opportunities available."

    return f"""
📊 Smart Money AI Daily Report
Date: {today}
Generated: {timestamp} {REPORT_TIMEZONE}

Market Snapshot
Market Tone: {market_tone}
Watchlist Symbols: {len(watchlist_symbols)}

Watchlist Movers
{build_watchlist_snapshot(watchlist_symbols, watchlist_quotes)}

Smart Money Score Summary
{build_score_summary(scores)}

Top Opportunities
{top_opportunities}

Risk Notes
{build_risk_notes(top_scores, watchlist_quotes)}

AI Summary
{build_ai_summary(raw_scores)}

Action Checklist
{build_action_checklist(market_tone)}

Next Commands
/top10
/scorecard SYMBOL
/watchlist report
/marketbrief

Notes
This report is informational only and is not financial advice.
""".strip()