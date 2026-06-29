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


def clean_symbol(symbol: Any) -> str:
    return str(symbol or "UNKNOWN").strip().upper().replace("$", "")


def get_value(data: dict, keys: list[str], default=None):
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def clean_text(text: Any, max_length: int = 140) -> str:
    if text is None:
        return ""

    cleaned = " ".join(str(text).split())

    if len(cleaned) <= max_length:
        return cleaned

    return cleaned[: max_length - 3].rstrip() + "..."


def get_first_text(value: Any, fallback: str) -> str:
    if isinstance(value, list):
        for item in value:
            text = clean_text(item)
            if text:
                return text
        return fallback

    if isinstance(value, tuple):
        return get_first_text(list(value), fallback)

    if isinstance(value, str) and value.strip():
        return clean_text(value)

    return fallback


def normalize_score_item(item: Any) -> dict:
    if isinstance(item, dict):
        symbol = get_value(
            item,
            ["symbol", "ticker", "name"],
            "UNKNOWN",
        )

        score = get_value(
            item,
            ["final_score", "score", "smart_money_score", "total_score", "rating_score"],
            None,
        )

        rating = get_value(
            item,
            ["rating", "grade", "signal", "recommendation"],
            "Unrated",
        )

        risk_label = get_value(
            item,
            ["risk_label", "risk_level", "risk"],
            "N/A",
        )

        category = get_value(
            item,
            ["category", "sector", "industry"],
            "N/A",
        )

        category_adjustment = get_value(
            item,
            ["category_adjustment", "adjustment"],
            0,
        )

        reason = get_value(
            item,
            ["reason", "summary", "thesis", "note", "explanation"],
            "",
        )

        strengths = get_value(
            item,
            ["strengths", "pros", "bull_case", "positive_factors"],
            [],
        )

        weaknesses = get_value(
            item,
            ["weaknesses", "cons", "bear_case", "negative_factors"],
            [],
        )

        risks = get_value(
            item,
            ["risks", "risk_notes", "warnings"],
            [],
        )

        return {
            "symbol": clean_symbol(symbol),
            "score": safe_float(score),
            "rating": str(rating).strip() or "Unrated",
            "risk_label": str(risk_label).strip() or "N/A",
            "category": str(category).strip() or "N/A",
            "category_adjustment": safe_float(category_adjustment) or 0,
            "reason": clean_text(reason, 180),
            "strengths": strengths,
            "weaknesses": weaknesses,
            "risks": risks,
            "raw": item,
        }

    if isinstance(item, (list, tuple)) and item:
        symbol = clean_symbol(item[0])
        score = safe_float(item[1]) if len(item) > 1 else None

        return {
            "symbol": symbol,
            "score": score,
            "rating": "Unrated",
            "risk_label": "N/A",
            "category": "N/A",
            "category_adjustment": 0,
            "reason": "",
            "strengths": [],
            "weaknesses": [],
            "risks": [],
            "raw": item,
        }

    return {
        "symbol": clean_symbol(item),
        "score": None,
        "rating": "Unrated",
        "risk_label": "N/A",
        "category": "N/A",
        "category_adjustment": 0,
        "reason": "",
        "strengths": [],
        "weaknesses": [],
        "risks": [],
        "raw": item,
    }


def normalize_scores(scores: Any) -> list[dict]:
    if scores is None:
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


def format_score(score: float | None) -> str:
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


def build_score_summary(scores: list[dict]) -> str:
    if not scores:
        return "No scoring data available."

    scored_values = [
        item["score"]
        for item in scores
        if item["score"] is not None
    ]

    if not scored_values:
        return "No scored symbols available."

    elite = len([score for score in scored_values if score >= 90])
    high_conviction = len([score for score in scored_values if score >= 82])
    strong_watch = len([score for score in scored_values if score >= 75])
    watchable = len([score for score in scored_values if score >= 68])

    return f"""
Total Scored Symbols: {len(scores)}
Elite 90+: {elite}
High Conviction 82+: {high_conviction}
Strong Watch 75+: {strong_watch}
Watchable 68+: {watchable}
Highest Score: {format_score(max(scored_values))}
Average Score: {format_score(sum(scored_values) / len(scored_values))}
""".strip()


def format_opportunity_line(index: int, item: dict) -> str:
    symbol = item["symbol"]
    score = format_score(item["score"])
    signal = classify_score(item["score"])
    rating = item.get("rating") or "Unrated"
    risk_label = item.get("risk_label") or "N/A"
    category = item.get("category") or "N/A"
    adjustment = format_adjustment(item.get("category_adjustment"))

    top_strength = get_first_text(
        item.get("strengths"),
        "No major strength detail available.",
    )

    key_weakness = get_first_text(
        item.get("weaknesses"),
        "No major weakness detail available.",
    )

    return (
        f"{index}. {symbol} — {score}/100 | {signal}\n"
        f"   Rating: {rating} | Risk: {risk_label}\n"
        f"   Category: {category} | Adjustment: {adjustment}\n"
        f"   Strength: {clean_text(top_strength, 110)}\n"
        f"   Watch: {clean_text(key_weakness, 110)}"
    )


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
        1
        for item in top_scores
        if item["score"] is not None and item["score"] >= 82
    )

    high_risk_count = sum(
        1
        for item in top_scores
        if "high" in str(item.get("risk_label", "")).lower()
    )

    weak_count = sum(
        1
        for item in top_scores
        if item["score"] is not None and item["score"] < 50
    )

    positive_adjustments = sum(
        1
        for item in top_scores
        if safe_float(item.get("category_adjustment")) is not None
        and safe_float(item.get("category_adjustment")) > 0
    )

    if high_conviction_count:
        notes.append(
            f"{high_conviction_count} high-conviction name(s) are present in the current top ranking."
        )

    if high_risk_count:
        notes.append(
            f"{high_risk_count} top-ranked name(s) carry elevated risk labels."
        )

    if weak_count:
        notes.append(
            f"{weak_count} low-score name(s) appear in the ranking and should be treated cautiously."
        )

    if positive_adjustments:
        notes.append(
            f"{positive_adjustments} top-ranked name(s) benefit from positive category adjustments."
        )

    if watchlist_quotes:
        large_movers = []

        for quote in watchlist_quotes.values():
            if not isinstance(quote, dict):
                continue

            symbol = clean_symbol(quote.get("symbol") or quote.get("ticker"))
            change = get_quote_change_percent(quote)

            if symbol and symbol != "UNKNOWN" and change is not None and abs(change) >= 2:
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

    score_summary = build_score_summary(normalized_scores)

    if top_scores:
        top_opportunities = "\n\n".join(
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
📊 Smart Money AI Daily Report
Date: {today}
Generated: {timestamp} {REPORT_TIMEZONE}

Market Snapshot
Market Tone: {market_tone}
Watchlist Symbols: {len(watchlist_symbols)}

Watchlist Movers
{watchlist_snapshot}

Smart Money Score Summary
{score_summary}

Top Opportunities
{top_opportunities}

Risk Notes
{risk_notes}

AI Summary
{ai_summary}

Action Checklist
{action_checklist}

Next Commands
/top10
/scorecard SYMBOL
/watchlist report
/marketbrief

Notes
This report is informational only and is not financial advice.
Use /marketbrief for a quick market snapshot.
Use /watchlist report for your full custom watchlist.
""".strip()