from datetime import datetime

from src.reports.tradeplan_report import (
    action_bias,
    clean_symbol,
    conviction_level,
    get_category,
    get_score,
    risk_level,
)
from src.scoring.scoring_engine import get_stock_scores


def safe_int(value, default: int = 10) -> int:
    try:
        return int(value)
    except Exception:
        return default


def clamp_limit(value, minimum: int = 3, maximum: int = 20, default: int = 10) -> int:
    limit = safe_int(value, default=default)

    if limit < minimum:
        return minimum

    if limit > maximum:
        return maximum

    return limit


def display_score(value) -> str:
    try:
        score = float(value)
    except Exception:
        return "N/A"

    if score.is_integer():
        return str(int(score))

    return str(round(score, 1))


def entry_style(score: float) -> str:
    if score >= 90:
        return "Buy only on confirmation; avoid chasing."
    if score >= 82:
        return "Use pullbacks or confirmed strength."
    if score >= 75:
        return "Watch for volume and price confirmation."
    if score >= 65:
        return "Research first; wait for a cleaner setup."
    return "Low priority until the setup improves."


def validation_focus(score: float, category: str) -> str:
    category_text = str(category or "").lower()

    if "defense" in category_text or "drone" in category_text or "cyber" in category_text:
        return "Confirm defense theme strength, news flow, and risk."

    if "ai" in category_text or "semiconductor" in category_text:
        return "Confirm AI demand, volume, and macro/rate pressure."

    if score >= 85:
        return "Confirm score quality, volume, and news context."

    return "Confirm risk, price action, and thesis quality."


def build_tradeplan_snapshot(stock: dict, index: int) -> str:
    ticker = clean_symbol(stock.get("ticker") or stock.get("symbol") or "UNKNOWN")
    score = get_score(stock)
    category = get_category(stock)

    return f"""
{index}. {ticker} — {conviction_level(score)} Conviction
Score: {display_score(score)}/100
Category: {category}
Action Bias: {action_bias(score)}
Risk: {risk_level(score, category)}
Entry Style: {entry_style(score)}
Validation Focus: {validation_focus(score, category)}
Full Plan: /tradeplan {ticker}
""".strip()


def build_tradeplans_report(limit: int = 10) -> str:
    limit = clamp_limit(limit)

    try:
        scores = get_stock_scores()
    except Exception as error:
        return f"""
🎯 Smart Money Top Trade Plans

Status: unavailable right now.

Error: {type(error).__name__}: {error}

Research only. Not financial advice.
""".strip()

    if not scores:
        return """
🎯 Smart Money Top Trade Plans

Status: No score data available.

Try:
/top10
/stock NVDA
/tradeplan NVDA

Research only. Not financial advice.
""".strip()

    selected = scores[:limit]

    snapshots = "\n\n".join(
        build_tradeplan_snapshot(stock, index)
        for index, stock in enumerate(selected, start=1)
    )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""
🎯 Smart Money Top Trade Plans

Purpose
This report converts the top Smart Money ideas into simple trade-plan snapshots. It is designed to help decide what deserves attention, what needs confirmation, and what should be avoided until the setup improves.

Top Ideas Reviewed: {len(selected)}

{snapshots}

How To Use This
• Use /tradeplans for the ranked action overview.
• Use /tradeplan SYMBOL for the full plan.
• Confirm with /scorecard, /risk, /volume, /tickernews, and /stockdata before acting.
• Do not treat any single score or headline as a stand-alone buy signal.

Generated: {generated_at}

Research only. Not financial advice.
""".strip()