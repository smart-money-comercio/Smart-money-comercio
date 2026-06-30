from typing import Any


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_symbol(raw_symbol: Any) -> str:
    return str(raw_symbol or "UNKNOWN").strip().upper().replace("$", "")


def clean_text(value: Any, max_length: int = 180) -> str:
    if value is None:
        return ""

    text = " ".join(str(value).split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def get_value(data: dict, keys: list[str], default=None):
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def normalize_bullets(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, str):
        text = clean_text(value)
        return [text] if text else fallback

    if isinstance(value, list):
        items = []
        for item in value:
            text = clean_text(item)
            if text:
                items.append(text)
        return items or fallback

    if isinstance(value, tuple):
        return normalize_bullets(list(value), fallback)

    return fallback


def normalize_score_item(symbol_hint: str | None, item: Any) -> dict:
    if isinstance(item, dict):
        symbol = get_value(
            item,
            ["ticker", "symbol", "name"],
            symbol_hint or "UNKNOWN",
        )

        score = get_value(
            item,
            ["final_score", "score", "smart_money_score", "total_score", "rating_score"],
            None,
        )

        return {
            "symbol": clean_symbol(symbol),
            "score": safe_float(score),
            "rating": str(
                get_value(item, ["rating", "grade", "signal"], "Unrated")
            ).strip() or "Unrated",
            "risk_label": str(
                get_value(item, ["risk_label", "risk_level", "risk"], "N/A")
            ).strip() or "N/A",
            "category": str(
                get_value(item, ["category", "sector", "industry"], "N/A")
            ).strip() or "N/A",
            "category_adjustment": safe_float(
                get_value(item, ["category_adjustment", "adjustment"], 0)
            ) or 0,
            "reason": clean_text(
                get_value(item, ["reason", "summary", "thesis", "note", "explanation"], ""),
                240,
            ),
            "strengths": get_value(
                item,
                ["strengths", "pros", "bull_case", "positive_factors"],
                [],
            ),
            "weaknesses": get_value(
                item,
                ["weaknesses", "cons", "bear_case", "negative_factors"],
                [],
            ),
            "risks": get_value(
                item,
                ["risks", "risk_notes", "warnings", "risk_factors"],
                [],
            ),
            "raw": item,
        }

    if isinstance(item, (list, tuple)) and item:
        return {
            "symbol": clean_symbol(symbol_hint or item[0]),
            "score": safe_float(item[1]) if len(item) > 1 else None,
            "rating": "Unrated",
            "risk_label": "N/A",
            "category": "N/A",
            "category_adjustment": 0,
            "reason": "",
            "strengths": [],
            "weaknesses": [],
            "risks": [],
            "raw": item,
        }

    return {
        "symbol": clean_symbol(symbol_hint or item),
        "score": None,
        "rating": "Unrated",
        "risk_label": "N/A",
        "category": "N/A",
        "category_adjustment": 0,
        "reason": "",
        "strengths": [],
        "weaknesses": [],
        "risks": [],
        "raw": item,
    }


def normalize_scores(scores: Any) -> list[dict]:
    if scores is None:
        return []

    normalized = []

    if isinstance(scores, dict):
        for symbol, value in scores.items():
            normalized.append(normalize_score_item(str(symbol), value))

    elif isinstance(scores, list):
        normalized = [normalize_score_item(None, item) for item in scores]

    return sorted(
        normalized,
        key=lambda item: item["score"] if item["score"] is not None else -999,
        reverse=True,
    )


def find_score_for_symbol(scores: list[dict], symbol: str) -> dict | None:
    clean = clean_symbol(symbol)

    for item in scores:
        if clean_symbol(item.get("symbol")) == clean:
            return item

    return None


def get_quote_for_symbol(quotes: dict, symbol: str) -> dict | None:
    clean = clean_symbol(symbol)

    if not isinstance(quotes, dict):
        return None

    direct = quotes.get(clean)

    if isinstance(direct, dict):
        return direct

    for value in quotes.values():
        if not isinstance(value, dict):
            continue

        quote_symbol = clean_symbol(
            value.get("symbol")
            or value.get("ticker")
            or ""
        )

        if quote_symbol == clean:
            return value

    return None


def get_quote_value(quote: dict | None, keys: list[str]):
    if not isinstance(quote, dict):
        return None

    for key in keys:
        value = quote.get(key)
        if value is not None:
            return value

    return None


def get_price(quote: dict | None) -> float | None:
    return safe_float(
        get_quote_value(
            quote,
            [
                "price",
                "regularMarketPrice",
                "regular_market_price",
                "current_price",
                "last_price",
            ],
        )
    )


def get_change(quote: dict | None) -> float | None:
    return safe_float(
        get_quote_value(
            quote,
            [
                "change",
                "regularMarketChange",
                "regular_market_change",
                "price_change",
            ],
        )
    )


def get_change_percent(quote: dict | None) -> float | None:
    return safe_float(
        get_quote_value(
            quote,
            [
                "change_percent",
                "percent_change",
                "regularMarketChangePercent",
                "regular_market_change_percent",
                "changePercent",
            ],
        )
    )


def get_volume(quote: dict | None) -> float | None:
    return safe_float(
        get_quote_value(
            quote,
            [
                "volume",
                "regularMarketVolume",
                "regular_market_volume",
            ],
        )
    )


def format_score(value: Any) -> str:
    score = safe_float(value)

    if score is None:
        return "N/A"

    if score.is_integer():
        return str(int(score))

    return f"{score:.1f}"


def format_adjustment(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "0"

    if number > 0:
        return f"+{number:.0f}"

    return f"{number:.0f}"


def format_price(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    return f"${number:,.2f}"


def format_change(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    sign = "+" if number >= 0 else ""
    return f"{sign}{number:,.2f}"


def format_percent(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    sign = "+" if number >= 0 else ""
    return f"{sign}{number:.2f}%"


def format_volume(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    abs_value = abs(number)

    if abs_value >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"

    if abs_value >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"

    if abs_value >= 1_000:
        return f"{number / 1_000:.2f}K"

    return f"{number:,.0f}"


def classify_signal(score: float | None) -> str:
    if score is None:
        return "Unrated"
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


def classify_price_action(change_percent: float | None) -> str:
    if change_percent is None:
        return "Price action unavailable"
    if change_percent >= 5:
        return "Major upside move today"
    if change_percent >= 2:
        return "Strong upside move today"
    if change_percent > 0:
        return "Positive today"
    if change_percent <= -5:
        return "Major downside move today"
    if change_percent <= -2:
        return "Weak today"
    if change_percent < 0:
        return "Slightly negative today"
    return "Flat today"


def build_conviction_readout(score: float | None, risk_label: str, symbol: str) -> str:
    if score is None:
        return (
            f"{symbol} is not currently in the Smart Money scoring output. "
            "Conviction is unavailable until the ticker is added to the scoring watchlist, "
            "but market data can still be reviewed with /quote, /market, and /risk."
        )

    if score >= 90:
        return "Elite score. Strong opportunity profile, but confirm valuation and entry."
    if score >= 82:
        return "High-conviction score. Worth deeper review if market setup confirms."
    if score >= 75:
        return "Strong watch candidate. Good enough for active monitoring."
    if score >= 68:
        return "Good watch candidate. Wait for clean confirmation."
    if score >= 60:
        return "Moderate setup. Needs stronger trend, catalyst, or valuation support."
    if score >= 50:
        return "Neutral setup. Avoid forcing a trade without a stronger thesis."

    if "high" in str(risk_label).lower():
        return "Weak score with elevated risk. Skip unless thesis materially improves."

    return "Weak score. Better opportunities likely exist elsewhere."


def build_fallback_thesis(symbol: str, quote: dict | None) -> str:
    price = get_price(quote)
    change_percent = get_change_percent(quote)

    if quote:
        return (
            f"{symbol} is not currently in the Smart Money scoring output, "
            f"so no proprietary thesis is available yet. Current market data shows "
            f"price at {format_price(price)} with today’s move at {format_percent(change_percent)}. "
            f"Add {symbol} to the scoring watchlist if you want a full Smart Money thesis."
        )

    return (
        f"{symbol} is not currently in the Smart Money scoring output, "
        "and quote data was unavailable. Add this ticker to the scoring watchlist "
        "to generate a full Smart Money thesis."
    )


def build_default_strengths(score: float | None, change_percent: float | None) -> list[str]:
    strengths = []

    if score is not None and score >= 82:
        strengths.append("Score is in the high-conviction range.")

    if score is not None and score >= 75:
        strengths.append("Overall Smart Money profile is stronger than average.")

    if change_percent is not None and change_percent > 0:
        strengths.append("Ticker is positive on the current market session.")

    if not strengths:
        strengths.append("No clear strength details were provided by the scoring engine.")

    return strengths


def build_default_weaknesses(score: float | None, change_percent: float | None) -> list[str]:
    weaknesses = []

    if score is None:
        weaknesses.append("Ticker is not currently included in the Smart Money scoring output.")

    if score is not None and score < 68:
        weaknesses.append("Score is below the preferred opportunity range.")

    if change_percent is not None and change_percent < 0:
        weaknesses.append("Ticker is negative on the current market session.")

    if not weaknesses:
        weaknesses.append("No major weakness details were provided by the scoring engine.")

    return weaknesses


def build_default_risks(score: float | None, risk_label: str, change_percent: float | None) -> list[str]:
    risks = []

    if score is None:
        risks.append("No Smart Money score is available for this ticker yet.")

    if "high" in str(risk_label).lower():
        risks.append("Risk label suggests position sizing should be reduced.")

    if change_percent is not None and abs(change_percent) >= 5:
        risks.append("Large same-day move increases short-term volatility risk.")

    if score is not None and score < 60:
        risks.append("Lower score limits conviction.")

    if not risks:
        risks.append("Confirm valuation, trend, news, earnings date, and entry level before acting.")

    return risks


def build_next_step(score: float | None, symbol: str) -> str:
    if score is None:
        return f"Use /quote {symbol}, /market {symbol}, and /risk {symbol}; add {symbol} to the Smart Money watchlist for full scoring."
    if score >= 90:
        return "Review for best entry only after confirming chart, volume, news, and valuation."
    if score >= 82:
        return "Add to active review list and compare against sector leaders."
    if score >= 75:
        return "Monitor closely for breakout, pullback, or catalyst confirmation."
    if score >= 68:
        return "Keep on watchlist and wait for a cleaner setup."
    if score >= 60:
        return "Wait for stronger confirmation before acting."
    return "Skip for now unless the thesis materially improves."


def format_bullets(items: list[str], max_items: int = 3) -> str:
    return "\n".join(
        f"• {clean_text(item, 150)}"
        for item in items[:max_items]
    )


def build_scorecard(symbol: str, score_item: dict | None = None, quote: dict | None = None) -> str:
    clean = clean_symbol(symbol)

    price = get_price(quote)
    change = get_change(quote)
    change_percent = get_change_percent(quote)
    volume = get_volume(quote)

    if score_item:
        score = safe_float(score_item.get("score"))
        rating = score_item.get("rating") or classify_signal(score)
        risk_label = score_item.get("risk_label") or "N/A"
        category = score_item.get("category") or "N/A"
        category_adjustment = score_item.get("category_adjustment", 0)
        thesis = clean_text(
            score_item.get("reason")
            or "No thesis provided by scoring engine.",
            240,
        )

        strengths = normalize_bullets(
            score_item.get("strengths"),
            build_default_strengths(score, change_percent),
        )

        weaknesses = normalize_bullets(
            score_item.get("weaknesses"),
            build_default_weaknesses(score, change_percent),
        )

        risk_items = normalize_bullets(
            score_item.get("risks"),
            build_default_risks(score, risk_label, change_percent),
        )
    else:
        score = None
        rating = "Unrated"
        risk_label = "N/A"
        category = "Not in scoring watchlist"
        category_adjustment = 0
        thesis = build_fallback_thesis(clean, quote)
        strengths = build_default_strengths(score, change_percent)
        weaknesses = build_default_weaknesses(score, change_percent)
        risk_items = build_default_risks(score, risk_label, change_percent)

    signal = classify_signal(score)
    price_action = classify_price_action(change_percent)
    conviction = build_conviction_readout(score, risk_label, clean)
    next_step = build_next_step(score, clean)

    return f"""
🧾 Smart Money AI Scorecard: {clean}

Market Data
Price: {format_price(price)}
Today: {format_change(change)} ({format_percent(change_percent)})
Volume: {format_volume(volume)}
Price Action: {price_action}

Smart Money Score
Score: {format_score(score)}/100
Signal: {signal}
Rating: {rating}
Risk Label: {risk_label}
Category: {category}
Category Adjustment: {format_adjustment(category_adjustment)}

Conviction Readout
{conviction}

Thesis
{thesis}

Strengths
{format_bullets(strengths)}

Weaknesses
{format_bullets(weaknesses)}

Risk Notes
{format_bullets(risk_items)}

Next Step
{next_step}

Next Commands
/risk {clean}
/quote {clean}
/market {clean}
/ticker {clean}

Notes
This scorecard is informational only and is not financial advice.
Verify price, news, valuation, earnings, and liquidity before making decisions.
""".strip()