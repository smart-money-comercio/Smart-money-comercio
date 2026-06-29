from typing import Any

def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def get_value(data: dict, keys: list[str], default=None):
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def clean_symbol(raw_symbol: str) -> str:
    return raw_symbol.strip().upper().replace("$", "")


def normalize_score_item(symbol_hint: str | None, item: Any) -> dict:
    if isinstance(item, dict):
        symbol = (
            item.get("symbol")
            or item.get("ticker")
            or symbol_hint
            or item.get("name")
            or "UNKNOWN"
        )

        score = get_value(
            item,
            ["score", "total_score", "smart_money_score", "rating_score"],
            None,
        )

        rating = get_value(
            item,
            ["rating", "grade", "signal", "recommendation"],
            "",
        )

        reason = get_value(
            item,
            ["reason", "summary", "thesis", "note", "explanation"],
            "",
        )

        sector = get_value(
            item,
            ["sector", "industry", "category"],
            "",
        )

        strengths = get_value(
            item,
            ["strengths", "pros", "bull_case", "positive_factors"],
            [],
        )

        weaknesses = get_value(
            item,
            ["weaknesses", "cons", "bear_case", "negative_factors"],
            [],
        )

        risks = get_value(
            item,
            ["risks", "risk_notes", "risk", "warning"],
            [],
        )

        return {
            "symbol": str(symbol).upper(),
            "score": safe_float(score),
            "rating": str(rating).strip(),
            "reason": str(reason).strip(),
            "sector": str(sector).strip(),
            "strengths": strengths,
            "weaknesses": weaknesses,
            "risks": risks,
            "raw": item,
        }

    if isinstance(item, (list, tuple)) and item:
        symbol = str(symbol_hint or item[0]).upper()
        score = safe_float(item[1]) if len(item) > 1 else None

        return {
            "symbol": symbol,
            "score": score,
            "rating": "",
            "reason": "",
            "sector": "",
            "strengths": [],
            "weaknesses": [],
            "risks": [],
            "raw": item,
        }

    return {
        "symbol": str(symbol_hint or item).upper(),
        "score": None,
        "rating": "",
        "reason": "",
        "sector": "",
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
        if item["symbol"].upper() == clean:
            return item

    return None


def format_score(score: float | None) -> str:
    if score is None:
        return "N/A"

    if score.is_integer():
        return str(int(score))

    return f"{score:.1f}"


def classify_signal(score: float | None) -> str:
    if score is None:
        return "Unrated"
    if score >= 85:
        return "High conviction"
    if score >= 75:
        return "Strong watch"
    if score >= 65:
        return "Moderate watch"
    if score >= 50:
        return "Neutral"
    return "Weak"


def classify_risk(score: float | None, change_percent: float | None) -> str:
    if change_percent is not None and abs(change_percent) >= 5:
        return "High short-term volatility"

    if score is None:
        return "Unknown"

    if score >= 85:
        return "Moderate — strong score, but confirm valuation and entry."
    if score >= 75:
        return "Moderate — attractive, but still needs confirmation."
    if score >= 65:
        return "Medium-high — wait for cleaner setup."
    if score >= 50:
        return "High — mixed profile."
    return "Very high — weak score."


def build_next_step(score: float | None) -> str:
    if score is None:
        return "Review manually before taking action."
    if score >= 85:
        return "Check chart trend, volume, news, valuation, and entry level."
    if score >= 75:
        return "Compare against sector peers and consider adding to active watchlist."
    if score >= 65:
        return "Monitor for confirmation, breakout, pullback, or catalyst."
    if score >= 50:
        return "Wait for stronger confirmation before acting."
    return "Skip for now unless the thesis materially improves."


def get_quote_for_symbol(quotes: dict, symbol: str) -> dict | None:
    clean = clean_symbol(symbol)

    if not isinstance(quotes, dict):
        return None

    quote = quotes.get(clean)

    if isinstance(quote, dict):
        return quote

    for value in quotes.values():
        if not isinstance(value, dict):
            continue

        quote_symbol = str(
            value.get("symbol")
            or value.get("ticker")
            or ""
        ).upper()

        if quote_symbol == clean:
            return value

    return None


def get_quote_value(quote: dict | None, keys: list[str]):
    if not quote:
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


def format_price(price: float | None) -> str:
    if price is None:
        return "N/A"

    return f"${price:,.2f}"


def format_percent(value: float | None) -> str:
    if value is None:
        return "N/A"

    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def normalize_bullet_items(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            return [cleaned]
        return fallback

    if isinstance(value, list):
        cleaned_items = []

        for item in value:
            item_text = str(item).strip()
            if item_text:
                cleaned_items.append(item_text)

        return cleaned_items or fallback

    if isinstance(value, tuple):
        return normalize_bullet_items(list(value), fallback)

    return fallback


def clean_text(text: str, max_length: int = 180) -> str:
    if not text:
        return ""

    cleaned = " ".join(text.split())

    if len(cleaned) <= max_length:
        return cleaned

    return cleaned[: max_length - 3].rstrip() + "..."


def build_default_strengths(score: float | None, change_percent: float | None) -> list[str]:
    strengths = []

    if score is not None and score >= 75:
        strengths.append("Score is above the strong-watch threshold.")

    if change_percent is not None and change_percent > 0:
        strengths.append("Ticker is positive on the current market session.")

    if not strengths:
        strengths.append("No clear strength details were provided by the scoring engine.")

    return strengths


def build_default_weaknesses(score: float | None, change_percent: float | None) -> list[str]:
    weaknesses = []

    if score is not None and score < 65:
        weaknesses.append("Score is below the preferred opportunity range.")

    if change_percent is not None and change_percent < 0:
        weaknesses.append("Ticker is negative on the current market session.")

    if not weaknesses:
        weaknesses.append("No major weakness details were provided by the scoring engine.")

    return weaknesses


def format_bullets(items: list[str], max_items: int = 3) -> str:
    return "\n".join(f"• {clean_text(item)}" for item in items[:max_items])


def build_scorecard(symbol: str, score_item: dict | None = None, quote: dict | None = None) -> str:
    clean = clean_symbol(symbol)

    price = get_price(quote)
    change_percent = get_change_percent(quote)

    if score_item:
        score = score_item["score"]
        rating = score_item.get("rating") or ""
        sector = score_item.get("sector") or ""
        reason = clean_text(score_item.get("reason") or "No thesis provided by scoring engine.")

        strengths = normalize_bullet_items(
            score_item.get("strengths"),
            build_default_strengths(score, change_percent),
        )

        weaknesses = normalize_bullet_items(
            score_item.get("weaknesses"),
            build_default_weaknesses(score, change_percent),
        )

        risk_items = normalize_bullet_items(
            score_item.get("risks"),
            [classify_risk(score, change_percent)],
        )
    else:
        score = None
        rating = ""
        sector = ""
        reason = "This symbol was not found in the current scoring engine output."
        strengths = build_default_strengths(score, change_percent)
        weaknesses = build_default_weaknesses(score, change_percent)
        risk_items = [classify_risk(score, change_percent)]

    signal = classify_signal(score)
    next_step = build_next_step(score)

    optional_lines = []

    if rating:
        optional_lines.append(f"Rating: {rating}")

    if sector:
        optional_lines.append(f"Sector: {sector}")

    optional_block = ""
    if optional_lines:
        optional_block = "\n" + "\n".join(optional_lines)

    return f"""
🧾 Smart Money AI Scorecard: {clean}

Market Data
Price: {format_price(price)}
Today: {format_percent(change_percent)}

Score
Smart Money Score: {format_score(score)}
Signal: {signal}{optional_block}

Thesis
{reason}

Strengths
{format_bullets(strengths)}

Weaknesses
{format_bullets(weaknesses)}

Risk Notes
{format_bullets(risk_items)}

Next Step
{next_step}

Notes
This is informational only and is not financial advice.
Use /risk {clean} for a deeper risk view.
Use /quote {clean} for a quick price check.
""".strip()


