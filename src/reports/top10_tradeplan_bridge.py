from src.reports.tradeplan_language import build_tradeplan_snapshot_card
from src.scoring.scoring_engine import get_stock_scores


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

    cards = [
        build_tradeplan_snapshot_card(stock, index)
        for index, stock in enumerate(selected, start=1)
    ]

    return f"""
Trade Plan Snapshot
Quick action reads for the highest-ranked Smart Money ideas. These are not buy signals by themselves; they show what needs confirmation before acting.

{chr(10).join(chr(10) + card for card in cards)}

More Detail:
/tradeplans
/tradeplan SYMBOL
""".strip()