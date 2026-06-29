import asyncio
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from src.commands.watchlist_commands import fetch_quotes_for_symbols
from src.scoring.scoring_engine import get_stock_scores


MAX_TOP_RESULTS = 10


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
            "",
        )

        reason = get_value(
            item,
            ["reason", "summary", "thesis", "note", "explanation"],
            "",
        )

        sector = get_value(
            item,
            ["sector", "industry", "category"],
            "",
        )

        return {
            "symbol": str(symbol).upper(),
            "score": safe_float(score),
            "rating": str(rating).strip(),
            "reason": str(reason).strip(),
            "sector": str(sector).strip(),
            "raw": item,
        }

    if isinstance(item, (list, tuple)) and item:
        symbol = str(item[0]).upper()
        score = safe_float(item[1]) if len(item) > 1 else None

        return {
            "symbol": symbol,
            "score": score,
            "rating": "",
            "reason": "",
            "sector": "",
            "raw": item,
        }

    return {
        "symbol": str(item).upper(),
        "score": None,
        "rating": "",
        "reason": "",
        "sector": "",
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
                    {
                        "symbol": str(symbol).upper(),
                        "score": safe_float(value),
                        "rating": "",
                        "reason": "",
                        "sector": "",
                        "raw": value,
                    }
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


def classify_signal(score: float | None) -> str:
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


def build_risk_note(score: float | None) -> str:
    if score is None:
        return "Verify data quality before acting."
    if score >= 85:
        return "Strong score, but confirm price is not extended."
    if score >= 75:
        return "Good candidate; confirm trend and earnings date."
    if score >= 65:
        return "Watchlist candidate; wait for cleaner confirmation."
    if score >= 50:
        return "Mixed profile; size carefully or wait."
    return "Low score; avoid unless thesis changes."


def build_next_step(score: float | None) -> str:
    if score is None:
        return "Review manually."
    if score >= 85:
        return "Check chart, volume, news, and entry level."
    if score >= 75:
        return "Add to active watchlist and compare against sector peers."
    if score >= 65:
        return "Monitor for breakout, pullback, or catalyst."
    if score >= 50:
        return "Wait for stronger confirmation."
    return "Skip for now."


def get_quote_for_symbol(quotes: dict, symbol: str) -> dict | None:
    if not isinstance(quotes, dict):
        return None

    quote = quotes.get(symbol) or quotes.get(symbol.upper())

    if isinstance(quote, dict):
        return quote

    for value in quotes.values():
        if not isinstance(value, dict):
            continue

        quote_symbol = str(
            value.get("symbol")
            or value.get("ticker")
            or ""
        ).upper()

        if quote_symbol == symbol.upper():
            return value

    return None


def get_quote_value(quote: dict | None, keys: list[str]):
    if not quote:
        return None

    for key in keys:
        value = quote.get(key)
        if value is not None:
            return value

    return None


def get_price(quote: dict | None) -> float | None:
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


def get_change_percent(quote: dict | None) -> float | None:
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


def clean_reason(reason: str, max_length: int = 120) -> str:
    if not reason:
        return "No thesis provided by scoring engine."

    cleaned = " ".join(reason.split())

    if len(cleaned) <= max_length:
        return cleaned

    return cleaned[: max_length - 3].rstrip() + "..."


def format_top10_item(index: int, item: dict, quotes: dict) -> str:
    symbol = item["symbol"]
    score = item["score"]
    quote = get_quote_for_symbol(quotes, symbol)

    price = get_price(quote)
    change_percent = get_change_percent(quote)

    signal = classify_signal(score)
    score_text = format_score(score)
    reason = clean_reason(item["reason"])
    risk_note = build_risk_note(score)
    next_step = build_next_step(score)

    rating = item.get("rating") or ""
    sector = item.get("sector") or ""

    optional_details = []

    if rating:
        optional_details.append(f"Rating: {rating}")

    if sector:
        optional_details.append(f"Sector: {sector}")

    optional_line = ""
    if optional_details:
        optional_line = "\n   " + " | ".join(optional_details)

    return f"""
{index}. {symbol} — {signal}
   Price: {format_price(price)} ({format_percent(change_percent)})
   Score: {score_text}{optional_line}
   Why: {reason}
   Risk: {risk_note}
   Next: {next_step}
""".rstrip()


def build_top10_message(top_items: list[dict], quotes: dict) -> str:
    if not top_items:
        return """
🏆 Smart Money AI Top 10

No ranked opportunities are available right now.

Try again later or run /report for the full market report.
""".strip()

    lines = [
        format_top10_item(index, item, quotes)
        for index, item in enumerate(top_items, start=1)
    ]

    return f"""
🏆 Smart Money AI Top 10

Ranked Opportunities
{chr(10).join(lines)}

How to use this
• High conviction: investigate for possible action.
• Strong watch: add to active watchlist.
• Moderate watch: wait for confirmation.
• Neutral or weak: avoid forcing a trade.

Notes
This is informational only and is not financial advice.
Use /scorecard SYMBOL for a deeper single-stock view.
Use /risk SYMBOL before making any decision.
""".strip()


async def top10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Building Smart Money AI top 10...")

    try:
        raw_scores = await asyncio.to_thread(get_stock_scores)
    except Exception as exc:
        await update.message.reply_text(f"❌ Top 10 failed: scoring unavailable: {exc}")
        return

    normalized_scores = normalize_scores(raw_scores)
    top_items = normalized_scores[:MAX_TOP_RESULTS]

    symbols = [item["symbol"] for item in top_items if item["symbol"] != "UNKNOWN"]

    try:
        quotes = await asyncio.to_thread(fetch_quotes_for_symbols, symbols)
    except Exception:
        quotes = {}

    message = build_top10_message(top_items, quotes)
    await update.message.reply_text(message)