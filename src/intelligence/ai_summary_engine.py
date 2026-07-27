import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.utils import score_display as score_display


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_SUMMARY_MEMORY_FILE = PROJECT_ROOT / "data" / "ai_summary_memory.json"

SUMMARY_TIMEZONE = "America/Lima"
MAX_MEMORY_DAYS = 20
MAX_SUMMARY_CHARS = 1050


def read_json(path: Path, default: Any):
    try:
        if not path.exists():
            return default

        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, sort_keys=True)
    except Exception:
        return


def today_key() -> str:
    return datetime.now(ZoneInfo(SUMMARY_TIMEZONE)).strftime("%Y-%m-%d")


def daily_seed() -> int:
    return int(datetime.now(ZoneInfo(SUMMARY_TIMEZONE)).strftime("%Y%m%d"))


def clean_text(value: Any, max_length: int = 180) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def clean_report_language(value: Any, max_length: int = MAX_SUMMARY_CHARS) -> str:
    text = clean_text(value, max_length + 200)

    replacements = {
        "My read: My read:": "My read:",
        "Today’s edge is the shift, not the noise: Today’s edge is the shift, not the noise:": "Today’s edge is the shift, not the noise:",
        "not financial advice": "research only",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return clean_text(text, max_length)


def safe_score_display(function_name: str, stock: dict | None, fallback: str) -> str:
    try:
        function = getattr(score_display, function_name)
        value = function(stock or {})
        return clean_text(value, 120) or fallback
    except Exception:
        return fallback


def get_ticker(stock: dict | None) -> str:
    return safe_score_display("get_ticker", stock, "UNKNOWN")


def get_action_label(stock: dict | None) -> str:
    return safe_score_display("get_action_label", stock, "Watch")


def get_risk_label(stock: dict | None) -> str:
    return safe_score_display("get_risk_label", stock, "Risk needs review")


def get_category(stock: dict | None) -> str:
    return safe_score_display("get_category", stock, "General")


def get_smart_money_label(stock: dict | None) -> str:
    return safe_score_display("get_smart_money_label", stock, "Smart Money watch")


def normalize_label(value: Any) -> str:
    text = clean_text(value, 120)

    replacements = {
        "Core Smart Money Quality": "quality",
        "Core Smart Money quality": "quality",
        "Prime Opportunity": "prime opportunity",
        "High Conviction": "high-conviction",
        "Strong Watch": "strong watch",
        "Developing Watch": "developing watch",
    }

    return replacements.get(text, text).lower()


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("$", "")


def get_score_value(stock: dict | None) -> float:
    if not isinstance(stock, dict):
        return 0.0

    for key in [
        "final_score",
        "score",
        "smart_money_score",
        "total_score",
        "rating_score",
    ]:
        try:
            value = stock.get(key)

            if value is not None:
                return float(value)
        except Exception:
            continue

    return 0.0


def format_percent(value: Any) -> str:
    try:
        number = float(value)
        sign = "+" if number > 0 else ""
        return f"{sign}{number:.2f}%"
    except Exception:
        return "n/a"


def extract_themes(context: dict | None, limit: int = 5) -> list[str]:
    if not isinstance(context, dict):
        return []

    candidates = []

    for key in [
        "headline_themes",
        "themes",
        "active_themes",
        "macro_themes",
    ]:
        value = context.get(key)

        if isinstance(value, list):
            candidates.extend(value)

    theme_summary = context.get("theme_summary")

    if isinstance(theme_summary, dict):
        ranked = theme_summary.get("ranked_themes") or []

        for item in ranked:
            if isinstance(item, dict):
                candidates.append(item.get("theme"))
            elif isinstance(item, (list, tuple)) and item:
                candidates.append(item[0])

    seen = set()
    themes = []

    for item in candidates:
        theme = clean_text(item, 80)

        if not theme or theme.lower() in seen:
            continue

        seen.add(theme.lower())
        themes.append(theme)

        if len(themes) >= limit:
            break

    return themes


def primary_theme(context: dict | None) -> str:
    themes = extract_themes(context, limit=1)
    return themes[0] if themes else "confirmation"


def theme_text(context: dict | None) -> str:
    themes = extract_themes(context, limit=3)
    return ", ".join(themes) if themes else "earnings, rates, headlines, and confirmation"


def macro_pressure(context: dict | None) -> str:
    if not isinstance(context, dict):
        return "mixed macro pressure"

    text = " ".join(
        str(value)
        for value in [
            context.get("macro_pressure"),
            context.get("global_macro_pressure"),
            context.get("risk_pressure"),
            context.get("market_pressure"),
            context.get("summary"),
        ]
        if value
    ).lower()

    themes = " ".join(extract_themes(context, limit=8)).lower()
    combined = f"{text} {themes}"

    if "oil" in combined or "geopolitical" in combined or "energy" in combined:
        return "oil and geopolitical pressure"

    if "fed" in combined or "inflation" in combined or "rates" in combined or "treasury" in combined:
        return "rates and inflation pressure"

    if "credit" in combined or "bank" in combined or "liquidity" in combined:
        return "credit and liquidity pressure"

    if "consumer" in combined or "spending" in combined:
        return "consumer-demand pressure"

    if "defense" in combined or "munitions" in combined:
        return "defense and geopolitical demand pressure"

    if "ai" in combined or "chips" in combined or "semiconductor" in combined:
        return "AI-capex proof pressure"

    return "mixed macro pressure"


def read_ai_memory() -> dict:
    data = read_json(AI_SUMMARY_MEMORY_FILE, {"days": []})

    if not isinstance(data, dict):
        return {"days": []}

    if not isinstance(data.get("days"), list):
        data["days"] = []

    return data


def save_ai_memory(memory: dict) -> None:
    days = memory.get("days") or []

    if not isinstance(days, list):
        days = []

    memory["days"] = days[-MAX_MEMORY_DAYS:]

    write_json(AI_SUMMARY_MEMORY_FILE, memory)


def signature(value: str) -> str:
    text = clean_text(value, 120).lower()
    keep = []

    for char in text:
        if char.isalnum() or char.isspace():
            keep.append(char)

    return " ".join("".join(keep).split())[:90]


def recent_signatures(memory: dict) -> set[str]:
    signatures = set()

    for day in memory.get("days", [])[-7:]:
        item = day.get("lead_signature")

        if item:
            signatures.add(str(item))

    return signatures


def remember_ai_summary(lead: str, themes: list[str], top_ticker: str) -> None:
    memory = read_ai_memory()
    current_date = today_key()

    days = [
        day
        for day in memory.get("days", [])
        if day.get("date") != current_date
    ]

    days.append(
        {
            "date": current_date,
            "lead": clean_text(lead, 220),
            "lead_signature": signature(lead),
            "themes": themes[:5],
            "top_ticker": top_ticker,
        }
    )

    memory["days"] = days[-MAX_MEMORY_DAYS:]
    save_ai_memory(memory)


def first_change_line(what_changed_today: str) -> str:
    lines = []

    for raw_line in str(what_changed_today or "").splitlines():
        line = raw_line.strip().strip("•").strip()

        if line:
            lines.append(line)

    if not lines:
        return ""

    return clean_text(lines[0], 220)


def build_lead_candidates(
    top_scores: list[dict],
    movers: list[dict],
    market_tone: str,
    context: dict,
    what_changed_today: str,
) -> list[str]:
    best = top_scores[0] if top_scores else None
    best_ticker = get_ticker(best) if best else ""
    best_label = normalize_label(get_smart_money_label(best)) if best else ""
    themes = extract_themes(context, limit=5)
    main_theme = themes[0] if themes else "confirmation"
    themes_joined = " ".join(themes).lower()
    pressure = macro_pressure(context)
    change = first_change_line(what_changed_today)
    change_lower = str(what_changed_today or "").lower()

    mover = movers[0] if movers else {}
    mover_symbol = normalize_symbol(mover.get("symbol")) if isinstance(mover, dict) else ""
    mover_change = format_percent(mover.get("change_percent")) if isinstance(mover, dict) else "n/a"

    candidates = []

    if change:
        candidates.append(
            f"The first read today is the change signal: {change}"
        )

    if "new theme" in change_lower:
        candidates.append(
            f"Today’s opportunity is not the loudest headline; it is the new theme entering the model. {change}"
        )

    if "top watch changed" in change_lower:
        candidates.append(
            f"The ranking board shifted today. {change} That deserves more attention than another recycled macro headline."
        )

    if "market tone changed" in change_lower:
        candidates.append(
            f"The market message changed before the watchlist did. {change}"
        )

    if "theme persistence" in change_lower:
        candidates.append(
            f"The important signal is persistence. {change} Persistent themes deserve a higher bar for evidence, not blind momentum chasing."
        )

    if "defense procurement" in themes_joined or "munitions" in themes_joined:
        candidates.append(
            "Today’s sharpest read-through is budget-backed defense demand: munitions depth, autonomy, ISR, cyber, missile defense, and scalable production matter more than generic geopolitical fear."
        )

    if "defense" in themes_joined and "ai" in themes_joined:
        candidates.append(
            "The market is starting to treat defense AI like an industrial demand story, not just a software headline."
        )

    if "ai / chips" in themes_joined or "ai infrastructure" in themes_joined or "chips" in themes_joined:
        candidates.append(
            "Today’s AI read is about proof of return, not hype: chips, cloud, power, and data-center spending need to translate into margins or durable order books."
        )

    if "oil" in themes_joined or "geopolitical" in themes_joined:
        candidates.append(
            "Oil and geopolitical risk are the macro transmission channel today; if energy stress bleeds into inflation expectations, growth trades need cleaner confirmation."
        )

    if "earnings" in themes_joined:
        candidates.append(
            "Earnings quality matters more than the headline beat today; guidance, backlog, margins, and capex discipline are the real tells."
        )

    if "banks" in themes_joined or "credit" in themes_joined:
        candidates.append(
            "The financial-plumbing read matters today: credit, liquidity, yields, and risk appetite can either validate or kill the equity setup."
        )

    if mover_symbol:
        candidates.append(
            f"The live-market clue is {mover_symbol}, moving {mover_change}; that is the first place to check whether price action confirms the story."
        )

    if best_ticker:
        candidates.append(
            f"The report is narrowing toward selectivity: {best_ticker} is the cleanest ranked watch with a {best_label} profile, but confirmation still beats conviction."
        )

    candidates.append(
        f"Today’s edge is discipline: the lead theme is {main_theme}, the tone is {market_tone.lower()}, and the pressure point is {pressure}."
    )

    return candidates


def choose_daily_lead(candidates: list[str]) -> str:
    memory = read_ai_memory()
    used = recent_signatures(memory)

    unique = []

    for candidate in candidates:
        candidate = clean_text(candidate, 260)

        if not candidate:
            continue

        if candidate in unique:
            continue

        unique.append(candidate)

    if not unique:
        return "Today’s edge is selectivity: the report needs confirmation before conviction."

    fresh = [
        candidate
        for candidate in unique
        if signature(candidate) not in used
    ]

    pool = fresh or unique
    index = daily_seed() % len(pool)

    return pool[index]


def build_portfolio_implication(
    best: dict | None,
    movers: list[dict],
    context: dict,
    market_tone: str,
) -> str:
    themes = theme_text(context)
    pressure = macro_pressure(context)

    if not best:
        return (
            f"Portfolio implication: treat this as a filter day. The active themes are {themes}, "
            f"but there is not enough top-ranked conviction to force a new idea."
        )

    ticker = get_ticker(best)
    label = normalize_label(get_smart_money_label(best))
    category = get_category(best)
    risk = get_risk_label(best)
    action = get_action_label(best)

    implication = (
        f"Portfolio implication: {ticker} is the first name to review because it screens as {label} "
        f"inside {category}. The setup is not automatic; tone is {market_tone.lower()}, "
        f"pressure is {pressure}, risk read is {risk}, and action read is {action}."
    )

    if movers:
        mover = movers[0]
        symbol = normalize_symbol(mover.get("symbol"))
        change = format_percent(mover.get("change_percent"))

        if symbol and symbol != ticker:
            implication += (
                f" Separate that from the live tape: {symbol} is the biggest mover at {change}, "
                f"so it should be checked for confirmation or exhaustion."
            )

    return implication


def build_validation_test(
    best: dict | None,
    movers: list[dict],
    context: dict,
) -> str:
    themes = " ".join(extract_themes(context, limit=5)).lower()
    ticker = get_ticker(best) if best else ""

    if "defense" in themes or "munitions" in themes:
        return (
            "Validation test: look for hard evidence — contracts, budget language, backlog, production capacity, "
            "DoD demand, or partner announcements. Ignore defense headlines that do not map to revenue."
        )

    if "ai" in themes or "chips" in themes:
        return (
            "Validation test: look for capex discipline, order visibility, margin durability, data-center demand, "
            "and whether customers are still spending after the first AI hype cycle."
        )

    if "oil" in themes or "geopolitical" in themes:
        return (
            "Validation test: check whether oil, yields, and the dollar are confirming the same risk message. "
            "A single headline is not enough."
        )

    if "earnings" in themes:
        return (
            "Validation test: prioritize guidance, margin commentary, backlog, and forward demand over the headline EPS beat."
        )

    if ticker:
        return (
            f"Validation test: inspect {ticker} first, then confirm whether volume, relative strength, and the active theme are moving in the same direction."
        )

    return (
        "Validation test: wait for alignment between headline flow, price action, volume, and market breadth before acting."
    )


def build_evolving_ai_summary(
    top_scores: list[dict],
    movers: list[dict],
    market_tone: str,
    context: dict,
    what_changed_today: str = "",
    record_memory: bool = True,
) -> str:
    top_scores = top_scores or []
    movers = movers or []
    context = context or {}

    best = top_scores[0] if top_scores else None
    ticker = get_ticker(best) if best else ""

    candidates = build_lead_candidates(
        top_scores=top_scores,
        movers=movers,
        market_tone=market_tone,
        context=context,
        what_changed_today=what_changed_today,
    )

    lead = choose_daily_lead(candidates)
    themes = extract_themes(context, limit=5)

    implication = build_portfolio_implication(
        best=best,
        movers=movers,
        context=context,
        market_tone=market_tone,
    )

    validation = build_validation_test(
        best=best,
        movers=movers,
        context=context,
    )

    summary = f"{lead}\n\n{implication}\n\n{validation}"

    if record_memory:
        remember_ai_summary(lead, themes, ticker)

    return clean_report_language(summary, MAX_SUMMARY_CHARS)