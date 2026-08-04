import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.portfolio_intelligence_report import build_portfolio_intelligence_report
from src.utils.telegram_messages import edit_or_reply_long_message
from src.scoring.scoring_engine import get_stock_scores
from src.utils.score_display import (
    get_action_label,
    get_category,
    get_portfolio_fit,
    get_risk_label,
    get_smart_money_label,
    get_ticker,
)


async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🧭 Building portfolio intelligence...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_portfolio_intelligence_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="🧭 Portfolio Intelligence",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Portfolio Intelligence\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


# Compatibility alias in case register_commands.py imports portfolio.
async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await portfolio_command(update, context)

def is_dividend_candidate(item: dict) -> bool:
    text = " ".join(
        [
            str(get_category(item) or ""),
            str(get_portfolio_fit(item) or ""),
            str(get_smart_money_label(item) or ""),
            str(item.get("dividend_yield", "")),
            str(item.get("yield", "")),
            str(item.get("income", "")),
        ]
    ).lower()

    return any(
        term in text
        for term in [
            "dividend",
            "income",
            "yield",
            "utility",
            "reit",
            "defensive",
            "stability",
        ]
    )


def score_value(item: dict) -> float:
    for key in [
        "score",
        "total_score",
        "smart_money_score",
        "overall_score",
        "final_score",
        "composite_score",
    ]:
        try:
            if item.get(key) is not None:
                return float(item.get(key))
        except Exception:
            pass

    return 0.0


def build_dividends_report() -> str:
    try:
        raw_scores = get_stock_scores()
    except Exception:
        raw_scores = []

    if isinstance(raw_scores, dict):
        scores = []

        for symbol, value in raw_scores.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("ticker", symbol)
                item.setdefault("symbol", symbol)
                scores.append(item)
    elif isinstance(raw_scores, list):
        scores = [item for item in raw_scores if isinstance(item, dict)]
    else:
        scores = []

    candidates = [item for item in scores if is_dividend_candidate(item)]

    if not candidates:
        candidates = scores[:8]

    candidates = sorted(candidates, key=score_value, reverse=True)[:8]

    if not candidates:
        return """
💵 Dividend / Income Intelligence

Status: No scored dividend or income candidates available right now.

Use:
/portfolio
/top10
/brief
""".strip()

    lines = []

    for index, item in enumerate(candidates, start=1):
        ticker = get_ticker(item)
        score = score_value(item)
        label = get_smart_money_label(item)
        risk = get_risk_label(item)
        action = get_action_label(item)
        category = get_category(item)
        fit = get_portfolio_fit(item)

        lines.append(
            f"{index}. {ticker} — {score:.0f}/100 | {label}\n"
            f"   Category: {category}\n"
            f"   Portfolio Fit: {fit}\n"
            f"   Risk/Action: {risk} | {action}"
        )

    return f"""
💵 Dividend / Income Intelligence

Income Read
Dividend and income candidates should be treated as portfolio ballast, not automatic buys. Prioritize quality, risk control, payout durability, and entry discipline.

Candidates
{chr(10).join(lines)}

Portfolio Use
• Use income names to reduce volatility, not to chase yield.
• Avoid weak scores with high yield unless risk is clearly understood.
• Confirm with /risk SYMBOL and /scorecard SYMBOL before sizing.

Related Commands:
/portfolio
/top10
/brief
""".strip()


async def dividends_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "💵 Building dividend / income intelligence...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_dividends_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="💵 Dividend / Income Intelligence",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Dividend / Income Intelligence\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


# Compatibility alias for register_commands.py
async def dividends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await dividends_command(update, context)

def is_growth_candidate(item: dict) -> bool:
    text = " ".join(
        [
            str(get_category(item) or ""),
            str(get_portfolio_fit(item) or ""),
            str(get_smart_money_label(item) or ""),
            str(item.get("growth", "")),
            str(item.get("momentum", "")),
            str(item.get("category", "")),
            str(item.get("sector", "")),
            str(item.get("industry", "")),
        ]
    ).lower()

    return any(
        term in text
        for term in [
            "growth",
            "ai",
            "technology",
            "tech",
            "semiconductor",
            "software",
            "cloud",
            "automation",
            "mobility",
            "momentum",
            "innovation",
        ]
    )


def build_growth_report() -> str:
    try:
        raw_scores = get_stock_scores()
    except Exception:
        raw_scores = []

    if isinstance(raw_scores, dict):
        scores = []

        for symbol, value in raw_scores.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("ticker", symbol)
                item.setdefault("symbol", symbol)
                scores.append(item)

    elif isinstance(raw_scores, list):
        scores = [item for item in raw_scores if isinstance(item, dict)]

    else:
        scores = []

    candidates = [item for item in scores if is_growth_candidate(item)]

    if not candidates:
        candidates = scores[:8]

    candidates = sorted(candidates, key=score_value, reverse=True)[:8]

    if not candidates:
        return """
🚀 Growth Intelligence

Status: No scored growth candidates available right now.

Use:
/portfolio
/top10
/brief
""".strip()

    lines = []

    for index, item in enumerate(candidates, start=1):
        ticker = get_ticker(item)
        score = score_value(item)
        label = get_smart_money_label(item)
        risk = get_risk_label(item)
        action = get_action_label(item)
        category = get_category(item)
        fit = get_portfolio_fit(item)

        lines.append(
            f"{index}. {ticker} — {score:.0f}/100 | {label}\n"
            f"   Category: {category}\n"
            f"   Portfolio Fit: {fit}\n"
            f"   Risk/Action: {risk} | {action}"
        )

    return f"""
🚀 Growth Intelligence

Growth Read
Growth candidates should be treated as opportunity names, not automatic buys. Prioritize high Smart Money scores, volume confirmation, earnings/catalyst support, and controlled risk.

Candidates
{chr(10).join(lines)}

Portfolio Use
• Use growth names for upside exposure, but avoid chasing stretched moves.
• Confirm with /volume SYMBOL, /earnings SYMBOL, and /risk SYMBOL before sizing.
• Prefer names that also rank well in /top10 and fit the current /portfolio stance.

Related Commands:
/portfolio
/top10
/brief
""".strip()


async def growth_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🚀 Building growth intelligence...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_growth_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="🚀 Growth Intelligence",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Growth Intelligence\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


# Compatibility alias for register_commands.py
async def growth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await growth_command(update, context)