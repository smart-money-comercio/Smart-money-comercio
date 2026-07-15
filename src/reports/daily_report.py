import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.commands.watchlist_commands import fetch_quotes_for_symbols
from src.reports.morning_brief_intro import build_morning_brief_intro
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

DAILY_REPORT_LIVE_QUOTES = os.getenv("DAILY_REPORT_LIVE_QUOTES", "0").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


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


def get_value(data: dict, keys: list[str], default=None):
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def first_list_text(value: Any, fallback: str, max_length: int = 130) -> str:
    if isinstance(value, list):
        for item in value:
            text = clean_text(item, max_length)
            if text:
                return text
        return fallback

    if isinstance(value, tuple):
        return first_list_text(list(value), fallback, max_length)

    if isinstance(value, str) and value.strip():
        return clean_text(value, max_length)

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
                    get_value(item, ["strengths", "pros", "bull_case", "reason", "thesis"], []),
                    "The setup has a developing thesis but needs confirmation.",
                ),
                "weakness": first_list_text(
                    get_value(item, ["weaknesses", "cons", "bear_case", "risks"], []),
                    "Main risk still needs review.",
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
            "strength": "The setup has a developing thesis but needs confirmation.",
            "weakness": "Main risk still needs review.",
        }

    ticker = clean_symbol(item)

    return {
        "ticker": ticker,
        "symbol": ticker,
        "score": None,
        "rating": "Unrated",
        "risk_label": "N/A",
        "category": "N/A",
        "strength": "The setup has a developing thesis but needs confirmation.",
        "weakness": "Main risk still needs review.",
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

    if not DAILY_REPORT_LIVE_QUOTES:
        return symbols, {}

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
        return "Fast mode / quote-neutral"

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
        return f"""
Tone: Fast mode / quote-neutral
Watchlist: {len(symbols)} symbols loaded
Live Quotes: Disabled for daily report speed
Note: Use /global, /marketbrief, /watchlist movers, or /ticker SYMBOL for live market context.
""".strip()

    changes = [item["change_percent"] for item in movers]
    positive = len([change for change in changes if change > 0])
    negative = len([change for change in changes if change < 0])
    average = sum(changes) / len(changes)

    strongest = max(movers, key=lambda item: item["change_percent"])
    weakest = min(movers, key=lambda item: item["change_percent"])

    return f"""
Tone: {build_market_tone(movers)}
Breadth: {positive} up / {negative} down / {len(movers)} live
Avg Move: {format_percent(average)}
Strongest: {strongest["symbol"]} {format_percent(strongest["change_percent"])}
Weakest: {weakest["symbol"]} {format_percent(weakest["change_percent"])}
""".strip()


def build_watchlist_snapshot(symbols: list[str], movers: list[dict]) -> str:
    if not symbols:
        return "Watchlist unavailable."

    if not movers:
        return f"{len(symbols)} symbols loaded. Live movement is disabled in /report fast mode."

    return "\n".join(
        f"• {item['symbol']}: {format_price(item['price'])} ({format_percent(item['change_percent'])})"
        for item in movers[:MAX_WATCHLIST_MOVERS]
    )


def safe_morning_brief_intro() -> str:
    try:
        from src.reports.morning_brief_intro import build_morning_brief_intro

        return build_morning_brief_intro()
    except Exception as error:
        return f"""
Good morning.

Morning brief intro is unavailable right now.

Reason:
{type(error).__name__}
""".strip()


def safe_earnings_economic_calendar() -> str:
    try:
        from src.reports.earnings_economic_calendar import (
            build_earnings_economic_calendar_section,
        )

        return build_earnings_economic_calendar_section()
    except Exception as error:
        return f"""
Earnings and Economic Calendar

Calendar section unavailable right now.

Reason:
{type(error).__name__}
""".strip()


def load_global_context() -> dict:
    """
    Fast daily-report macro context.

    Do not call live network data here.
    Live macro/headline data belongs in /global and /headlines only.
    This keeps /report, /testdaily, scheduled daily reports, and deployment preflight fast.
    """
    return {
        "snapshot": [],
        "headlines": [],
        "headline_themes": [],
        "regime": "Fast Daily Mode",
        "nasdaq": 0.0,
        "vix": 0.0,
        "tlt": 0.0,
        "dollar": 0.0,
        "oil": 0.0,
        "gold": 0.0,
        "china": 0.0,
        "eem": 0.0,
    }


def get_macro_pressure(context: dict) -> str:
    pressures = []

    if context["vix"] > 5:
        pressures.append("volatility rising")

    if context["nasdaq"] < -0.75:
        pressures.append("growth pressure")

    if context["tlt"] < -0.75 and context["dollar"] > 0.5:
        pressures.append("rates/dollar pressure")

    if context["oil"] > 2:
        pressures.append("oil/inflation pressure")

    if context["china"] < -1 or context["eem"] < -1:
        pressures.append("global risk weakness")

    if not pressures:
        return "no major macro pressure"

    return ", ".join(pressures[:3])


def category_macro_note(category: str, context: dict) -> str:
    category_upper = category.upper()

    if "AI" in category_upper or "SEMICONDUCTOR" in category_upper or "TECH" in category_upper:
        if context["nasdaq"] < -0.75 or (context["tlt"] < -0.75 and context["dollar"] > 0.5):
            return "Macro check: growth and AI may face pressure from rates, dollar strength, or Nasdaq weakness."
        return "Macro check: growth backdrop is acceptable if Nasdaq support holds."

    if "DEFENSE" in category_upper or "DRONE" in category_upper or "WARFARE" in category_upper:
        if "Defense / Geopolitical" in context.get("headline_themes", []):
            return "Macro check: geopolitical headlines may support defense interest."
        return "Macro check: defense exposure remains more event-driven than index-driven."

    if "CYBER" in category_upper:
        return "Macro check: cybersecurity can hold up better if enterprise security spending remains resilient."

    if "ENERGY" in category_upper or "OIL" in category_upper or "POWER" in category_upper:
        if context["oil"] > 2:
            return "Macro check: oil strength may support energy exposure but can pressure inflation expectations."
        return "Macro check: energy needs commodity confirmation."

    if "DIVIDEND" in category_upper or "UTILITY" in category_upper or "INCOME" in category_upper:
        if context["vix"] > 5:
            return "Macro check: defensive income names may matter more if volatility keeps rising."
        return "Macro check: income exposure remains useful as portfolio ballast."

    return f"Macro check: current backdrop shows {get_macro_pressure(context)}."


def build_global_portfolio_impact(context: dict, top_scores: list[dict]) -> str:
    regime = context.get("regime", "Unavailable")
    pressure = get_macro_pressure(context)

    affected = []

    for item in top_scores:
        ticker = get_ticker(item)
        category = get_category(item).upper()

        if "AI" in category or "SEMICONDUCTOR" in category or "TECH" in category:
            if context["nasdaq"] < -0.75 or (context["tlt"] < -0.75 and context["dollar"] > 0.5):
                affected.append(f"{ticker}: watch rates/dollar pressure on growth.")
        elif "ENERGY" in category or "OIL" in category or "POWER" in category:
            if context["oil"] > 2:
                affected.append(f"{ticker}: oil strength may help, but inflation risk rises.")
        elif "DEFENSE" in category or "DRONE" in category or "WARFARE" in category:
            if "Defense / Geopolitical" in context.get("headline_themes", []):
                affected.append(f"{ticker}: geopolitical headlines may increase attention.")
        elif "DIVIDEND" in category or "UTILITY" in category or "INCOME" in category:
            if context["vix"] > 5:
                affected.append(f"{ticker}: defensive role improves if volatility stays elevated.")

    if not affected:
        affected.append("No direct macro hit to top ideas; focus on confirmation, sizing, and price action.")

    impact_lines = "\n".join(f"• {line}" for line in affected[:3])
    themes = ", ".join(context.get("headline_themes", [])) or "Use /global and /headlines for live themes"

    return f"""
Regime: {regime}
Pressure: {pressure}

Portfolio Impact
{impact_lines}

Headline Themes: {themes}
""".strip()


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
{chr(10).join(lines[:4])}
""".strip()


def build_opportunity_why(item: dict, context: dict) -> str:
    ticker = get_ticker(item)
    label = get_smart_money_label(item)
    signal = get_signal_strength(item)
    fit = get_portfolio_fit(item)
    action = get_action_label(item)
    volume = get_volume_label(item)
    category = get_category(item)
    strength = item.get("strength") or first_list_text(
        item.get("strengths", []),
        "The setup has a developing thesis but needs confirmation.",
        130,
    )
    weakness = item.get("weakness") or first_list_text(
        item.get("weaknesses") or item.get("risks"),
        "Risk still needs review.",
        120,
    )
    macro_note = category_macro_note(category, context)

    return (
        f"{ticker} is showing a {label.lower()} profile with {signal.lower()} confirmation. "
        f"It fits as {fit.lower()} and current action is {action}. "
        f"Volume read: {volume}. Main support: {strength} "
        f"Main watch-out: {weakness} {macro_note}"
    )


def format_opportunity(index: int, item: dict, context: dict) -> str:
    ticker = get_ticker(item)
    label = get_smart_money_label(item)
    action = get_action_label(item)
    risk = get_risk_label(item)
    category = get_category(item)

    why = clean_text(build_opportunity_why(item, context), 360)

    return (
        f"{index}. {ticker} — {label}\n"
        f"   Action: {action} | Risk: {risk}\n"
        f"   Theme: {category}\n"
        f"   Why: {why}"
    )


def build_top_opportunities(
    top_scores: list[dict],
    context: dict,
    scoring_error: str = "",
) -> str:
    if top_scores:
        return "\n\n".join(
            format_opportunity(index, item, context)
            for index, item in enumerate(top_scores, start=1)
        )

    if scoring_error:
        return f"Scoring unavailable: {scoring_error}"

    return "No scoring opportunities available."


def build_risk_notes(top_scores: list[dict], movers: list[dict], context: dict) -> str:
    notes = []

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

    if context["vix"] > 5:
        notes.append("Volatility is rising; avoid chasing extended entries.")

    if context["tlt"] < -0.75 and context["dollar"] > 0.5:
        notes.append("Rates/dollar pressure can hurt long-duration growth names.")

    if elevated_risk:
        notes.append(
            "Tighter sizing needed on elevated-risk names: "
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

def build_weekly_calendar_pointer() -> str:
    return """
Weekly Calendar:
Full earnings and economic calendar moved to /weeklycalendar.

Today’s focus:
• Use /weeklycalendar for CPI, PPI, retail sales, jobless claims, housing, sentiment, and major earnings.
• Use /headlines for current market-moving headlines.
• Use /global for live macro risk and market regime.
""".strip()


def build_executive_summary(
    top_scores: list[dict],
    movers: list[dict],
    market_tone: str,
    context: dict,
) -> str:
    best = top_scores[0] if top_scores else None
    biggest_mover = movers[0] if movers else None
    pressure = get_macro_pressure(context)

    lines = [
        f"• Market tone: {market_tone}.",
        f"• Global pressure: {pressure}.",
    ]

    if best:
        lines.append(
            f"• Best setup: {get_ticker(best)} — {get_smart_money_label(best)}; "
            f"next step is {get_action_label(best).lower()}."
        )

    if biggest_mover:
        lines.append(
            f"• Biggest live move: {biggest_mover['symbol']} "
            f"{format_percent(biggest_mover['change_percent'])}."
        )

    return "\n".join(lines)


def build_clean_ai_summary(
    top_scores: list[dict],
    movers: list[dict],
    market_tone: str,
    context: dict,
) -> str:
    best = top_scores[0] if top_scores else None
    second = top_scores[1] if len(top_scores) > 1 else None
    pressure = get_macro_pressure(context)

    if not best:
        return (
            f"The portfolio tone is {market_tone.lower()} with {pressure}. "
            "There is no clear top setup yet, so the better move is to wait for confirmation."
        )

    summary = (
        f"The portfolio read is {market_tone.lower()} with {pressure}. "
        f"{get_ticker(best)} is the cleanest setup because it combines a "
        f"{get_smart_money_label(best).lower()} profile, {get_signal_strength(best).lower()} confirmation, "
        f"and a {get_portfolio_fit(best).lower()} role."
    )

    if second:
        summary += (
            f" {get_ticker(second)} is the secondary watch, but action should depend on volume, "
            "risk level, and whether the broader market confirms."
        )

    if movers:
        summary += (
            f" The largest live move is {movers[0]['symbol']} at "
            f"{format_percent(movers[0]['change_percent'])}, which should be checked before acting."
        )

    return summary


def build_action_checklist(
    top_scores: list[dict],
    movers: list[dict],
    context: dict,
) -> str:
    actions = []

    best = top_scores[0] if top_scores else None

    if best:
        ticker = get_ticker(best)
        actions.append(f"Run /scorecard {ticker} before making any decision.")
        actions.append(f"Confirm live demand with /volume {ticker}.")
    else:
        actions.append("Wait for a cleaner Smart Money setup before acting.")

    if movers:
        actions.append(f"Review the biggest mover: /ticker {movers[0]['symbol']}.")

    if context["vix"] > 5 or context["tlt"] < -0.75:
        actions.append("Keep position size conservative until volatility/rates cool.")
    else:
        actions.append("Use /top10 to compare the top three opportunities.")

    return "\n".join(f"• {action}" for action in actions[:4])


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
    global_context = load_global_context()

    morning_brief_intro = build_morning_brief_intro()

    executive_summary = build_executive_summary(
        top_scores=top_scores,
        movers=movers,
        market_tone=market_tone,
        context=global_context,
    )

    return f"""
📊 Smart Money AI Daily Report
Daily Brief
Date: {today}
Generated: {timestamp} {REPORT_TIMEZONE}

{morning_brief_intro}

Executive Summary
{executive_summary}

Market Snapshot
{build_market_snapshot(watchlist_symbols, movers)}


Watchlist Movers
{build_watchlist_snapshot(watchlist_symbols, movers)}

Global Portfolio Impact
{build_global_portfolio_impact(global_context, top_scores)}

Smart Money Rating Summary
{build_score_summary(scores)}

Top Opportunities
{build_top_opportunities(top_scores, global_context, scoring_error)}

Risk Notes
{build_risk_notes(top_scores, movers, global_context)}

AI Summary
{build_clean_ai_summary(top_scores, movers, market_tone, global_context)}

Action Checklist
{build_action_checklist(top_scores, movers, global_context)}

Next Commands
/global
/headlines
/top10
/scorecard SYMBOL
/watchlist movers

Notes
Informational only. Not financial advice.
""".strip()