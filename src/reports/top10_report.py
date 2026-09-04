from collections import Counter
from typing import Any

from src.reports.top10_tradeplan_bridge import build_top10_tradeplan_snapshot_section
from src.intelligence.top10_evolution import (
    build_top10_change_summary,
    format_change_summary,
    record_top10_ranking,
    safe_float,
)
from src.utils.score_display import (
    get_action_label,
    get_category,
    get_risk_label,
    get_signal_strength,
    get_smart_money_label,
    get_ticker,
)


def normalize_stock_items(stocks: Any) -> list[dict]:
    if isinstance(stocks, list):
        return [item for item in stocks if isinstance(item, dict)]

    if isinstance(stocks, dict):
        if "scores" in stocks and isinstance(stocks["scores"], list):
            return [item for item in stocks["scores"] if isinstance(item, dict)]

        items = []

        for key, value in stocks.items():
            if isinstance(value, dict):
                copy = dict(value)
                copy.setdefault("ticker", key)
                copy.setdefault("symbol", key)
                items.append(copy)

        return items

    return []


def get_score_value(stock: dict) -> float:
    for key in [
        "score",
        "total_score",
        "smart_money_score",
        "overall_score",
        "final_score",
        "composite_score",
    ]:
        value = safe_float(stock.get(key))

        if value is not None:
            return value

    return 0.0


def normalize_symbol(stock: dict) -> str:
    symbol = get_ticker(stock) or stock.get("symbol") or stock.get("ticker")
    return str(symbol or "UNKNOWN").upper().replace("$", "").strip()


def conviction_label(score: float, signal: str, risk: str) -> str:
    risk_lower = str(risk or "").lower()

    if score >= 85 and "high" not in risk_lower:
        return "High Conviction"

    if score >= 80:
        return "Strong Watch"

    if score >= 70:
        return "Constructive Watch"

    return "Developing"


def compact_text(value: str, max_chars: int = 90) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def build_why_line(symbol: str, score: float, label: str, category: str, signal: str) -> str:
    category_clean = str(category or "").strip()

    if category_clean and category_clean.lower() not in {
        "unknown",
        "none",
        "n/a",
        "uncategorized",
    }:
        return compact_text(f"{category_clean} setup; {label}; {signal}.", 95)

    return compact_text(f"{label}; {signal}; score {score:.0f}/100.", 95)


def build_watch_line(risk: str, action: str) -> str:
    risk_clean = str(risk or "Unknown").strip()
    action_clean = str(action or "Watch").strip()

    return compact_text(f"Risk: {risk_clean}. Action: {action_clean}.", 95)


def build_action_line(score: float, risk: str, action: str) -> str:
    risk_lower = str(risk or "").lower()
    action_clean = str(action or "").strip()

    if score >= 85 and "high" not in risk_lower:
        return "Favor pullbacks or confirmation."

    if score >= 75:
        return "Watch for volume/catalyst confirmation."

    if "high" in risk_lower:
        return "Use caution; risk is elevated."

    return action_clean or "Keep on watch."


def enrich_stock(stock: dict) -> dict:
    score = get_score_value(stock)
    symbol = normalize_symbol(stock)

    try:
        label = get_smart_money_label(stock)
    except Exception:
        label = "Signal developing"

    try:
        signal = get_signal_strength(stock)
    except Exception:
        signal = label

    try:
        risk = get_risk_label(stock)
    except Exception:
        risk = "Unknown"

    try:
        action = get_action_label(stock)
    except Exception:
        action = "Watch"

    try:
        category = get_category(stock)
    except Exception:
        category = "Uncategorized"

    return {
        "symbol": symbol,
        "score": score,
        "label": label,
        "signal": signal,
        "risk": risk,
        "action": action,
        "category": category,
        "conviction": conviction_label(score, signal, risk),
    }


def rank_candidates(stocks: list[dict], limit: int = 20) -> list[dict]:
    enriched = [enrich_stock(stock) for stock in stocks]

    enriched.sort(
        key=lambda item: (
            item["score"],
            1 if "high" not in str(item["risk"]).lower() else 0,
            item["symbol"],
        ),
        reverse=True,
    )

    return enriched[:limit]


def is_high_risk(item: dict) -> bool:
    risk = str(item.get("risk") or "").lower()

    return any(
        phrase in risk
        for phrase in [
            "high",
            "elevated",
            "aggressive",
            "speculative",
            "volatile",
        ]
    )


def clean_category(category: str) -> str:
    value = str(category or "").strip()

    if not value:
        return ""

    if value.lower() in {"unknown", "none", "n/a", "uncategorized"}:
        return ""

    return value


def build_top20_summary(ranked: list[dict]) -> str:
    if not ranked:
        return "No ranked ideas available."

    conviction_counts = Counter(item.get("conviction") or "Developing" for item in ranked)
    categories = [clean_category(item.get("category")) for item in ranked]
    categories = [category for category in categories if category]
    category_counts = Counter(categories)

    high_conviction = conviction_counts.get("High Conviction", 0)
    strong_watch = conviction_counts.get("Strong Watch", 0)
    constructive = conviction_counts.get("Constructive Watch", 0)

    top_idea = ranked[0]
    top_symbol = top_idea.get("symbol", "UNKNOWN")
    top_score = top_idea.get("score", 0)

    highest_risk = [item["symbol"] for item in ranked if is_high_risk(item)]
    highest_risk_text = ", ".join(highest_risk[:4]) if highest_risk else "None flagged"

    most_common_theme = "Mixed"
    if category_counts:
        most_common_theme = category_counts.most_common(1)[0][0]

    if high_conviction:
        best_action = "Review the top 3 with /stock and wait for confirmation."
    elif strong_watch:
        best_action = "Track the strongest watches for volume or catalyst confirmation."
    else:
        best_action = "Use this as a watchlist, not an action list."

    return f"""
Top 20 Summary
• Top idea: {top_symbol} — {top_score:.0f}/100
• High Conviction: {high_conviction}
• Strong Watch: {strong_watch}
• Constructive Watch: {constructive}
• Most common theme: {most_common_theme}
• Highest risk names: {highest_risk_text}
• Best next action: {best_action}
""".strip()

def classify_action_bucket(item: dict) -> str:
    score = item.get("score") or 0
    risk = str(item.get("risk") or "").lower()
    action = str(item.get("action") or "").lower()
    conviction = str(item.get("conviction") or "").lower()

    weak_action_terms = [
        "avoid",
        "sell",
        "reduce",
        "weak",
        "caution",
        "no action",
    ]

    high_risk_terms = [
        "high",
        "elevated",
        "aggressive",
        "speculative",
        "volatile",
    ]

    if any(term in action for term in weak_action_terms) and score < 75:
        return "Weak / Avoid"

    if any(term in risk for term in high_risk_terms):
        return "High Risk / Wait"

    if score >= 85 or "high conviction" in conviction:
        return "Best Setup / Pullback Candidates"

    if score >= 75 or "strong watch" in conviction:
        return "Watch for Confirmation"

    return "Developing / Watchlist Only"


def build_action_buckets(ranked: list[dict]) -> str:
    bucket_order = [
        "Best Setup / Pullback Candidates",
        "Watch for Confirmation",
        "High Risk / Wait",
        "Developing / Watchlist Only",
        "Weak / Avoid",
    ]

    buckets = {bucket: [] for bucket in bucket_order}

    for item in ranked:
        bucket = classify_action_bucket(item)
        symbol = item.get("symbol")

        if symbol:
            buckets.setdefault(bucket, []).append(symbol)

    lines = ["Action Buckets"]

    for bucket in bucket_order:
        symbols = buckets.get(bucket) or []

        if not symbols:
            continue

        symbol_text = ", ".join(symbols[:8])

        if len(symbols) > 8:
            symbol_text += f", +{len(symbols) - 8} more"

        lines.append(f"{bucket}:\n• {symbol_text}")

    if len(lines) == 1:
        return "Action Buckets\n• No clear action buckets available."

    return "\n\n".join(lines)

def format_candidate(index: int, item: dict) -> str:
    symbol = item["symbol"]
    score = item["score"]
    label = item["label"]
    signal = item["signal"]
    risk = item["risk"]
    action = item["action"]
    category = item["category"]

    return f"""
{index}. {symbol} — {item["conviction"]} | {score:.0f}/100
Why: {build_why_line(symbol, score, label, category, signal)}
Watch: {build_watch_line(risk, action)}
Action: {build_action_line(score, risk, action)}
""".strip()


def trim_change_text(change_text: str, max_chars: int = 850) -> str:
    text = str(change_text or "").strip()

    if len(text) <= max_chars:
        return text

    lines = []
    total = 0

    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        if total + len(line) + 1 > max_chars:
            break

        lines.append(line)
        total += len(line) + 1

    if not lines:
        return compact_text(text, max_chars)

    return "\n".join(lines)


def build_top10_report(stocks, limit: int = 20, record_memory: bool = True) -> str:
    items = normalize_stock_items(stocks)
    tradeplan_snapshot = build_top10_tradeplan_snapshot_section(limit=5)
    if not items:
        return """
Top 20 Smart Money Ideas

Status: No scoring data available right now.

Use:
/brief
/snapshot
/stock SYMBOL
""".strip()

    ranked = rank_candidates(items, limit=limit)
    summary = build_top20_summary(ranked)
    action_buckets = build_action_buckets(ranked)

    if record_memory:
        evolution = record_top10_ranking(ranked, limit=limit)
        changes = build_top10_change_summary(
            evolution.get("previous"),
            evolution.get("current"),
        )
        change_text = trim_change_text(format_change_summary(changes))
    else:
        change_text = "Ranking memory disabled for this run."

    body = "\n\n".join(
        format_candidate(index, item)
        for index, item in enumerate(ranked, start=1)
    )

    return f"""
🏆 Top {limit} Smart Money Ideas

{summary}

{action_buckets}

Ranking Changes
{change_text}

Ideas
{body}


Use:
/snapshot
/brief
/stock SYMBOL
/scorecard SYMBOL

{tradeplan_snapshot}

Research only. Not financial advice.
""".strip()