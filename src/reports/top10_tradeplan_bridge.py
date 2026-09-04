from src.reports.tradeplan_report import (
    action_bias,
    clean_symbol,
    conviction_level,
    get_category,
    get_score,
    risk_level,
)
from src.scoring.scoring_engine import get_stock_scores


def compact_score(score: float) -> str:
    try:
        score = float(score)
    except Exception:
        return "N/A"

    if score.is_integer():
        return str(int(score))

    return str(round(score, 1))


def build_top10_tradeplan_line(stock: dict, index: int) -> str:
    ticker = clean_symbol(stock.get("ticker") or stock.get("symbol") or "UNKNOWN")
    score = get_score(stock)
    category = get_category(stock)

    return (
        f"{index}. {ticker} — {conviction_level(score)} Conviction\n"
        f"Score: {compact_score(score)}/100\n"
        f"Action Bias: {action_bias(score)}\n"
        f"Risk: {risk_level(score, category)}\n"
        f"Full Plan: /tradeplan {ticker}"
    )


def build_top10_tradeplan_snapshot_section(limit: int = 5) -> str:
    try:
        scores = get_stock_scores()
    except Exception:
        scores = []

    if not scores:
        return """
Trade Plan Snapshot
Status: No score data available.
Use /tradeplans after score data refreshes.
""".strip()

    selected = scores[: max(1, min(int(limit or 5), 10))]

    lines = [
        build_top10_tradeplan_line(stock, index)
        for index, stock in enumerate(selected, start=1)
    ]

    return f"""
Trade Plan Snapshot
These are quick action reads for the highest-ranked Smart Money ideas. Use the full command before acting.

{chr(10).join(chr(10) + line for line in lines)}

More Detail:
/tradeplans
/tradeplan SYMBOL
""".strip()