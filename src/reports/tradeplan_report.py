from datetime import datetime

from src.reports.tradeplan_language import (
    action_bias,
    clean_symbol,
    conviction_level,
    entry_style,
    find_stock,
    get_category,
    get_score,
    risk_level,
    safe_number,
    validation_focus,
)


def display_score(value) -> str:
    score = safe_number(value, default=0)

    if score <= 0:
        return "N/A"

    if score.is_integer():
        return f"{int(score)}/100"

    return f"{round(score, 1)}/100"


def setup_style(score: float) -> str:
    return entry_style(score)


def score_drivers(stock: dict) -> list[str]:
    drivers = []

    smart_score = safe_number(stock.get("smart_score"), default=0)
    defense_score = safe_number(stock.get("defense_score"), default=0)
    congress_score = safe_number(stock.get("congress_score"), default=0)
    insider_score = safe_number(stock.get("insider_score"), default=0)

    if smart_score >= 80:
        drivers.append("strong Smart Money score support")

    if defense_score >= 70:
        drivers.append("defense / AI warfare theme support")

    if congress_score > 0:
        drivers.append("congressional trading signal support")

    if insider_score > 0:
        drivers.append("insider activity signal support")

    if not drivers:
        drivers.append("mixed signal support that needs more confirmation")

    return drivers


def format_driver_sentence(drivers: list[str]) -> str:
    if not drivers:
        return "The setup needs more confirmation."

    if len(drivers) == 1:
        return f"The main support factor is {drivers[0]}."

    if len(drivers) == 2:
        return f"The main support factors are {drivers[0]} and {drivers[1]}."

    return f"The main support factors are {', '.join(drivers[:-1])}, and {drivers[-1]}."


def build_confirmation_checklist(symbol: str) -> str:
    return f"""
[ ] /scorecard {symbol} confirms the total Smart Money score is still strong.
[ ] /risk {symbol} shows risk is acceptable before entry.
[ ] /volume {symbol} confirms money flow is improving.
[ ] /tickernews {symbol} shows no major negative headline shift.
[ ] /stockdata {symbol} supports the thesis with external fundamentals or analyst context.
""".strip()


def build_score_breakdown(stock: dict) -> str:
    return f"""
Overall Score: {display_score(stock.get("final_score", stock.get("score")))}
Smart Money Score: {display_score(stock.get("smart_score"))}
Defense Score: {display_score(stock.get("defense_score"))}
Congress Score: {display_score(stock.get("congress_score"))}
Insider Score: {display_score(stock.get("insider_score"))}
""".strip()


def build_missing_tradeplan(symbol: str) -> str:
    return f"""
🎯 Smart Money Trade Plan: {symbol}

Current Read
Action Bias: Not enough score data
Conviction: Low
Risk Level: Unknown
Category: Not found in current scoring universe

Why It Matters
{symbol} is not currently available in the Smart Money scoring engine, so the bot cannot build a full trade plan from internal score data yet.

Entry Plan
Do not force a setup. Add {symbol} to the watchlist or run deeper research first.

Confirmation Checklist
[ ] /stock {symbol}
[ ] /quote {symbol}
[ ] /tickernews {symbol}
[ ] /stockdata {symbol}

Risk Plan
Treat this as research-only until the ticker has score coverage, news context, and risk validation.

Smart Money Verdict
No trade plan is available yet because the internal scoring engine does not have enough data for {symbol}.

Research only. Not financial advice.
""".strip()


def build_tradeplan_report(symbol: str) -> str:
    ticker = clean_symbol(symbol)

    if not ticker or ticker == "UNKNOWN":
        return """
🎯 Smart Money Trade Plan

Usage:
/tradeplan SYMBOL

Examples:
/tradeplan NVDA
/tradeplan PLTR
/tradeplan AVAV

Research only. Not financial advice.
""".strip()

    stock = find_stock(ticker)

    if not stock:
        return build_missing_tradeplan(ticker)

    score = get_score(stock)
    category = get_category(stock)
    drivers = score_drivers(stock)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""
🎯 Smart Money Trade Plan: {ticker}

Current Read
Action Bias: {action_bias(score)}
Conviction: {conviction_level(score)}
Risk Level: {risk_level(score, category)}
Category: {category}

Score Breakdown
{build_score_breakdown(stock)}

Why It Matters
{format_driver_sentence(drivers)} The trade plan should be based on confirmation, not prediction.

Entry Plan
{setup_style(score)}

Preferred Approach
• Start with a small position only after confirmation.
• Add only if price action, volume, and news context improve together.
• Avoid chasing sharp moves after the signal is already extended.

Confirmation Checklist
{build_confirmation_checklist(ticker)}

Validation Focus
{validation_focus(score, category)}

Risk Plan
Invalidation: The setup weakens if score quality falls, volume fades, news turns negative, or the stock loses key support.
Positioning: Keep position size modest until the setup confirms.
Review trigger: Recheck the plan after major earnings, macro news, SEC filings, analyst changes, or unusual volume.

Smart Money Verdict
{ticker} is a {conviction_level(score).lower()}-conviction idea with a {risk_level(score, category).lower()} risk profile. The best approach is to let the setup confirm before acting.

Generated: {generated_at}

Research only. Not financial advice.
""".strip()
