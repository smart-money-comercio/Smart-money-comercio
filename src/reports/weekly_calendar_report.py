import os
from datetime import datetime
from zoneinfo import ZoneInfo

from src.reports.live_market_calendar import (
    build_full_market_calendar,
)


REPORT_TIMEZONE = os.getenv(
    "REPORT_TIMEZONE",
    "America/New_York",
)


def build_weekly_calendar_report() -> str:
    now = datetime.now(
        ZoneInfo(REPORT_TIMEZONE)
    )

    today = now.strftime(
        "%B %d, %Y"
    )

    timestamp = now.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    calendar_section = (
        build_full_market_calendar()
    )

    return f"""
Smart Money AI Weekly Calendar
Earnings and Economic Week Ahead
Date: {today}
Generated: {timestamp} {REPORT_TIMEZONE}

{calendar_section}

Research only. Not financial advice.
""".strip()
