"""Independent settings for the fast, event-driven Telegram monitor."""

from __future__ import annotations

import math
import os
import re


def number(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if math.isfinite(value) and minimum <= value <= maximum else default
    except (TypeError, ValueError):
        return default


def settings() -> dict:
    raw = os.getenv("SPECIAL_ALERT_SYMBOLS", "TSLA,NVDA,MSFT,AVGO,PLTR,AVAV,KTOS,CRWD")
    symbols = list(dict.fromkeys(item.strip().upper() for item in raw.split(",")
                                if re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,9}", item.strip())))[:20]
    sp = number("SPECIAL_ALERT_SP500_DROP", 1.5, 0.1, 30)
    nasdaq = number("SPECIAL_ALERT_NASDAQ_DROP", 2.0, 0.1, 30)
    return {
        "enabled": os.getenv("SPECIAL_ALERTS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"},
        "symbols": symbols,
        "top_count": int(number("SPECIAL_ALERT_TOP_COUNT", 10, 0, 10)),
        "interval": int(number("SPECIAL_ALERT_INTERVAL_SECONDS", 300, 60, 3600)),
        "max_quote_age": number("SPECIAL_ALERT_MAX_QUOTE_AGE_SECONDS", 1200, 60, 1800),
        "news_hours": number("SPECIAL_ALERT_NEWS_MAX_HOURS", 6, 0.25, 24),
        "sp_drop": sp, "nasdaq_drop": nasdaq,
        "sp_severe": max(sp, number("SPECIAL_ALERT_SP500_SEVERE_DROP", 3.0, 0.1, 40)),
        "nasdaq_severe": max(nasdaq, number("SPECIAL_ALERT_NASDAQ_SEVERE_DROP", 4.0, 0.1, 40)),
        "sp_two_day": number("SPECIAL_ALERT_SP500_TWO_SESSION_DROP", 3.0, 0.1, 40),
        "nasdaq_two_day": number("SPECIAL_ALERT_NASDAQ_TWO_SESSION_DROP", 4.0, 0.1, 40),
    }
