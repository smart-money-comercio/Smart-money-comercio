def clean_symbol(value) -> str:
    return str(value or "UNKNOWN").strip().upper().replace("$", "")


def safe_number(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()

        return float(value)
    except Exception:
        return default


def get_score(stock: dict) -> float:
    return safe_number(
        stock.get(
            "final_score",
            stock.get(
                "score",
                stock.get(
                    "smart_score",
                    stock.get("smart_money_score", stock.get("total_score", 0)),
                ),
            ),
        ),
        default=0,
    )


def get_category(stock: dict) -> str:
    return str(
        stock.get("category")
        or stock.get("theme")
        or stock.get("sector")
        or "General Market"
    ).strip()


def compact_score(score: float) -> str:
    score = safe_number(score)

    if score <= 0:
        return "N/A"

    if score.is_integer():
        return str(int(score))

    return str(round(score, 1))


def action_bias(score: float) -> str:
    score = safe_number(score)

    if score >= 90:
        return "High-conviction watch — buy only on confirmation"

    if score >= 82:
        return "Constructive — favored on confirmed strength"

    if score >= 75:
        return "Watchlist — wait for better confirmation"

    if score >= 65:
        return "Neutral — research first, trade second"

    return "Low priority — avoid forcing the setup"


def conviction_level(score: float) -> str:
    score = safe_number(score)

    if score >= 90:
        return "High"

    if score >= 82:
        return "Medium-High"

    if score >= 75:
        return "Medium"

    if score >= 65:
        return "Low-Medium"

    return "Low"


def risk_level(score: float, category: str) -> str:
    score = safe_number(score)
    category_text = str(category or "").lower()

    risk_terms = [
        "growth",
        "ai",
        "semiconductor",
        "chip",
        "drones",
        "drone",
        "cyber",
        "defense",
        "autonomous",
        "software",
    ]

    if score < 65:
        return "High"

    if any(term in category_text for term in risk_terms):
        return "Medium-High"

    if score >= 85:
        return "Medium"

    return "Medium"


def entry_style(score: float) -> str:
    score = safe_number(score)

    if score >= 90:
        return "Confirm first; do not chase extended strength."

    if score >= 82:
        return "Use pullbacks or confirmed breakouts."

    if score >= 75:
        return "Wait for price, volume, and news confirmation."

    if score >= 65:
        return "Research first; setup is not clean yet."

    return "Low priority until signals improve."


def validation_focus(score: float, category: str) -> str:
    score = safe_number(score)
    category_text = str(category or "").lower()

    if "defense" in category_text or "drone" in category_text or "cyber" in category_text:
        return "Confirm defense theme strength, contract/news flow, volume, and risk."

    if "ai" in category_text or "semiconductor" in category_text or "chip" in category_text:
        return "Confirm AI demand, volume, earnings quality, and macro/rate pressure."

    if "dividend" in category_text or "income" in category_text or "utility" in category_text:
        return "Confirm yield support, balance-sheet quality, and rate sensitivity."

    if score >= 85:
        return "Confirm score quality, volume, news context, and risk."

    return "Confirm risk, price action, and thesis quality."


def plain_tradeplan_read(stock: dict) -> dict:
    ticker = clean_symbol(stock.get("ticker") or stock.get("symbol") or "UNKNOWN")
    score = get_score(stock)
    category = get_category(stock)

    return {
        "ticker": ticker,
        "score": score,
        "score_text": compact_score(score),
        "category": category,
        "conviction": conviction_level(score),
        "action_bias": action_bias(score),
        "risk": risk_level(score, category),
        "entry_style": entry_style(score),
        "validation_focus": validation_focus(score, category),
    }


def build_tradeplan_snapshot_card(stock: dict, index: int) -> str:
    read = plain_tradeplan_read(stock)

    return f"""
{index}. {read["ticker"]} — {read["conviction"]} conviction | {read["score_text"]}/100
Theme: {read["category"]}
Action Bias: {read["action_bias"]}
Risk: {read["risk"]}
Entry Style: {read["entry_style"]}
Validation Focus: {read["validation_focus"]}
Full Plan: /tradeplan {read["ticker"]}
""".strip()


def build_tradeplan_daily_line(stock: dict, index: int) -> str:
    read = plain_tradeplan_read(stock)

    return (
        f"{index}. {read['ticker']} — {read['conviction']} conviction, "
        f"{read['score_text']}/100, {read['risk']} risk. "
        f"Action: {read['action_bias']} "
        f"Entry: {read['entry_style']} "
        f"Full plan: /tradeplan {read['ticker']}"
    )


def build_tradeplan_short_line(stock: dict, index: int) -> str:
    read = plain_tradeplan_read(stock)

    return (
        f"{index}. {read['ticker']} — {read['conviction']} conviction | "
        f"{read['score_text']}/100 | {read['risk']} risk | "
        f"{read['action_bias']} | /tradeplan {read['ticker']}"
    )

def find_stock(symbol: str) -> dict:
    target = clean_symbol(symbol)

    try:
        from src.scoring.scoring_engine import get_stock_scores

        scores = get_stock_scores()
    except Exception:
        return {}

    for stock in scores or []:
        if not isinstance(stock, dict):
            continue

        ticker = clean_symbol(stock.get("ticker") or stock.get("symbol"))

        if ticker == target:
            return stock

    return {}
