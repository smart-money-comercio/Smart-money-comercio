from src.scoring.scoring_engine import get_stock_scores
from src.scoring.risk_engine import get_risk_profile
from src.market.market_data import get_market_data, format_number, format_percent
from src.market.earnings_data import get_earnings_data


def calculate_undervalued_score(stock, market_data, earnings_data, risk_profile):
    score = 0
    reasons = []

    final_score = stock.get("final_score", 0)
    risk_score = risk_profile.get("risk_score", 100)

    pe_ratio = market_data.get("pe_ratio") if market_data.get("found") else None
    forward_pe = market_data.get("forward_pe") if market_data.get("found") else None
    dividend_yield = market_data.get("dividend_yield") if market_data.get("found") else None

    revenue_growth = earnings_data.get("revenue_growth") if earnings_data.get("found") else None
    net_margin = earnings_data.get("net_margin") if earnings_data.get("found") else None

    # Smart Money strength
    if final_score >= 80:
        score += 25
        reasons.append("Strong Smart Money score")
    elif final_score >= 70:
        score += 15
        reasons.append("Solid Smart Money score")

    # Valuation
    if forward_pe and forward_pe <= 25:
        score += 25
        reasons.append("Reasonable forward P/E")
    elif forward_pe and forward_pe <= 40:
        score += 15
        reasons.append("Acceptable forward P/E")

    if pe_ratio and pe_ratio <= 25:
        score += 15
        reasons.append("Reasonable trailing P/E")
    elif pe_ratio and pe_ratio <= 40:
        score += 8
        reasons.append("Moderate trailing P/E")

    # Earnings quality
    if revenue_growth and revenue_growth > 10:
        score += 15
        reasons.append("Positive revenue growth")

    if net_margin and net_margin > 0.10:
        score += 10
        reasons.append("Healthy net margin")

    # Dividend support
    if dividend_yield and dividend_yield >= 0.03:
        score += 10
        reasons.append("Dividend yield support")
    elif dividend_yield and dividend_yield >= 0.015:
        score += 5
        reasons.append("Some dividend support")

    # Risk adjustment
    if risk_score <= 50:
        score += 15
        reasons.append("Lower risk profile")
    elif risk_score <= 65:
        score += 8
        reasons.append("Moderate risk profile")
    elif risk_score >= 80:
        score -= 15
        reasons.append("High risk profile")

    return max(score, 0), reasons


def get_undervalued_ideas(limit=10):
    stocks = get_stock_scores()
    results = []

    for stock in stocks:
        ticker = stock["ticker"]

        market_data = get_market_data(ticker)
        earnings_data = get_earnings_data(ticker)
        risk_profile = get_risk_profile(stock)

        undervalued_score, reasons = calculate_undervalued_score(
            stock,
            market_data,
            earnings_data,
            risk_profile
        )

        if undervalued_score >= 35:
            results.append({
                "ticker": ticker,
                "category": stock["category"],
                "final_score": stock["final_score"],
                "undervalued_score": undervalued_score,
                "risk_level": risk_profile["risk_level"],
                "risk_score": risk_profile["risk_score"],
                "price": market_data.get("price") if market_data.get("found") else None,
                "market_cap": market_data.get("market_cap") if market_data.get("found") else None,
                "pe_ratio": market_data.get("pe_ratio") if market_data.get("found") else None,
                "forward_pe": market_data.get("forward_pe") if market_data.get("found") else None,
                "dividend_yield": market_data.get("dividend_yield") if market_data.get("found") else None,
                "revenue_growth": earnings_data.get("revenue_growth") if earnings_data.get("found") else None,
                "reasons": reasons,
            })

    return sorted(
        results,
        key=lambda x: x["undervalued_score"],
        reverse=True
    )[:limit]