def clamp(value, minimum=0, maximum=100):
    return max(minimum, min(value, maximum))


def get_risk_profile(stock):
    ticker = stock["ticker"]
    category = stock["category"].lower()

    risk_score = 50
    risk_factors = []

    # Growth risk
    if "growth" in category:
        risk_score += 15
        risk_factors.append("Growth stock volatility")

    if "ai" in category:
        risk_score += 10
        risk_factors.append("AI valuation and competition risk")

    # Defense / cyber / space risk
    if "defense" in category:
        risk_score += 5
        risk_factors.append("Government contract and budget risk")

    if "cyber" in category:
        risk_score += 8
        risk_factors.append("Cybersecurity sector competition risk")

    if "space" in category:
        risk_score += 12
        risk_factors.append("Space industry execution risk")

    if "drones" in category or "autonomous" in category:
        risk_score += 10
        risk_factors.append("Emerging defense technology risk")

    # ETF risk reduction
    if "etf" in category:
        risk_score -= 15
        risk_factors.append("ETF diversification lowers single-stock risk")

    if "core market" in category:
        risk_score -= 20
        risk_factors.append("Broad market ETF diversification")

    # Dividend risk reduction
    if "dividend" in category:
        risk_score -= 10
        risk_factors.append("Dividend profile may reduce volatility")

    if "consumer defensive" in category:
        risk_score -= 10
        risk_factors.append("Consumer defensive stability")

    if "healthcare" in category:
        risk_score -= 5
        risk_factors.append("Healthcare defensive characteristics")

    # Ticker-specific adjustments
    high_volatility = ["TSLA", "RKLB", "ONDS", "SHOP", "KTOS", "AVAV"]
    lower_volatility = ["VOO", "SCHD", "VYM", "JNJ", "PG", "KO", "PEP"]

    if ticker in high_volatility:
        risk_score += 12
        risk_factors.append("Higher volatility ticker")

    if ticker in lower_volatility:
        risk_score -= 10
        risk_factors.append("Historically more defensive ticker profile")

    risk_score = clamp(risk_score)

    if risk_score >= 75:
        risk_level = "High"
    elif risk_score >= 60:
        risk_level = "Moderate-High"
    elif risk_score >= 40:
        risk_level = "Moderate"
    else:
        risk_level = "Lower"

    return {
        "ticker": ticker,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "risk_factors": risk_factors,
    }