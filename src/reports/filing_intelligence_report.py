from typing import Any

from src.intelligence.filing_evolution import (
    build_filing_evolution_notes,
    build_filing_memory_summary,
    build_filing_record,
    record_filing_read,
    safe_float,
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


def clean_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("$", "").strip()


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

        return items

    return []


def get_score_value(score_data: dict) -> float | None:
    for key in [
        "score",
        "total_score",
        "smart_money_score",
        "overall_score",
        "final_score",
        "composite_score",
    ]:
        value = safe_float(score_data.get(key))

        if value is not None:
            return value

    return None


def find_score_data(symbol: str, scores: list[dict]) -> dict:
    symbol = clean_symbol(symbol)

    for item in scores:
        ticker = clean_symbol(
            get_ticker(item) or item.get("symbol") or item.get("ticker")
        )

        if ticker == symbol:
            return item

    return {"symbol": symbol, "ticker": symbol}


def get_first_value(data: dict, keys: list[str], default=None):
    for key in keys:
        value = data.get(key)

        if value is not None and str(value).strip():
            return value

    return default


def compact_text(value: Any, max_chars: int = 180) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def bullet_lines(items: list[str]) -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]

    if not cleaned:
        return "• No clear filing detail available."

    return "\n".join(f"• {item}" for item in cleaned)


def format_score(score: float | None) -> str:
    if score is None:
        return "N/A"

    return f"{score:.0f}/100"


def stringify_filing_payload(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, dict):
        parts = []

        for key in [
            "title",
            "form",
            "filing_type",
            "type",
            "date",
            "filing_date",
            "summary",
            "description",
            "text",
            "risk",
            "risk_factors",
        ]:
            if value.get(key):
                parts.append(f"{key}: {value.get(key)}")

        if parts:
            return " | ".join(parts)

        return " | ".join(f"{key}: {item}" for key, item in list(value.items())[:8])

    if isinstance(value, list):
        parts = []

        for item in value[:3]:
            text = stringify_filing_payload(item)

            if text:
                parts.append(text)

        return " || ".join(parts)

    return str(value or "").strip()


def extract_filing_context(score_data: dict) -> str:
    value = get_first_value(
        score_data,
        [
            "filing_context",
            "sec_context",
            "filing_summary",
            "sec_summary",
            "latest_filing_summary",
            "latest_sec_filing",
            "latest_filing",
            "filings",
            "sec_filings",
            "filing_text",
            "risk_factors",
            "disclosures",
        ],
        "",
    )

    text = stringify_filing_payload(value)

    if text:
        return compact_text(text, 650)

    return "No detailed SEC filing context is available from the current data source."


def extract_filing_type(score_data: dict, filing_context: str) -> str:
    value = get_first_value(
        score_data,
        [
            "filing_type",
            "latest_filing_type",
            "sec_form",
            "form_type",
            "form",
            "filingForm",
        ],
        "",
    )

    if value:
        return str(value).strip().upper()

    text = filing_context.upper()

    for filing_type in ["10-K", "10-Q", "8-K", "S-1", "S-3", "S-4", "13F", "13D", "13G", "4", "144"]:
        if filing_type in text:
            return filing_type

    return "Unavailable"


def extract_filing_date(score_data: dict, filing_context: str) -> str:
    value = get_first_value(
        score_data,
        [
            "filing_date",
            "latest_filing_date",
            "sec_filing_date",
            "report_date",
            "filed_at",
            "filingDate",
        ],
        "",
    )

    if value:
        return str(value).strip()

    return "Unavailable"


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    lowered = str(text or "").lower()

    return [keyword for keyword in keywords if keyword.lower() in lowered]


DILUTION_KEYWORDS = [
    "offering",
    "shelf registration",
    "s-3",
    "dilution",
    "convertible",
    "warrant",
    "equity issuance",
    "at-the-market",
    "atm program",
    "secondary offering",
]

LIQUIDITY_KEYWORDS = [
    "going concern",
    "substantial doubt",
    "liquidity",
    "debt covenant",
    "default",
    "credit facility",
    "refinancing",
    "cash burn",
    "working capital",
]

LEGAL_KEYWORDS = [
    "litigation",
    "investigation",
    "subpoena",
    "sec investigation",
    "doj",
    "ftc",
    "regulatory",
    "settlement",
    "restatement",
    "material weakness",
]

GUIDANCE_KEYWORDS = [
    "guidance",
    "outlook",
    "forecast",
    "backlog",
    "contract",
    "award",
    "demand",
    "margin",
    "revenue growth",
    "raised",
    "increase",
    "beat",
]

OWNERSHIP_KEYWORDS = [
    "beneficial ownership",
    "insider",
    "form 4",
    "13d",
    "13g",
    "institutional",
    "purchase",
    "sale",
    "ownership",
]

RISK_LANGUAGE_KEYWORDS = [
    "risk factor",
    "material adverse",
    "uncertain",
    "volatility",
    "dependence",
    "customer concentration",
    "supply chain",
    "competition",
]


def analyze_filing_signals(filing_context: str, filing_type: str) -> dict:
    text = f"{filing_type} {filing_context}"

    dilution = keyword_hits(text, DILUTION_KEYWORDS)
    liquidity = keyword_hits(text, LIQUIDITY_KEYWORDS)
    legal = keyword_hits(text, LEGAL_KEYWORDS)
    guidance = keyword_hits(text, GUIDANCE_KEYWORDS)
    ownership = keyword_hits(text, OWNERSHIP_KEYWORDS)
    risk_language = keyword_hits(text, RISK_LANGUAGE_KEYWORDS)

    return {
        "dilution": dilution,
        "liquidity": liquidity,
        "legal": legal,
        "guidance": guidance,
        "ownership": ownership,
        "risk_language": risk_language,
    }


def build_disclosure_status(score: float | None, signals: dict, risk: str, action: str) -> str:
    risk_lower = str(risk or "").lower()
    action_lower = str(action or "").lower()

    if signals["dilution"] or signals["liquidity"] or signals["legal"]:
        return "Disclosure risk detected"

    if signals["guidance"] and score is not None and score >= 75 and "high" not in risk_lower:
        return "Thesis-supportive disclosure"

    if signals["ownership"]:
        return "Ownership / insider disclosure watch"

    if any(term in action_lower for term in ["avoid", "reduce", "caution"]):
        return "Cautious disclosure setup"

    if score is not None and score >= 80:
        return "No obvious filing conflict detected"

    return "Disclosure read developing"


def build_filing_risk(signals: dict, risk: str, filing_type: str) -> str:
    risk_lower = str(risk or "").lower()
    filing_upper = str(filing_type or "").upper()

    if signals["liquidity"] or signals["legal"]:
        return "High"

    if signals["dilution"]:
        return "Elevated"

    if any(term in risk_lower for term in ["high", "speculative", "elevated", "volatile"]):
        return "Elevated"

    if filing_upper in {"S-1", "S-3", "S-4", "144"}:
        return "Elevated"

    if signals["risk_language"]:
        return "Medium-high"

    return "Medium"


def build_thesis_effect(score: float | None, disclosure_status: str, filing_risk: str, signals: dict) -> str:
    if disclosure_status == "Thesis-supportive disclosure":
        return "Supports thesis"

    if disclosure_status == "Disclosure risk detected":
        return "Weakens or complicates thesis"

    if filing_risk in {"High", "Elevated"}:
        return "Raises validation burden"

    if signals["ownership"]:
        return "Adds ownership context"

    if score is not None and score >= 80:
        return "No major filing conflict"

    return "Neutral / developing"


def build_portfolio_impact(
    score: float | None,
    filing_risk: str,
    thesis_effect: str,
    portfolio_fit: str,
    risk: str,
) -> str:
    risk_lower = str(risk or "").lower()

    if filing_risk == "High":
        return "Reduce conviction / avoid adding"

    if filing_risk == "Elevated":
        return "Smaller sizing / wait for clarity"

    if thesis_effect == "Supports thesis" and score is not None and score >= 80 and "high" not in risk_lower:
        return "Can support portfolio conviction"

    if thesis_effect == "Raises validation burden":
        return "Keep on watch but require confirmation"

    if "core" in str(portfolio_fit or "").lower() and filing_risk in {"Medium", "Medium-high"}:
        return "Hold as monitored core candidate"

    return "Watchlist impact only"


def describe_hits(label: str, hits: list[str]) -> str:
    if not hits:
        return ""

    shown = ", ".join(dict.fromkeys(hits[:4]))

    return f"{label}: {shown}."


def build_signal_findings(signals: dict) -> list[str]:
    findings = [
        describe_hits("Dilution / issuance signals", signals["dilution"]),
        describe_hits("Liquidity / debt signals", signals["liquidity"]),
        describe_hits("Legal / regulatory signals", signals["legal"]),
        describe_hits("Guidance / demand signals", signals["guidance"]),
        describe_hits("Ownership / insider signals", signals["ownership"]),
        describe_hits("Risk language", signals["risk_language"]),
    ]

    findings = [item for item in findings if item]

    if not findings:
        findings.append("No obvious high-risk filing keywords detected in the available context.")

    return findings[:6]


def build_filing_read(
    symbol: str,
    filing_type: str,
    disclosure_status: str,
    filing_risk: str,
    thesis_effect: str,
    portfolio_impact: str,
) -> str:
    if disclosure_status == "Thesis-supportive disclosure":
        return (
            f"{symbol} has filing context that appears supportive of the thesis. "
            "The portfolio implication is constructive only if price, volume, and risk also confirm."
        )

    if disclosure_status == "Disclosure risk detected":
        return (
            f"{symbol} has filing/disclosure risk that can weaken conviction. "
            "The portfolio response should be smaller sizing, patience, or no add until clarified."
        )

    if filing_risk in {"High", "Elevated"}:
        return (
            f"{symbol} has elevated filing risk. "
            "This raises the validation burden before the name deserves portfolio capital."
        )

    if thesis_effect == "No major filing conflict":
        return (
            f"{symbol} has no obvious filing conflict in the available context. "
            "That does not make it a buy; it simply removes one disclosure-level objection."
        )

    return (
        f"{symbol} has a developing filing read. "
        f"Current portfolio impact: {portfolio_impact}."
    )


def build_portfolio_read(
    score: float | None,
    filing_risk: str,
    thesis_effect: str,
    portfolio_impact: str,
    category: str,
    fit: str,
) -> list[str]:
    notes = [
        f"Portfolio impact: {portfolio_impact}.",
        f"Thesis effect: {thesis_effect}.",
        f"Filing risk: {filing_risk}.",
    ]

    if score is not None:
        if score >= 85:
            notes.append(
                "High score means filing risk matters more, not less, because the name may already be a priority candidate."
            )
        elif score >= 75:
            notes.append(
                "Constructive score needs filing confirmation before increasing conviction."
            )
        else:
            notes.append(
                "Lower score means filings should be treated as watchlist context, not an action trigger."
            )

    category_lower = str(category or "").lower()

    if any(
        term in category_lower
        for term in ["ai", "chip", "semiconductor", "technology", "growth"]
    ):
        notes.append(
            "For AI/growth exposure, filings should confirm demand, margins, backlog, capex efficiency, or customer quality."
        )

    if any(
        term in category_lower
        for term in ["defense", "warfare", "aerospace", "military", "munition"]
    ):
        notes.append(
            "For defense exposure, filings should confirm funded contracts, backlog, budget visibility, or scalable production."
        )

    if fit:
        notes.append(f"Portfolio fit overlay: {fit}.")

    return notes[:6]

def build_confirming_signals(category: str) -> list[str]:
    category_lower = str(category or "").lower()

    signals = [
        "10-Q / 10-K language confirms revenue quality, margin stability, cash flow, or demand.",
        "8-K confirms a real contract, guidance update, strategic transaction, or operational milestone.",
        "Risk factors do not materially worsen versus the prior read.",
    ]

    if any(term in category_lower for term in ["ai", "chip", "semiconductor", "technology", "growth"]):
        signals.append("AI/growth filings confirm backlog, demand durability, margin leverage, or customer expansion.")

    if any(term in category_lower for term in ["defense", "warfare", "aerospace", "military", "munition"]):
        signals.append("Defense filings confirm funded demand, contract awards, backlog growth, or production scale.")

    return signals[:5]


def build_breaking_signals(category: str) -> list[str]:
    category_lower = str(category or "").lower()

    signals = [
        "New dilution, shelf registration, convertible debt, or equity issuance risk.",
        "Going-concern, liquidity, covenant, restatement, material weakness, or investigation language.",
        "Guidance or risk-factor language gets worse while the stock still screens well.",
    ]

    if any(term in category_lower for term in ["ai", "chip", "semiconductor", "technology", "growth"]):
        signals.append("AI/growth filing language points to margin pressure, customer concentration, slowing demand, or capex strain.")

    if any(term in category_lower for term in ["defense", "warfare", "aerospace", "military", "munition"]):
        signals.append("Defense filings show headlines are not translating into funded backlog or revenue.")

    return signals[:5]


def build_filing_action(
    symbol: str,
    score: float | None,
    filing_risk: str,
    portfolio_impact: str,
    action: str,
) -> str:
    if filing_risk == "High":
        return "Do not add based on this filing context. Resolve disclosure risk first."

    if filing_risk == "Elevated":
        return f"Keep sizing smaller and validate with /risk {symbol}, /volume {symbol}, and /earnings {symbol}."

    if portfolio_impact == "Can support portfolio conviction" and score is not None and score >= 80:
        return f"Filing context supports the thesis. Confirm with /volume {symbol} before increasing conviction."

    if score is not None and score >= 75:
        return f"Constructive but not decisive. Use /scorecard {symbol} and monitor future filings."

    return f"Watchlist-only. Current action bias: {action or 'Watch'}."


def build_related_commands(symbol: str) -> str:
    return f"""
/stock {symbol}
/scorecard {symbol}
/risk {symbol}
/volume {symbol}
/earnings {symbol}
/analyst {symbol}
/top10
""".strip()


def build_filing_intelligence_report(symbol: str, mode: str = "filing") -> str:
    symbol = clean_symbol(symbol)

    if not symbol:
        return "Usage: /filing SYMBOL"

    try:
        raw_scores = get_stock_scores()
    except Exception:
        raw_scores = []

    scores = normalize_score_items(raw_scores)
    score_data = find_score_data(symbol, scores)
    score = get_score_value(score_data)

    try:
        label = get_smart_money_label(score_data)
    except Exception:
        label = "Signal developing"

    try:
        signal = get_signal_strength(score_data)
    except Exception:
        signal = label

    try:
        risk = get_risk_label(score_data)
    except Exception:
        risk = "Unknown"

    try:
        action = get_action_label(score_data)
    except Exception:
        action = "Watch"

    try:
        category = get_category(score_data)
    except Exception:
        category = "Uncategorized"

    try:
        fit = get_portfolio_fit(score_data)
    except Exception:
        fit = "Unknown"

    try:
        volume_label = get_volume_label(score_data)
    except Exception:
        volume_label = "Volume confirmation unavailable"

    filing_context = extract_filing_context(score_data)
    filing_type = extract_filing_type(score_data, filing_context)
    filing_date = extract_filing_date(score_data, filing_context)
    signals = analyze_filing_signals(filing_context, filing_type)

    disclosure_status = build_disclosure_status(
        score=score,
        signals=signals,
        risk=risk,
        action=action,
    )

    filing_risk = build_filing_risk(
        signals=signals,
        risk=risk,
        filing_type=filing_type,
    )

    thesis_effect = build_thesis_effect(
        score=score,
        disclosure_status=disclosure_status,
        filing_risk=filing_risk,
        signals=signals,
    )

    portfolio_impact = build_portfolio_impact(
        score=score,
        filing_risk=filing_risk,
        thesis_effect=thesis_effect,
        portfolio_fit=fit,
        risk=risk,
    )

    try:
        ranked_item = rank_candidates([score_data], limit=1)[0]
        bucket = classify_action_bucket(ranked_item)
    except Exception:
        bucket = "Watch for Confirmation"

    record = build_filing_record(
        symbol=symbol,
        score=score,
        filing_type=filing_type,
        filing_date=filing_date,
        disclosure_status=disclosure_status,
        filing_risk=filing_risk,
        portfolio_impact=portfolio_impact,
        thesis_effect=thesis_effect,
        action=action,
        risk=risk,
        signal=signal,
        category=category,
    )

    evolution = record_filing_read(symbol, record)

    evolution_notes = build_filing_evolution_notes(
        evolution.get("previous"),
        evolution.get("current"),
    )

    portfolio_notes = build_portfolio_read(
        score=score,
        filing_risk=filing_risk,
        thesis_effect=thesis_effect,
        portfolio_impact=portfolio_impact,
        category=category,
        fit=fit,
    )

    title = "SEC / Filing Intelligence" if mode != "sec" else "SEC Disclosure Intelligence"

    return f"""
📄 {symbol} {title}

Headline
Disclosure Status: {disclosure_status}
Filing Risk: {filing_risk}
Portfolio Impact: {portfolio_impact}
Thesis Effect: {thesis_effect}
Filing Type: {filing_type}
Filing Date: {filing_date}
Score: {format_score(score)}
Signal: {label}
Conviction: {signal}
Risk: {risk}
Action: {action}
Bucket: {bucket}
Category: {category}

Filing Context
{filing_context}

Filing Read
{build_filing_read(symbol, filing_type, disclosure_status, filing_risk, thesis_effect, portfolio_impact)}

Disclosure Signals
{bullet_lines(build_signal_findings(signals))}

Portfolio Impact
{bullet_lines(portfolio_notes)}

What Changed
{bullet_lines(evolution_notes)}

Evolving Analysis
{build_filing_memory_summary(symbol)}

What Would Confirm The Filing Read
{bullet_lines(build_confirming_signals(category))}

What Would Break The Filing Read
{bullet_lines(build_breaking_signals(category))}

Filing Action
{build_filing_action(symbol, score, filing_risk, portfolio_impact, action)}

Related Commands:
{build_related_commands(symbol)}

Research only. Not financial advice.
""".strip()