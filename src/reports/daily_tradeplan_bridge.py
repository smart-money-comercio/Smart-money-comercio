from src.reports.tradeplan_report import (
    action_bias,
    clean_symbol,
    conviction_level,
    get_category,
    get_score,
    risk_level,
)


def compact_score(score: float) -> str:
    try:
        score = float(score)
    except Exception:
        return "N/A"

    if score.is_integer():
        return str(int(score))

    return str(round(score, 1))


def entry_style(score: float) -> str:
    if score >= 90:
        return "Confirm first; do not chase extended strength."

    if score >= 82:
        return "Use pullbacks or confirmed breakouts."

    if score >= 75:
        return "Wait for price and volume confirmation."

    if score >= 65:
        return "Research first; setup is not clean yet."

    return "Low priority until signals improve."


def build_daily_tradeplan_line(stock: dict, index: int) -> str:
    ticker = clean_symbol(stock.get("ticker") or stock.get("symbol") or "UNKNOWN")
    score = get_score(stock)
    category = get_category(stock)

    return (
        f"{index}. {ticker} — {conviction_level(score)} conviction, "
        f"{compact_score(score)}/100, {risk_level(score, category)} risk. "
        f"{action_bias(score)} Entry: {entry_style(score)} Full plan: /tradeplan {ticker}"
    )


def build_daily_tradeplan_snapshot_section(stocks: list[dict] | None = None, limit: int = 3) -> str:
    stocks = [stock for stock in stocks or [] if isinstance(stock, dict)]

    if not stocks:
        return """
Trade Plan Snapshot
No trade-plan candidates available yet. Run /top10 or /tradeplans after the score engine refreshes.
""".strip()

    selected = stocks[: max(1, min(int(limit or 3), 5))]

    lines = [
        build_daily_tradeplan_line(stock, index)
        for index, stock in enumerate(selected, start=1)
    ]

    return f"""
Trade Plan Snapshot
Top action reads from today’s Smart Money list:

{chr(10).join(lines)}

Use /tradeplans for the ranked overview or /tradeplan SYMBOL for the full plan.
""".strip()