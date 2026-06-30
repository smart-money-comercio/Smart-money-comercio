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


def classify_transaction(transaction: Any) -> str:
    text = str(transaction or "").strip().lower()

    if "purchase" in text or "buy" in text or "acquisition" in text:
        return "🟢 Purchase"

    if "sale" in text or "sell" in text or "sold" in text:
        return "🔴 Sale"

    return "⚪ Other"


def is_purchase(transaction: Any) -> bool:
    return "purchase" in str(transaction or "").strip().lower()


def is_sale(transaction: Any) -> bool:
    return "sale" in str(transaction or "").strip().lower()


def amount_rank(amount_range: Any) -> int:
    text = str(amount_range or "").upper()

    if "$5M" in text:
        return 6
    if "$1M" in text:
        return 5
    if "$500K" in text:
        return 4
    if "$250K" in text:
        return 3
    if "$100K" in text:
        return 2
    if "$50K" in text or "$15K" in text:
        return 1

    return 0


def relevance_rank(value: Any) -> int:
    text = str(value or "").strip().upper()

    if text == "HIGH":
        return 3
    if text == "MEDIUM":
        return 2
    if text == "LOW":
        return 1

    return 0


def trade_sort_key(trade: dict) -> tuple:
    return (
        amount_rank(trade.get("amount_range")),
        relevance_rank(trade.get("committee_relevance")),
        clean_symbol(trade.get("ticker")),
    )


def filter_trades(trades: list[dict], symbol: str | None = None) -> list[dict]:
    if not symbol:
        return list(trades)

    clean = clean_symbol(symbol)

    return [
        trade
        for trade in trades
        if clean_symbol(trade.get("ticker")) == clean
    ]


def unique_tickers(trades: list[dict]) -> list[str]:
    tickers = sorted(
        {
            clean_symbol(trade.get("ticker"))
            for trade in trades
            if clean_symbol(trade.get("ticker")) != "UNKNOWN"
        }
    )

    return tickers


def build_trade_summary(trades: list[dict]) -> str:
    if not trades:
        return "No congressional trade records found."

    purchases = [trade for trade in trades if is_purchase(trade.get("transaction"))]
    sales = [trade for trade in trades if is_sale(trade.get("transaction"))]
    tickers = unique_tickers(trades)

    high_relevance = [
        trade
        for trade in trades
        if str(trade.get("committee_relevance", "")).strip().upper() == "HIGH"
    ]

    return "\n".join(
        [
            f"Total Records: {len(trades)}",
            f"Unique Tickers: {len(tickers)}",
            f"Purchases: {len(purchases)}",
            f"Sales: {len(sales)}",
            f"High-Relevance Records: {len(high_relevance)}",
        ]
    )


def format_score_line(symbol: str, score_map: dict[str, int | float]) -> str:
    score = score_map.get(clean_symbol(symbol))

    if score is None:
        return "Congress Score: N/A"

    return f"Congress Score: {score}/100"


def build_trade_line(index: int, trade: dict, score_map: dict[str, int | float]) -> str:
    symbol = clean_symbol(trade.get("ticker"))
    politician = clean_text(trade.get("politician") or "Unknown", 70)
    chamber = clean_text(trade.get("chamber") or "N/A", 40)
    transaction = classify_transaction(trade.get("transaction"))
    sector = clean_text(trade.get("sector") or "N/A", 90)
    amount_range = clean_text(trade.get("amount_range") or "N/A", 40)
    disclosure_date = clean_text(trade.get("disclosure_date") or "Unknown", 40)
    owner = clean_text(trade.get("owner") or "N/A", 60)
    relevance = clean_text(trade.get("committee_relevance") or "N/A", 30)
    signal = clean_text(trade.get("signal") or "N/A", 40)
    notes = clean_text(trade.get("notes") or "", 120)

    notes_line = ""
    if notes:
        notes_line = f"\n   Notes: {notes}"

    return (
        f"{index}. {symbol} — {transaction}\n"
        f"   Politician: {politician} | Chamber: {chamber}\n"
        f"   Amount: {amount_range} | Disclosure: {disclosure_date}\n"
        f"   Sector: {sector}\n"
        f"   Committee Relevance: {relevance} | Signal: {signal}\n"
        f"   Owner: {owner}\n"
        f"   {format_score_line(symbol, score_map)}"
        f"{notes_line}"
    )


def build_ranked_sections(trades: list[dict], score_map: dict[str, int | float]) -> str:
    if not trades:
        return "No congressional trade records available."

    purchases = [
        trade for trade in trades
        if is_purchase(trade.get("transaction"))
    ]

    sales = [
        trade for trade in trades
        if is_sale(trade.get("transaction"))
    ]

    others = [
        trade for trade in trades
        if not is_purchase(trade.get("transaction")) and not is_sale(trade.get("transaction"))
    ]

    purchases.sort(key=trade_sort_key, reverse=True)
    sales.sort(key=trade_sort_key, reverse=True)

    sections = []

    if purchases:
        sections.append("🟢 Ranked Purchases")
        sections.extend(
            build_trade_line(index, trade, score_map)
            for index, trade in enumerate(purchases[:10], start=1)
        )

    if sales:
        if sections:
            sections.append("")
        sections.append("🔴 Ranked Sales")
        sections.extend(
            build_trade_line(index, trade, score_map)
            for index, trade in enumerate(sales[:10], start=1)
        )

    if others:
        if sections:
            sections.append("")
        sections.append("⚪ Other Records")
        sections.extend(
            build_trade_line(index, trade, score_map)
            for index, trade in enumerate(others[:5], start=1)
        )

    return "\n\n".join(sections)


def build_score_impact(score_map: dict[str, int | float]) -> str:
    if not score_map:
        return "No Congress score impact available."

    ranked = sorted(
        score_map.items(),
        key=lambda item: safe_float(item[1]) if safe_float(item[1]) is not None else -999,
        reverse=True,
    )

    lines = []

    for symbol, score in ranked[:10]:
        score_value = safe_float(score)

        if score_value is None:
            label = "Unavailable"
        elif score_value >= 80:
            label = "Strong positive"
        elif score_value >= 65:
            label = "Positive"
        elif score_value >= 45:
            label = "Neutral / limited"
        elif score_value >= 25:
            label = "Weak"
        else:
            label = "Negative"

        lines.append(f"• {symbol}: {score}/100 — {label}")

    return "\n".join(lines)


def build_congress_report(
    trades: list[dict],
    score_map: dict[str, int | float],
    symbol: str | None = None,
) -> str:
    filtered_trades = filter_trades(trades, symbol)
    clean = clean_symbol(symbol) if symbol else None

    title = "🏛️ Smart Money AI Congress Report"

    if clean:
        title = f"🏛️ Smart Money AI Congress Report: {clean}"

    if not filtered_trades:
        if clean:
            return f"""
{title}

No congressional trade records found for {clean}.

Congress Score
{clean}: {score_map.get(clean, 50)}/100

Next Commands
/scorecard {clean}
/ticker {clean}
/top10
/report

Notes
A neutral Congress score usually means no matching congressional trade data is available.
This is informational only and is not financial advice.
""".strip()

        return f"""
{title}

No congressional trade records are currently available.

Notes
This is informational only and is not financial advice.
""".strip()

    return f"""
{title}

Summary
{build_trade_summary(filtered_trades)}

Congress Score Impact
{build_score_impact(score_map)}

Trade Details
{build_ranked_sections(filtered_trades, score_map)}

Next Commands
/scorecard SYMBOL
/ticker SYMBOL
/top10
/report

Notes
This report uses the current local Congress trade dataset.
Congress trades can involve spouses, family accounts, delayed disclosures, ETFs, or diversified portfolios.
This is informational only and is not financial advice.
""".strip()