from datetime import datetime, timezone
from typing import Any

from src.insiders.insider_data import get_insider_trades_for_symbol


NEUTRAL_SCORE = 50.0
MIN_SCORE = 0.0
MAX_SCORE = 100.0

WHALE_PURCHASE_MIN = 250_000
MAJOR_WHALE_PURCHASE_MIN = 1_000_000
MEGA_WHALE_PURCHASE_MIN = 5_000_000


ROLE_WEIGHTS = {
    "CEO": 1.35,
    "CHIEF EXECUTIVE": 1.35,
    "CFO": 1.25,
    "CHIEF FINANCIAL": 1.25,
    "COO": 1.15,
    "PRESIDENT": 1.15,
    "DIRECTOR": 1.10,
    "10% OWNER": 1.05,
    "OFFICER": 1.00,
}


def clean_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("$", "")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def clamp_score(value: Any) -> float:
    score = safe_float(value, NEUTRAL_SCORE)
    return max(MIN_SCORE, min(MAX_SCORE, score))


def parse_date(value: Any):
    text = str(value or "").strip()

    if not text:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def days_old(trade: dict) -> int:
    date = parse_date(
        trade.get("filing_date")
        or trade.get("date")
        or trade.get("transaction_date")
    )

    if not date:
        return 365

    return max(0, (datetime.now(timezone.utc) - date).days)


def recency_weight(trade: dict) -> float:
    age = days_old(trade)

    if age <= 7:
        return 1.40
    if age <= 30:
        return 1.20
    if age <= 90:
        return 1.00
    if age <= 180:
        return 0.60

    return 0.25


def role_weight(trade: dict) -> float:
    role = str(trade.get("role") or "").upper()

    for keyword, weight in ROLE_WEIGHTS.items():
        if keyword in role:
            return weight

    return 0.90


def value_weight(trade: dict) -> float:
    value = safe_float(trade.get("value"), 0)

    if value >= 5_000_000:
        return 1.45
    if value >= 1_000_000:
        return 1.30
    if value >= 250_000:
        return 1.15
    if value >= 50_000:
        return 1.00
    if value > 0:
        return 0.75

    shares = safe_float(trade.get("shares"), 0)

    if shares >= 100_000:
        return 1.00
    if shares > 0:
        return 0.65

    return 0.50


def is_open_market_purchase(trade: dict) -> bool:
    code = str(trade.get("transaction_code") or "").upper()
    signal = str(trade.get("signal") or "").lower()

    return code == "P" or "purchase" in signal


def classify_whale_purchase(value: float) -> str:
    if value >= MEGA_WHALE_PURCHASE_MIN:
        return "Mega Whale Buy"
    if value >= MAJOR_WHALE_PURCHASE_MIN:
        return "Major Whale Buy"
    if value >= WHALE_PURCHASE_MIN:
        return "Whale Buy"

    return "Standard Buy"


def get_whale_purchases(trades: list[dict]) -> list[dict]:
    whales = []

    for trade in trades or []:
        if not is_open_market_purchase(trade):
            continue

        value = safe_float(trade.get("value"), 0)

        if value < WHALE_PURCHASE_MIN:
            continue

        whale_trade = dict(trade)
        whale_trade["whale_label"] = classify_whale_purchase(value)
        whale_trade["whale_value"] = value
        whales.append(whale_trade)

    return sorted(
        whales,
        key=lambda trade: safe_float(trade.get("whale_value"), 0),
        reverse=True,
    )


def build_whale_purchase_summary(trades: list[dict]) -> dict:
    whales = get_whale_purchases(trades)

    total_value = sum(
        safe_float(trade.get("value"), 0)
        for trade in whales
    )

    unique_buyers = {
        str(trade.get("insider_name") or trade.get("insider") or "").upper()
        for trade in whales
        if trade.get("insider_name") or trade.get("insider")
    }

    mega_count = len(
        [
            trade
            for trade in whales
            if safe_float(trade.get("value"), 0) >= MEGA_WHALE_PURCHASE_MIN
        ]
    )

    major_count = len(
        [
            trade
            for trade in whales
            if safe_float(trade.get("value"), 0) >= MAJOR_WHALE_PURCHASE_MIN
        ]
    )

    cluster_whale = len(unique_buyers) >= 2 and total_value >= MAJOR_WHALE_PURCHASE_MIN

    if mega_count:
        label = "Mega Whale Buying"
    elif major_count:
        label = "Major Whale Buying"
    elif cluster_whale:
        label = "Cluster Whale Buying"
    elif whales:
        label = "Whale Buying"
    else:
        label = "No Whale Buying"

    return {
        "label": label,
        "count": len(whales),
        "mega_count": mega_count,
        "major_count": major_count,
        "cluster_whale": cluster_whale,
        "unique_buyers": len(unique_buyers),
        "total_value": round(total_value, 2),
        "top_whales": whales[:3],
    }


def transaction_points(trade: dict) -> float:
    code = str(trade.get("transaction_code") or "").upper()
    signal = str(trade.get("signal") or "").lower()

    if code == "P" or "purchase" in signal:
        base = 12.0
    elif code == "S" or signal == "sale":
        base = -6.0
    elif code == "F" or "withholding" in signal:
        base = -1.5
    elif code == "M" or "exercise" in signal:
        base = 1.0
    elif code == "A" or "award" in signal or "grant" in signal:
        base = 0.5
    elif code == "G" or "gift" in signal:
        base = 0.0
    else:
        base = 0.0

    return base * recency_weight(trade) * role_weight(trade) * value_weight(trade)


def get_signal_breakdown(trades: list[dict]) -> dict:
    purchases = [
        trade
        for trade in trades
        if is_open_market_purchase(trade)
    ]

    sales = [
        trade
        for trade in trades
        if str(trade.get("transaction_code") or "").upper() == "S"
        or str(trade.get("signal") or "").lower() == "sale"
    ]

    tax_sales = [
        trade
        for trade in trades
        if str(trade.get("transaction_code") or "").upper() == "F"
    ]

    awards = [
        trade
        for trade in trades
        if str(trade.get("transaction_code") or "").upper() in {"A", "M"}
    ]

    total_purchase_value = sum(safe_float(trade.get("value"), 0) for trade in purchases)
    total_sale_value = sum(safe_float(trade.get("value"), 0) for trade in sales)
    total_tax_value = sum(safe_float(trade.get("value"), 0) for trade in tax_sales)

    unique_buyers = {
        str(trade.get("insider_name") or trade.get("insider") or "").upper()
        for trade in purchases
        if trade.get("insider_name") or trade.get("insider")
    }

    unique_sellers = {
        str(trade.get("insider_name") or trade.get("insider") or "").upper()
        for trade in sales
        if trade.get("insider_name") or trade.get("insider")
    }

    whale_summary = build_whale_purchase_summary(trades)

    return {
        "purchases": len(purchases),
        "sales": len(sales),
        "tax_sales": len(tax_sales),
        "awards": len(awards),
        "total_purchase_value": round(total_purchase_value, 2),
        "total_sale_value": round(total_sale_value, 2),
        "total_tax_value": round(total_tax_value, 2),
        "unique_buyers": len(unique_buyers),
        "unique_sellers": len(unique_sellers),
        "whale_label": whale_summary["label"],
        "whale_purchases": whale_summary["count"],
        "whale_buyers": whale_summary["unique_buyers"],
        "whale_purchase_value": whale_summary["total_value"],
        "major_whale_purchases": whale_summary["major_count"],
        "mega_whale_purchases": whale_summary["mega_count"],
        "cluster_whale_buying": whale_summary["cluster_whale"],
        "top_whales": whale_summary["top_whales"],
    }


def classify_insider_label(score: float) -> str:
    score = clamp_score(score)

    if score >= 75:
        return "Strong Insider Buying"
    if score >= 65:
        return "Positive Insider Signal"
    if score >= 55:
        return "Slightly Positive"
    if score >= 45:
        return "Neutral / Mixed"
    if score >= 35:
        return "Insider Selling Pressure"

    return "Heavy Insider Selling"


def build_insider_score_details(ticker: str, force_refresh: bool = False) -> dict:
    symbol = clean_symbol(ticker)

    if not symbol:
        return {
            "ticker": "UNKNOWN",
            "score": NEUTRAL_SCORE,
            "label": "Neutral / Mixed",
            "reason": "No ticker provided.",
            "trades": [],
            "breakdown": get_signal_breakdown([]),
        }

    trades = get_insider_trades_for_symbol(symbol, force_refresh=force_refresh)

    breakdown = get_signal_breakdown(trades)

    if not trades:
        return {
            "ticker": symbol,
            "score": NEUTRAL_SCORE,
            "label": "Neutral / Mixed",
            "reason": "No recent SEC Form 4 purchase or sale signal found.",
            "trades": [],
            "breakdown": breakdown,
        }

    raw_points = sum(transaction_points(trade) for trade in trades)
    confirmation_bonus = 0.0

    if breakdown["unique_buyers"] >= 2:
        confirmation_bonus += 5.0

    if breakdown["purchases"] >= 2:
        confirmation_bonus += 4.0

    if breakdown["total_purchase_value"] >= 1_000_000:
        confirmation_bonus += 4.0

    if breakdown.get("mega_whale_purchases", 0) >= 1:
        confirmation_bonus += 9.0
    elif breakdown.get("major_whale_purchases", 0) >= 1:
        confirmation_bonus += 6.0
    elif breakdown.get("whale_purchases", 0) >= 1:
        confirmation_bonus += 3.0

    if breakdown.get("cluster_whale_buying"):
        confirmation_bonus += 5.0

    if breakdown["unique_sellers"] >= 3 and breakdown["total_sale_value"] > breakdown["total_purchase_value"]:
        confirmation_bonus -= 5.0

    if breakdown["sales"] >= 4 and breakdown["purchases"] == 0:
        confirmation_bonus -= 4.0

    score = clamp_score(NEUTRAL_SCORE + raw_points + confirmation_bonus)
    label = classify_insider_label(score)

    reason_parts = []

    if breakdown["purchases"]:
        purchase_reason = (
            f"{breakdown['purchases']} purchase(s) from "
            f"{breakdown['unique_buyers']} buyer(s)"
        )

        if breakdown.get("whale_purchases", 0):
            purchase_reason += (
                f", including {breakdown['whale_purchases']} whale purchase(s) "
                f"totaling ${breakdown.get('whale_purchase_value', 0):,.0f}"
            )

        reason_parts.append(purchase_reason)

    if breakdown["sales"]:
        reason_parts.append(
            f"{breakdown['sales']} sale(s) from {breakdown['unique_sellers']} seller(s)"
        )

    if breakdown["tax_sales"]:
        reason_parts.append(f"{breakdown['tax_sales']} tax/withholding transaction(s)")

    if not reason_parts:
        reason_parts.append("activity is mostly neutral grants, awards, or option exercises")

    reason = (
        f"{label}: "
        + "; ".join(reason_parts)
        + ". Open-market purchases and whale buys carry the most weight; routine sales and tax withholding are discounted."
    )

    return {
        "ticker": symbol,
        "score": round(score, 1),
        "label": label,
        "reason": reason,
        "trades": trades,
        "breakdown": breakdown,
        "raw_points": round(raw_points, 2),
        "confirmation_bonus": round(confirmation_bonus, 2),
    }


def get_insider_score(ticker: str) -> float:
    """
    Backward-compatible function used by scoring_engine.py.

    This must remain fast/cache-only because it is called during:
    - /report
    - /top10
    - /scorecard
    - deployment preflight
    """
    details = build_insider_score_details(ticker, force_refresh=False)
    return clamp_score(details.get("score", NEUTRAL_SCORE))

score_insider_activity = get_insider_score
get_insider_signal = build_insider_score_details