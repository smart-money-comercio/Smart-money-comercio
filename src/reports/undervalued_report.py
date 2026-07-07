from typing import Any


MIN_FINAL_SCORE = 70
MIN_STABILITY_SCORE = 55
HIGH_CONVICTION_SCORE = 80
HIGH_RISK_PENALTY = 12


def safe_float(value: Any, default: float = 0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("$", "")


def clean_text(value: Any, max_length: int = 140) -> str:
    if value is None:
        return ""

    text = " ".join(str(value).split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def get_score(stock: dict, *keys: str, default: float = 0) -> float:
    for key in keys:
        if key in stock and stock.get(key) is not None:
            return safe_float(stock.get(key), default)

    return default


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


def is_high_risk(stock: dict, risk_profile: dict | None) -> bool:
    combined = " ".join(
        [
            get_risk_text(stock, risk_profile),
            clean_text(stock.get("category") or "", 100),
        ]
    ).upper()

    high_risk_words = [
        "HIGH RISK",
        "HIGH",
        "SPECULATIVE",
        "AGGRESSIVE",
        "VOLATILE",
        "EARLY STAGE",
    ]

    return any(word in combined for word in high_risk_words)


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


def get_value_gap_score(stock: dict, risk_profile: dict | None) -> float:
    final_score = get_score(stock, "final_score", "score", "smart_money_score")
    smart_score = get_score(stock, "smart_score")
    stability_score = get_score(stock, "defense_score")
    congress_score = get_score(stock, "congress_score")
    insider_score = get_score(stock, "insider_score")

    signal_quality = (
        final_score * 0.45
        + smart_score * 0.20
        + stability_score * 0.15
        + congress_score * 0.10
        + insider_score * 0.10
    )

    overlap_bonus = get_signal_overlap(stock) * 4
    risk_penalty = HIGH_RISK_PENALTY if is_high_risk(stock, risk_profile) else 0

    return round(signal_quality + overlap_bonus - risk_penalty, 1)


def get_value_label(stock: dict, risk_profile: dict | None) -> str:
    value_gap = get_value_gap_score(stock, risk_profile)
    final_score = get_score(stock, "final_score", "score", "smart_money_score")
    stability_score = get_score(stock, "defense_score")
    overlap = get_signal_overlap(stock)

    if value_gap >= 85 and stability_score >= 75 and overlap >= 3:
        return "High-quality value watch"

    if value_gap >= 78 and final_score >= HIGH_CONVICTION_SCORE:
        return "Strong value watch"

    if value_gap >= 72 and overlap >= 2:
        return "Developing value watch"

    if is_high_risk(stock, risk_profile):
        return "Speculative value watch"

    return "Needs more confirmation"


def is_candidate(stock: dict, risk_profile: dict | None) -> bool:
    final_score = get_score(stock, "final_score", "score", "smart_money_score")
    stability_score = get_score(stock, "defense_score")
    value_gap = get_value_gap_score(stock, risk_profile)
    overlap = get_signal_overlap(stock)

    if final_score < MIN_FINAL_SCORE:
        return False

    if stability_score < MIN_STABILITY_SCORE and overlap < 3:
        return False

    return value_gap >= 68


def rank_key(item: tuple[dict, dict | None]) -> tuple:
    stock, risk_profile = item

    return (
        get_value_gap_score(stock, risk_profile),
        get_signal_overlap(stock),
        get_score(stock, "final_score", "score", "smart_money_score"),
        get_score(stock, "defense_score"),
    )


def build_thesis(stock: dict) -> str:
    reason = clean_text(stock.get("reason") or stock.get("thesis") or "", 170)

    if reason:
        return reason

    category = clean_text(stock.get("category") or "Unknown category", 90)

    return (
        "This stock screens as a valuation watch candidate because its signal quality "
        f"appears stronger than its risk-adjusted profile suggests in {category}."
    )


def build_strengths(stock: dict) -> str:
    strengths = stock.get("strengths")

    if isinstance(strengths, list) and strengths:
        return "; ".join(clean_text(item, 75) for item in strengths[:3])

    return "Strong candidates should combine core score, stability, and smart-money signal support."


def build_risks(stock: dict, risk_profile: dict | None) -> str:
    risks = stock.get("risks")

    if isinstance(risks, list) and risks:
        return "; ".join(clean_text(item, 75) for item in risks[:3])

    weaknesses = stock.get("weaknesses")

    if isinstance(weaknesses, list) and weaknesses:
        return "; ".join(clean_text(item, 75) for item in weaknesses[:3])

    return get_risk_text(stock, risk_profile)


def build_stock_block(index: int, stock: dict, risk_profile: dict | None) -> str:
    ticker = clean_symbol(stock.get("ticker")) or "UNKNOWN"
    category = clean_text(stock.get("category") or "Unknown", 90)

    final_score = get_score(stock, "final_score", "score", "smart_money_score")
    smart_score = get_score(stock, "smart_score")
    congress_score = get_score(stock, "congress_score")
    insider_score = get_score(stock, "insider_score")
    stability_score = get_score(stock, "defense_score")
    value_gap = get_value_gap_score(stock, risk_profile)
    overlap = get_signal_overlap(stock)
    risk_text = get_risk_text(stock, risk_profile)

    return f"""
{index}. {ticker} — {get_value_label(stock, risk_profile)}
Category: {category}
Value Gap Score: {value_gap}/100
Final Score: {final_score:.0f}/100 | Smart Score: {smart_score:.0f}/100
Congress: {congress_score:.0f}/100 | Insider: {insider_score:.0f}/100 | Stability: {stability_score:.0f}/100
Signal Overlap: {overlap}/4
Risk: {risk_text}
Thesis: {build_thesis(stock)}
Strengths: {build_strengths(stock)}
Risk Notes: {build_risks(stock, risk_profile)}
""".strip()


def filter_symbol(items: list[tuple[dict, dict | None]], symbol: str | None) -> list[tuple[dict, dict | None]]:
    if not symbol:
        return items

    clean = clean_symbol(symbol)

    return [
        item
        for item in items
        if clean_symbol(item[0].get("ticker")) == clean
    ]


def build_summary(items: list[tuple[dict, dict | None]]) -> str:
    candidates = [
        item
        for item in items
        if is_candidate(item[0], item[1])
    ]

    high_quality = [
        item
        for item in candidates
        if get_value_gap_score(item[0], item[1]) >= 85
    ]

    developing = [
        item
        for item in candidates
        if 72 <= get_value_gap_score(item[0], item[1]) < 85
    ]

    speculative = [
        item
        for item in candidates
        if is_high_risk(item[0], item[1])
    ]

    return "\n".join(
        [
            f"Total Reviewed: {len(items)}",
            f"Value Watch Candidates: {len(candidates)}",
            f"High-Quality Candidates: {len(high_quality)}",
            f"Developing Candidates: {len(developing)}",
            f"Speculative Candidates: {len(speculative)}",
        ]
    )


def build_undervalued_report(
    stocks: list[dict],
    risk_profiles: dict[str, dict],
    symbol: str | None = None,
    limit: int = 8,
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
💎 Smart Money AI Valuation Watch: {clean}

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
        shown_items = filtered_items[:1]
        title = f"💎 Smart Money AI Valuation Watch: {clean}"
    else:
        candidates = [
            item
            for item in filtered_items
            if is_candidate(item[0], item[1])
        ]

        shown_items = sorted(candidates, key=rank_key, reverse=True)[:limit]
        title = "💎 Smart Money AI Undervalued / Value Watch"

    if shown_items:
        blocks = "\n\n".join(
            build_stock_block(index, stock, risk_profile)
            for index, (stock, risk_profile) in enumerate(shown_items, start=1)
        )
    else:
        blocks = "No value watch candidates passed the current filters."

    return f"""
{title}

Summary
{build_summary(filtered_items)}

Screening Rules
Minimum Final Score: {MIN_FINAL_SCORE}
Minimum Stability Score: {MIN_STABILITY_SCORE}
High-risk names are penalized, not excluded.
This is a signal-quality screen, not a full intrinsic-value model.

Ranked Value Watch
{blocks}

Next Commands
/scorecard SYMBOL
/ticker SYMBOL
/smartmoney SYMBOL
/conviction SYMBOL
/top10
/report

Note
“Undervalued” here means the stock may deserve further valuation research based on score/risk/signal balance.
It does not mean the stock is guaranteed to be below intrinsic value.
This is informational only and is not financial advice.
""".strip()