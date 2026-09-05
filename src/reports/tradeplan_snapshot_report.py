from src.reports.tradeplan_language import (
    action_bias,
    build_tradeplan_daily_line,
    build_tradeplan_short_line,
    build_tradeplan_snapshot_card,
    clean_symbol,
    conviction_level,
    entry_style,
    find_stock,
    get_category,
    get_score,
    risk_level,
    validation_focus,
)


def entry_style(score: float) -> str:
    if score >= 90:
        return "Buy only on confirmation; avoid chasing extended moves."

    if score >= 82:
        return "Use pullbacks or confirmed strength."

    if score >= 75:
        return "Watch for volume, price, and news confirmation."

    if score >= 65:
        return "Research first; wait for a cleaner setup."

    return "Low priority until the setup improves."


def validation_focus(score: float, category: str) -> str:
    category_text = str(category or "").lower()

    if "defense" in category_text or "drone" in category_text or "cyber" in category_text:
        return "Confirm defense theme strength, news flow, volume, and risk."

    if "ai" in category_text or "semiconductor" in category_text:
        return "Confirm AI demand, volume, external rating support, and macro/rate pressure."

    if score >= 85:
        return "Confirm score quality, volume, news context, and risk."

    return "Confirm risk, price action, and thesis quality."


def build_tradeplan_snapshot_section(symbol: str) -> str:
    ticker = clean_symbol(symbol)

    if not ticker:
        return """
Trade Plan Snapshot
Status: No symbol provided.
Full Plan: /tradeplan SYMBOL
""".strip()

    stock = find_stock(ticker)

    if not stock:
        return f"""
Trade Plan Snapshot
Action Bias: Not enough internal score data
Conviction: Low
Risk Level: Unknown
Entry Style: Research first. Do not force a setup without score coverage.
Validation Focus: Confirm with /stockdata {ticker}, /tickernews {ticker}, and /quote {ticker}.
Full Plan: /tradeplan {ticker}
""".strip()

    score = get_score(stock)
    category = get_category(stock)

    return f"""
Trade Plan Snapshot
Action Bias: {action_bias(score)}
Conviction: {conviction_level(score)}
Risk Level: {risk_level(score, category)}
Entry Style: {entry_style(score)}
Validation Focus: {validation_focus(score, category)}
Full Plan: /tradeplan {ticker}
""".strip()