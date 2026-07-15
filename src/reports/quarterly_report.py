from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.scoring.scoring_engine import get_stock_scores
from src.utils.score_display import (
    get_action_label,
    get_category,
    get_portfolio_fit,
    get_risk_label,
    get_signal_strength,
    get_smart_money_label,
    get_ticker,
)
from src.utils.watchlist_store import load_watchlist


REPORT_TIMEZONE = "America/Lima"
MAX_TOP_NAMES = 5


def clean_text(value: Any, max_length: int = 260) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default

        return float(value)
    except Exception:
        return default


def get_value(data: dict, keys: list[str], default=None):
    for key in keys:
        value = data.get(key)

        if value is not None:
            return value

    return default


def normalize_score_item(item: Any) -> dict:
    if isinstance(item, dict):
        ticker = str(
            get_value(item, ["ticker", "symbol", "name"], "UNKNOWN")
        ).upper().replace("$", "")

        score = get_value(
            item,
            ["final_score", "score", "smart_money_score", "total_score", "rating_score"],
            None,
        )

        normalized = dict(item)

        normalized.update(
            {
                "ticker": ticker,
                "symbol": ticker,
                "score": safe_float(score),
            }
        )

        return normalized

    return {
        "ticker": str(item or "UNKNOWN").upper().replace("$", ""),
        "symbol": str(item or "UNKNOWN").upper().replace("$", ""),
        "score": None,
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


def get_completed_quarter_label(now: datetime | None = None) -> str:
    now = now or datetime.now(ZoneInfo(REPORT_TIMEZONE))
    month = now.month
    year = now.year

    current_quarter = ((month - 1) // 3) + 1
    completed_quarter = current_quarter - 1

    if completed_quarter == 0:
        completed_quarter = 4
        year -= 1

    return f"Q{completed_quarter} {year}"


def load_headline_theme_cache() -> dict:
    try:
        from src.reports.morning_brief_intro import load_morning_brief_cache

        payload = load_morning_brief_cache()

        if isinstance(payload, dict):
            return payload

    except Exception:
        pass

    return {}


def get_cached_theme_names(payload: dict) -> list[str]:
    theme_summary = payload.get("theme_summary") or {}
    ranked = theme_summary.get("ranked_themes") or []

    themes = []

    for item in ranked:
        if isinstance(item, dict):
            theme = item.get("theme")
        elif isinstance(item, (list, tuple)) and item:
            theme = item[0]
        else:
            theme = None

        if theme and theme not in themes:
            themes.append(theme)

    return themes[:6]


def build_quarter_opening(quarter_label: str, themes: list[str]) -> str:
    theme_text = ", ".join(themes[:4]) if themes else "AI, earnings, inflation, rates, and portfolio quality"

    return f"""
We are pleased to deliver your {quarter_label} Smart Money AI Market Review and Outlook.

The quarter was defined by {theme_text}. The market continued to reward companies with durable earnings power, strong balance sheets, and exposure to long-term capital spending themes. At the same time, leadership remained selective, which means portfolio construction mattered as much as stock selection.
""".strip()


def build_theme_review(themes: list[str]) -> str:
    if not themes:
        return """
The main market themes were earnings quality, inflation, interest rates, AI leadership, credit conditions, and market breadth. The key takeaway is that investors continued to favor companies with visible growth, resilient margins, and strong balance sheets.
""".strip()

    lines = []

    for theme in themes[:6]:
        if theme == "AI / Chips":
            lines.append(
                "• AI / Chips: AI remained the dominant growth theme, but investors became more selective around valuation, margins, and semiconductor supply-chain confirmation."
            )
        elif theme == "AI Infrastructure / Power":
            lines.append(
                "• AI Infrastructure / Power: The AI buildout expanded beyond chips into power, grid capacity, cooling, data centers, and capital spending."
            )
        elif theme == "Inflation / Fed":
            lines.append(
                "• Inflation / Fed: Inflation and rate expectations continued to drive discount rates, growth-stock appetite, and bond-market volatility."
            )
        elif theme == "Earnings Season":
            lines.append(
                "• Earnings Season: Earnings quality, guidance, and margin durability became the main test for market leadership."
            )
        elif theme == "Banks / Credit":
            lines.append(
                "• Banks / Credit: Bank results and credit indicators helped investors judge whether consumer and loan stress remained contained."
            )
        elif theme == "Consumer Stress":
            lines.append(
                "• Consumer Stress: Household pressure, credit cards, groceries, and retail pricing remained important signals for the broader economy."
            )
        elif theme == "Oil / Geopolitical Risk":
            lines.append(
                "• Oil / Geopolitical Risk: Energy and geopolitical headlines created inflation risk but also supported defense and security-related themes."
            )
        elif theme == "Market Breadth / Rotation":
            lines.append(
                "• Market Breadth / Rotation: Investors watched whether leadership could broaden beyond crowded mega-cap and AI winners."
            )
        else:
            lines.append(f"• {theme}: This theme influenced market tone and portfolio positioning.")

    return "\n".join(lines)


def build_watchlist_review(scores: list[dict]) -> str:
    if not scores:
        return "Watchlist scoring was unavailable for this review."

    top = scores[:MAX_TOP_NAMES]

    lines = []

    for item in top:
        ticker = get_ticker(item)
        label = get_smart_money_label(item)
        signal = get_signal_strength(item)
        fit = get_portfolio_fit(item)
        action = get_action_label(item)
        risk = get_risk_label(item)
        category = get_category(item)

        lines.append(
            f"• {ticker}: {label} | Signal: {signal} | Fit: {fit} | Action: {action} | Risk: {risk} | Theme: {category}"
        )

    return "\n".join(lines)


def build_portfolio_attribution(scores: list[dict], themes: list[str]) -> str:
    helped = []
    hurt = []

    if any(theme in themes for theme in ["AI / Chips", "AI Infrastructure / Power"]):
        helped.append("AI infrastructure exposure remained a key long-term opportunity.")
        hurt.append("Crowded AI and semiconductor names required patience around pullbacks and valuation resets.")

    if "Banks / Credit" in themes or "Consumer Stress" in themes:
        helped.append("Quality balance sheets and disciplined sizing helped reduce credit-cycle risk.")
        hurt.append("Consumer and credit stress created risk for lower-quality cyclicals.")

    if "Inflation / Fed" in themes:
        helped.append("Diversification across growth, defense, income, and quality helped manage rate volatility.")
        hurt.append("Higher-rate concerns pressured long-duration growth and speculative names.")

    if not helped:
        helped.append("Diversification across themes helped reduce dependence on a single market driver.")

    if not hurt:
        hurt.append("The main drag was market selectivity, with leadership concentrated in fewer high-conviction names.")

    return f"""
What helped:
{chr(10).join("• " + item for item in helped[:4])}

What hurt or needed caution:
{chr(10).join("• " + item for item in hurt[:4])}
""".strip()


def build_smart_money_signals(scores: list[dict]) -> str:
    if not scores:
        return "Smart Money signal data was unavailable."

    labels = {}

    for item in scores:
        label = get_smart_money_label(item)
        labels[label] = labels.get(label, 0) + 1

    label_lines = [
        f"• {label}: {count}"
        for label, count in sorted(labels.items(), key=lambda item: item[1], reverse=True)
    ]

    top_names = ", ".join(get_ticker(item) for item in scores[:5])

    return f"""
Signal count:
{chr(10).join(label_lines[:6])}

Highest-priority watchlist names:
{top_names if top_names else "N/A"}

Interpretation:
The Smart Money layer should be used to separate durable setups from short-term noise. High-conviction names still need confirmation from price action, volume, earnings quality, and risk level.
""".strip()


def build_outlook(themes: list[str]) -> str:
    outlook_items = []

    if "AI / Chips" in themes or "AI Infrastructure / Power" in themes:
        outlook_items.append(
            "AI remains the main structural theme, but the next phase should favor companies that can convert spending into revenue, margin durability, and cash flow."
        )

    if "Inflation / Fed" in themes:
        outlook_items.append(
            "The rate outlook remains important. Softer inflation would support risk appetite, while sticky inflation could pressure growth and speculative names."
        )

    if "Banks / Credit" in themes or "Consumer Stress" in themes:
        outlook_items.append(
            "Credit quality and consumer stress should be monitored closely because they can determine whether the economy slows gradually or more abruptly."
        )

    if "Market Breadth / Rotation" in themes:
        outlook_items.append(
            "Broader participation would improve the setup for small caps, cyclicals, and non-mega-cap opportunities."
        )

    if not outlook_items:
        outlook_items.append(
            "The preferred setup is selective risk-taking: stay invested, avoid chasing extended names, and use pullbacks to upgrade quality."
        )

    return "\n".join(f"• {item}" for item in outlook_items[:5])


def build_action_plan(scores: list[dict]) -> str:
    top = scores[:3]

    actions = [
        "Use /report for the current daily portfolio read.",
        "Use /weeklycalendar for macro and earnings events.",
        "Use /global and /headlines for live market context.",
    ]

    for item in top:
        ticker = get_ticker(item)
        actions.append(f"Run /scorecard {ticker} before adding or trimming exposure.")

    return "\n".join(f"• {item}" for item in actions[:6])


def build_quarterly_market_review(quarter_label: str | None = None) -> str:
    now = datetime.now(ZoneInfo(REPORT_TIMEZONE))
    today = now.strftime("%B %d, %Y")
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    quarter_label = clean_text(quarter_label or get_completed_quarter_label(now), 40)

    try:
        raw_scores = get_stock_scores()
        scoring_error = ""
    except Exception as error:
        raw_scores = []
        scoring_error = type(error).__name__

    scores = normalize_scores(raw_scores)

    try:
        watchlist_symbols = load_watchlist()
    except Exception:
        watchlist_symbols = []

    theme_payload = load_headline_theme_cache()
    themes = get_cached_theme_names(theme_payload)

    opening = build_quarter_opening(quarter_label, themes)

    scoring_note = ""

    if scoring_error:
        scoring_note = f"\n\nScoring note: scoring engine unavailable during this review ({scoring_error})."

    return f"""
📘 Smart Money AI Quarterly Review
Market Review and Outlook
Quarter: {quarter_label}
Date: {today}
Generated: {timestamp} {REPORT_TIMEZONE}

{opening}

Executive Summary
• Market leadership remained selective, with investors focused on earnings quality, AI infrastructure, rates, credit conditions, and portfolio durability.
• Watchlist count: {len(watchlist_symbols)} symbols.
• Top Smart Money candidates should be reviewed with scorecards before action.
• The preferred approach is selective exposure, disciplined sizing, and using volatility to upgrade quality.

Main Market Themes
{build_theme_review(themes)}

Portfolio Attribution
{build_portfolio_attribution(scores, themes)}

Watchlist Review
{build_watchlist_review(scores)}

Smart Money Signals
{build_smart_money_signals(scores)}

Outlook
{build_outlook(themes)}

Action Plan
{build_action_plan(scores)}

Next Commands
/report
/weeklycalendar
/global
/headlines
/top10
/scorecard SYMBOL

Notes
This quarterly review is informational only and is not financial advice.{scoring_note}
""".strip()