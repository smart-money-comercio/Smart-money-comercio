"""Separate pre-open risk inputs and limits; regular-session rules are unchanged."""

import os
from src.config.special_alerts import number

SYMBOLS = ("SPY","QQQ","SMH","NQ=F","ES=F","NVDA","AMD","AVGO","ARM","QCOM","MSFT","TSLA","PLTR")
CHIPS = ("NVDA","AMD","AVGO","ARM","QCOM")


def settings():
    return {"enabled":os.getenv("PREMARKET_ENABLED","true").lower().strip() not in {"0","false","off","no"},
            "max_age":int(number("PREMARKET_MAX_QUOTE_AGE_SECONDS",900,300,900)),
            "chip_gap":number("PREMARKET_CHIP_GAP_PERCENT",3,2,10),
            "tech_gap":number("PREMARKET_TECH_GAP_PERCENT",.75,.5,3),
            "broad_gap":number("PREMARKET_BROAD_GAP_PERCENT",.75,.5,3)}
