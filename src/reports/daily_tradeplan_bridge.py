from src.reports.tradeplan_language import build_tradeplan_daily_line


def build_daily_tradeplan_snapshot_section(
    stocks: list[dict] | None = None,
    limit: int = 3,
) -> str:
    stocks = [stock for stock in stocks or [] if isinstance(stock, dict)]

    if not stocks:
        return """
Trade Plan Snapshot
No trade-plan candidates available yet. Run /top10 or /tradeplans after the score engine refreshes.
""".strip()

    selected = stocks[: max(1, min(int(limit or 3), 5))]

    lines = [
        build_tradeplan_daily_line(stock, index)
        for index, stock in enumerate(selected, start=1)
    ]

    return f"""
Trade Plan Snapshot
Top action reads from today’s Smart Money list:

{chr(10).join(lines)}

Use /tradeplans for the ranked overview or /tradeplan SYMBOL for the full plan.
""".strip()