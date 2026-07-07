from typing import Any


CORE_MIN_SCORE = 75
GROWTH_MIN_SCORE = 75
SPECULATIVE_KEYWORDS = [
    "HIGH RISK",
    "SPECULATIVE",
    "EARLY STAGE",
    "AUTONOMOUS",
    "SPACE",
]


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


def get_score(stock: dict, *keys: str, default: float = 0) -> float:
    for key in keys:
        if key in stock and stock.get(key) is not None:
            return safe_float(stock.get(key), default)

    return default


def get_category(stock: dict) -> str:
    return clean_text(stock.get("category") or "Unknown", 100)


def get_risk_text(stock: dict, risk_profile: dict | None) -> str:
    if isinstance(risk_profile, dict):
        if risk_profile.get("risk_level"):
            return clean_text(risk_profile.get("risk_level"), 80)
        if risk_profile.get("risk_label"):
            return clean_text(risk_profile.get("risk_label"), 80)

    return clean_text(
        stock.get("risk_label") or stock.get("risk_level") or "Risk needs review",
        80,
    )


def has_keyword(stock: dict, keywords: list[str]) -> bool:
    text = " ".join(
        [
            clean_text(stock.get("ticker") or "", 40),
            clean_text(stock.get("category") or "", 120),
            clean_text(stock.get("risk_label") or "", 120),
            clean_text(stock.get("rating") or "", 120),
        ]
    ).upper()

    return any(keyword.upper() in text for keyword in keywords)


def classify_role(stock: dict, risk_profile: dict | None = None) -> str:
    category = get_category(stock).upper()
    ticker = clean_symbol(stock.get("ticker"))
    final_score = get_score(stock, "final_score", "score", "smart_money_score")
    stability_score = get_score(stock, "defense_score")

    if ticker in {"VOO", "QQQ", "SCHD", "VYM"}:
        return "Core"

    if any(word in category for word in ["CORE", "ETF", "S&P", "MARKET ETF"]):
        return "Core"

    if any(word in category for word in ["DIVIDEND", "INCOME", "REIT", "HIGH DIVIDEND"]):
        return "Dividend / Income"

    if any(word in category for word in ["CYBER", "ZERO TRUST", "SECURITY"]):
        return "Cybersecurity"

    if any(word in category for word in ["DEFENSE", "AEROSPACE", "MISSILE", "NAVAL", "DRONE"]):
        return "Defense"

    if has_keyword(stock, SPECULATIVE_KEYWORDS):
        return "Speculative"

    if final_score >= GROWTH_MIN_SCORE and any(
        word in category
        for word in ["AI", "GROWTH", "CLOUD", "SEMICONDUCTOR", "SOFTWARE", "STREAMING"]
    ):
        return "Growth"

    if stability_score >= 80 and final_score >= CORE_MIN_SCORE:
        return "Core"

    if final_score >= GROWTH_MIN_SCORE:
        return "Growth"

    return "Watchlist"


def role_order(role: str) -> int:
    order = {
        "Core": 1,
        "Growth": 2,
        "Defense": 3,
        "Cybersecurity": 4,
        "Dividend / Income": 5,
        "Speculative": 6,
        "Watchlist": 7,
    }

    return order.get(role, 99)


def get_signal_overlap(stock: dict) -> int:
    congress_score = get_score(stock, "congress_score")
    insider_score = get_score(stock, "insider_score")
    final_score = get_score(stock, "final_score", "score", "smart_money_score")
    stability_score = get_score(stock, "defense_score")

    overlap = 0

    if congress_score >= 65:
        overlap += 1

    if insider_score >= 65:
        overlap += 1

    if final_score >= 75:
        overlap += 1

    if stability_score >= 75:
        overlap += 1

    return overlap


def rank_key(item: tuple[dict, dict | None]) -> tuple:
    stock, risk_profile = item

    role = classify_role(stock, risk_profile)

    return (
        -role_order(role),
        get_score(stock, "final_score", "score", "smart_money_score"),
        get_signal_overlap(stock),
        get_score(stock, "defense_score"),
    )


def rank_within_role(item: tuple[dict, dict | None]) -> tuple:
    stock, risk_profile = item

    return (
        get_score(stock, "final_score", "score", "smart_money_score"),
        get_signal_overlap(stock),
        get_score(stock, "defense_score"),
        get_score(stock, "congress_score") + get_score(stock, "insider_score"),
    )


def build_thesis(stock: dict) -> str:
    reason = clean_text(stock.get("reason") or stock.get("thesis") or "", 170)

    if reason:
        return reason

    role = classify_role(stock)
    category = get_category(stock)

    return f"Fits the {role} bucket based on score profile, category, and signal mix in {category}."


def build_risk_notes(stock: dict, risk_profile: dict | None) -> str:
    risks = stock.get("risks")

    if isinstance(risks, list) and risks:
        return "; ".join(clean_text(item, 75) for item in risks[:3])

    weaknesses = stock.get("weaknesses")

    if isinstance(weaknesses, list) and weaknesses:
        return "; ".join(clean_text(item, 75) for item in weaknesses[:3])

    return get_risk_text(stock, risk_profile)


def build_stock_line(index: int, stock: dict, risk_profile: dict | None) -> str:
    ticker = clean_symbol(stock.get("ticker")) or "UNKNOWN"
    category = get_category(stock)
    role = classify_role(stock, risk_profile)

    final_score = get_score(stock, "final_score", "score", "smart_money_score")
    congress_score = get_score(stock, "congress_score")
    insider_score = get_score(stock, "insider_score")
    stability_score = get_score(stock, "defense_score")
    risk_text = get_risk_text(stock, risk_profile)

    return f"""
{index}. {ticker} — {role}
Category: {category}
Final Score: {final_score:.0f}/100 | Stability: {stability_score:.0f}/100
Congress: {congress_score:.0f}/100 | Insider: {insider_score:.0f}/100
Signal Overlap: {get_signal_overlap(stock)}/4
Risk: {risk_text}
Role Thesis: {build_thesis(stock)}
Risk Notes: {build_risk_notes(stock, risk_profile)}
""".strip()


def build_summary(items: list[tuple[dict, dict | None]]) -> str:
    buckets = group_by_role(items)

    lines = [f"Total Reviewed: {len(items)}"]

    for role in [
        "Core",
        "Growth",
        "Defense",
        "Cybersecurity",
        "Dividend / Income",
        "Speculative",
        "Watchlist",
    ]:
        count = len(buckets.get(role, []))

        if count:
            lines.append(f"{role}: {count}")

    return "\n".join(lines)


def group_by_role(items: list[tuple[dict, dict | None]]) -> dict[str, list[tuple[dict, dict | None]]]:
    groups: dict[str, list[tuple[dict, dict | None]]] = {}

    for item in items:
        stock, risk_profile = item
        role = classify_role(stock, risk_profile)
        groups.setdefault(role, []).append(item)

    for role in groups:
        groups[role].sort(key=rank_within_role, reverse=True)

    return groups


def filter_symbol(items: list[tuple[dict, dict | None]], symbol: str | None) -> list[tuple[dict, dict | None]]:
    if not symbol:
        return items

    clean = clean_symbol(symbol)

    return [
        item
        for item in items
        if clean_symbol(item[0].get("ticker")) == clean
    ]


def build_role_section(
    role: str,
    items: list[tuple[dict, dict | None]],
    limit: int,
) -> str:
    if not items:
        return ""

    blocks = "\n\n".join(
        build_stock_line(index, stock, risk_profile)
        for index, (stock, risk_profile) in enumerate(items[:limit], start=1)
    )

    return f"{role}\n{blocks}"


def build_portfolio_report(
    stocks: list[dict],
    risk_profiles: dict[str, dict],
    symbol: str | None = None,
    per_bucket_limit: int = 4,
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
📦 Smart Money AI Portfolio Role Report: {clean}

No scoring record found for {clean}.

Try:
/scorecard {clean}
/ticker {clean}
/smartmoney {clean}
/conviction {clean}

Note
This is informational only and is not financial advice.
""".strip()

    if clean:
        stock, risk_profile = filtered_items[0]
        role = classify_role(stock, risk_profile)
        sections = build_stock_line(1, stock, risk_profile)
        title = f"📦 Smart Money AI Portfolio Role Report: {clean}"
        role_note = f"Portfolio Role: {role}"
    else:
        groups = group_by_role(filtered_items)

        sections = "\n\n".join(
            section
            for section in [
                build_role_section("Core", groups.get("Core", []), per_bucket_limit),
                build_role_section("Growth", groups.get("Growth", []), per_bucket_limit),
                build_role_section("Defense", groups.get("Defense", []), per_bucket_limit),
                build_role_section("Cybersecurity", groups.get("Cybersecurity", []), per_bucket_limit),
                build_role_section("Dividend / Income", groups.get("Dividend / Income", []), per_bucket_limit),
                build_role_section("Speculative", groups.get("Speculative", []), per_bucket_limit),
                build_role_section("Watchlist", groups.get("Watchlist", []), per_bucket_limit),
            ]
            if section
        )

        title = "📦 Smart Money AI Portfolio Roles"
        role_note = "Buckets are research roles, not allocation instructions."

    if not sections:
        sections = "No portfolio role records available."

    return f"""
{title}

Summary
{build_summary(filtered_items)}

{role_note}

Portfolio Buckets
{sections}

Next Commands
/scorecard SYMBOL
/ticker SYMBOL
/smartmoney SYMBOL
/conviction SYMBOL
/undervalued SYMBOL
/top10
/report

Note
This report groups research ideas by possible portfolio role.
It does not recommend position size, allocation, or financial advice.
""".strip()