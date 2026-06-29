from typing import Any

from src.market.market_data import format_number, format_percent


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("$", "")


def format_price(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    return f"${number:,.2f}"


def format_plain(value: Any) -> str:
    if value is None:
        return "N/A"

    return str(value)


def classify_market_cap(market_cap: Any) -> str:
    value = safe_float(market_cap)

    if value is None:
        return "Market cap unavailable"

    if value >= 200_000_000_000:
        return "Mega-cap"
    if value >= 10_000_000_000:
        return "Large-cap"
    if value >= 2_000_000_000:
        return "Mid-cap"
    if value >= 300_000_000:
        return "Small-cap"

    return "Micro-cap / speculative"


def classify_valuation(pe_ratio: Any, forward_pe: Any) -> str:
    pe = safe_float(pe_ratio)
    fpe = safe_float(forward_pe)
    valuation = fpe if fpe is not None else pe

    if valuation is None:
        return "Valuation data unavailable"

    if valuation >= 80:
        return "Very expensive valuation"
    if valuation >= 50:
        return "Expensive valuation"
    if valuation >= 30:
        return "Elevated valuation"
    if valuation >= 15:
        return "Moderate valuation"
    if valuation > 0:
        return "Lower valuation"

    return "Valuation not meaningful"


def classify_beta(beta: Any) -> str:
    value = safe_float(beta)

    if value is None:
        return "Volatility data unavailable"

    if value >= 2:
        return "Very high volatility"
    if value >= 1.5:
        return "High volatility"
    if value >= 1.1:
        return "Above-market volatility"
    if value >= 0.8:
        return "Market-like volatility"
    if value >= 0:
        return "Below-market volatility"

    return "Unusual beta profile"


def calculate_52_week_position(price: Any, low: Any, high: Any) -> str:
    price_value = safe_float(price)
    low_value = safe_float(low)
    high_value = safe_float(high)

    if price_value is None or low_value is None or high_value is None:
        return "52-week position unavailable"

    if high_value <= low_value:
        return "52-week position unavailable"

    position = ((price_value - low_value) / (high_value - low_value)) * 100
    position = max(0, min(100, position))

    if position >= 80:
        zone = "near the high end of its 52-week range"
    elif position >= 60:
        zone = "in the upper half of its 52-week range"
    elif position >= 40:
        zone = "near the middle of its 52-week range"
    elif position >= 20:
        zone = "in the lower half of its 52-week range"
    else:
        zone = "near the low end of its 52-week range"

    return f"{position:.1f}% — {zone}"


def build_quick_readout(data: dict) -> str:
    readout = []

    market_cap_label = classify_market_cap(data.get("market_cap"))
    valuation_label = classify_valuation(data.get("pe_ratio"), data.get("forward_pe"))
    beta_label = classify_beta(data.get("beta"))
    range_position = calculate_52_week_position(
        data.get("price"),
        data.get("week_52_low"),
        data.get("week_52_high"),
    )

    readout.append(f"{market_cap_label} profile.")
    readout.append(f"{valuation_label}.")
    readout.append(f"{beta_label}.")
    readout.append(range_position + ".")

    return "\n".join(f"• {item}" for item in readout)


def build_quote_report(symbol: str, data: dict) -> str:
    clean = clean_symbol(symbol)

    ticker = data.get("ticker") or clean
    company_name = data.get("company_name") or "N/A"

    price = data.get("price")
    market_cap = data.get("market_cap")
    pe_ratio = data.get("pe_ratio")
    forward_pe = data.get("forward_pe")
    dividend_yield = data.get("dividend_yield")
    beta = data.get("beta")
    week_52_low = data.get("week_52_low")
    week_52_high = data.get("week_52_high")

    quick_readout = build_quick_readout(data)

    return f"""
💹 Smart Money AI Quote: {ticker}

Company
{company_name}

Price
Current Price: {format_price(price)}

Size
Market Cap: {format_number(market_cap)}
Profile: {classify_market_cap(market_cap)}

Valuation
P/E Ratio: {format_plain(pe_ratio)}
Forward P/E: {format_plain(forward_pe)}
Readout: {classify_valuation(pe_ratio, forward_pe)}

Income
Dividend Yield: {format_percent(dividend_yield)}

Volatility
Beta: {format_plain(beta)}
Readout: {classify_beta(beta)}

52-Week Range
Low: {format_price(week_52_low)}
High: {format_price(week_52_high)}
Position: {calculate_52_week_position(price, week_52_low, week_52_high)}

Quick Readout
{quick_readout}

Next Commands
/scorecard {ticker}
/risk {ticker}
/market {ticker}
/earnings {ticker}

Notes
This quote is informational only and is not financial advice.
""".strip()