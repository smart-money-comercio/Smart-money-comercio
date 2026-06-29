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


def format_score(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    if number.is_integer():
        return str(int(number))

    return f"{number:.1f}"


def classify_score(score: Any) -> str:
    value = safe_float(score)

    if value is None:
        return "Unrated"

    if value >= 90:
        return "Elite"
    if value >= 80:
        return "Strong"
    if value >= 70:
        return "Good"
    if value >= 60:
        return "Average"
    if value >= 50:
        return "Weak watch"
    return "Low conviction"


def classify_market_cap(market_cap: Any) -> str:
    value = safe_float(market_cap)

    if value is None:
        return "Market cap unavailable"

    if value >= 200_000_000_000:
        return "Mega-cap / highly liquid"
    if value >= 10_000_000_000:
        return "Large-cap / liquid"
    if value >= 2_000_000_000:
        return "Mid-cap / moderate liquidity"
    if value >= 300_000_000:
        return "Small-cap / higher risk"

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

    return "Valuation may not be meaningful"


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

    if position >= 85:
        zone = "near its 52-week high"
    elif position >= 65:
        zone = "in the upper part of its 52-week range"
    elif position >= 40:
        zone = "near the middle of its 52-week range"
    elif position >= 20:
        zone = "in the lower part of its 52-week range"
    else:
        zone = "near its 52-week low"

    return f"{position:.1f}% — {zone}"


def get_stock_field(stock: dict | None, key: str, default="N/A"):
    if not stock:
        return default

    value = stock.get(key)

    if value is None:
        return default

    return value


def get_market_field(market_data: dict | None, key: str, default="N/A"):
    if not market_data or not market_data.get("found"):
        return default

    value = market_data.get(key)

    if value is None:
        return default

    return value


def build_score_readout(stock: dict | None) -> str:
    final_score = get_stock_field(stock, "final_score", None)
    smart_score = get_stock_field(stock, "smart_score", None)
    defense_score = get_stock_field(stock, "defense_score", None)
    congress_score = get_stock_field(stock, "congress_score", 0)
    insider_score = get_stock_field(stock, "insider_score", 0)

    lines = [
        f"Final score is {classify_score(final_score)}.",
        f"Smart score is {classify_score(smart_score)}.",
        f"Defense score is {classify_score(defense_score)}.",
    ]

    congress_value = safe_float(congress_score)
    insider_value = safe_float(insider_score)

    if congress_value is not None and congress_value > 0:
        lines.append("Congress activity contributes to the score.")

    if insider_value is not None and insider_value > 0:
        lines.append("Insider activity contributes to the score.")

    return "\n".join(f"• {line}" for line in lines)


def build_market_readout(market_data: dict | None) -> str:
    if not market_data or not market_data.get("found"):
        return "• Market data unavailable."

    market_cap = market_data.get("market_cap")
    pe_ratio = market_data.get("pe_ratio")
    forward_pe = market_data.get("forward_pe")
    beta = market_data.get("beta")
    price = market_data.get("price")
    week_52_low = market_data.get("week_52_low")
    week_52_high = market_data.get("week_52_high")

    lines = [
        classify_market_cap(market_cap) + ".",
        classify_valuation(pe_ratio, forward_pe) + ".",
        classify_beta(beta) + ".",
        calculate_52_week_position(price, week_52_low, week_52_high) + ".",
    ]

    return "\n".join(f"• {line}" for line in lines)


def build_risk_readout(risk_profile: dict | None) -> str:
    if not risk_profile:
        return "Risk profile unavailable."

    risk_level = risk_profile.get("risk_level") or "N/A"
    risk_score = risk_profile.get("risk_score")

    return f"{risk_level} risk with a score of {format_score(risk_score)}/100."


def clean_analysis_text(analysis: str | None) -> str:
    if not analysis:
        return "AI analysis unavailable."

    cleaned = str(analysis).strip()

    if not cleaned:
        return "AI analysis unavailable."

    return cleaned


def build_ticker_report(
    symbol: str,
    stock: dict | None,
    risk_profile: dict | None,
    market_data: dict | None,
    analysis: str | None,
) -> str:
    clean = clean_symbol(symbol)

    ticker = get_stock_field(stock, "ticker", clean)
    category = get_stock_field(stock, "category", "N/A")

    company_name = get_market_field(market_data, "company_name", ticker)
    sector = get_market_field(market_data, "sector", "N/A")
    industry = get_market_field(market_data, "industry", "N/A")

    price = get_market_field(market_data, "price", None)
    market_cap = get_market_field(market_data, "market_cap", None)
    pe_ratio = get_market_field(market_data, "pe_ratio", None)
    forward_pe = get_market_field(market_data, "forward_pe", None)
    dividend_yield = get_market_field(market_data, "dividend_yield", None)
    beta = get_market_field(market_data, "beta", None)
    week_52_low = get_market_field(market_data, "week_52_low", None)
    week_52_high = get_market_field(market_data, "week_52_high", None)

    smart_score = get_stock_field(stock, "smart_score", None)
    defense_score = get_stock_field(stock, "defense_score", None)
    congress_score = get_stock_field(stock, "congress_score", 0)
    insider_score = get_stock_field(stock, "insider_score", 0)
    final_score = get_stock_field(stock, "final_score", None)

    risk_level = "N/A"
    risk_score = "N/A"

    if risk_profile:
        risk_level = risk_profile.get("risk_level") or "N/A"
        risk_score = risk_profile.get("risk_score", "N/A")

    return f"""
📈 Smart Money AI Ticker Snapshot: {ticker}

Company
Name: {company_name}
Sector: {sector}
Industry: {industry}
Category: {category}

Watchlist Scores
Smart Score: {format_score(smart_score)}
Defense Score: {format_score(defense_score)}
Congress Score: {format_score(congress_score)}
Insider Score: {format_score(insider_score)}
Final Score: {format_score(final_score)}
Score Readout:
{build_score_readout(stock)}

Risk Profile
Risk Level: {risk_level}
Risk Score: {risk_score}/100
Risk Readout: {build_risk_readout(risk_profile)}

Market Snapshot
Price: {format_price(price)}
Market Cap: {format_number(market_cap)}
Market Cap Profile: {classify_market_cap(market_cap)}

Valuation
P/E Ratio: {format_plain(pe_ratio)}
Forward P/E: {format_plain(forward_pe)}
Valuation Readout: {classify_valuation(pe_ratio, forward_pe)}

Income
Dividend Yield: {format_percent(dividend_yield)}

Volatility
Beta: {format_plain(beta)}
Volatility Readout: {classify_beta(beta)}

52-Week Range
Low: {format_price(week_52_low)}
High: {format_price(week_52_high)}
Position: {calculate_52_week_position(price, week_52_low, week_52_high)}

Market Readout
{build_market_readout(market_data)}

AI Analysis
{clean_analysis_text(analysis)}

Next Commands
/quote {ticker}
/market {ticker}
/scorecard {ticker}
/risk {ticker}
/earnings {ticker}

Notes
This ticker snapshot is informational only and is not financial advice.
Verify market data before making investment decisions.
""".strip()