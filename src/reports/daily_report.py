from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.commands.watchlist_commands import fetch_quotes_for_symbols
from src.reports.action_checklist import (
    build_action_checklist as build_relevant_action_checklist,
)
from src.reports.ai_summary import build_ai_summary as build_relevant_ai_summary
from src.reports.global_market_report import build_global_risk_snapshot
from src.scoring.scoring_engine import get_stock_scores
from src.utils.score_display import (
    get_action_label,
    get_category,
    get_portfolio_fit,
    get_risk_label,
    get_signal_strength,
    get_smart_money_label,
    get_ticker,
    get_volume_label,
)
from src.utils.watchlist_store import load_watchlist


REPORT_TIMEZONE = "America/Lima"

MAX_TOP_OPPORTUNITIES = 3
MAX_WATCHLIST_MOVERS = 4
MAX_AI_SUMMARY_CHARS = 650
MAX_ACTION_CHARS = 500


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_symbol(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper().replace("$", "")


def clean_text(value: Any, max_length: int = 140) -> str:
    if value is None:
        return ""

    text = " ".join(str(value).split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def truncate_text(value: Any, max_length: int) -> str:
    text = str(value or "").strip()

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
            text = clean_text(item, 120)
            if text:
                return text
        return fallback

    if isinstance(value, tuple):
        return first_list_text(list(value), fallback)

    if isinstance(value, str) and value.strip():
        return clean_text(value, 120)

    return fallback


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


def normalize_score_item(item: Any) -> dict:
    if isinstance(item, dict):
        score = get_value(
            item,
            ["final_score", "score", "smart_money_score", "total_score", "rating_score"],
            None,
        )

        ticker = clean_symbol(
            get_value(item, ["ticker", "symbol", "name"], "UNKNOWN")
        )

        normalized = dict(item)

        normalized.update(
            {
                "ticker": ticker,
                "symbol": ticker,
                "score": safe_float(score),
                "rating": str(
                    get_value(
                        item,
                        ["smart_money_label", "rating", "grade", "signal"],
                        "Unrated",
                    )
                ),
                "risk_label": str(
                    get_value(item, ["risk_label", "risk_level", "risk"], "N/A")
                ),
                "category": str(
                    get_value(item, ["category", "sector", "industry"], "N/A")
                ),
                "strength": first_list_text(
                    get_value(item, ["strengths", "pros", "bull_case", "reason"], []),
                    "No strength detail available.",
                ),
                "weakness": first_list_text(
                    get_value(item, ["weaknesses", "cons", "bear_case", "risks"], []),
                    "No weakness detail available.",
                ),
            }
        )

        return normalized

    if isinstance(item, (list, tuple)) and item:
        ticker = clean_symbol(item[0])

        return {
            "ticker": ticker,
            "symbol": ticker,
            "score": safe_float(item[1]) if len(item) > 1 else None,
            "rating": "Unrated",
            "risk_label": "N/A",
            "category": "N/A",
            "strength": "No strength detail available.",
            "weakness": "No weakness detail available.",
        }

    ticker = clean_symbol(item)

    return {
        "ticker": ticker,
        "symbol": ticker,
        "score": None,
        "rating": "Unrated",
        "risk_label": "N/A",
        "category": "N/A",
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
                item.setdefault("ticker", symbol)
                item.setdefault("symbol", symbol)
                normalized.append(normalize_score_item(item))
            else:
                normalized.append(
                    normalize_score_item(
                        {
                            "ticker": symbol,
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


def collect_watchlist_movers(symbols: list[str], quotes: dict) -> list[dict]:
    movers = []

    for symbol in symbols or []:
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

    movers.sort(key=lambda item: abs(item["change_percent"]), reverse=True)

    return movers


def build_market_tone(movers: list[dict]) -> str:
    if not movers:
        return "Data unavailable"

    changes = [item["change_percent"] for item in movers]
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


def build_market_snapshot(symbols: list[str], movers: list[dict]) -> str:
    if not symbols:
        return "Watchlist unavailable."

    if not movers:
        return f"{len(symbols)} watchlist symbols loaded, but live quote movement is unavailable."

    changes = [item["change_percent"] for item in movers]
    positive = len([change for change in changes if change > 0])
    negative = len([change for change in changes if change < 0])
    average = sum(changes) / len(changes)

    strongest = max(movers, key=lambda item: item["change_percent"])
    weakest = min(movers, key=lambda item: item["change_percent"])

    return f"""
Tone: {build_market_tone(movers)}
Breadth: {positive} up / {negative} down / {len(movers)} with live data
Average Move: {format_percent(average)}
Strongest: {strongest["symbol"]} {format_percent(strongest["change_percent"])}
Weakest: {weakest["symbol"]} {format_percent(weakest["change_percent"])}
""".strip()


def build_watchlist_snapshot(symbols: list[str], movers: list[dict]) -> str:
    if not symbols:
        return "Watchlist unavailable."

    if not movers:
        return f"{len(symbols)} symbols loaded, but no live movement data available."

    return "\n".join(
        f"• {item['symbol']}: {format_price(item['price'])} ({format_percent(item['change_percent'])})"
        for item in movers[:MAX_WATCHLIST_MOVERS]
    )


def build_score_summary(scores: list[dict]) -> str:
    if not scores:
        return "No scored symbols available."

    counts = {}

    for item in scores:
        label = get_smart_money_label(item)
        counts[label] = counts.get(label, 0) + 1

    priority_labels = [
        "Prime Opportunity",
        "High Conviction",
        "Strong Watch",
        "Developing Watch",
        "Early Watch",
        "Neutral",
        "Weak Signal",
    ]

    lines = []

    for label in priority_labels:
        if counts.get(label):
            lines.append(f"• {label}: {counts[label]}")

    if not lines:
        lines = [
            f"• {label}: {count}"
            for label, count in sorted(counts.items())
        ]

    top_names = ", ".join(get_ticker(item) for item in scores[:5])

    return f"""
Reviewed: {len(scores)} names
Top Watch: {top_names if top_names else "N/A"}
{chr(10).join(lines[:5])}
""".strip()


def format_opportunity(index: int, item: dict) -> str:
    ticker = get_ticker(item)
    label = get_smart_money_label(item)
    signal = get_signal_strength(item)
    fit = get_portfolio_fit(item)
    action = get_action_label(item)
    risk = get_risk_label(item)
    volume = get_volume_label(item)
    category = get_category(item)

    strength = clean_text(
        item.get("strength")
        or first_list_text(item.get("strengths", []), "No strength detail available."),
        105,
    )

    return (
        f"{index}. {ticker} — {label}\n"
        f"   Signal: {signal} | Risk: {risk} | Volume: {volume}\n"
        f"   Fit: {fit}\n"
        f"   Action: {action}\n"
        f"   Theme: {category}\n"
        f"   Why: {strength}"
    )


def build_top_opportunities(top_scores: list[dict], scoring_error: str = "") -> str:
    if top_scores:
        return "\n\n".join(
            format_opportunity(index, item)
            for index, item in enumerate(top_scores, start=1)
        )

    if scoring_error:
        return f"Scoring unavailable: {scoring_error}"

    return "No scoring opportunities available."


def build_risk_notes(top_scores: list[dict], movers: list[dict]) -> str:
    notes = []

    high_conviction = [
        get_ticker(item)
        for item in top_scores
        if get_smart_money_label(item) in {"Prime Opportunity", "High Conviction"}
    ]

    elevated_risk = [
        get_ticker(item)
        for item in top_scores
        if get_risk_label(item) in {"High Risk", "Speculative", "Elevated"}
    ]

    large_movers = [
        item["symbol"]
        for item in movers
        if abs(item["change_percent"]) >= 2
    ]

    if high_conviction:
        notes.append(
            "Highest conviction focus: "
            + ", ".join(high_conviction[:3])
            + "."
        )

    if elevated_risk:
        notes.append(
            "Use tighter sizing on elevated-risk names: "
            + ", ".join(elevated_risk[:3])
            + "."
        )

    if large_movers:
        notes.append(
            "Large live moves detected: "
            + ", ".join(sorted(set(large_movers))[:5])
            + "."
        )

    if not notes:
        return "No major report-level risk flags detected."

    return "\n".join(f"• {note}" for note in notes[:4])


def build_executive_summary(
    top_scores: list[dict],
    movers: list[dict],
    market_tone: str,
) -> str:
    best = top_scores[0] if top_scores else None
    biggest_mover = movers[0] if movers else None

    lines = [f"• Market tone: {market_tone}."]

    if best:
        lines.append(
            f"• Best setup: {get_ticker(best)} — {get_smart_money_label(best)} "
            f"with {get_signal_strength(best).lower()} confirmation."
        )

    if biggest_mover:
        lines.append(
            f"• Biggest live move: {biggest_mover['symbol']} "
            f"{format_percent(biggest_mover['change_percent'])}."
        )

    if best:
        lines.append(
            f"• Action focus: {get_action_label(best)}; confirm with /scorecard {get_ticker(best)}."
        )
    else:
        lines.append("• Action focus: wait for stronger confirmation.")

    return "\n".join(lines)


def build_daily_ai_summary(raw_scores: Any) -> str:
    try:
        summary = build_relevant_ai_summary(stocks=raw_scores)
    except Exception as exc:
        return f"AI summary unavailable: {type(exc).__name__}"

    if not summary:
        return "AI summary unavailable."

    return truncate_text(summary, MAX_AI_SUMMARY_CHARS)


def build_daily_action_checklist(raw_scores: Any) -> str:
    try:
        checklist = build_relevant_action_checklist(stocks=raw_scores)
    except Exception as exc:
        return f"Action Checklist unavailable: {type(exc).__name__}"

    return truncate_text(checklist, MAX_ACTION_CHARS)


def safe_global_risk_snapshot() -> str:
    try:
        snapshot = build_global_risk_snapshot()
    except Exception as error:
        return f"""
🌍 Global Risk Snapshot

Market Regime:
Unavailable

Portfolio Impact:
- Global risk snapshot could not be built right now.

Reason:
{type(error).__name__}

Use /global for the full macro risk report.
""".strip()

    return snapshot.replace("\nUse /global for the full macro risk report.", "").strip()


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
    movers = collect_watchlist_movers(watchlist_symbols, watchlist_quotes)
    market_tone = build_market_tone(movers)

    executive_summary = build_executive_summary(
        top_scores=top_scores,
        movers=movers,
        market_tone=market_tone,
    )

    global_risk_snapshot = safe_global_risk_snapshot()
    top_opportunities = build_top_opportunities(top_scores, scoring_error)
    ai_summary = build_daily_ai_summary(raw_scores)
    action_checklist = build_daily_action_checklist(raw_scores)

    return f"""
📊 Smart Money AI Daily Brief
Date: {today}
Generated: {timestamp} {REPORT_TIMEZONE}

Executive Summary
{executive_summary}

Market Snapshot
{build_market_snapshot(watchlist_symbols, movers)}

Watchlist Movers
{build_watchlist_snapshot(watchlist_symbols, movers)}

{global_risk_snapshot}

Smart Money Rating Summary
{build_score_summary(scores)}

Top Opportunities
{top_opportunities}

Risk Notes
{build_risk_notes(top_scores, movers)}

AI Summary
{ai_summary}

Action Checklist
{action_checklist}

Next Commands
/global
/top10
/smartmoney
/scorecard SYMBOL
/watchlist movers

Notes
Informational only. Not financial advice.
""".strip()