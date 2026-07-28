import os
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.commands.watchlist_commands import fetch_quotes_for_symbols

try:
    from src.config.theme_watchlist_universe import build_relevant_watchlist
except Exception:
    def build_relevant_watchlist(
        manual_symbols=None,
        context=None,
        scores=None,
        max_symbols=20,
    ):
        symbols = manual_symbols or []
        return symbols[:max_symbols]

try:
    from src.intelligence.watchlist_evolution import (
        build_evolved_watchlist_universe,
        record_watchlist_evolution_day,
    )
except Exception:
    def build_evolved_watchlist_universe(
        manual_symbols=None,
        context=None,
        scores=None,
        max_symbols=20,
    ):
        try:
            return build_relevant_watchlist(
                manual_symbols=manual_symbols,
                context=context,
                scores=scores,
                max_symbols=max_symbols,
            )
        except Exception:
            symbols = manual_symbols or []
            return symbols[:max_symbols]

    def record_watchlist_evolution_day(
        watchlist_symbols=None,
        context=None,
    ):
        return None

from src.intelligence.ai_summary_engine import build_evolving_ai_summary
from src.intelligence.market_memory import build_what_changed_today

try:
    from src.intelligence.theme_scoring import build_theme_scorecard
except Exception:
    def build_theme_scorecard(
        context=None,
        market_tone="Quote data unavailable",
        what_changed_today="",
    ):
        themes = []
        if isinstance(context, dict):
            themes = context.get("headline_themes") or []
        theme_text = ", ".join(str(theme) for theme in themes[:5]) if themes else "Theme history is still building."
        return f"• {theme_text}\n• Market tone: {market_tone}."
from src.scoring.scoring_engine import get_stock_scores
from src.utils.score_display import (
    get_action_label,
    get_category,
    get_portfolio_fit,
    get_risk_label,
    get_signal_strength,
    get_smart_money_label,
    get_ticker,
    get_volume_label,
)
from src.utils.watchlist_store import load_watchlist


REPORT_TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
MARKET_TIMEZONE = os.getenv("MARKET_TIMEZONE", "America/New_York")

MAX_TOP_OPPORTUNITIES = 2
MAX_WATCHLIST_MOVERS = 6
MAX_RELEVANT_WATCHLIST = 20
MAX_MORNING_BRIEF_CHARS = 900
MAX_THEME_READ_CHARS = 620
MAX_WHAT_CHANGED_CHARS = 620

# Default back to live movement.
# Set DAILY_REPORT_LIVE_QUOTES=0 only if you need emergency fast mode.
DAILY_REPORT_LIVE_QUOTES = os.getenv("DAILY_REPORT_LIVE_QUOTES", "1").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


HIGH_IMPACT_MACRO_THEMES = {
    "Oil / Geopolitical Risk",
    "Defense / AI Warfare",
    "Defense Procurement / Munitions",
    "AI / Chips",
    "AI Infrastructure / Power",
    "Earnings Season",
    "Inflation / Fed",
    "Banks / Credit",
    "Consumer Stress",
    "Policy / Regulation",
    "Automation / Mobility",
    "Market Breadth / Rotation",
}

GEOPOLITICAL_PRESSURE_KEYWORDS = [
    "hormuz",
    "strait of hormuz",
    "iran",
    "missile",
    "strike",
    "strikes",
    "attack",
    "attacks",
    "tanker",
    "tankers",
    "shipping",
    "blockade",
    "gulf",
    "middle east",
    "red sea",
    "energy export",
    "oil supply",
    "oil disruption",
    "sanctions",
]

DEFENSE_AI_WARFARE_KEYWORDS = [
    "iran",
    "hormuz",
    "strait of hormuz",
    "strike",
    "strikes",
    "missile",
    "missiles",
    "drone",
    "drones",
    "uav",
    "counter-drone",
    "counter drone",
    "interceptor",
    "air defense",
    "patriot",
    "thaad",
    "tomahawk",
    "naval",
    "shipping",
    "red sea",
    "gulf",
    "military",
    "defense",
    "defence",
    "dod",
    "department of defense",
    "pentagon",
    "centcom",
    "cyber",
    "electronic warfare",
    "isr",
    "surveillance",
    "radar",
    "autonomous",
    "ai warfare",
    "famm",
    "family of affordable mass missiles",
    "low-cost cruise missile",
    "low cost cruise missile",
    "affordable mass missile",
    "palletized munition",
    "standoff weapon",
    "standoff weapons",
    "munitions",
    "missile stockpile",
    "strike munitions",
    "barracuda",
    "rusty dagger",
    "coaspire",
    "anduril",
    "zone 5",
    "leidos",
    "kongsberg",
    "framework agreements",
    "multi-year procurement",
    "defense industrial base",
    "surge production",
    "air-launched cruise missile",
    "palletized munitions",
    "stand-off weapon",
    "stand-off weapons",
    "weapons stockpile",
    "mass missiles",
    "affordable cruise missile",
    "barracuda-500",
    "agm-188",
    "agm-189",
    "firm-fixed-price",
]

DEFENSE_AI_WARFARE_CATEGORIES = [
    "DEFENSE",
    "DRONE",
    "WARFARE",
    "AEROSPACE",
    "CYBER",
    "AI WARFARE",
    "MILITARY",
    "SECURITY",
    "AUTONOMOUS",
    "ISR",
    "SURVEILLANCE",
    "MISSILE",
    "COUNTER-DRONE",
    "COUNTER DRONE",
    "MUNITION",
    "MUNITIONS",
    "MISSILES",
    "PROPULSION",
    "SENSORS",
    "DEFENSE PROCUREMENT",
    "AIR DEFENSE",
    "MISSILE DEFENSE",
    "INDUSTRIAL BASE",
]

GENERIC_THEME_LABELS = {
    "market",
    "markets",
    "stock market",
    "stocks",
    "equities",
    "market news",
    "general market",
}


SMART_MONEY_LABEL_TRANSLATIONS = {
    "Core Smart Money Quality": "Quality setup",
    "Prime Opportunity": "Top-ranked setup",
    "High Conviction": "High-conviction setup",
    "Strong Watch": "Strong watchlist candidate",
    "Developing Watch": "Developing setup",
    "Early Watch": "Early-stage setup",
    "Neutral": "Neutral setup",
    "Weak Signal": "Weak signal",
}


def get_market_status_label() -> str:
    now_et = datetime.now(ZoneInfo(MARKET_TIMEZONE))

    if now_et.weekday() >= 5:
        return "Closed — weekend. Price moves reflect the last completed regular session."

    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

    if now_et < market_open:
        return "Closed — pre-market. Moves may reflect the prior regular session."

    if now_et > market_close:
        return "Closed — after-hours. Moves reflect the completed regular session."

    return "Open — live session."


def normalize_theme_name(theme: str | None) -> str:
    text = " ".join(str(theme or "").split())

    if not text:
        return ""

    if text.lower() in GENERIC_THEME_LABELS:
        return ""

    aliases = {
        "Oil / Geopolitical Risk": "Geopolitical / oil risk",
        "Defense / AI Warfare": "Defense / AI warfare",
        "Defense Procurement / Munitions": "Defense procurement / munitions",
        "AI / Chips": "AI / chips",
        "AI Infrastructure / Power": "AI infrastructure / power",
        "Earnings Season": "Earnings season",
        "Inflation / Fed": "Inflation / Fed risk",
        "Banks / Credit": "Banks / credit",
        "Consumer Stress": "Consumer pressure",
        "Policy / Regulation": "Policy / regulation",
        "Automation / Mobility": "Automation / mobility",
        "Market Breadth / Rotation": "Market breadth / rotation",
    }

    return aliases.get(text, text)

def get_clean_headline_themes(context: dict, limit: int = 4) -> list[str]:
    themes = []

    for theme in context.get("headline_themes", []) or []:
        cleaned = normalize_theme_name(theme)

        if cleaned and cleaned not in themes:
            themes.append(cleaned)

    return themes[:limit]


def get_primary_theme(context: dict) -> str:
    themes = get_clean_headline_themes(context, limit=1)

    if themes:
        return themes[0]

    if has_geopolitical_pressure(context):
        return "Geopolitical / oil risk"

    if has_defense_ai_warfare_pressure(context):
        return "Defense / AI warfare"

    if context.get("nasdaq", 0) < -0.75:
        return "Growth pressure"

    if context.get("oil", 0) > 1:
        return "Oil / inflation risk"

    return "Macro / earnings setup"


def translate_smart_money_label(item: dict) -> str:
    raw_label = get_smart_money_label(item)

    translations = {
        "Core Smart Money Quality": "Quality setup",
        "Core Smart Money quality": "Quality setup",
        "Prime Opportunity": "Top-ranked setup",
        "High Conviction": "High-conviction setup",
        "Strong Watch": "Strong watchlist candidate",
        "Developing Watch": "Developing setup",
        "Early Watch": "Early-stage setup",
        "Neutral": "Neutral setup",
        "Weak Signal": "Weak signal",
    }

    return translations.get(raw_label, raw_label)

def build_market_moves_line(context: dict, movers: list[dict]) -> str:
    macro_moves = (
        f"S&P {format_percent(context.get('sp500'))}, "
        f"Nasdaq {format_percent(context.get('nasdaq'))}, "
        f"Russell {format_percent(context.get('russell'))}, "
        f"VIX {format_percent(context.get('vix'))}, "
        f"Oil {format_percent(context.get('oil'))}, "
        f"TLT {format_percent(context.get('tlt'))}"
    )

    if not movers:
        return macro_moves

    strongest = max(movers, key=lambda item: item["change_percent"])
    weakest = min(movers, key=lambda item: item["change_percent"])

    return (
        f"{macro_moves}. "
        f"Watchlist: {strongest['symbol']} strongest at {format_percent(strongest['change_percent'])}; "
        f"{weakest['symbol']} weakest at {format_percent(weakest['change_percent'])}."
    )

def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None

        return float(value)
    except (TypeError, ValueError):
        return None


def clean_symbol(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper().replace("$", "")


def clean_text(value: Any, max_length: int = 160) -> str:
    if value is None:
        return ""

    text = " ".join(str(value).split())

    if len(text) <= max_length:
        return text

    if max_length <= 3:
        return text[:max_length]

    return text[: max_length - 3].rstrip() + "..."


REPORT_PHRASE_REPLACEMENTS = {
    "Core Smart Money quality is strong": "Smart Money ranking is strong",
    "core smart money quality is strong": "Smart Money ranking is strong",
    "Core Smart Money Quality": "Quality setup",
    "core smart money quality": "quality setup",
}

def clean_report_language(value: Any, max_length: int = 220) -> str:
    text = " ".join(str(value or "").split())

    for old, new in REPORT_PHRASE_REPLACEMENTS.items():
        text = text.replace(old, new)

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def trim_block(value: str, max_length: int) -> str:
    text = str(value or "").strip()

    if len(text) <= max_length:
        return text

    trimmed = text[:max_length].rstrip()
    split_at = trimmed.rfind("\n\n")

    if split_at > 400:
        trimmed = trimmed[:split_at].rstrip()

    return trimmed + "\n\nBrief trimmed for daily report. Use /headlines and /global for more context."


def get_value(data: dict, keys: list[str], default=None):
    for key in keys:
        value = data.get(key)

        if value is not None:
            return value

    return default


def first_list_text(value: Any, fallback: str, max_length: int = 120) -> str:
    if isinstance(value, list):
        for item in value:
            text = clean_text(item, max_length)

            if text:
                return text

        return fallback

    if isinstance(value, tuple):
        return first_list_text(list(value), fallback, max_length)

    if isinstance(value, str) and value.strip():
        return clean_text(value, max_length)

    return fallback


def format_price(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    return f"${number:,.2f}"


def format_percent(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    sign = "+" if number >= 0 else ""

    return f"{sign}{number:.2f}%"


def normalize_score_item(item: Any) -> dict:
    if isinstance(item, dict):
        score = get_value(
            item,
            ["final_score", "score", "smart_money_score", "total_score", "rating_score"],
            None,
        )

        ticker = clean_symbol(
            get_value(item, ["ticker", "symbol", "name"], "UNKNOWN")
        )

        normalized = dict(item)

        normalized.update(
            {
                "ticker": ticker,
                "symbol": ticker,
                "score": safe_float(score),
                "rating": str(
                    get_value(
                        item,
                        ["smart_money_label", "rating", "grade", "signal"],
                        "Unrated",
                    )
                ),
                "risk_label": str(
                    get_value(item, ["risk_label", "risk_level", "risk"], "N/A")
                ),
                "category": str(
                    get_value(item, ["category", "sector", "industry"], "N/A")
                ),
                "strength": first_list_text(
                    get_value(
                        item,
                        ["strengths", "pros", "bull_case", "reason", "thesis"],
                        [],
                    ),
                    "Developing thesis; needs confirmation.",
                ),
                "weakness": first_list_text(
                    get_value(item, ["weaknesses", "cons", "bear_case", "risks"], []),
                    "Risk still needs review.",
                ),
            }
        )

        return normalized

    if isinstance(item, (list, tuple)) and item:
        ticker = clean_symbol(item[0])

        return {
            "ticker": ticker,
            "symbol": ticker,
            "score": safe_float(item[1]) if len(item) > 1 else None,
            "rating": "Unrated",
            "risk_label": "N/A",
            "category": "N/A",
            "strength": "Developing thesis; needs confirmation.",
            "weakness": "Risk still needs review.",
        }

    ticker = clean_symbol(item)

    return {
        "ticker": ticker,
        "symbol": ticker,
        "score": None,
        "rating": "Unrated",
        "risk_label": "N/A",
        "category": "N/A",
        "strength": "Developing thesis; needs confirmation.",
        "weakness": "Risk still needs review.",
    }


def normalize_scores(scores: Any) -> list[dict]:
    if not scores:
        return []

    normalized = []

    if isinstance(scores, dict):
        for symbol, value in scores.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("ticker", symbol)
                item.setdefault("symbol", symbol)
                normalized.append(normalize_score_item(item))
            else:
                normalized.append(
                    normalize_score_item(
                        {
                            "ticker": symbol,
                            "symbol": symbol,
                            "score": value,
                        }
                    )
                )

    elif isinstance(scores, list):
        normalized = [normalize_score_item(item) for item in scores]

    return sorted(
        normalized,
        key=lambda item: item["score"] if item["score"] is not None else -999,
        reverse=True,
    )


def get_quote_value(quote: dict | None, keys: list[str]):
    if not isinstance(quote, dict):
        return None

    for key in keys:
        value = quote.get(key)

        if value is not None:
            return value

    return None


def get_quote_price(quote: dict | None):
    return get_quote_value(
        quote,
        [
            "price",
            "regularMarketPrice",
            "regular_market_price",
            "current_price",
            "last_price",
        ],
    )


def get_quote_change_percent(quote: dict | None):
    return get_quote_value(
        quote,
        [
            "change_percent",
            "percent_change",
            "regularMarketChangePercent",
            "regular_market_change_percent",
            "changePercent",
        ],
    )


def fetch_watchlist_quotes(context: dict | None = None) -> tuple[list[str], dict]:
    try:
        manual_symbols = load_watchlist()
    except Exception:
        manual_symbols = []

    context = context or {}
    scores = context.get("scores", []) if isinstance(context, dict) else []

    try:
        symbols = build_evolved_watchlist_universe(
            manual_symbols=manual_symbols,
            context=context,
            scores=scores,
            max_symbols=MAX_RELEVANT_WATCHLIST,
        )
    except Exception:
        try:
            symbols = build_relevant_watchlist(
                manual_symbols=manual_symbols,
                context=context,
                scores=scores,
                max_symbols=MAX_RELEVANT_WATCHLIST,
            )
        except Exception:
            symbols = manual_symbols[:MAX_RELEVANT_WATCHLIST]

    symbols = [
        str(symbol).strip().upper()
        for symbol in symbols or []
        if str(symbol).strip()
    ]

    symbols = list(dict.fromkeys(symbols))[:MAX_RELEVANT_WATCHLIST]

    if not symbols:
        return [], {}

    if not DAILY_REPORT_LIVE_QUOTES:
        return symbols, {}

    try:
        quotes = fetch_quotes_for_symbols(symbols)
    except Exception:
        return symbols, {}

    if not isinstance(quotes, dict):
        return symbols, {}

    return symbols, quotes


def collect_watchlist_movers(symbols: list[str], quotes: dict) -> list[dict]:
    movers = []

    for symbol in symbols or []:
        quote = quotes.get(symbol) or quotes.get(symbol.upper())

        if not isinstance(quote, dict):
            continue

        change_percent = safe_float(get_quote_change_percent(quote))
        price = safe_float(get_quote_price(quote))

        if change_percent is None:
            continue

        movers.append(
            {
                "symbol": symbol.upper(),
                "price": price,
                "change_percent": change_percent,
            }
        )

    movers.sort(key=lambda item: abs(item["change_percent"]), reverse=True)

    return movers


def build_market_tone(movers: list[dict]) -> str:
    if not movers:
        return "Quote data unavailable"

    changes = [item["change_percent"] for item in movers]
    positive = len([change for change in changes if change > 0])
    negative = len([change for change in changes if change < 0])
    average = sum(changes) / len(changes)

    if average >= 1 and positive > negative:
        return "Risk-on / bullish"

    if average <= -1 and negative > positive:
        return "Risk-off / bearish"

    if positive > negative:
        return "Constructive / mildly bullish"

    if negative > positive:
        return "Defensive / mildly bearish"

    return "Mixed / neutral"


def build_market_snapshot(symbols: list[str], movers: list[dict]) -> str:
    if not symbols:
        return "Watchlist unavailable."

    if not movers:
        quote_status = "Off" if not DAILY_REPORT_LIVE_QUOTES else "Unavailable"

        return f"""
Market Session: {get_market_status_label()}
Tone: Quote data unavailable
Watchlist: {len(symbols)} symbols
Live Quotes: {quote_status}
Use: /global, /headlines, /watchlist movers, or /ticker SYMBOL for live context.
""".strip()

    changes = [item["change_percent"] for item in movers]
    positive = len([change for change in changes if change > 0])
    negative = len([change for change in changes if change < 0])
    average = sum(changes) / len(changes)

    strongest = max(movers, key=lambda item: item["change_percent"])
    weakest = min(movers, key=lambda item: item["change_percent"])

    return f"""
Market Session: {get_market_status_label()}
Tone: {build_market_tone(movers)}
Breadth: {positive} up / {negative} down / {len(movers)} live
Average Move: {format_percent(average)}
Strongest: {strongest["symbol"]} {format_percent(strongest["change_percent"])}
Weakest: {weakest["symbol"]} {format_percent(weakest["change_percent"])}
""".strip()

def build_watchlist_snapshot(symbols: list[str], movers: list[dict]) -> str:
    if not symbols:
        return "Watchlist unavailable."

    universe_text = ", ".join(symbols[:MAX_RELEVANT_WATCHLIST])

    if not movers:
        return (
            f"Relevant research universe: {len(symbols)} symbols\n"
            f"{universe_text}\n\n"
            "Live movement data is unavailable."
        )

    mover_text = "\n".join(
        f"• {item['symbol']}: {format_price(item['price'])} ({format_percent(item['change_percent'])})"
        for item in movers[:MAX_WATCHLIST_MOVERS]
    )

    return f"""
Relevant research universe: {len(symbols)} symbols
{universe_text}

Largest live movers:
{mover_text}
""".strip()

def safe_morning_brief_intro() -> str:
    try:
        from src.reports.morning_brief_intro import build_morning_brief_intro

        intro = build_morning_brief_intro()

        return trim_block(intro, MAX_MORNING_BRIEF_CHARS)
    except Exception as error:
        return f"""
Good morning.

Morning brief intro is unavailable right now.

Reason: {type(error).__name__}
""".strip()


def load_morning_brief_payload() -> dict:
    try:
        from src.reports.morning_brief_intro import load_morning_brief_cache

        payload = load_morning_brief_cache()

        if isinstance(payload, dict):
            return payload

    except Exception:
        pass

    return {}


def get_cache_age_minutes(payload: dict) -> float | None:
    try:
        cached_at = float(payload.get("cached_at", 0) or 0)

        if cached_at <= 0:
            return None

        return (time.time() - cached_at) / 60
    except Exception:
        return None


def extract_headline_themes(payload: dict) -> list[str]:
    theme_summary = payload.get("theme_summary") or {}
    ranked = theme_summary.get("ranked_themes") or []
    headlines = payload.get("headlines") or []

    themes = []

    def add_theme(theme: str | None) -> None:
        if theme and theme not in themes:
            themes.append(theme)

    for item in ranked:
        if isinstance(item, dict):
            add_theme(item.get("theme"))
        elif isinstance(item, (list, tuple)) and item:
            add_theme(item[0])

    for headline in headlines:
        if isinstance(headline, dict):
            for theme in headline.get("themes") or []:
                add_theme(theme)

    priority = [
        theme
        for theme in themes
        if theme in HIGH_IMPACT_MACRO_THEMES
    ]

    others = [
        theme
        for theme in themes
        if theme not in priority
    ]

    cleaned = []

    for theme in priority + others:
        normalized = normalize_theme_name(theme)

        if normalized and normalized not in cleaned:
            cleaned.append(normalized)

    return cleaned[:6]

def extract_headline_examples(payload: dict) -> list[str]:
    headlines = payload.get("headlines") or []
    examples = []
    priority_examples = []

    for item in headlines:
        if isinstance(item, dict):
            title = item.get("title", "")
            source = item.get("source", "")
            themes = item.get("themes") or []

            formatted = f"{title} ({source or 'source'})" if title else ""

            if not formatted:
                continue

            lower_title = title.lower()

            if (
                "Oil / Geopolitical Risk" in themes
                or "Defense / AI Warfare" in themes
                or any(keyword in lower_title for keyword in GEOPOLITICAL_PRESSURE_KEYWORDS)
                or any(keyword in lower_title for keyword in DEFENSE_AI_WARFARE_KEYWORDS)
            ):
                priority_examples.append(formatted)
            else:
                examples.append(formatted)

        elif isinstance(item, str):
            lower_title = item.lower()

            if (
                any(keyword in lower_title for keyword in GEOPOLITICAL_PRESSURE_KEYWORDS)
                or any(keyword in lower_title for keyword in DEFENSE_AI_WARFARE_KEYWORDS)
            ):
                priority_examples.append(item)
            else:
                examples.append(item)

    combined = priority_examples + examples

    return combined[:4]

def extract_market_move(payload: dict, symbol: str) -> float:
    moves = payload.get("market_moves") or []

    for item in moves:
        if str(item.get("symbol", "")).upper() == symbol.upper():
            value = safe_float(item.get("move"))
            return value if value is not None else 0.0

    return 0.0


def build_weekly_calendar_pointer() -> str:
    return """
Week Ahead:
Use /weeklycalendar for the full macro and earnings calendar.

Focus:
• Inflation, rates, banks, AI/semi earnings, and consumer strength.
• Avoid chasing names directly before major catalysts.
""".strip()


def load_global_context() -> dict:
    """
    Daily report macro context.

    Uses the Morning Brief cache instead of making a new live global request.
    send_report.py refreshes this cache before scheduled delivery.
    """
    payload = load_morning_brief_payload()
    themes = extract_headline_themes(payload)
    examples = extract_headline_examples(payload)
    age_minutes = get_cache_age_minutes(payload)

    if age_minutes is None:
        cache_status = "No Morning Brief cache"
    elif age_minutes <= 360:
        cache_status = f"Fresh Morning Brief cache ({age_minutes:.0f} min old)"
    else:
        cache_status = f"Stale Morning Brief cache ({age_minutes:.0f} min old)"

    return {
        "headline_themes": themes,
        "headline_examples": examples,
        "regime": cache_status,
        "sp500": extract_market_move(payload, "^GSPC"),
        "nasdaq": extract_market_move(payload, "^IXIC"),
        "dow": extract_market_move(payload, "^DJI"),
        "russell": extract_market_move(payload, "^RUT"),
        "vix": extract_market_move(payload, "^VIX"),
        "tlt": extract_market_move(payload, "TLT"),
        "oil": extract_market_move(payload, "USO"),
        "gold": extract_market_move(payload, "GLD"),
        "dollar": extract_market_move(payload, "UUP"),
        "china": 0.0,
        "eem": 0.0,
    }


def headline_text_for_pressure(context: dict) -> str:
    themes = " ".join(context.get("headline_themes", []) or [])
    examples = " ".join(context.get("headline_examples", []) or [])

    return f"{themes} {examples}".lower()


def has_geopolitical_pressure(context: dict) -> bool:
    themes = context.get("headline_themes", []) or []
    theme_text = " ".join(str(theme).lower() for theme in themes)
    text = headline_text_for_pressure(context)

    if "oil" in theme_text and ("geopolitical" in theme_text or "risk" in theme_text):
        return True

    return any(keyword in text for keyword in GEOPOLITICAL_PRESSURE_KEYWORDS)


def has_defense_ai_warfare_pressure(context: dict) -> bool:
    themes = context.get("headline_themes", []) or []
    theme_text = " ".join(str(theme).lower() for theme in themes)
    text = headline_text_for_pressure(context)

    if "defense" in theme_text or "warfare" in theme_text or "munitions" in theme_text:
        return True

    return any(keyword in text for keyword in DEFENSE_AI_WARFARE_KEYWORDS)


def is_defense_ai_warfare_category(category: str) -> bool:
    category_upper = str(category or "").upper()

    return any(keyword in category_upper for keyword in DEFENSE_AI_WARFARE_CATEGORIES)


def get_macro_pressure(context: dict) -> str:
    pressures = []
    themes = context.get("headline_themes", []) or []
    normalized_theme_text = " ".join(str(theme).lower() for theme in themes)

    if has_geopolitical_pressure(context):
        pressures.append("Hormuz/Iran geopolitical shipping risk")

    if "procurement" in normalized_theme_text or "munitions" in normalized_theme_text:
        pressures.append("defense procurement/munitions demand signal")
    elif has_defense_ai_warfare_pressure(context):
        pressures.append("defense/AI warfare demand signal")

    if "inflation" in normalized_theme_text or "fed" in normalized_theme_text:
        pressures.append("inflation/Fed event risk")

    if "bank" in normalized_theme_text or "credit" in normalized_theme_text:
        pressures.append("bank/credit risk")

    if "consumer" in normalized_theme_text:
        pressures.append("consumer stress risk")

    if context["vix"] > 3:
        pressures.append("volatility rising")

    if context["nasdaq"] < -0.75:
        pressures.append("growth pressure")

    if context["sp500"] < -0.75:
        pressures.append("broad index pressure")

    if context["russell"] < -1:
        pressures.append("small-cap weakness")

    if context["tlt"] < -0.75:
        pressures.append("rate/duration pressure")

    if context["oil"] > 1.0:
        pressures.append("oil/inflation pressure")

    if context["gold"] > 1:
        pressures.append("safety/inflation hedge demand")

    if not pressures:
        return "no major macro pressure"

    return ", ".join(pressures[:5])


def category_macro_note(category: str, context: dict) -> str:
    category_upper = str(category or "").upper()
    themes = context.get("headline_themes", [])

    # Put defense/AI warfare first so "AI Warfare" is not captured by generic AI logic.
    if is_defense_ai_warfare_category(category):
        if has_defense_ai_warfare_pressure(context):
            return (
                "Macro check: escalation increases attention on DoD, drones, "
                "counter-drone, missile defense, cyber, ISR, and AI warfare exposure."
            )

        return "Macro check: defense remains event-driven and useful as geopolitical ballast."

    if "AI" in category_upper or "SEMICONDUCTOR" in category_upper or "TECH" in category_upper:
        if any("ai" in str(theme).lower() for theme in themes):
            return "Macro check: AI remains active; confirm whether leadership is broadening or rotating."

        if context["nasdaq"] < -0.75:
            return "Macro check: Nasdaq pressure may weigh on growth and AI names."

        return "Macro check: AI/growth setup needs Nasdaq and rates confirmation."

    if "CYBER" in category_upper:
        return "Macro check: cybersecurity can hold up if enterprise security spending remains resilient."

    if "ENERGY" in category_upper or "OIL" in category_upper or "POWER" in category_upper:
        if context["oil"] > 1.5:
            return "Macro check: oil strength may support energy but can raise inflation pressure."

        if any("ai infrastructure" in str(theme).lower() or "power" in str(theme).lower() for theme in themes):
            return "Macro check: AI power demand remains a supportive infrastructure theme."

        return "Macro check: energy and power need commodity/capex confirmation."

    if "DIVIDEND" in category_upper or "UTILITY" in category_upper or "INCOME" in category_upper:
        if context["vix"] > 3:
            return "Macro check: income exposure can help if volatility rises."

        return "Macro check: income exposure remains useful as portfolio ballast."

    return f"Macro check: {get_macro_pressure(context)}."


def build_global_portfolio_impact(context: dict, top_scores: list[dict]) -> str:
    themes = context.get("headline_themes", [])
    examples = context.get("headline_examples", [])
    pressure = get_macro_pressure(context)

    theme_text = ", ".join(themes[:4]) if themes else "Refresh cache or run /global."

    top_theme_notes = []

    for item in top_scores[:2]:
        ticker = get_ticker(item)
        category = get_category(item)
        top_theme_notes.append(f"• {ticker}: {category_macro_note(category, context)}")

    if not top_theme_notes:
        top_theme_notes.append("• No direct macro hit to top ideas.")

    market_moves = (
        f"S&P {format_percent(context.get('sp500'))}, "
        f"Nasdaq {format_percent(context.get('nasdaq'))}, "
        f"Russell {format_percent(context.get('russell'))}, "
        f"VIX {format_percent(context.get('vix'))}, "
        f"Oil {format_percent(context.get('oil'))}, "
        f"TLT {format_percent(context.get('tlt'))}"
    )

    example_text = "\n".join(
        f"• {clean_text(item, 135)}"
        for item in examples[:2]
    ) or "• No headline examples available."

    risk_label = "Elevated" if pressure != "no major macro pressure" else "Normal"

    return f"""
Macro Risk: {risk_label}
Pressure: {pressure}
Market Moves: {market_moves}
Themes: {theme_text}

Portfolio Read:
{chr(10).join(top_theme_notes)}

Signal Examples:
{example_text}
""".strip()


def build_defense_ai_warfare_impact(
    context: dict,
    top_scores: list[dict],
    scores: list[dict],
) -> str:
    if not has_defense_ai_warfare_pressure(context):
        return ""

    procurement_theme_active = any(
        "procurement" in str(theme).lower() or "munitions" in str(theme).lower()
        for theme in context.get("headline_themes", []) or []
    )

    if procurement_theme_active:
        impact_intro = (
            "This is stronger than a normal defense headline. A multi-year munitions push points to budget-backed demand for low-cost missiles, autonomous strike systems, sensors, mission software, propulsion, and scalable defense manufacturing."
        )
    else:
        impact_intro = (
            "Strikes, shipping risk, and escalation headlines shift the market conversation from generic AI to mission-critical defense technology: drones, counter-drone systems, missile defense, cyber, ISR, naval protection, and autonomous warfare."
        )

    defense_names = [
        item
        for item in scores
        if is_defense_ai_warfare_category(get_category(item))
    ]

    if defense_names:
        watch_text = "\n".join(
            f"• {get_ticker(item)}: {translate_smart_money_label(item)} | "
            f"{get_category(item)} | {get_action_label(item)}"
            for item in defense_names[:4]
        )
    else:
        watch_text = "• No direct defense/AI warfare names detected in the current scored watchlist."

    if top_scores:
        best = top_scores[0]
        action_text = (
            f"Start with {get_ticker(best)} only if the score, volume, and price action confirm. "
            "Do not chase every defense headline."
        )
    else:
        action_text = (
            "Do not chase every defense stock. Prioritize names with direct DoD exposure, rising volume, strong Smart Money scores, and a clear role in AI-enabled defense or battlefield infrastructure."
        )

    return f"""
Defense / AI Warfare Impact:
{impact_intro}

Watchlist Focus:
{watch_text}

How I would treat it:
{action_text}
""".strip()


def build_score_summary(scores: list[dict]) -> str:
    if not scores:
        return "No scored symbols available."

    counts = {}

    for item in scores:
        label = get_smart_money_label(item)
        counts[label] = counts.get(label, 0) + 1

    top_names = ", ".join(get_ticker(item) for item in scores[:5])

    priority_labels = [
        "Prime Opportunity",
        "High Conviction",
        "Strong Watch",
        "Developing Watch",
        "Early Watch",
    ]

    label_text = ", ".join(
        f"{label}: {counts[label]}"
        for label in priority_labels
        if counts.get(label)
    )

    return f"""
Reviewed: {len(scores)} names
Top Watch: {top_names if top_names else "N/A"}
Signal Mix: {label_text if label_text else "Mixed"}
""".strip()


def build_opportunity_edge(item: dict, context: dict) -> str:
    category = str(get_category(item) or "")
    category_upper = category.upper()
    themes = " ".join(context.get("headline_themes", []) or []).lower()

    raw_strength = item.get("strength") or first_list_text(
        item.get("strengths", []),
        "",
        120,
    )
    strength = clean_report_language(raw_strength, 120)

    if is_defense_ai_warfare_category(category):
        if has_defense_ai_warfare_pressure(context):
            return (
                "Defense/AI warfare exposure has current headline support; focus on real demand, "
                "DoD links, munitions, ISR, cyber, autonomy, or production scale."
            )

        return "Defense exposure can act as portfolio ballast, but it needs a direct catalyst before upgrading."

    if "AI" in category_upper or "TECH" in category_upper or "SEMICONDUCTOR" in category_upper:
        if "ai" in themes or "chips" in themes or "infrastructure" in themes:
            return "AI/growth leadership has theme support; the setup needs proof through earnings, margins, orders, and volume."

        return "AI/growth setup ranks well, but it needs Nasdaq, rates, and volume confirmation."

    if "ENERGY" in category_upper or "OIL" in category_upper or "POWER" in category_upper:
        return "Energy/power exposure is tied to oil, infrastructure demand, rates, and AI power demand."

    if "BANK" in category_upper or "FINANCIAL" in category_upper or "CREDIT" in category_upper:
        return "Financial setup depends on yields, credit quality, liquidity, and broader risk appetite."

    if "DIVIDEND" in category_upper or "UTILITY" in category_upper or "INCOME" in category_upper:
        return "Stability/income profile can help if volatility or rate uncertainty rises."

    if strength and strength.lower() not in {"quality setup", "smart money ranking is strong"}:
        return strength

    return "Ranks well enough to monitor, but the edge still needs confirmation from price action and volume."


def build_opportunity_trigger(item: dict, context: dict) -> str:
    category = str(get_category(item) or "")
    category_upper = category.upper()
    macro_pressure = get_macro_pressure(context)

    if is_defense_ai_warfare_category(category):
        return "Trigger: contract flow, backlog, budget language, volume, or relative strength confirms the defense thesis."

    if "AI" in category_upper or "TECH" in category_upper or "SEMICONDUCTOR" in category_upper:
        return "Trigger: price strength, volume, Nasdaq support, earnings quality, or AI demand commentary confirms."

    if "ENERGY" in category_upper or "OIL" in category_upper or "POWER" in category_upper:
        return "Trigger: oil, power demand, rates, or infrastructure headlines confirm the setup."

    if "BANK" in category_upper or "FINANCIAL" in category_upper or "CREDIT" in category_upper:
        return "Trigger: credit spreads, yields, deposits, or market breadth improve."

    if macro_pressure != "no major macro pressure":
        return f"Trigger: setup holds despite {macro_pressure}."

    return "Trigger: price, volume, and relative strength confirm before acting."


def format_opportunity(index: int, item: dict, context: dict) -> str:
    ticker = get_ticker(item)
    label = translate_smart_money_label(item)
    action = get_action_label(item)
    risk = get_risk_label(item)
    category = get_category(item)

    edge = clean_report_language(build_opportunity_edge(item, context), 190)
    trigger = clean_report_language(build_opportunity_trigger(item, context), 170)

    return (
        f"{index}. {ticker} — {label}\n"
        f"   Theme: {category}\n"
        f"   Edge: {edge}\n"
        f"   {trigger}\n"
        f"   Risk/Action: {risk} | {action}"
    )


def build_top_opportunities(
    top_scores: list[dict],
    context: dict,
    scoring_error: str = "",
) -> str:
    if not top_scores:
        if scoring_error:
            return f"Scoring unavailable: {scoring_error}"

        return "No scoring opportunities available."

    return "\n\n".join(
        format_opportunity(index, item, context)
        for index, item in enumerate(top_scores[:MAX_TOP_OPPORTUNITIES], start=1)
    )


def build_risk_notes(top_scores: list[dict], movers: list[dict], context: dict) -> str:
    notes = []
    macro_pressure = get_macro_pressure(context)

    elevated_risk = [
        get_ticker(item)
        for item in top_scores
        if get_risk_label(item) in {"High Risk", "Speculative", "Elevated"}
    ]

    large_movers = [
        item
        for item in movers
        if abs(item.get("change_percent", 0)) >= 2
    ]

    if macro_pressure != "no major macro pressure":
        notes.append(f"Main risk: {macro_pressure}.")

    if elevated_risk:
        notes.append(
            "Sizing risk: keep entries smaller on "
            + ", ".join(elevated_risk[:3])
            + "."
        )

    if large_movers:
        biggest = large_movers[0]
        notes.append(
            f"Move risk: {biggest['symbol']} is already moving "
            f"{format_percent(biggest['change_percent'])}; avoid chasing without confirmation."
        )

    if has_defense_ai_warfare_pressure(context):
        notes.append(
            "Theme risk: defense headlines need contract, backlog, budget, or volume confirmation."
        )

    if not notes:
        return "No major report-level risk flags. Main risk is still chasing before confirmation."

    return "\n".join(f"• {note}" for note in notes[:3])


def build_executive_summary(
    top_scores: list[dict],
    movers: list[dict],
    market_tone: str,
    context: dict,
) -> str:
    best = top_scores[0] if top_scores else None
    primary_theme = get_primary_theme(context)
    pressure = get_macro_pressure(context)
    market_moves = build_market_moves_line(context, movers)

    lines = [
        f"• Main theme: {primary_theme}.",
        f"• Market tone: {market_tone}; macro pressure: {pressure}.",
        f"• Market moves: {market_moves}",
    ]

    if best:
        lines.append(
            f"• Best watch: {get_ticker(best)} — {translate_smart_money_label(best)}. "
            f"Next step: /scorecard {get_ticker(best)}."
        )

    if has_defense_ai_warfare_pressure(context):
        lines.append(
            "• Defense read: escalation is a theme confirmation signal for defense, cyber, drones, ISR, and AI warfare names — not an automatic chase signal."
        )

    return "\n".join(lines)

def build_portfolio_read(
    context: dict,
    top_scores: list[dict],
    scores: list[dict],
) -> str:
    themes = get_clean_headline_themes(context, limit=3)
    pressure = get_macro_pressure(context)
    best = top_scores[0] if top_scores else None

    notes = []

    if has_geopolitical_pressure(context):
        notes.append(
            "Geopolitical risk is two-sided: it can pressure broad risk appetite through oil, shipping, and inflation, while increasing attention on defense and security exposure."
        )

    if has_defense_ai_warfare_pressure(context):
        defense_names = [
            item
            for item in scores
            if is_defense_ai_warfare_category(get_category(item))
        ]

        if defense_names:
            names = ", ".join(get_ticker(item) for item in defense_names[:5])
            notes.append(f"Defense/AI warfare watchlist exposure detected: {names}.")
        else:
            notes.append("Defense theme is active, but no direct defense/AI warfare watchlist exposure was detected.")

    if best:
        notes.append(
            f"{get_ticker(best)} is the cleanest ranked setup today, but it still needs price/volume confirmation before action."
        )

    if themes:
        notes.append(f"Theme focus: {', '.join(themes)}.")

    if pressure == "no major macro pressure" and not notes:
        notes.append("No major macro stress is dominating, so stock-specific quality and entry discipline matter most.")

    return "\n".join(f"• {note}" for note in notes[:4])


def compact_report_block(value: Any, max_lines: int = 4, max_line_length: int = 170) -> str:
    lines = []

    for raw_line in str(value or "").splitlines():
        line = " ".join(raw_line.strip().split())

        if not line:
            continue

        line = line.replace("Action: ", "Watch: ")
        line = line.replace("require ", "confirm ")
        line = line.replace("before acting", "before sizing")
        line = line.replace("headline quality", "signal quality")
        line = line.replace("headline noise", "market noise")

        if not line.startswith("•"):
            line = f"• {line}"

        lines.append(clean_text(line, max_line_length))

        if len(lines) >= max_lines:
            break

    return "\n".join(lines)


def build_optimized_theme_read(
    context: dict,
    market_tone: str,
    what_changed_today: str = "",
) -> str:
    try:
        raw_scorecard = build_theme_scorecard(
            context=context,
            market_tone=market_tone,
            what_changed_today=what_changed_today,
        )
    except Exception:
        raw_scorecard = "Theme scorecard unavailable."

    compact = compact_report_block(
        raw_scorecard,
        max_lines=3,
        max_line_length=175,
    )

    if compact:
        return compact

    primary_theme = get_primary_theme(context)
    pressure = get_macro_pressure(context)

    return (
        f"• Lead theme: {primary_theme}.\n"
        f"• Pressure: {pressure}.\n"
        "• Standard: confirm price, volume, and signal quality before sizing."
    )


def build_compact_defense_impact(
    context: dict,
    top_scores: list[dict],
    scores: list[dict],
) -> str:
    full_impact = build_defense_ai_warfare_impact(context, top_scores, scores)

    if not full_impact:
        return ""

    defense_names = [
        item
        for item in scores
        if is_defense_ai_warfare_category(get_category(item))
    ]
    names = ", ".join(get_ticker(item) for item in defense_names[:4])

    if not names:
        names = "no direct scored exposure"

    if any("procurement" in str(theme).lower() or "munitions" in str(theme).lower() for theme in context.get("headline_themes", []) or []):
        read = "budget-backed munitions/procurement demand"
    else:
        read = "defense, ISR, cyber, drones, autonomy, and missile-defense demand"

    return (
        "Defense / AI Warfare\n"
        f"• Read: {read}.\n"
        f"• Names: {names}.\n"
        "• Standard: confirm contract flow, volume, and direct revenue exposure before sizing."
    )


def build_clean_ai_summary(
    top_scores: list[dict],
    movers: list[dict],
    market_tone: str,
    context: dict,
    what_changed_today: str = "",
) -> str:
    return build_evolving_ai_summary(
        top_scores=top_scores,
        movers=movers,
        market_tone=market_tone,
        context=context,
        what_changed_today=what_changed_today,
        record_memory=True,
    )

def build_action_checklist(
    top_scores: list[dict],
    movers: list[dict],
    context: dict,
) -> str:
    actions = []
    best = top_scores[0] if top_scores else None
    macro_pressure = get_macro_pressure(context)
    themes = " ".join(context.get("headline_themes", []) or []).lower()

    if best:
        ticker = get_ticker(best)
        actions.append(f"/scorecard {ticker} — validate the top-ranked setup.")
        actions.append(f"/volume {ticker} — confirm whether money flow supports the score.")
    else:
        actions.append("/top10 — refresh the ranked opportunity list.")

    if movers:
        mover = movers[0]
        actions.append(
            f"/ticker {mover['symbol']} — inspect the largest live move before acting."
        )

    if (
        macro_pressure != "no major macro pressure"
        or "earnings" in themes
        or "fed" in themes
        or "inflation" in themes
    ):
        actions.append("/weeklycalendar — check upcoming catalysts before sizing.")

    if has_defense_ai_warfare_pressure(context):
        actions.append("/defense — review defense/AI warfare exposure separately.")

    return "\n".join(f"• {action}" for action in actions[:4])


def build_daily_report() -> str:
    now = datetime.now(ZoneInfo(REPORT_TIMEZONE))
    today = now.strftime("%B %d, %Y")
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    try:
        raw_scores = get_stock_scores()
        scoring_error = ""
    except Exception as exc:
        raw_scores = []
        scoring_error = type(exc).__name__

    scores = normalize_scores(raw_scores)
    top_scores = scores[:MAX_TOP_OPPORTUNITIES]

    global_context = load_global_context()
    global_context["scores"] = scores

    watchlist_symbols, watchlist_quotes = fetch_watchlist_quotes(global_context)
    record_watchlist_evolution_day(watchlist_symbols, global_context)

    movers = collect_watchlist_movers(watchlist_symbols, watchlist_quotes)
    market_tone = build_market_tone(movers)

    what_changed_today = build_what_changed_today(
        context=global_context,
        top_scores=top_scores,
        movers=movers,
        market_tone=market_tone,
        watchlist_symbols=watchlist_symbols,
        record=True,
    )

    theme_read = build_optimized_theme_read(
        context=global_context,
        market_tone=market_tone,
        what_changed_today=what_changed_today,
    )

    defense_impact = build_compact_defense_impact(
        context=global_context,
        top_scores=top_scores,
        scores=scores,
    )

    executive_summary = build_executive_summary(
        top_scores=top_scores,
        movers=movers,
        market_tone=market_tone,
        context=global_context,
    )

    return f"""
📊 Smart Money AI Daily Report
Daily Brief
Date: {today}
Generated: {timestamp} {REPORT_TIMEZONE}

Executive Summary
{executive_summary}

What Changed Today
{trim_block(what_changed_today, MAX_WHAT_CHANGED_CHARS)}

Theme Read
{theme_read}

Market Snapshot
{build_market_snapshot(watchlist_symbols, movers)}

Portfolio Read
{build_portfolio_read(global_context, top_scores, scores)}

{defense_impact}

Watchlist Movers
{build_watchlist_snapshot(watchlist_symbols, movers)}

Top Opportunities
{build_top_opportunities(top_scores, global_context, scoring_error)}

Risk Notes
{build_risk_notes(top_scores, movers, global_context)}

AI Summary
{build_clean_ai_summary(top_scores, movers, market_tone, global_context, what_changed_today)}

Action Checklist
{build_action_checklist(top_scores, movers, global_context)}

Next Commands
/scorecard SYMBOL
/top10
/weeklycalendar
/global

Notes
Informational only. Not financial advice.
""".strip()