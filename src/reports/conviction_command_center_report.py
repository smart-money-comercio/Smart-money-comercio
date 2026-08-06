from collections import Counter
from typing import Any

from src.intelligence.conviction_evolution import (
    build_conviction_evolution_notes,
    build_conviction_memory_summary,
    build_conviction_record,
    record_conviction_read,
    safe_float,
)
from src.intelligence.defense_live_sources import fetch_defense_live_context
from src.intelligence.global_live_sources import fetch_global_live_context
from src.reports.global_intelligence_report import (
    MACRO_SYMBOLS,
    build_macro_regime,
    build_risk_regime,
    get_quote_data,
    pressure_notes,
    top_theme as global_top_theme,
)
from src.reports.top10_report import classify_action_bucket, rank_candidates
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


try:
    from src.congress.congress_scoring import get_congress_score
except Exception:
    get_congress_score = None


try:
    from src.insiders.insider_scoring import get_insider_score
except Exception:
    get_insider_score = None


MAX_CANDIDATES = 30
MAX_OUTPUT_NAMES = 8


DEFENSE_SYMBOL_HINTS = {
    "LMT",
    "RTX",
    "NOC",
    "GD",
    "BA",
    "HII",
    "LHX",
    "LDOS",
    "KTOS",
    "AVAV",
    "PLTR",
    "MRCY",
    "BWXT",
    "TDY",
    "TXT",
    "CW",
    "HEI",
    "RKLB",
}


DEFENSE_TERMS = [
    "defense",
    "warfare",
    "aerospace",
    "military",
    "missile",
    "munition",
    "munitions",
    "drone",
    "uav",
    "cyber",
    "isr",
    "surveillance",
    "radar",
    "sensor",
    "space",
    "shipbuilding",
    "naval",
    "intelligence",
]


def clean_symbol(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper().replace("$", "")


def normalize_score_items(raw_scores: Any) -> list[dict]:
    if isinstance(raw_scores, list):
        return [item for item in raw_scores if isinstance(item, dict)]

    if isinstance(raw_scores, dict):
        if "scores" in raw_scores and isinstance(raw_scores["scores"], list):
            return [item for item in raw_scores["scores"] if isinstance(item, dict)]

        items = []

        for key, value in raw_scores.items():
            if isinstance(value, dict):
                copy = dict(value)
                copy.setdefault("ticker", key)
                copy.setdefault("symbol", key)
                items.append(copy)
            else:
                items.append(
                    {
                        "ticker": key,
                        "symbol": key,
                        "score": value,
                    }
                )

        return items

    return []


def get_score_value(item: dict) -> float | None:
    for key in [
        "score",
        "total_score",
        "smart_money_score",
        "overall_score",
        "final_score",
        "composite_score",
    ]:
        value = safe_float(item.get(key))

        if value is not None:
            return value

    return None


def format_score(score: float | None) -> str:
    if score is None:
        return "N/A"

    return f"{score:.0f}/100"


def format_decimal(score: float | None) -> str:
    if score is None:
        return "N/A"

    return f"{score:.1f}"


def bullet_lines(items: list[str]) -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]

    if not cleaned:
        return "• No conviction detail available."

    return "\n".join(f"• {item}" for item in cleaned)


def safe_label(func, item: dict, fallback: str) -> str:
    try:
        value = func(item)
        return str(value or fallback)
    except Exception:
        return fallback


def compact_text(value: Any, max_chars: int = 120) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def extract_numeric_score(value: Any) -> float | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return safe_float(value)

    if isinstance(value, dict):
        for key in [
            "score",
            "total_score",
            "congress_score",
            "insider_score",
            "signal_score",
            "final_score",
            "overall_score",
        ]:
            number = safe_float(value.get(key))

            if number is not None:
                return number

    return safe_float(value)


def enrich_item(item: dict) -> dict:
    copy = dict(item)

    symbol = clean_symbol(get_ticker(copy) or copy.get("symbol") or copy.get("ticker"))
    score = get_score_value(copy)

    copy["symbol"] = symbol
    copy["ticker"] = symbol
    copy["score"] = score
    copy["label"] = safe_label(get_smart_money_label, copy, "Signal developing")
    copy["signal"] = safe_label(get_signal_strength, copy, copy["label"])
    copy["risk"] = safe_label(get_risk_label, copy, "Unknown")
    copy["action"] = safe_label(get_action_label, copy, "Watch")
    copy["category"] = safe_label(get_category, copy, "Uncategorized")
    copy["portfolio_fit"] = safe_label(get_portfolio_fit, copy, "Unknown")
    copy["volume"] = safe_label(get_volume_label, copy, "Volume confirmation unavailable")

    try:
        ranked_item = rank_candidates([copy], limit=1)[0]
        copy["bucket"] = classify_action_bucket(ranked_item)
    except Exception:
        copy["bucket"] = "Watch for Confirmation"

    return copy


def get_ranked_items(scores: list[dict]) -> list[dict]:
    try:
        ranked = rank_candidates(scores, limit=MAX_CANDIDATES)
    except Exception:
        ranked = sorted(
            [enrich_item(item) for item in scores],
            key=lambda item: item.get("score") if item.get("score") is not None else -999,
            reverse=True,
        )[:MAX_CANDIDATES]

    return [enrich_item(item) for item in ranked]


def score_smart_money(item: dict) -> tuple[float, str]:
    score = item.get("score")

    if score is None:
        return 0.0, "Smart Money score unavailable"

    points = max(0.0, min(float(score), 100.0)) * 0.25

    if score >= 85:
        note = "strong score"
    elif score >= 75:
        note = "constructive score"
    elif score >= 65:
        note = "developing score"
    else:
        note = "weak score"

    return points, note


def score_risk(item: dict) -> tuple[float, str]:
    risk = str(item.get("risk") or "").lower()
    bucket = str(item.get("bucket") or "").lower()
    action = str(item.get("action") or "").lower()

    if any(term in risk for term in ["low", "controlled", "moderate"]) and "high risk" not in bucket:
        return 15.0, "risk controlled"

    if any(term in risk for term in ["high", "elevated", "volatile", "speculative"]) or "high risk" in bucket:
        return 3.0, "risk elevated"

    if any(term in action for term in ["avoid", "reduce", "caution"]):
        return 4.0, "action warns risk"

    return 9.0, "risk mixed"


def score_volume(item: dict) -> tuple[float, str]:
    volume = str(item.get("volume") or "").lower()

    if any(term in volume for term in ["confirm", "strong", "positive", "accumulation", "heavy", "above"]):
        return 12.0, "volume confirms"

    if any(term in volume for term in ["weak", "low", "thin", "unconfirmed", "needs"]):
        return 3.0, "volume unconfirmed"

    return 7.0, "volume neutral"


def score_catalyst(item: dict) -> tuple[float, str]:
    text = " ".join(
        [
            str(item.get("earnings_date", "")),
            str(item.get("next_earnings_date", "")),
            str(item.get("catalyst", "")),
            str(item.get("catalyst_status", "")),
            str(item.get("earnings_signal", "")),
            str(item.get("earnings_summary", "")),
            str(item.get("growth", "")),
            str(item.get("backlog", "")),
        ]
    ).lower()

    if any(term in text for term in ["strong", "beat", "raise", "raised", "positive", "backlog", "contract", "award"]):
        return 10.0, "catalyst supportive"

    if any(term in text for term in ["miss", "cut", "lowered", "weak", "delay", "negative"]):
        return 2.0, "catalyst risk"

    if text.strip():
        return 6.0, "catalyst watch"

    return 4.0, "catalyst unavailable"


def score_analyst(item: dict) -> tuple[float, str]:
    text = " ".join(
        [
            str(item.get("analyst_rating", "")),
            str(item.get("analyst_consensus", "")),
            str(item.get("consensus", "")),
            str(item.get("price_target", "")),
            str(item.get("target_upside", "")),
            str(item.get("analyst_summary", "")),
        ]
    ).lower()

    upside = safe_float(item.get("target_upside"))

    if upside is not None:
        if upside >= 15:
            return 10.0, "analyst upside supportive"

        if upside <= -5:
            return 2.0, "analyst downside risk"

    if any(term in text for term in ["strong buy", "buy", "outperform", "overweight", "positive"]):
        return 9.0, "analysts supportive"

    if any(term in text for term in ["sell", "underperform", "downgrade", "negative"]):
        return 2.0, "analysts cautious"

    if text.strip():
        return 6.0, "analyst neutral/mixed"

    return 4.0, "analyst unavailable"


def score_filing(item: dict) -> tuple[float, str]:
    text = " ".join(
        [
            str(item.get("filing_context", "")),
            str(item.get("sec_context", "")),
            str(item.get("filing_summary", "")),
            str(item.get("sec_summary", "")),
            str(item.get("latest_filing_summary", "")),
            str(item.get("risk_factors", "")),
            str(item.get("disclosures", "")),
        ]
    ).lower()

    red_flags = [
        "going concern",
        "substantial doubt",
        "dilution",
        "offering",
        "shelf",
        "convertible",
        "warrant",
        "restatement",
        "material weakness",
        "investigation",
        "subpoena",
        "default",
        "covenant",
    ]

    positives = [
        "contract",
        "award",
        "backlog",
        "guidance",
        "raised",
        "margin",
        "demand",
        "cash flow",
        "profitability",
    ]

    if any(term in text for term in red_flags):
        return 1.0, "filing risk present"

    if any(term in text for term in positives):
        return 10.0, "filings/disclosures supportive"

    if text.strip():
        return 7.0, "filings clean/mixed"

    return 5.0, "filing context unavailable"


def score_congress_insider(symbol: str) -> tuple[float, str]:
    signals = []
    total = 0.0

    if get_congress_score is not None:
        try:
            congress_value = extract_numeric_score(get_congress_score(symbol))
            if congress_value is not None:
                if congress_value >= 70:
                    total += 5.0
                    signals.append("Congress overlap supportive")
                elif congress_value >= 50:
                    total += 3.0
                    signals.append("Congress overlap neutral")
                else:
                    total += 1.0
                    signals.append("Congress overlap weak")
        except Exception:
            pass

    if get_insider_score is not None:
        try:
            insider_value = extract_numeric_score(get_insider_score(symbol))
            if insider_value is not None:
                if insider_value >= 70:
                    total += 5.0
                    signals.append("insider signal supportive")
                elif insider_value >= 50:
                    total += 3.0
                    signals.append("insider signal neutral")
                else:
                    total += 1.0
                    signals.append("insider signal weak")
        except Exception:
            pass

    if not signals:
        return 3.0, "Congress/insider unavailable"

    return min(total, 10.0), "; ".join(signals[:2])


def is_defense_candidate(item: dict) -> bool:
    symbol = clean_symbol(item.get("symbol") or item.get("ticker"))

    if symbol in DEFENSE_SYMBOL_HINTS:
        return True

    text = " ".join(
        [
            str(item.get("category") or ""),
            str(item.get("portfolio_fit") or ""),
            str(item.get("label") or ""),
            str(item.get("signal") or ""),
            str(item.get("sector") or ""),
            str(item.get("industry") or ""),
            str(item.get("theme") or ""),
            str(item.get("description") or ""),
            str(item.get("business_summary") or ""),
        ]
    ).lower()

    return any(term in text for term in DEFENSE_TERMS)


def score_macro_fit(item: dict, risk_regime: str, global_context: dict, defense_context: dict) -> tuple[float, str]:
    category = str(item.get("category") or "").lower()
    fit = str(item.get("portfolio_fit") or "").lower()
    label = str(item.get("label") or "").lower()
    risk_lower = str(risk_regime or "").lower()

    themes = " ".join(
        str(theme.get("theme") or "")
        for theme in (global_context.get("themes", []) or []) + (defense_context.get("themes", []) or [])
    ).lower()

    if "risk-off" in risk_lower:
        if any(term in category + fit + label for term in ["defense", "dividend", "income", "quality", "defensive"]):
            return 8.0, "fits defensive macro"

        return 3.0, "macro requires caution"

    if "risk-on" in risk_lower:
        if any(term in category + fit + label for term in ["growth", "ai", "technology", "semiconductor"]):
            return 8.0, "fits risk-on macro"

        return 6.0, "macro acceptable"

    if is_defense_candidate(item) and any(term in themes for term in ["defense", "geopolitical", "policy"]):
        return 8.0, "defense/policy fit"

    return 5.0, "macro fit neutral"


def score_conviction_item(item: dict, risk_regime: str, global_context: dict, defense_context: dict) -> dict:
    symbol = item["symbol"]

    components = []

    for builder in [
        score_smart_money,
        score_risk,
        score_volume,
        score_catalyst,
        score_analyst,
        score_filing,
    ]:
        points, note = builder(item)
        components.append((points, note))

    congress_points, congress_note = score_congress_insider(symbol)
    macro_points, macro_note = score_macro_fit(item, risk_regime, global_context, defense_context)

    components.append((congress_points, congress_note))
    components.append((macro_points, macro_note))

    total = sum(points for points, _note in components)
    positive_notes = [note for points, note in components if points >= 7]
    weak_notes = [note for points, note in components if points <= 3]

    enriched = dict(item)
    enriched["conviction_score"] = round(max(0.0, min(total, 100.0)), 1)
    enriched["positive_notes"] = positive_notes[:5]
    enriched["weak_notes"] = weak_notes[:5]
    enriched["component_notes"] = [note for _points, note in components]

    return enriched


def conviction_label(score: float | None) -> str:
    if score is None:
        return "Unavailable"

    if score >= 88:
        return "Confirmed Conviction"

    if score >= 80:
        return "High Conviction"

    if score >= 72:
        return "Validation Candidate"

    if score >= 62:
        return "Developing"

    return "Weak / Avoid"


def is_confirmed(item: dict) -> bool:
    return safe_float(item.get("conviction_score"), 0) >= 80 and not is_elevated_risk(item)


def is_validation_candidate(item: dict) -> bool:
    score = safe_float(item.get("conviction_score"), 0) or 0
    return 65 <= score < 80 or needs_confirmation(item)


def is_elevated_risk(item: dict) -> bool:
    risk = str(item.get("risk") or "").lower()
    bucket = str(item.get("bucket") or "").lower()
    action = str(item.get("action") or "").lower()
    weak_notes = " ".join(item.get("weak_notes", []) or []).lower()

    return (
        any(term in risk for term in ["high", "elevated", "speculative", "volatile"])
        or "high risk" in bucket
        or any(term in action for term in ["avoid", "reduce", "caution"])
        or "filing risk" in weak_notes
    )


def needs_confirmation(item: dict) -> bool:
    volume = str(item.get("volume") or "").lower()
    signal = str(item.get("signal") or "").lower()
    bucket = str(item.get("bucket") or "").lower()
    action = str(item.get("action") or "").lower()
    weak_notes = " ".join(item.get("weak_notes", []) or []).lower()

    return (
        "confirmation" in bucket
        or "watch" in action
        or any(term in signal for term in ["developing", "early", "weak"])
        or any(term in volume for term in ["weak", "unconfirmed", "thin", "low", "needs"])
        or any(term in weak_notes for term in ["unavailable", "unconfirmed", "catalyst risk"])
    )


def average_conviction(items: list[dict]) -> float | None:
    values = [
        safe_float(item.get("conviction_score"))
        for item in items
        if safe_float(item.get("conviction_score")) is not None
    ]

    if not values:
        return None

    return sum(values) / len(values)


def top_category(items: list[dict]) -> str:
    categories = [
        str(item.get("category") or "").strip()
        for item in items
        if str(item.get("category") or "").strip()
        and str(item.get("category") or "").lower() not in {"unknown", "n/a", "uncategorized"}
    ]

    if not categories:
        return "Mixed / developing"

    return Counter(categories).most_common(1)[0][0]


def build_conviction_regime(
    confirmed: list[dict],
    validation: list[dict],
    risk_names: list[dict],
    risk_regime: str,
) -> str:
    risk_lower = str(risk_regime or "").lower()

    if "risk-off" in risk_lower:
        return "Strict validation / risk-first"

    if len(confirmed) >= 4 and len(risk_names) <= 3:
        return "Conviction improving"

    if len(confirmed) >= 2:
        return "Selective conviction"

    if len(validation) >= 5:
        return "Watchlist-heavy / needs proof"

    if len(risk_names) >= 5:
        return "Risk-control regime"

    return "Developing conviction"


def format_name_line(index: int, item: dict) -> str:
    conviction_score = safe_float(item.get("conviction_score"))
    label = conviction_label(conviction_score)
    notes = ", ".join(item.get("positive_notes", [])[:2]) or "signal developing"

    return (
        f"{index}. {item['symbol']} — {format_decimal(conviction_score)} | {label}\n"
        f"   Base Score: {format_score(item.get('score'))} | Risk: {item.get('risk')} | Bucket: {item.get('bucket')}\n"
        f"   Why: {compact_text(notes, 140)}"
    )


def format_names(items: list[dict], limit: int = 6) -> str:
    if not items:
        return "• No names available in this bucket."

    lines = []

    for index, item in enumerate(items[:limit], start=1):
        lines.append(format_name_line(index, item))

    return "\n".join(lines)


def format_risk_names(items: list[dict]) -> str:
    if not items:
        return "• No major risk-control names detected."

    lines = []

    for item in items[:6]:
        weak = ", ".join(item.get("weak_notes", [])[:2]) or item.get("risk")
        lines.append(
            f"• {item['symbol']}: {format_decimal(item.get('conviction_score'))} | {item.get('risk')} | {compact_text(weak, 110)}"
        )

    return "\n".join(lines)


def format_validation_queue(items: list[dict]) -> str:
    if not items:
        return "• No major validation queue detected."

    lines = []

    for item in items[:6]:
        symbol = item["symbol"]
        weak = ", ".join(item.get("weak_notes", [])[:2]) or "needs confirmation"
        lines.append(
            f"• {symbol}: {compact_text(weak, 100)} | /volume {symbol} → /earnings {symbol} → /analyst {symbol} → /filing {symbol}"
        )

    return "\n".join(lines)


def format_overlap_matrix(items: list[dict]) -> str:
    if not items:
        return "• No overlap matrix available."

    lines = []

    for item in items[:8]:
        positives = len(item.get("positive_notes", []) or [])
        weak = len(item.get("weak_notes", []) or [])
        lines.append(
            f"• {item['symbol']}: conviction {format_decimal(item.get('conviction_score'))} | positives {positives} | weak spots {weak}"
        )

    return "\n".join(lines)


def build_conviction_action(regime: str, confirmed: list[dict], validation: list[dict], risk_names: list[dict]) -> str:
    if confirmed:
        symbol = confirmed[0]["symbol"]

        if regime in {"Conviction improving", "Selective conviction"}:
            return f"Start with {symbol}; confirm entry quality with /volume {symbol}, /risk {symbol}, and /filing {symbol} before sizing."

        return f"{symbol} is the cleanest overlap candidate, but regime still requires validation before action."

    if validation:
        symbol = validation[0]["symbol"]
        return f"No fully confirmed setup yet. Begin validation with /volume {symbol}, /earnings {symbol}, /analyst {symbol}, and /filing {symbol}."

    if risk_names:
        symbol = risk_names[0]["symbol"]
        return f"Conviction is blocked by risk. Review /risk {symbol} and avoid forcing trades."

    return "No actionable conviction cluster yet. Use /top10 for ideas and wait for confirmation."


def build_next_commands(confirmed: list[dict], validation: list[dict], risk_names: list[dict]) -> str:
    commands = [
        "/smartmoney",
        "/global",
        "/portfolio",
        "/top10",
    ]

    target = None

    if confirmed:
        target = confirmed[0]["symbol"]
    elif validation:
        target = validation[0]["symbol"]
    elif risk_names:
        target = risk_names[0]["symbol"]

    if target:
        commands.extend(
            [
                f"/stock {target}",
                f"/scorecard {target}",
                f"/volume {target}",
                f"/risk {target}",
                f"/filing {target}",
            ]
        )

    commands.append("/brief")

    return "\n".join(f"• {command}" for command in commands[:10])


def build_executive_notes(
    regime: str,
    macro_regime: str,
    risk_regime: str,
    top_theme: str,
    avg_score: float | None,
    confirmed: list[dict],
    validation: list[dict],
    risk_names: list[dict],
) -> list[str]:
    return [
        f"Conviction regime: {regime}.",
        f"Macro regime: {macro_regime}.",
        f"Risk regime: {risk_regime}.",
        f"Top conviction theme: {top_theme}.",
        f"Average conviction score: {format_decimal(avg_score)}.",
        f"Confirmed names: {len(confirmed)}; validation queue: {len(validation)}; risk-control names: {len(risk_names)}.",
        f"Top candidate: {confirmed[0]['symbol'] if confirmed else validation[0]['symbol'] if validation else 'Unavailable'}.",
    ]


def build_conviction_command_center_report(force_refresh: bool = False) -> str:
    try:
        raw_scores = get_stock_scores()
    except Exception:
        raw_scores = []

    scores = normalize_score_items(raw_scores)
    ranked = get_ranked_items(scores)

    global_context = fetch_global_live_context(force_refresh=force_refresh)
    defense_context = fetch_defense_live_context(force_refresh=force_refresh)

    quotes = get_quote_data(list(MACRO_SYMBOLS.keys()))
    risk_regime = build_risk_regime(quotes, global_context)
    macro_regime = build_macro_regime(quotes, global_context)
    macro_theme = global_top_theme(global_context)
    macro_notes = pressure_notes(quotes, global_context)

    conviction_items = [
        score_conviction_item(item, risk_regime, global_context, defense_context)
        for item in ranked
    ]

    conviction_items.sort(
        key=lambda item: safe_float(item.get("conviction_score"), 0) or 0,
        reverse=True,
    )

    confirmed = [item for item in conviction_items if is_confirmed(item)]
    validation = [
        item
        for item in conviction_items
        if item not in confirmed and is_validation_candidate(item)
    ]
    risk_names = [item for item in conviction_items if is_elevated_risk(item)]

    avg_conviction = average_conviction(conviction_items)
    top_conviction = safe_float(conviction_items[0].get("conviction_score")) if conviction_items else None
    theme = top_category(conviction_items)

    regime = build_conviction_regime(
        confirmed=confirmed,
        validation=validation,
        risk_names=risk_names,
        risk_regime=risk_regime,
    )

    action = build_conviction_action(
        regime=regime,
        confirmed=confirmed,
        validation=validation,
        risk_names=risk_names,
    )

    record = build_conviction_record(
        conviction_regime=regime,
        macro_regime=macro_regime,
        risk_regime=risk_regime,
        top_symbols=[item["symbol"] for item in conviction_items[:MAX_OUTPUT_NAMES]],
        confirmed_symbols=[item["symbol"] for item in confirmed[:MAX_OUTPUT_NAMES]],
        validation_symbols=[item["symbol"] for item in validation[:MAX_OUTPUT_NAMES]],
        risk_symbols=[item["symbol"] for item in risk_names[:MAX_OUTPUT_NAMES]],
        average_conviction_score=avg_conviction,
        top_conviction_score=top_conviction,
        action=action,
    )

    evolution = record_conviction_read(record)

    evolution_notes = build_conviction_evolution_notes(
        evolution.get("previous"),
        evolution.get("current"),
    )

    return f"""
🔥 Conviction Command Center

Executive Read
Conviction Regime: {regime}
Macro Regime: {macro_regime}
Risk Regime: {risk_regime}
Macro Theme: {macro_theme}
Top Conviction Theme: {theme}
Average Conviction Score: {format_decimal(avg_conviction)}
Top Conviction Score: {format_decimal(top_conviction)}

Signal Summary
{bullet_lines(build_executive_notes(
    regime=regime,
    macro_regime=macro_regime,
    risk_regime=risk_regime,
    top_theme=theme,
    avg_score=avg_conviction,
    confirmed=confirmed,
    validation=validation,
    risk_names=risk_names,
))}

Confirmed / Actionable Candidates
{format_names(confirmed, limit=6)}

Highest Conviction Watchlist
{format_names(conviction_items, limit=8)}

Validation Queue
{format_validation_queue(validation)}

Risk-Control Names
{format_risk_names(risk_names)}

Signal Overlap Matrix
{format_overlap_matrix(conviction_items)}

Macro / Defense Fit
• Macro theme: {macro_theme}
• Risk regime: {risk_regime}
• Macro pressure: {compact_text("; ".join(macro_notes[:4]), 220)}
• Defense-source themes: {compact_text(", ".join(str(item.get("theme")) for item in defense_context.get("themes", [])[:4]), 180)}

Congress / Insider Overlay
• Congress and insider signals are included when scoring data is available.
• They are treated as confirmation overlays, not stand-alone buy signals.
• A strong overlap score still requires volume, risk, filing, and catalyst validation.

What Changed
{bullet_lines(evolution_notes)}

Evolving Analysis
{build_conviction_memory_summary()}

Conviction Action
{action}

Next Commands
{build_next_commands(confirmed, validation, risk_names)}

Research only. Not financial advice.
""".strip()