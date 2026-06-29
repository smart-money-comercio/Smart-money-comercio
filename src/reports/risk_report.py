from typing import Any


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("$", "")


def format_number(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    if number >= 1_000_000_000_000:
        return f"${number / 1_000_000_000_000:.2f}T"

    if number >= 1_000_000_000:
        return f"${number / 1_000_000_000:.2f}B"

    if number >= 1_000_000:
        return f"${number / 1_000_000:.2f}M"

    return f"${number:,.0f}"


def format_price(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    return f"${number:,.2f}"


def format_percent(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    return f"{number:.2f}%"


def classify_beta_risk(beta: float | None) -> str:
    if beta is None:
        return "Beta unavailable"

    if beta >= 2:
        return "Very high volatility"
    if beta >= 1.5:
        return "High volatility"
    if beta >= 1.1:
        return "Above-market volatility"
    if beta >= 0.8:
        return "Market-like volatility"
    if beta >= 0:
        return "Below-market volatility"

    return "Unusual beta profile"


def classify_valuation_risk(pe_ratio: float | None, forward_pe: float | None) -> str:
    valuation = forward_pe if forward_pe is not None else pe_ratio

    if valuation is None:
        return "Valuation data unavailable"

    if valuation >= 80:
        return "Very high valuation risk"
    if valuation >= 50:
        return "High valuation risk"
    if valuation >= 30:
        return "Elevated valuation risk"
    if valuation >= 15:
        return "Moderate valuation risk"
    if valuation > 0:
        return "Lower valuation risk"

    return "Valuation may not be meaningful"


def classify_market_cap_risk(market_cap: float | None) -> str:
    if market_cap is None:
        return "Market cap unavailable"

    if market_cap >= 200_000_000_000:
        return "Mega-cap liquidity profile"
    if market_cap >= 10_000_000_000:
        return "Large-cap liquidity profile"
    if market_cap >= 2_000_000_000:
        return "Mid-cap risk profile"
    if market_cap >= 300_000_000:
        return "Small-cap risk profile"

    return "Micro-cap / speculative risk profile"


def derive_fallback_risk_score(market_data: dict | None) -> int:
    if not market_data or not market_data.get("found"):
        return 75

    beta = safe_float(market_data.get("beta"))
    pe_ratio = safe_float(market_data.get("pe_ratio"))
    forward_pe = safe_float(market_data.get("forward_pe"))
    market_cap = safe_float(market_data.get("market_cap"))

    score = 40

    if beta is None:
        score += 10
    elif beta >= 2:
        score += 35
    elif beta >= 1.5:
        score += 25
    elif beta >= 1.1:
        score += 15
    elif beta < 0.8:
        score += 5

    valuation = forward_pe if forward_pe is not None else pe_ratio

    if valuation is None:
        score += 10
    elif valuation >= 80:
        score += 30
    elif valuation >= 50:
        score += 22
    elif valuation >= 30:
        score += 14
    elif valuation <= 0:
        score += 18

    if market_cap is None:
        score += 10
    elif market_cap < 300_000_000:
        score += 30
    elif market_cap < 2_000_000_000:
        score += 22
    elif market_cap < 10_000_000_000:
        score += 12

    return max(0, min(100, score))


def classify_risk_level(risk_score: int | float | None) -> str:
    score = safe_float(risk_score)

    if score is None:
        return "Unknown"

    if score >= 85:
        return "Very High"
    if score >= 70:
        return "High"
    if score >= 55:
        return "Medium-High"
    if score >= 40:
        return "Moderate"
    return "Lower"


def build_position_guidance(risk_level: str) -> str:
    normalized = risk_level.lower()

    if "very high" in normalized:
        return "Use very small sizing or avoid until risk improves."
    if "high" in normalized:
        return "Use reduced sizing and require strong confirmation."
    if "medium" in normalized:
        return "Use disciplined sizing and define a stop before entry."
    if "moderate" in normalized:
        return "Standard sizing may be reasonable only with a clean setup."

    return "Sizing can be more flexible, but still define risk first."


def build_verification_checklist(risk_level: str) -> list[str]:
    checklist = [
        "Confirm earnings date and major upcoming catalysts.",
        "Check chart trend, support, resistance, and volume.",
        "Review news for legal, regulatory, or dilution risk.",
    ]

    if risk_level.lower() in {"high", "very high", "medium-high"}:
        checklist.append("Avoid entering without a clear invalidation level.")

    return checklist


def get_market_data_field(market_data: dict | None, key: str, default="N/A"):
    if not market_data or not market_data.get("found"):
        return default

    value = market_data.get(key)

    if value is None:
        return default

    return value


def build_risk_drivers(
    risk_profile: dict | None,
    market_data: dict | None,
) -> list[str]:
    drivers = []

    if risk_profile:
        factors = risk_profile.get("risk_factors") or []

        for factor in factors:
            text = str(factor).strip()
            if text:
                drivers.append(text)

    if market_data and market_data.get("found"):
        beta = safe_float(market_data.get("beta"))
        pe_ratio = safe_float(market_data.get("pe_ratio"))
        forward_pe = safe_float(market_data.get("forward_pe"))
        market_cap = safe_float(market_data.get("market_cap"))

        drivers.append(classify_beta_risk(beta))
        drivers.append(classify_valuation_risk(pe_ratio, forward_pe))
        drivers.append(classify_market_cap_risk(market_cap))

    cleaned = []

    for driver in drivers:
        if driver and driver not in cleaned:
            cleaned.append(driver)

    if not cleaned:
        cleaned.append("Risk drivers unavailable from current data.")

    return cleaned[:6]


def format_bullets(items: list[str]) -> str:
    return "\n".join(f"• {item}" for item in items)


def build_risk_report(
    symbol: str,
    stock: dict | None,
    risk_profile: dict | None,
    market_data: dict | None,
) -> str:
    clean = clean_symbol(symbol)

    company_name = get_market_data_field(market_data, "company_name", clean)
    sector = get_market_data_field(market_data, "sector", "N/A")
    industry = get_market_data_field(market_data, "industry", "N/A")
    price = get_market_data_field(market_data, "price", None)
    market_cap = get_market_data_field(market_data, "market_cap", None)
    beta = get_market_data_field(market_data, "beta", None)
    pe_ratio = get_market_data_field(market_data, "pe_ratio", None)
    forward_pe = get_market_data_field(market_data, "forward_pe", None)
    dividend_yield = get_market_data_field(market_data, "dividend_yield", None)

    if risk_profile:
        risk_score = risk_profile.get("risk_score")
        risk_level = risk_profile.get("risk_level") or classify_risk_level(risk_score)
    else:
        risk_score = derive_fallback_risk_score(market_data)
        risk_level = classify_risk_level(risk_score)

    category = "N/A"

    if stock:
        category = stock.get("category") or "N/A"

    risk_drivers = build_risk_drivers(risk_profile, market_data)
    position_guidance = build_position_guidance(str(risk_level))
    checklist = build_verification_checklist(str(risk_level))

    return f"""
⚠️ Smart Money AI Risk Report: {clean}

Company
Name: {company_name}
Sector: {sector}
Industry: {industry}
Category: {category}

Market Snapshot
Price: {format_price(price)}
Market Cap: {format_number(market_cap)}
Beta: {beta if beta not in {None, 'N/A'} else 'N/A'}
P/E: {pe_ratio if pe_ratio not in {None, 'N/A'} else 'N/A'}
Forward P/E: {forward_pe if forward_pe not in {None, 'N/A'} else 'N/A'}
Dividend Yield: {format_percent(dividend_yield)}

Risk Rating
Risk Level: {risk_level}
Risk Score: {risk_score}/100

Key Risk Drivers
{format_bullets(risk_drivers)}

Position Guidance
{position_guidance}

Before Acting
{format_bullets(checklist)}

Notes
This risk report is informational only and is not financial advice.
Use /scorecard {clean} for the opportunity view.
Use /quote {clean} for quick market data.
""".strip()