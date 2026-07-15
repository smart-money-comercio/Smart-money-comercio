from datetime import datetime
from zoneinfo import ZoneInfo

from src.reports.earnings_economic_calendar import (
    build_earnings_economic_calendar_section,
)


REPORT_TIMEZONE = "America/Lima"


def build_weekly_calendar_report() -> str:
    now = datetime.now(ZoneInfo(REPORT_TIMEZONE))
    today = now.strftime("%B %d, %Y")
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    calendar_section = build_earnings_economic_calendar_section()

    return f"""
📅 Smart Money AI Weekly Calendar
Earnings and Economic Week Ahead
Date: {today}
Generated: {timestamp} {REPORT_TIMEZONE}

{calendar_section}

How To Use This:
• CPI and PPI set the inflation and Fed-rate tone.
• Bank earnings give the first read on credit quality, deposits, trading, and consumer stress.
• ASML and TSM are the most important AI/semi supply-chain reads.
• Retail sales, jobless claims, housing, and sentiment will help confirm whether the consumer is weakening or stabilizing.
• Use /report for the daily portfolio brief and /global for live macro risk.

Next Commands:
/report
/global
/headlines
/top10
/scorecard SYMBOL

Notes
Informational only. Not financial advice.
""".strip()