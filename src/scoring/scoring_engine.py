import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

from typing import Any

from src.congress.congress_scoring import get_congress_score
from src.insiders.insider_scoring import get_insider_score
from src.scoring.watchlist import WATCHLIST


NEUTRAL_SCORE = 50.0
MIN_SCORE = 0.0
MAX_SCORE = 100.0

PROJECT_ROOT = Path(__file__).resolve().parents[2]

VOLUME_CACHE_SECONDS = 60 * 60 * 4
VOLUME_CACHE_FILE = PROJECT_ROOT / "data" / "volume_signal_cache.json"
VOLUME_REQUEST_TIMEOUT = 3
ENABLE_LIVE_VOLUME = False


CATEGORY_BONUS = {
    "defense": 3.0,
    "drone": 2.5,
    "warfare": 2.5,
    "cybersecurity": 2.5,
    "cyber": 2.5,
    "ai": 2.0,
    "semiconductor": 2.0,
    "infrastructure": 1.5,
    "energy": 1.5,
    "dividend": 1.5,
    "income": 1.5,
    "etf": 1.0,
    "core": 1.0,
    "growth": 1.0,
    "speculative": -3.0,
    "high risk": -4.0,
    "early stage": -3.0,
}


SPECULATIVE_TICKERS = {
    "RKLB",
    "ONDS",
    "ACHR",
    "JOBY",
    "SOUN",
    "IONQ",
}


def safe_float(value: Any, default: float = NEUTRAL_SCORE) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp_score(value: Any) -> float:
    score = safe_float(value, NEUTRAL_SCORE)
    return max(MIN_SCORE, min(MAX_SCORE, score))


def score_or_default(value: Any, default: float = NEUTRAL_SCORE) -> float:
    return clamp_score(default if value is None else value)


def clean_symbol(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper().replace("$", "")


def clean_text(value: Any, max_length: int = 160) -> str:
    if value is None:
        return ""

    text = " ".join(str(value).split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def get_category_adjustment(category: Any, ticker: str = "") -> float:
    if not category:
        return 0.0

    category_text = str(category).lower()
    adjustment = 0.0

    for keyword, bonus in CATEGORY_BONUS.items():
        if keyword in category_text:
            adjustment += bonus

    if clean_symbol(ticker) in SPECULATIVE_TICKERS:
        adjustment -= 1.5

    return max(-8.0, min(8.0, adjustment))


def get_risk_adjustment(stock: dict) -> float:
    category = clean_text(stock.get("category"), 160).lower()
    ticker = clean_symbol(stock.get("ticker"))

    adjustment = 0.0

    if "high risk" in category:
        adjustment -= 4.0
    elif "speculative" in category:
        adjustment -= 3.0
    elif "early stage" in category:
        adjustment -= 2.5

    if ticker in SPECULATIVE_TICKERS:
        adjustment -= 1.5

    defense_score = score_or_default(stock.get("defense_score"), NEUTRAL_SCORE)

    if defense_score >= 80:
        adjustment += 1.5
    elif defense_score < 55:
        adjustment -= 2.0

    return adjustment


def get_signal_overlap(stock: dict) -> int:
    overlap = 0

    if score_or_default(stock.get("smart_score"), NEUTRAL_SCORE) >= 75:
        overlap += 1

    if score_or_default(stock.get("congress_score"), NEUTRAL_SCORE) >= 65:
        overlap += 1

    if score_or_default(stock.get("insider_score"), NEUTRAL_SCORE) >= 65:
        overlap += 1

    if score_or_default(stock.get("defense_score"), NEUTRAL_SCORE) >= 75:
        overlap += 1

    return overlap


def get_overlap_bonus(stock: dict) -> float:
    overlap = get_signal_overlap(stock)

    if overlap >= 4:
        return 5.0
    if overlap == 3:
        return 3.0
    if overlap == 2:
        return 1.25
    if overlap == 1:
        return 0.0

    return -2.0


def get_smart_money_confirmation_adjustment(stock: dict) -> float:
    congress_score = score_or_default(stock.get("congress_score"), NEUTRAL_SCORE)
    insider_score = score_or_default(stock.get("insider_score"), NEUTRAL_SCORE)

    congress_strong = congress_score >= 65
    insider_strong = insider_score >= 65

    congress_weak = congress_score <= 40
    insider_weak = insider_score <= 40

    if congress_strong and insider_strong:
        return 3.0

    if congress_strong or insider_strong:
        return 1.25

    if congress_weak and insider_weak:
        return -3.0

    if congress_weak or insider_weak:
        return -1.0

    return 0.0


def get_data_confidence_adjustment(stock: dict) -> float:
    congress_score = score_or_default(stock.get("congress_score"), NEUTRAL_SCORE)
    insider_score = score_or_default(stock.get("insider_score"), NEUTRAL_SCORE)

    neutral_count = 0

    if congress_score == NEUTRAL_SCORE:
        neutral_count += 1

    if insider_score == NEUTRAL_SCORE:
        neutral_count += 1

    if neutral_count == 2:
        return -1.25

    if neutral_count == 1:
        return -0.5

    return 0.0


def classify_smart_money_label(final_score: float) -> str:
    final_score = clamp_score(final_score)

    if final_score >= 90:
        return "Prime Opportunity"
    if final_score >= 85:
        return "High Conviction"
    if final_score >= 78:
        return "Strong Watch"
    if final_score >= 70:
        return "Developing Watch"
    if final_score >= 60:
        return "Early Watch"
    if final_score >= 50:
        return "Neutral"
    return "Weak Signal"


def classify_rating(final_score: float) -> str:
    """
    Backward-compatible rating field.
    Older reports may still use stock["rating"].
    """
    return classify_smart_money_label(final_score)


def classify_signal_strength(stock: dict) -> str:
    overlap = get_signal_overlap(stock)

    if overlap >= 4:
        return "Confirmed"
    if overlap == 3:
        return "Strong"
    if overlap == 2:
        return "Improving"
    if overlap == 1:
        return "Early"

    return "Thin"


def classify_risk_label(defense_score: Any, final_score: Any, category: Any = "") -> str:
    defense = score_or_default(defense_score, NEUTRAL_SCORE)
    final = score_or_default(final_score, NEUTRAL_SCORE)
    category_text = clean_text(category, 160).lower()

    if "speculative" in category_text or "high risk" in category_text or "early stage" in category_text:
        return "Speculative"

    if defense >= 80 and final >= 75:
        return "Controlled"

    if defense >= 65:
        return "Balanced"

    if defense >= 50:
        return "Elevated"

    return "High Risk"


def classify_portfolio_fit(stock: dict) -> str:
    category = clean_text(stock.get("category"), 160).upper()
    final_score = score_or_default(stock.get("final_score"), NEUTRAL_SCORE)
    risk_label = clean_text(stock.get("risk_label"), 160).upper()
    overlap = get_signal_overlap(stock)

    if "DIVIDEND" in category or "INCOME" in category:
        return "Income / Defensive Sleeve"

    if "ETF" in category or "INDEX" in category or "CORE" in category:
        return "Core Portfolio Sleeve"

    if "SPECULATIVE" in category or "EARLY" in category or "HIGH RISK" in risk_label:
        if overlap >= 3 and final_score >= 78:
            return "Speculative Watch"
        return "Small Speculative Watch"

    if "DEFENSE" in category or "DRONE" in category or "WARFARE" in category:
        return "Defense / Strategic Theme"

    if "CYBER" in category:
        return "Cybersecurity Growth Watch"

    if "AI" in category or "GROWTH" in category:
        if final_score >= 78:
            return "Core Growth Watch"
        return "Growth Watch"

    if final_score >= 85:
        return "High-Conviction Watch"

    if final_score >= 70:
        return "General Watchlist"

    return "Monitor Only"


def classify_action_label(stock: dict) -> str:
    final_score = score_or_default(stock.get("final_score"), NEUTRAL_SCORE)
    overlap = get_signal_overlap(stock)
    risk_label = clean_text(stock.get("risk_label"), 160).upper()

    if final_score >= 85 and overlap >= 3 and "HIGH RISK" not in risk_label and "SPECULATIVE" not in risk_label:
        return "Review First"

    if final_score >= 78 and overlap >= 2:
        return "Watch Closely"

    if final_score >= 70:
        return "Monitor"

    if overlap <= 1:
        return "Wait for Confirmation"

    return "Review Carefully"


def classify_score_story(stock: dict) -> str:
    label = classify_smart_money_label(
        score_or_default(stock.get("final_score"), NEUTRAL_SCORE)
    )
    signal_strength = classify_signal_strength(stock)
    portfolio_fit = classify_portfolio_fit(stock)
    action_label = classify_action_label(stock)

    return (
        f"{label} | Signal: {signal_strength} | "
        f"Fit: {portfolio_fit} | Action: {action_label}"
    )


def calculate_final_score(stock: dict, congress_score: float, insider_score: float) -> tuple[float, float]:
    smart_score = score_or_default(stock.get("smart_score"), NEUTRAL_SCORE)
    defense_score = score_or_default(stock.get("defense_score"), NEUTRAL_SCORE)
    ticker = clean_symbol(stock.get("ticker"))
    category = stock.get("category", "")

    category_adjustment = get_category_adjustment(category, ticker)

    scoring_context = {
        **stock,
        "ticker": ticker,
        "congress_score": congress_score,
        "insider_score": insider_score,
    }

    base_score = (
        smart_score * 0.42
        + defense_score * 0.20
        + congress_score * 0.18
        + insider_score * 0.20
    )

    final_score = (
    base_score
    + category_adjustment
    + get_overlap_bonus(scoring_context)
    + get_smart_money_confirmation_adjustment(scoring_context)
    + get_data_confidence_adjustment(scoring_context)
    + get_risk_adjustment(scoring_context)
    + get_volume_adjustment(scoring_context)
)

    return round(clamp_score(final_score), 1), category_adjustment


def build_strengths(stock: dict, congress_score: float, insider_score: float, category_adjustment: float) -> list[str]:
    strengths = []

    smart_score = score_or_default(stock.get("smart_score"), NEUTRAL_SCORE)
    defense_score = score_or_default(stock.get("defense_score"), NEUTRAL_SCORE)

    if smart_score >= 75:
        strengths.append("Core Smart Money quality is strong.")

    if defense_score >= 75:
        strengths.append("Stability profile supports the setup.")

    if congress_score >= 65:
        strengths.append("Congress activity adds confirmation.")

    if insider_score >= 65:
        strengths.append("Insider activity adds confirmation.")

    if category_adjustment > 0:
        strengths.append("The category has a supportive theme tailwind.")

    if get_signal_overlap(stock) >= 3:
        strengths.append("Multiple confirmation signals are aligned.")

    volume_label = str(stock.get("volume_label", ""))

    if volume_label in {"Unusual Demand", "Active Interest"}:
        strengths.append(f"Market volume confirms attention: {volume_label}.")    

    if not strengths:
        strengths.append("The idea remains on the broader watchlist, but confirmation is still developing.")

    return strengths


def build_weaknesses(stock: dict, congress_score: float, insider_score: float, category_adjustment: float) -> list[str]:
    weaknesses = []

    smart_score = score_or_default(stock.get("smart_score"), NEUTRAL_SCORE)
    defense_score = score_or_default(stock.get("defense_score"), NEUTRAL_SCORE)

    if smart_score < 60:
        weaknesses.append("Core Smart Money quality is still below the preferred range.")

    if defense_score < 55:
        weaknesses.append("Stability profile is weaker than preferred.")

    if congress_score < 40:
        weaknesses.append("Congress activity does not currently support the setup.")

    if insider_score < 40:
        weaknesses.append("Insider activity does not currently support the setup.")

    if category_adjustment < 0:
        weaknesses.append("Category risk reduces the setup quality.")

    if get_signal_overlap(stock) <= 1:
        weaknesses.append("Signal confirmation is still thin.")

    volume_label = str(stock.get("volume_label", ""))

    if volume_label == "Quiet Volume":
        weaknesses.append("Market volume is quiet, so confirmation is weaker.")

    if not weaknesses:
        weaknesses.append("No major score-level weakness detected.")

    return weaknesses


def build_risks(stock: dict, final_score: float, defense_score: float) -> list[str]:
    risks = []
    category = clean_text(stock.get("category"), 160).lower()

    if "growth" in category or "ai" in category:
        risks.append("Growth and AI names can move quickly if market sentiment weakens.")

    if "defense" in category or "drone" in category or "warfare" in category:
        risks.append("Defense-related themes may depend on budget cycles, contracts, and geopolitical timing.")

    if "cyber" in category:
        risks.append("Cybersecurity names can be sensitive to valuation and enterprise spending trends.")

    if "dividend" in category or "income" in category:
        risks.append("Income names should be reviewed for payout safety and balance-sheet strength.")

    if "speculative" in category or "high risk" in category or "early stage" in category:
        risks.append("Speculative names can move sharply and should not be sized like core holdings.")

    if defense_score < 55:
        risks.append("Stability profile suggests tighter risk control may be needed.")

    if final_score < 60:
        risks.append("Current setup has limited confirmation.")

    if not risks:
        risks.append("Review valuation, trend, earnings, news, and position size before acting.")

    return risks


def build_reason(stock: dict, final_score: float, congress_score: float, insider_score: float, category_adjustment: float) -> str:
    ticker = clean_symbol(stock.get("ticker"))
    category = clean_text(stock.get("category"), 120)
    label = classify_smart_money_label(final_score)

    context = {
        **stock,
        "final_score": final_score,
        "congress_score": congress_score,
        "insider_score": insider_score,
    }

    drivers = []

    if score_or_default(stock.get("smart_score"), NEUTRAL_SCORE) >= 75:
        drivers.append("core quality")

    if score_or_default(stock.get("defense_score"), NEUTRAL_SCORE) >= 75:
        drivers.append("stability")

    if congress_score >= 65:
        drivers.append("Congress activity")

    if insider_score >= 65:
        drivers.append("insider activity")

    if category_adjustment > 0:
        drivers.append("category tailwind")

    if get_signal_overlap(context) >= 3:
        drivers.append("signal alignment")

    if not drivers:
        drivers.append("watchlist-level fundamentals")

    return (
        f"{ticker} screens as a {label} idea in {category}. "
        f"The rating is driven by {', '.join(drivers)}."
    )


def get_live_congress_score(ticker: str) -> float:
    try:
        return score_or_default(get_congress_score(ticker), NEUTRAL_SCORE)
    except Exception:
        return NEUTRAL_SCORE


def get_live_insider_score(ticker: str) -> float:
    try:
        return score_or_default(get_insider_score(ticker), NEUTRAL_SCORE)
    except Exception:
        return NEUTRAL_SCORE

def read_volume_cache() -> dict:
    try:
        if not VOLUME_CACHE_FILE.exists():
            return {}

        with VOLUME_CACHE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, dict):
            return data

        return {}

    except Exception:
        return {}


def write_volume_cache(cache: dict) -> None:
    try:
        VOLUME_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

        with VOLUME_CACHE_FILE.open("w", encoding="utf-8") as file:
            json.dump(cache, file, indent=2, sort_keys=True)

    except Exception:
        return


def classify_volume_signal(volume_ratio: float | None) -> dict:
    if volume_ratio is None:
        return {
            "volume_score": 50.0,
            "volume_label": "Volume Unavailable",
            "volume_note": "Volume data was unavailable, so it was treated as neutral.",
        }

    if volume_ratio >= 2.0:
        return {
            "volume_score": 78.0,
            "volume_label": "Unusual Demand",
            "volume_note": "Trading volume is running well above its recent average.",
        }

    if volume_ratio >= 1.25:
        return {
            "volume_score": 65.0,
            "volume_label": "Active Interest",
            "volume_note": "Trading volume is above normal and confirms market attention.",
        }

    if volume_ratio >= 0.75:
        return {
            "volume_score": 52.0,
            "volume_label": "Normal Volume",
            "volume_note": "Trading volume is close to its recent average.",
        }

    return {
        "volume_score": 42.0,
        "volume_label": "Quiet Volume",
        "volume_note": "Trading volume is below normal, so confirmation is weaker.",
    }


def fetch_volume_signal_from_yahoo(ticker: str) -> dict:
    symbol = clean_symbol(ticker)

    if not ENABLE_LIVE_VOLUME:
        volume_data = classify_volume_signal(None)
        volume_data.update(
            {
                "ticker": symbol,
                "cached_at": time.time(),
            }
        )
        return volume_data

    if not symbol or symbol == "UNKNOWN":
        return classify_volume_signal(None)

    cache = read_volume_cache()
    cached = cache.get(symbol)
    now = time.time()

    if isinstance(cached, dict):
        cached_at = safe_float(cached.get("cached_at"), 0)

        if now - cached_at <= VOLUME_CACHE_SECONDS:
            return cached

    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{symbol}?range=3mo&interval=1d"
    )

    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 SmartMoneyAI/1.0",
                "Accept": "application/json",
            },
        )

        response = urllib.request.urlopen(
            request,
            timeout=VOLUME_REQUEST_TIMEOUT,
        )

        try:
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            response.close()

        result = payload.get("chart", {}).get("result", [])

        if not result:
            volume_data = classify_volume_signal(None)
        else:
            quote = result[0].get("indicators", {}).get("quote", [{}])[0]
            volumes = quote.get("volume") or []

            clean_volumes = [
                safe_float(volume, 0)
                for volume in volumes
                if safe_float(volume, 0) > 0
            ]

            if len(clean_volumes) < 10:
                volume_data = classify_volume_signal(None)
            else:
                latest_volume = clean_volumes[-1]
                recent_values = clean_volumes[-21:-1]
                recent_average = sum(recent_values) / max(1, len(recent_values))
                volume_ratio = latest_volume / recent_average if recent_average > 0 else None

                volume_data = classify_volume_signal(volume_ratio)
                volume_data.update(
                    {
                        "latest_volume": round(latest_volume),
                        "average_volume": round(recent_average),
                        "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
                    }
                )

    except (
        TimeoutError,
        socket.timeout,
        OSError,
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
        ValueError,
    ):
        volume_data = classify_volume_signal(None)

    except Exception:
        volume_data = classify_volume_signal(None)

    volume_data.update(
        {
            "ticker": symbol,
            "cached_at": now,
        }
    )

    cache[symbol] = volume_data
    write_volume_cache(cache)

    return volume_data


def get_volume_adjustment(stock: dict) -> float:
    volume_score = score_or_default(stock.get("volume_score"), 50)

    if volume_score >= 75:
        return 2.0

    if volume_score >= 65:
        return 1.0

    if volume_score < 45:
        return -1.0

    return 0.0

def enrich_stock(stock: dict) -> dict:
    enriched = dict(stock)

    ticker = clean_symbol(enriched.get("ticker") or enriched.get("symbol"))
    category = clean_text(enriched.get("category"), 120)

    smart_score = score_or_default(enriched.get("smart_score"), NEUTRAL_SCORE)
    defense_score = score_or_default(enriched.get("defense_score"), NEUTRAL_SCORE)

    congress_score = get_live_congress_score(ticker)
    insider_score = get_live_insider_score(ticker)
    volume_data = fetch_volume_signal_from_yahoo(ticker)

    enriched.update(
    {
        "ticker": ticker,
        "symbol": ticker,
        "category": category,
        "smart_score": smart_score,
        "defense_score": defense_score,
        "congress_score": round(congress_score, 1),
        "insider_score": round(insider_score, 1),

        # Volume confirmation.
        "volume_score": score_or_default(volume_data.get("volume_score"), NEUTRAL_SCORE),
        "volume_label": volume_data.get("volume_label", "Volume Unavailable"),
        "volume_note": volume_data.get("volume_note", ""),
        "volume_ratio": volume_data.get("volume_ratio"),
        "latest_volume": volume_data.get("latest_volume"),
        "average_volume": volume_data.get("average_volume"),
    }
)

    final_score, category_adjustment = calculate_final_score(
        enriched,
        congress_score,
        insider_score,
    )

    risk_label = classify_risk_label(
        defense_score=defense_score,
        final_score=final_score,
        category=category,
    )

    enriched.update(
        {
            # Numeric fields kept for sorting and compatibility.
            "final_score": final_score,
            "score": final_score,
            "smart_money_score": final_score,

            # User-friendly labels for reports and commands.
            "rating": classify_rating(final_score),
            "smart_money_label": classify_smart_money_label(final_score),
            "risk_label": risk_label,
            "signal_overlap": get_signal_overlap({**enriched, "final_score": final_score, "risk_label": risk_label}),
            "signal_strength": classify_signal_strength({**enriched, "final_score": final_score, "risk_label": risk_label}),
            "portfolio_fit": classify_portfolio_fit({**enriched, "final_score": final_score, "risk_label": risk_label}),
            "action_label": classify_action_label({**enriched, "final_score": final_score, "risk_label": risk_label}),
            "score_story": classify_score_story({**enriched, "final_score": final_score, "risk_label": risk_label}),

            # Diagnostic fields.
            "category_adjustment": category_adjustment,
            "risk_adjustment": get_risk_adjustment(enriched),
            "overlap_bonus": get_overlap_bonus(enriched),
            "smart_money_adjustment": get_smart_money_confirmation_adjustment(enriched),
            "data_confidence_adjustment": get_data_confidence_adjustment(enriched),
            "volume_adjustment": get_volume_adjustment(enriched),
        }
    )

    enriched["reason"] = build_reason(
        enriched,
        final_score,
        congress_score,
        insider_score,
        category_adjustment,
    )
    enriched["strengths"] = build_strengths(
        enriched,
        congress_score,
        insider_score,
        category_adjustment,
    )
    enriched["weaknesses"] = build_weaknesses(
        enriched,
        congress_score,
        insider_score,
        category_adjustment,
    )
    enriched["risks"] = build_risks(
        enriched,
        final_score,
        defense_score,
    )

    return enriched


def get_stock_scores() -> list[dict]:
    stocks = [stock.copy() for stock in WATCHLIST]

    enriched_stocks = [
        enrich_stock(stock)
        for stock in stocks
        if clean_symbol(stock.get("ticker") or stock.get("symbol")) != "UNKNOWN"
    ]

    return sorted(
        enriched_stocks,
        key=lambda item: (
            score_or_default(item.get("final_score"), 0),
            score_or_default(item.get("signal_overlap"), 0),
            score_or_default(item.get("defense_score"), 0),
        ),
        reverse=True,
    )


def get_smart_money_score(ticker: str) -> float:
    symbol = clean_symbol(ticker)

    for stock in get_stock_scores():
        if clean_symbol(stock.get("ticker")) == symbol:
            return score_or_default(stock.get("final_score"), NEUTRAL_SCORE)

    return NEUTRAL_SCORE


def score_ticker(ticker: str) -> dict:
    symbol = clean_symbol(ticker)

    for stock in WATCHLIST:
        current_symbol = clean_symbol(stock.get("ticker") or stock.get("symbol"))

        if current_symbol == symbol:
            return enrich_stock(dict(stock))

    fallback = {
        "ticker": symbol,
        "symbol": symbol,
        "category": "Uncategorized",
        "smart_score": NEUTRAL_SCORE,
        "defense_score": NEUTRAL_SCORE,
    }

    return enrich_stock(fallback)