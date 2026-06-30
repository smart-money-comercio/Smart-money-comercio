from typing import Any


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_symbol(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper().replace("$", "")


def clean_text(value: Any, max_length: int = 160) -> str:
    if value is None:
        return ""

    text = " ".join(str(value).split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def format_money(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    if abs(number) >= 1_000_000_000:
        return f"${number / 1_000_000_000:.2f}B"

    if abs(number) >= 1_000_000:
        return f"${number / 1_000_000:.2f}M"

    if abs(number) >= 1_000:
        return f"${number / 1_000:.2f}K"

    return f"${number:,.0f}"


def format_number(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    return f"{number:,.0f}"


def classify_insider_score(score: int | float | None) -> str:
    value = safe_float(score)

    if value is None:
        return "Unavailable"

    if value >= 80:
        return "Strong positive insider signal"
    if value >= 65:
        return "Positive insider signal"
    if value >= 45:
        return "Neutral / limited insider signal"
    if value >= 25:
        return "Weak insider signal"

    return "Negative insider signal"


def classify_trade_signal(transaction: Any) -> str:
    text = str(transaction or "").strip().lower()

    if "purchase" in text or "buy" in text or "acquisition" in text:
        return "🟢 Purchase"

    if "sale" in text or "sell" in text or "sold" in text or "disposition" in text:
        return "🔴 Sale"

    return "⚪ Other"


def sort_trades(trades: list[dict]) -> list[dict]:
    return sorted(
        trades,
        key=lambda trade: (
            str(trade.get("date") or ""),
            safe_float(trade.get("amount_estimate")) or 0,
        ),
        reverse=True,
    )


def filter_trades_for_symbol(trades: list[dict], symbol: str) -> list[dict]:
    clean = clean_symbol(symbol)

    return [
        trade
        for trade in trades
        if clean_symbol(trade.get("ticker")) == clean
    ]


def build_trade_line(index: int, trade: dict) -> str:
    transaction = trade.get("transaction") or "Unknown"
    signal = classify_trade_signal(transaction)
    insider = clean_text(trade.get("insider") or "Insider", 60)
    insider_name = clean_text(trade.get("insider_name") or "", 70)
    amount_range = clean_text(trade.get("amount_range") or "Unknown", 40)
    amount_estimate = trade.get("amount_estimate")
    shares = trade.get("shares")
    price = trade.get("price")
    filing_date = trade.get("filing_date") or trade.get("date") or "Unknown"
    form = trade.get("form") or "4"

    name_line = ""
    if insider_name:
        name_line = f" | Name: {insider_name}"

    return (
        f"{index}. {signal} | Role: {insider}{name_line}\n"
        f"   Amount: {amount_range} | Est: {format_money(amount_estimate)}\n"
        f"   Shares: {format_number(shares)} | Price: {format_money(price)}\n"
        f"   Form: {form} | Filing Date: {filing_date}"
    )


def build_trade_summary(trades: list[dict]) -> str:
    if not trades:
        return "No parsed Form 4 purchase/sale transactions found."

    purchases = 0
    sales = 0
    total_purchase_amount = 0.0
    total_sale_amount = 0.0

    for trade in trades:
        transaction = str(trade.get("transaction") or "").lower()
        amount = safe_float(trade.get("amount_estimate")) or 0

        if "purchase" in transaction:
            purchases += 1
            total_purchase_amount += amount

        elif "sale" in transaction:
            sales += 1
            total_sale_amount += amount

    net_amount = total_purchase_amount - total_sale_amount

    return "\n".join(
        [
            f"Parsed Trades: {len(trades)}",
            f"Purchases: {purchases} | Sales: {sales}",
            f"Purchase Amount: {format_money(total_purchase_amount)}",
            f"Sale Amount: {format_money(total_sale_amount)}",
            f"Net Insider Amount: {format_money(net_amount)}",
        ]
    )


def build_insider_readout(score: int | float | None, trades: list[dict]) -> str:
    label = classify_insider_score(score)

    if not trades:
        return (
            f"{label}. No recent parsed Form 4 purchase/sale transactions were found "
            "in the current insider cache for this ticker."
        )

    purchases = [
        trade for trade in trades
        if "purchase" in str(trade.get("transaction") or "").lower()
    ]

    sales = [
        trade for trade in trades
        if "sale" in str(trade.get("transaction") or "").lower()
    ]

    if len(purchases) > len(sales):
        return f"{label}. Insider activity leans positive based on recent parsed purchases."

    if len(sales) > len(purchases):
        return f"{label}. Insider activity leans cautious because sales outnumber purchases."

    return f"{label}. Insider activity is mixed or balanced."


def build_insider_report(
    symbol: str,
    insider_score: int | float | None,
    all_trades: list[dict],
    limit: int = 5,
) -> str:
    clean = clean_symbol(symbol)
    trades = sort_trades(filter_trades_for_symbol(all_trades, clean))

    if trades:
        trade_lines = "\n\n".join(
            build_trade_line(index, trade)
            for index, trade in enumerate(trades[:limit], start=1)
        )
    else:
        trade_lines = (
            "No parsed Form 4 purchase/sale transactions found for this ticker.\n"
            "The insider score may be neutral if no recent data is available."
        )

    return f"""
🧾 Smart Money AI Insider Report: {clean}

Insider Score
Score: {insider_score if insider_score is not None else "N/A"}/100
Readout: {build_insider_readout(insider_score, trades)}

Trade Summary
{build_trade_summary(trades)}

Recent Parsed Form 4 Trades
{trade_lines}

Next Commands
/scorecard {clean}
/ticker {clean}
/top10
/report

Notes
This report uses parsed SEC Form 4 data from the insider data cache.
Form 4 sales can occur for many reasons, including taxes, diversification, or planned selling.
This is informational only and is not financial advice.
""".strip()