from typing import Any

from src.reports.global_market_report import load_headlines
from src.utils.score_display import get_category, get_ticker


MAX_CURATED_HEADLINES = 3


def clean_text(value: Any, max_length: int = 180) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def get_ticker_profile(stock: dict) -> dict:
    ticker = get_ticker(stock)
    category = get_category(stock)
    category_text = normalize_text(category)

    profile = {
        "ticker": ticker,
        "category": category,
        "allowed_impacts": set(),
        "keywords": set(),
        "portfolio_read": "No specific portfolio headline profile available.",
    }

    profile["keywords"].add(ticker.lower())

    if any(word in category_text for word in ["ai", "semiconductor", "chip", "data center", "hardware"]):
        profile["allowed_impacts"].update(
            {
                "AI / Tech",
                "Rates / Inflation",
                "China / Trade",
                "Dollar / Safety",
            }
        )
        profile["keywords"].update(
            {
                "ai",
                "chip",
                "chips",
                "semiconductor",
                "semiconductors",
                "nvidia",
                "nasdaq",
                "tech",
                "technology",
                "data center",
                "export",
                "taiwan",
                "china",
                "tariff",
                "rates",
                "yield",
                "treasury",
                "fed",
                "dollar",
            }
        )
        profile["portfolio_read"] = (
            "AI and semiconductor names are most sensitive to Nasdaq trend, rates, dollar strength, "
            "export controls, China/Taiwan risk, and chip-demand headlines."
        )

    elif any(word in category_text for word in ["cyber", "software", "cloud", "security"]):
        profile["allowed_impacts"].update(
            {
                "AI / Tech",
                "Defense / Geopolitical",
                "Rates / Inflation",
            }
        )
        profile["keywords"].update(
            {
                "cyber",
                "cybersecurity",
                "security",
                "software",
                "cloud",
                "hack",
                "ransomware",
                "enterprise",
                "ai",
                "tech",
                "rates",
                "fed",
            }
        )
        profile["portfolio_read"] = (
            "Cybersecurity names are most affected by enterprise spending, AI/security demand, "
            "geopolitical cyber risk, and broad tech sentiment."
        )

    elif any(word in category_text for word in ["defense", "drone", "warfare", "military", "aerospace"]):
        profile["allowed_impacts"].update(
            {
                "Defense / Geopolitical",
                "China / Trade",
                "Dollar / Safety",
            }
        )
        profile["keywords"].update(
            {
                "defense",
                "war",
                "military",
                "missile",
                "drone",
                "drones",
                "pentagon",
                "geopolitical",
                "taiwan",
                "china",
                "middle east",
                "ukraine",
                "nato",
                "security",
            }
        )
        profile["portfolio_read"] = (
            "Defense names are most affected by geopolitical conflict, defense budgets, drone demand, "
            "China/Taiwan risk, and national-security headlines."
        )

    elif any(word in category_text for word in ["energy", "oil", "power", "grid", "utility", "nuclear", "infrastructure"]):
        profile["allowed_impacts"].update(
            {
                "Energy",
                "Rates / Inflation",
                "Dollar / Safety",
                "Market",
            }
        )
        profile["keywords"].update(
            {
                "oil",
                "crude",
                "energy",
                "opec",
                "power",
                "electricity",
                "grid",
                "utility",
                "utilities",
                "nuclear",
                "inflation",
                "rates",
                "yield",
            }
        )
        profile["portfolio_read"] = (
            "Energy, power, utility, and infrastructure names are most affected by oil, inflation, "
            "rates, power demand, and grid/electricity headlines."
        )

    elif any(word in category_text for word in ["dividend", "income", "defensive", "consumer", "retail"]):
        profile["allowed_impacts"].update(
            {
                "Rates / Inflation",
                "Dollar / Safety",
                "Market",
                "China / Trade",
            }
        )
        profile["keywords"].update(
            {
                "rates",
                "yield",
                "treasury",
                "fed",
                "inflation",
                "consumer",
                "retail",
                "spending",
                "dollar",
                "safe haven",
                "defensive",
                "tariff",
            }
        )
        profile["portfolio_read"] = (
            "Defensive, dividend, and consumer names are most affected by rates, inflation, "
            "consumer demand, dollar strength, and risk-off headlines."
        )

    else:
        profile["allowed_impacts"].update(
            {
                "AI / Tech",
                "Rates / Inflation",
                "Energy",
                "China / Trade",
                "Defense / Geopolitical",
                "Dollar / Safety",
            }
        )
        profile["keywords"].update(
            {
                word
                for word in category_text.replace("/", " ").replace("-", " ").split()
                if len(word) >= 4
            }
        )
        profile["portfolio_read"] = (
            "This name has a broader portfolio profile, so only headlines that match the ticker, "
            "category, or major risk theme are shown."
        )

    return profile


def score_headline_for_stock(headline: dict, profile: dict) -> int:
    title = normalize_text(headline.get("title"))
    impact = headline.get("impact") or "Market"
    ticker = profile["ticker"].lower()
    keywords = profile["keywords"]
    allowed_impacts = profile["allowed_impacts"]

    if not title:
        return 0

    score = 0

    if ticker and ticker in title:
        score += 7

    if impact in allowed_impacts:
        score += 3

    keyword_hits = [
        keyword
        for keyword in keywords
        if keyword and keyword in title
    ]

    score += min(len(keyword_hits), 4)

    if impact == "Market" and not keyword_hits and ticker not in title:
        score -= 4

    if impact not in allowed_impacts and ticker not in title and not keyword_hits:
        score -= 5

    return score


def curate_headlines_for_stock(stock: dict) -> list[dict]:
    profile = get_ticker_profile(stock)

    try:
        headlines = load_headlines()
    except Exception:
        return []

    curated = []

    for headline in headlines or []:
        score = score_headline_for_stock(headline, profile)

        if score < 4:
            continue

        item = dict(headline)
        item["relevance_score"] = score
        curated.append(item)

    curated.sort(
        key=lambda item: item.get("relevance_score", 0),
        reverse=True,
    )

    return curated[:MAX_CURATED_HEADLINES]


def build_headline_impact_summary(stock: dict) -> str:
    profile = get_ticker_profile(stock)
    curated = curate_headlines_for_stock(stock)

    if not curated:
        return f"""
Portfolio Headline Read:
{profile["portfolio_read"]}

Curated Headlines:
No portfolio-specific headline signal detected right now.

Interpretation:
Do not force a headline narrative. Use price action, volume, and Smart Money confirmation instead.
""".strip()

    lines = []

    for item in curated:
        impact = item.get("impact") or "Market"
        title = clean_text(item.get("title"), 170)
        source = clean_text(item.get("source"), 40)

        lines.append(f"- [{impact}] {title} ({source})")

    primary_impacts = []

    for item in curated:
        impact = item.get("impact") or "Market"
        if impact not in primary_impacts:
            primary_impacts.append(impact)

    return f"""
Portfolio Headline Read:
{profile["portfolio_read"]}

Relevant Themes:
{", ".join(primary_impacts[:3])}

Curated Headlines:
{chr(10).join(lines)}

Interpretation:
These headlines are shown because they match this ticker's portfolio theme, category exposure, or risk profile.
""".strip()