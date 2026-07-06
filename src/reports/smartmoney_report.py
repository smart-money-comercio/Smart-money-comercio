from typing import Any


SMART_CONGRESS_THRESHOLD = 65
SMART_INSIDER_THRESHOLD = 65
SMART_FINAL_SCORE_THRESHOLD = 75
SMART_STABILITY_THRESHOLD = 75


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


def get_signal_flags(stock: dict) -> dict:
    congress_score = get_stock_score(stock, "congress_score")
    insider_score = get_stock_score(stock, "insider_score")
    final_score = get_stock_score(stock, "final_score", "score", "smart_money_score")
    defense_score = get_stock_score(stock, "defense_score")

    return {
        "congress": congress_score >= SMART_CONGRESS_THRESHOLD,
        "insider": insider_score >= SMART_INSIDER_THRESHOLD,
        "core": final_score >= SMART_FINAL_SCORE_THRESHOLD,
        "stability": defense_score >= SMART_STABILITY_THRESHOLD,
    }


def get_overlap_count(stock: dict) -> int:
    flags = get_signal_flags(stock)
    return sum(1 for enabled in flags.values() if enabled)


def get_overlap_label(stock: dict) -> str:
    count = get_overlap_count(stock)

    if count >= 4:
        return "Elite overlap"
    if count == 3:
        return "Strong overlap"
    if count == 2:
        return "Moderate overlap"
    if count == 1:
        return "Single signal"

    return "Limited signal"


def get_signal_icons(stock: dict) -> str:
    flags = get_signal_flags(stock)

    parts = [
        "Congress ✅" if flags["congress"] else "Congress ⚪",
        "Insiders ✅" if flags["insider"] else "Insiders ⚪",
        "Core ✅" if flags["core"] else "Core ⚪",
        "Stability ✅" if flags["stability"] else "Stability ⚪",
    ]

    return " | ".join(parts)


def smartmoney_rank_key(stock: dict) -> tuple:
    congress_score = get_stock_score(stock, "congress_score")
    insider_score = get_stock_score(stock, "insider_score")
    final_score = get_stock_score(stock, "final_score", "score", "smart_money_score")
    defense_score = get_stock_score(stock, "defense_score")

    return (
        get_overlap_count(stock),
        final_score,
        congress_score + insider_score,
        defense_score,
    )


def filter_symbol(stocks: list[dict], symbol: str | None) -> list[dict]:
    if not symbol:
        return stocks

    clean = clean_symbol(symbol)

    return [
        stock
        for stock in stocks
        if clean_symbol(stock.get("ticker")) == clean
    ]


def build_thesis_line(stock: dict) -> str:
    reason = clean_text(stock.get("reason") or stock.get("thesis") or "", 160)

    if reason:
        return reason

    category = clean_text(stock.get("category") or "Unknown category", 100)
    overlap = get_overlap_label(stock)

    return f"{overlap} across Smart Money AI signals in {category}."


def build_strengths_line(stock: dict) -> str:
    strengths = stock.get("strengths")

    if isinstance(strengths, list) and strengths:
        return "; ".join(clean_text(item, 70) for item in strengths[:3])

    return "Signal strength depends on overlap between Congress, insider, core score, and stability inputs."


def build_risk_line(stock: dict) -> str:
    risks = stock.get("risks")

    if isinstance(risks, list) and risks:
        return "; ".join(clean_text(item, 70) for item in risks[:3])

    weaknesses = stock.get("weaknesses")

    if isinstance(weaknesses, list) and weaknesses:
        return "; ".join(clean_text(item, 70) for item in weaknesses[:3])

    risk_label = clean_text(stock.get("risk_label") or stock.get("risk_level") or "Risk needs review", 80)

    return risk_label


def build_stock_block(index: int, stock: dict) -> str:
    ticker = clean_symbol(stock.get("ticker")) or "UNKNOWN"
    category = clean_text(stock.get("category") or "Unknown", 90)

    final_score = get_stock_score(stock, "final_score", "score", "smart_money_score")
    congress_score = get_stock_score(stock, "congress_score")
    insider_score = get_stock_score(stock, "insider_score")
    defense_score = get_stock_score(stock, "defense_score")
    rating = clean_text(stock.get("rating") or get_overlap_label(stock), 70)
    risk_label = clean_text(stock.get("risk_label") or stock.get("risk_level") or "N/A", 70)

    return f"""
{index}. {ticker} — {get_overlap_label(stock)}
Category: {category}
Final Score: {final_score:.0f}/100 | Rating: {rating}
Congress: {congress_score:.0f}/100 | Insider: {insider_score:.0f}/100 | Stability: {defense_score:.0f}/100
Signals: {get_signal_icons(stock)}
Risk: {risk_label}
Thesis: {build_thesis_line(stock)}
Strengths: {build_strengths_line(stock)}
Risk Notes: {build_risk_line(stock)}
""".strip()


def build_summary(stocks: list[dict]) -> str:
    if not stocks:
        return "No stocks available."

    elite = [stock for stock in stocks if get_overlap_count(stock) >= 4]
    strong = [stock for stock in stocks if get_overlap_count(stock) == 3]
    moderate = [stock for stock in stocks if get_overlap_count(stock) == 2]
    limited = [stock for stock in stocks if get_overlap_count(stock) <= 1]

    return "\n".join(
        [
            f"Total Reviewed: {len(stocks)}",
            f"Elite Overlap: {len(elite)}",
            f"Strong Overlap: {len(strong)}",
            f"Moderate Overlap: {len(moderate)}",
            f"Limited / Single Signal: {len(limited)}",
        ]
    )


def build_smartmoney_report(
    stocks: list[dict],
    symbol: str | None = None,
    limit: int = 10,
) -> str:
    clean = clean_symbol(symbol) if symbol else None
    filtered_stocks = filter_symbol(stocks, clean)

    if clean and not filtered_stocks:
        return f"""
🧠 Smart Money AI Signal Report: {clean}

No scoring record found for {clean}.

Try:
/scorecard {clean}
/ticker {clean}
/top10
/report

Note
This is informational only and is not financial advice.
""".strip()

    ranked = sorted(
        filtered_stocks,
        key=smartmoney_rank_key,
        reverse=True,
    )

    if clean:
        title = f"🧠 Smart Money AI Signal Report: {clean}"
        shown = ranked[:1]
    else:
        title = "🧠 Smart Money AI Overlap Signals"
        shown = ranked[:limit]

    blocks = "\n\n".join(
        build_stock_block(index, stock)
        for index, stock in enumerate(shown, start=1)
    )

    if not blocks:
        blocks = "No Smart Money AI signal records available."

    return f"""
{title}

Summary
{build_summary(filtered_stocks)}

Signal Rules
Congress ✅ = score >= {SMART_CONGRESS_THRESHOLD}
Insiders ✅ = score >= {SMART_INSIDER_THRESHOLD}
Core ✅ = final score >= {SMART_FINAL_SCORE_THRESHOLD}
Stability ✅ = stability score >= {SMART_STABILITY_THRESHOLD}

Ranked Signals
{blocks}

Next Commands
/congress refresh
/insiders refresh
/scorecard SYMBOL
/ticker SYMBOL
/top10
/report

Note
Smart Money overlap means multiple research inputs are aligned.
It is not a standalone buy recommendation or financial advice.
""".strip()