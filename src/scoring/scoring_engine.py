from src.scoring.watchlist import WATCHLIST
from src.congress.congress_scoring import get_congress_score
from src.insiders.insider_scoring import get_insider_score


MIN_SCORE = 0
MAX_SCORE = 100


CATEGORY_BONUS = {
    "defense": 4,
    "cybersecurity": 3,
    "ai": 3,
    "semiconductor": 3,
    "energy": 2,
    "infrastructure": 2,
    "dividend": 2,
    "growth": 1,
    "speculative": -4,
    "high risk": -5,
}


def clamp_score(value):
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0

    return max(MIN_SCORE, min(MAX_SCORE, score))


def score_or_default(value, default=50):
    try:
        if value is None:
            return default
        return clamp_score(value)
    except Exception:
        return default


def get_category_adjustment(category):
    if not category:
        return 0

    category_text = str(category).lower()

    adjustment = 0

    for keyword, bonus in CATEGORY_BONUS.items():
        if keyword in category_text:
            adjustment += bonus

    return max(-8, min(8, adjustment))


def classify_rating(score):
    score = clamp_score(score)

    if score >= 90:
        return "Elite"
    if score >= 82:
        return "High conviction"
    if score >= 75:
        return "Strong watch"
    if score >= 68:
        return "Good watch"
    if score >= 60:
        return "Moderate watch"
    if score >= 50:
        return "Neutral"
    return "Weak"


def classify_risk_label(defense_score, final_score):
    defense = score_or_default(defense_score, 50)
    final = score_or_default(final_score, 50)

    if defense >= 80 and final >= 75:
        return "Moderate"
    if defense >= 65:
        return "Medium"
    if defense >= 50:
        return "Medium-high"
    return "High"


def build_strengths(stock, congress_score, insider_score, category_adjustment):
    strengths = []

    smart_score = score_or_default(stock.get("smart_score"), 50)
    defense_score = score_or_default(stock.get("defense_score"), 50)

    if smart_score >= 80:
        strengths.append("Strong core Smart Money score.")

    if defense_score >= 75:
        strengths.append("Above-average defense or stability profile.")

    if congress_score >= 70:
        strengths.append("Positive congressional activity signal.")

    if insider_score >= 70:
        strengths.append("Positive insider activity signal.")

    if category_adjustment > 0:
        strengths.append("Category tailwind improves the opportunity score.")

    if not strengths:
        strengths.append("No major strength signal dominates the current score.")

    return strengths


def build_weaknesses(stock, congress_score, insider_score, category_adjustment):
    weaknesses = []

    smart_score = score_or_default(stock.get("smart_score"), 50)
    defense_score = score_or_default(stock.get("defense_score"), 50)

    if smart_score < 60:
        weaknesses.append("Core Smart Money score is below preferred range.")

    if defense_score < 55:
        weaknesses.append("Defense or stability score is weak.")

    if congress_score < 40:
        weaknesses.append("Congressional activity signal is weak or unavailable.")

    if insider_score < 40:
        weaknesses.append("Insider activity signal is weak or unavailable.")

    if category_adjustment < 0:
        weaknesses.append("Category risk reduces the opportunity score.")

    if not weaknesses:
        weaknesses.append("No major weakness signal dominates the current score.")

    return weaknesses


def build_risks(stock, final_score, defense_score):
    risks = []

    category = str(stock.get("category", "")).lower()
    defense = score_or_default(defense_score, 50)
    final = score_or_default(final_score, 50)

    if final < 60:
        risks.append("Lower final score means conviction is limited.")

    if defense < 55:
        risks.append("Lower defense score may indicate higher downside risk.")

    if "speculative" in category or "high risk" in category:
        risks.append("Speculative category increases risk.")

    if not risks:
        risks.append("Confirm valuation, trend, earnings, and news before acting.")

    return risks


def build_reason(stock, final_score, congress_score, insider_score, category_adjustment):
    ticker = stock.get("ticker", "UNKNOWN")
    smart_score = score_or_default(stock.get("smart_score"), 50)
    defense_score = score_or_default(stock.get("defense_score"), 50)

    return (
        f"{ticker} receives a Smart Money Score of {round(final_score)} based on "
        f"core score strength ({round(smart_score)}), defense profile "
        f"({round(defense_score)}), congressional signal ({round(congress_score)}), "
        f"insider signal ({round(insider_score)}), and category adjustment "
        f"({category_adjustment:+})."
    )


def calculate_final_score(stock, congress_score, insider_score):
    smart_score = score_or_default(stock.get("smart_score"), 50)
    defense_score = score_or_default(stock.get("defense_score"), 50)
    category_adjustment = get_category_adjustment(stock.get("category"))

    base_score = (
        (smart_score * 0.45)
        + (defense_score * 0.20)
        + (congress_score * 0.175)
        + (insider_score * 0.175)
    )

    final_score = base_score + category_adjustment

    return round(clamp_score(final_score)), category_adjustment


def enrich_stock(stock):
    ticker = stock.get("ticker", "").upper()

    try:
        congress_score = clamp_score(get_congress_score(ticker))
    except Exception:
        congress_score = 0

    try:
        insider_score = clamp_score(get_insider_score(ticker))
    except Exception:
        insider_score = 0

    final_score, category_adjustment = calculate_final_score(
        stock,
        congress_score,
        insider_score,
    )

    defense_score = score_or_default(stock.get("defense_score"), 50)
    rating = classify_rating(final_score)
    risk_label = classify_risk_label(defense_score, final_score)

    stock["ticker"] = ticker
    stock["congress_score"] = round(congress_score)
    stock["insider_score"] = round(insider_score)
    stock["category_adjustment"] = category_adjustment

    # Compatibility fields used by existing commands.
    stock["final_score"] = final_score
    stock["score"] = final_score
    stock["smart_money_score"] = final_score
    stock["rating"] = rating
    stock["risk_label"] = risk_label

    # Rich fields used by /scorecard and reports.
    stock["reason"] = build_reason(
        stock,
        final_score,
        congress_score,
        insider_score,
        category_adjustment,
    )
    stock["strengths"] = build_strengths(
        stock,
        congress_score,
        insider_score,
        category_adjustment,
    )
    stock["weaknesses"] = build_weaknesses(
        stock,
        congress_score,
        insider_score,
        category_adjustment,
    )
    stock["risks"] = build_risks(
        stock,
        final_score,
        defense_score,
    )

    return stock


def get_stock_scores():
    stocks = [stock.copy() for stock in WATCHLIST]
    enriched_stocks = []

    for stock in stocks:
        enriched_stocks.append(enrich_stock(stock))

    return sorted(
        enriched_stocks,
        key=lambda item: item.get("final_score", 0),
        reverse=True,
    )