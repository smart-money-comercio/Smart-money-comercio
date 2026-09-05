from datetime import datetime

from src.reports.tradeplan_language import build_tradeplan_snapshot_card
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

    cards = [
        build_tradeplan_snapshot_card(stock, index)
        for index, stock in enumerate(selected, start=1)
    ]

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""
🎯 Smart Money Top Trade Plans

Executive Read
This report turns the highest-ranked Smart Money ideas into simple trade-plan snapshots. Use it to decide what deserves attention, what needs confirmation, and what should wait.

Purpose
The goal is not to chase the highest score. The goal is to match each idea with the right action style: confirm, wait, research, or avoid forcing the setup.

Top Ideas Reviewed: {len(selected)}

Trade Plan Snapshots

{chr(10).join(chr(10) + card for card in cards)}

How To Use This
• Use /tradeplans for the ranked action overview.
• Use /tradeplan SYMBOL for the full plan.
• Confirm with /scorecard, /risk, /volume, /tickernews, and /stockdata before acting.
• Upgrade conviction only when score quality, news context, volume, risk, and external validation agree.
• Do not treat any single score, headline, or analyst rating as a stand-alone buy signal.

Generated: {generated_at}

Research only. Not financial advice.
""".strip()