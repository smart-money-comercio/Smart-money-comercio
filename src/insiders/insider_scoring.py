from datetime import datetime, timezone
from typing import Any

from src.insiders.insider_data import get_insider_trades_for_symbol


NEUTRAL_SCORE = 50.0
MIN_SCORE = 0.0
MAX_SCORE = 100.0


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
    date = parse_date(trade.get("filing_date") or trade.get("date") or trade.get("transaction_date"))

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


def transaction_points(trade: dict) -> float:
    code = str(trade.get("transaction_code") or "").upper()
    signal = str(trade.get("signal") or "").lower()

    base = 0.0

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
        trade for trade in trades
        if str(trade.get("transaction_code") or "").upper() == "P"
        or "purchase" in str(trade.get("signal") or "").lower()
    ]

    sales = [
        trade for trade in trades
        if str(trade.get("transaction_code") or "").upper() == "S"
        or str(trade.get("signal") or "").lower() == "sale"
    ]

    tax_sales = [
        trade for trade in trades
        if str(trade.get("transaction_code") or "").upper() == "F"
    ]

    awards = [
        trade for trade in trades
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

    return {
        "purchases": len(purchases),
        "sales": len(sales),
        "tax_sales": len(tax_sales),
        "awards": len(awards),
        "total_purchase_value": total_purchase_value,
        "total_sale_value": total_sale_value,
        "total_tax_value": total_tax_value,
        "unique_buyers": len(unique_buyers),
        "unique_sellers": len(unique_sellers),
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
            "breakdown": {},
        }

    trades = get_insider_trades_for_symbol(symbol, force_refresh=force_refresh)

    if not trades:
        return {
            "ticker": symbol,
            "score": NEUTRAL_SCORE,
            "label": "Neutral / Mixed",
            "reason": "No recent SEC Form 4 purchase or sale signal found.",
            "trades": [],
            "breakdown": {
                "purchases": 0,
                "sales": 0,
                "tax_sales": 0,
                "awards": 0,
                "total_purchase_value": 0,
                "total_sale_value": 0,
                "unique_buyers": 0,
                "unique_sellers": 0,
            },
        }

    raw_points = sum(transaction_points(trade) for trade in trades)
    breakdown = get_signal_breakdown(trades)

    confirmation_bonus = 0.0

    if breakdown["unique_buyers"] >= 2:
        confirmation_bonus += 5.0

    if breakdown["purchases"] >= 2:
        confirmation_bonus += 4.0

    if breakdown["total_purchase_value"] >= 1_000_000:
        confirmation_bonus += 4.0

    if breakdown["unique_sellers"] >= 3 and breakdown["total_sale_value"] > breakdown["total_purchase_value"]:
        confirmation_bonus -= 5.0

    if breakdown["sales"] >= 4 and breakdown["purchases"] == 0:
        confirmation_bonus -= 4.0

    score = clamp_score(NEUTRAL_SCORE + raw_points + confirmation_bonus)
    label = classify_insider_label(score)

    reason_parts = []

    if breakdown["purchases"]:
        reason_parts.append(
            f"{breakdown['purchases']} purchase(s) from {breakdown['unique_buyers']} buyer(s)"
        )

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
        + ". Open-market purchases carry the most weight; routine sales and tax withholding are discounted."
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
    Returns only the numeric score.
    """
    details = build_insider_score_details(ticker)
    return clamp_score(details.get("score", NEUTRAL_SCORE))


# Backward-compatible aliases
score_insider_activity = get_insider_score
get_insider_signal = build_insider_score_details