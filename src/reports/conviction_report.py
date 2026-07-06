from typing import Any


CONGRESS_THRESHOLD = 65
INSIDER_THRESHOLD = 65
FINAL_SCORE_THRESHOLD = 75
STABILITY_THRESHOLD = 75


def safe_float(value: Any, default: float = 0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_text(value: Any, max_length: int = 140) -> str:
    if value is None:
        return ""

    text = " ".join(str(value).split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def clean_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("$", "")


def get_stock_score(stock: dict, *keys: str, default: float = 0) -> float:
    for key in keys:
        if key in stock and stock.get(key) is not None:
            return safe_float(stock.get(key), default)

    return default


def get_risk_value(stock: dict, risk_profile: dict | None, key: str, fallback_key: str | None = None, default: Any = "N/A"):
    if isinstance(risk_profile, dict) and risk_profile.get(key) is not None:
        return risk_profile.get(key)

    if fallback_key and stock.get(fallback_key) is not None:
        return stock.get(fallback_key)

    if stock.get(key) is not None:
        return stock.get(key)

    return default


def get_signal_flags(stock: dict) -> dict:
    congress_score = get_stock_score(stock, "congress_score")
    insider_score = get_stock_score(stock, "insider_score")
    final_score = get_stock_score(stock, "final_score", "score", "smart_money_score")
    stability_score = get_stock_score(stock, "defense_score")

    return {
        "congress": congress_score >= CONGRESS_THRESHOLD,
        "insider": insider_score >= INSIDER_THRESHOLD,
        "core": final_score >= FINAL_SCORE_THRESHOLD,
        "stability": stability_score >= STABILITY_THRESHOLD,
    }


def get_overlap_count(stock: dict) -> int:
    flags = get_signal_flags(stock)
    return sum(1 for enabled in flags.values() if enabled)


def is_high_risk(stock: dict, risk_profile: dict | None) -> bool:
    risk_text = " ".join(
        [
            clean_text(get_risk_value(stock, risk_profile, "risk_level", "risk_label", ""), 80),
            clean_text(get_risk_value(stock, risk_profile, "risk_label", "risk_level", ""), 80),
            clean_text(stock.get("category") or "", 100),
        ]
    ).upper()

    high_risk_keywords = [
        "HIGH",
        "SPECULATIVE",
        "AGGRESSIVE",
        "VOLATILE",
        "EARLY STAGE",
        "HIGH RISK",
    ]

    return any(keyword in risk_text for keyword in high_risk_keywords)


def is_controlled_risk(stock: dict, risk_profile: dict | None) -> bool:
    if is_high_risk(stock, risk_profile):
        return False

    stability_score = get_stock_score(stock, "defense_score")

    return stability_score >= STABILITY_THRESHOLD


def get_conviction_label(stock: dict, risk_profile: dict | None) -> str:
    overlap = get_overlap_count(stock)

    if overlap >= 3 and is_controlled_risk(stock, risk_profile):
        return "Controlled conviction"

    if overlap >= 3 and is_high_risk(stock, risk_profile):
        return "High conviction / high risk"

    if overlap >= 3:
        return "High conviction"

    if overlap == 2:
        return "Developing conviction"

    if overlap == 1:
        return "Single-signal watchlist"

    return "Limited conviction"


def get_signal_line(stock: dict) -> str:
    flags = get_signal_flags(stock)

    return " | ".join(
        [
            "Congress ✅" if flags["congress"] else "Congress ⚪",
            "Insiders ✅" if flags["insider"] else "Insiders ⚪",
            "Core ✅" if flags["core"] else "Core ⚪",
            "Stability ✅" if flags["stability"] else "Stability ⚪",
        ]
    )


def conviction_rank_key(item: tuple[dict, dict | None]) -> tuple:
    stock, risk_profile = item

    final_score = get_stock_score(stock, "final_score", "score", "smart_money_score")
    congress_score = get_stock_score(stock, "congress_score")
    insider_score = get_stock_score(stock, "insider_score")
    stability_score = get_stock_score(stock, "defense_score")

    controlled_bonus = 10 if is_controlled_risk(stock, risk_profile) else 0
    high_risk_penalty = -8 if is_high_risk(stock, risk_profile) else 0

    return (
        get_overlap_count(stock),
        final_score,
        congress_score + insider_score,
        stability_score + controlled_bonus + high_risk_penalty,
    )


def filter_symbol(items: list[tuple[dict, dict | None]], symbol: str | None) -> list[tuple[dict, dict | None]]:
    if not symbol:
        return items

    clean = clean_symbol(symbol)

    return [
        item
        for item in items
        if clean_symbol(item[0].get("ticker")) == clean
    ]


def build_strengths(stock: dict) -> str:
    strengths = stock.get("strengths")

    if isinstance(strengths, list) and strengths:
        return "; ".join(clean_text(item, 75) for item in strengths[:3])

    return "Multiple scoring inputs are reviewed together instead of relying on one signal."


def build_risks(stock: dict, risk_profile: dict | None) -> str:
    risks = stock.get("risks")

    if isinstance(risks, list) and risks:
        return "; ".join(clean_text(item, 75) for item in risks[:3])

    weaknesses = stock.get("weaknesses")

    if isinstance(weaknesses, list) and weaknesses:
        return "; ".join(clean_text(item, 75) for item in weaknesses[:3])

    risk_level = clean_text(get_risk_value(stock, risk_profile, "risk_level", "risk_label", "Risk needs review"), 90)

    return risk_level


def build_thesis(stock: dict) -> str:
    reason = clean_text(stock.get("reason") or stock.get("thesis") or "", 170)

    if reason:
        return reason

    category = clean_text(stock.get("category") or "Unknown category", 90)

    return f"Conviction is based on overlap between smart-money, core score, and risk-quality signals in {category}."


def build_stock_block(index: int, stock: dict, risk_profile: dict | None) -> str:
    ticker = clean_symbol(stock.get("ticker")) or "UNKNOWN"
    category = clean_text(stock.get("category") or "Unknown", 90)

    final_score = get_stock_score(stock, "final_score", "score", "smart_money_score")
    congress_score = get_stock_score(stock, "congress_score")
    insider_score = get_stock_score(stock, "insider_score")
    stability_score = get_stock_score(stock, "defense_score")

    risk_level = clean_text(get_risk_value(stock, risk_profile, "risk_level", "risk_label", "N/A"), 80)
    risk_score = get_risk_value(stock, risk_profile, "risk_score", default="N/A")

    return f"""
{index}. {ticker} — {get_conviction_label(stock, risk_profile)}
Category: {category}
Final Score: {final_score:.0f}/100
Congress: {congress_score:.0f}/100 | Insider: {insider_score:.0f}/100 | Stability: {stability_score:.0f}/100
Signal Overlap: {get_overlap_count(stock)}/4
Signals: {get_signal_line(stock)}
Risk Level: {risk_level} | Risk Score: {risk_score}/100
Thesis: {build_thesis(stock)}
Strengths: {build_strengths(stock)}
Risk Control: {build_risks(stock, risk_profile)}
""".strip()


def group_items(items: list[tuple[dict, dict | None]]) -> dict[str, list[tuple[dict, dict | None]]]:
    groups = {
        "controlled": [],
        "high_risk": [],
        "developing": [],
        "limited": [],
    }

    for item in items:
        stock, risk_profile = item
        overlap = get_overlap_count(stock)

        if overlap >= 3 and is_controlled_risk(stock, risk_profile):
            groups["controlled"].append(item)
        elif overlap >= 3 and is_high_risk(stock, risk_profile):
            groups["high_risk"].append(item)
        elif overlap >= 2:
            groups["developing"].append(item)
        else:
            groups["limited"].append(item)

    for key in groups:
        groups[key].sort(key=conviction_rank_key, reverse=True)

    return groups


def build_summary(items: list[tuple[dict, dict | None]]) -> str:
    groups = group_items(items)

    return "\n".join(
        [
            f"Total Reviewed: {len(items)}",
            f"Controlled Conviction: {len(groups['controlled'])}",
            f"High Conviction / High Risk: {len(groups['high_risk'])}",
            f"Developing Conviction: {len(groups['developing'])}",
            f"Limited / Single Signal: {len(groups['limited'])}",
        ]
    )


def build_section(title: str, items: list[tuple[dict, dict | None]], limit: int) -> str:
    if not items:
        return ""

    blocks = "\n\n".join(
        build_stock_block(index, stock, risk_profile)
        for index, (stock, risk_profile) in enumerate(items[:limit], start=1)
    )

    return f"{title}\n{blocks}"


def build_conviction_report(
    stocks: list[dict],
    risk_profiles: dict[str, dict],
    symbol: str | None = None,
    limit: int = 5,
) -> str:
    clean = clean_symbol(symbol) if symbol else None

    items = [
        (
            stock,
            risk_profiles.get(clean_symbol(stock.get("ticker")), {}),
        )
        for stock in stocks
    ]

    filtered_items = filter_symbol(items, clean)

    if clean and not filtered_items:
        return f"""
🔥 Smart Money AI Conviction Report: {clean}

No scoring record found for {clean}.

Try:
/scorecard {clean}
/ticker {clean}
/smartmoney {clean}
/top10

Note
This is informational only and is not financial advice.
""".strip()

    groups = group_items(filtered_items)

    if clean:
        stock, risk_profile = filtered_items[0]
        sections = build_stock_block(1, stock, risk_profile)
        title = f"🔥 Smart Money AI Conviction Report: {clean}"
    else:
        title = "🔥 Smart Money AI Conviction Report"

        sections = "\n\n".join(
            section
            for section in [
                build_section("✅ Controlled Conviction", groups["controlled"], limit),
                build_section("⚠️ High Conviction / High Risk", groups["high_risk"], limit),
                build_section("📈 Developing Conviction", groups["developing"], limit),
            ]
            if section
        )

    if not sections:
        sections = "No conviction records available."

    return f"""
{title}

Summary
{build_summary(filtered_items)}

Signal Rules
Congress ✅ = score >= {CONGRESS_THRESHOLD}
Insiders ✅ = score >= {INSIDER_THRESHOLD}
Core ✅ = final score >= {FINAL_SCORE_THRESHOLD}
Stability ✅ = stability score >= {STABILITY_THRESHOLD}

Ranked Conviction Ideas
{sections}

Next Commands
/smartmoney
/smartmoney SYMBOL
/scorecard SYMBOL
/ticker SYMBOL
/top10
/report

Note
High conviction means multiple signals overlap.
Controlled conviction adds risk-quality filtering.
High conviction does not automatically mean low risk.
This is informational only and is not financial advice.
""".strip()