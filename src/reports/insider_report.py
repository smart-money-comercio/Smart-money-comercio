from typing import Any

from src.insiders.insider_scoring import build_insider_score_details


def clean_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("$", "")


def clean_text(value: Any, max_length: int = 180) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def format_money(value: Any) -> str:
    number = safe_float(value, 0)

    if number >= 1_000_000:
        return f"${number / 1_000_000:.2f}M"

    if number >= 1_000:
        return f"${number / 1_000:.1f}K"

    if number > 0:
        return f"${number:,.0f}"

    return "N/A"


def format_number(value: Any) -> str:
    number = safe_float(value, 0)

    if number >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"

    if number >= 1_000:
        return f"{number / 1_000:.1f}K"

    if number > 0:
        return f"{number:,.0f}"

    return "N/A"


def filter_symbol_trades(symbol: str, all_trades: list[dict]) -> list[dict]:
    ticker = clean_symbol(symbol)

    return [
        trade
        for trade in all_trades or []
        if clean_symbol(trade.get("ticker")) == ticker
    ]


def format_trade_line(trade: dict) -> str:
    date = trade.get("date") or trade.get("filing_date") or "Unknown date"
    transaction = clean_text(trade.get("transaction") or trade.get("signal"), 80)
    insider = clean_text(trade.get("insider_name") or trade.get("insider"), 70)
    role = clean_text(trade.get("role"), 70)
    shares = format_number(trade.get("shares"))
    value = format_money(trade.get("value"))

    return (
        f"• {date} | {transaction}\n"
        f"  Insider: {insider} ({role})\n"
        f"  Shares: {shares} | Value: {value}"
    )
def build_whale_purchase_section(details: dict) -> str:
    breakdown = details.get("breakdown") or {}
    top_whales = breakdown.get("top_whales") or []

    label = breakdown.get("whale_label", "No Whale Buying")
    count = breakdown.get("whale_purchases", 0)
    buyers = breakdown.get("whale_buyers", 0)
    total_value = format_money(breakdown.get("whale_purchase_value", 0))

    if not top_whales:
        return f"""
Whale Status: {label}
Whale Purchases: {count}
Whale Buyers: {buyers}
Whale Purchase Value: {total_value}

Read:
No large open-market insider purchase signal detected right now.
""".strip()

    lines = []

    for trade in top_whales[:3]:
        date = trade.get("date") or trade.get("filing_date") or "Unknown date"
        insider = clean_text(trade.get("insider_name") or trade.get("insider"), 70)
        role = clean_text(trade.get("role"), 70)
        value = format_money(trade.get("value"))
        label_text = trade.get("whale_label", "Whale Buy")

        lines.append(
            f"• {date} | {label_text} | {value}\n"
            f"  Insider: {insider} ({role})"
        )

    return f"""
Whale Status: {label}
Whale Purchases: {count}
Whale Buyers: {buyers}
Whale Purchase Value: {total_value}

Top Whale Buys:
{chr(10).join(lines)}

Read:
Large open-market insider purchases can be a stronger conviction signal, especially when made by executives, directors, or multiple insiders.
""".strip()

def build_activity_summary(details: dict) -> str:
    breakdown = details.get("breakdown") or {}

    purchase_value = format_money(breakdown.get("total_purchase_value", 0))
    sale_value = format_money(breakdown.get("total_sale_value", 0))

    return f"""
Signal: {details.get("label", "Neutral / Mixed")}
Score: {details.get("score", 50)}
Purchases: {breakdown.get("purchases", 0)} | Buyers: {breakdown.get("unique_buyers", 0)} | Value: {purchase_value}
Sales: {breakdown.get("sales", 0)} | Sellers: {breakdown.get("unique_sellers", 0)} | Value: {sale_value}
Tax/Withholding: {breakdown.get("tax_sales", 0)}
Awards/Exercises: {breakdown.get("awards", 0)}
""".strip()


def build_interpretation(details: dict) -> str:
    score = safe_float(details.get("score"), 50)
    breakdown = details.get("breakdown") or {}

    if score >= 75:
        return (
            "Strong insider confirmation. Open-market buying, especially by executives or multiple insiders, "
            "is a meaningful positive signal."
        )

    if score >= 65:
        return (
            "Positive insider signal. Insider activity supports further research, but still confirm trend, volume, valuation, and risk."
        )

    if score >= 55:
        return (
            "Slightly positive insider read. The signal helps, but it is not strong enough by itself."
        )

    if score >= 45:
        return (
            "Neutral or mixed insider activity. No clear purchase/sale signal dominates."
        )

    if breakdown.get("sales", 0) > 0:
        return (
            "Insider selling pressure is present. Check whether sales are routine, tax-related, or part of a broader reduction pattern."
        )

    return (
        "Weak insider signal. There is not enough positive insider activity to support conviction right now."
    )


def build_insider_report(
    symbol: str,
    insider_score: float | None = None,
    all_trades: list[dict] | None = None,
    limit: int = 5,
) -> str:
    ticker = clean_symbol(symbol)

    details = build_insider_score_details(ticker)

    trades = details.get("trades") or []

    if not trades and all_trades:
        trades = filter_symbol_trades(ticker, all_trades)

    if insider_score is not None:
        details["score"] = insider_score

    recent_lines = [
        format_trade_line(trade)
        for trade in trades[:limit]
    ]

    if not recent_lines:
        recent_lines = ["No recent SEC Form 4 purchase/sale activity found for this ticker."]

    return f"""
🧾 Insider Intelligence: {ticker}

Current Insider Read
{build_activity_summary(details)}

Big Whale Purchases
{build_whale_purchase_section(details)}

Why It Matters
{clean_text(details.get("reason"), 650)}

Recent SEC Form 4 Activity
{chr(10).join(recent_lines)}

Interpretation
{build_interpretation(details)}

What To Watch
• Open-market purchases by CEOs, CFOs, directors, or multiple insiders matter most.
• Routine sales, tax withholding, gifts, and stock awards should not be treated the same as open-market buys.
• Use insider activity as confirmation, not as a standalone buy/sell signal.

Next Commands
/scorecard {ticker}
/smartmoney {ticker}
/risk {ticker}
/report

Note
This is research only, not financial advice.
""".strip()