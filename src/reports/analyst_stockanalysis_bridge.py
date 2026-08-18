import re
from typing import Any

from src.intelligence.stockanalysis_source import clean_symbol, fetch_stockanalysis_data


def safe_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value or "").replace(",", "").strip()
        match = re.search(r"-?\d+", text)

        if not match:
            return default

        return int(match.group(0))

    except Exception:
        return default


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default

        text = str(value).replace("%", "").replace("$", "").replace(",", "").strip()
        match = re.search(r"-?\d+(?:\.\d+)?", text)

        if not match:
            return default

        return float(match.group(0))

    except Exception:
        return default


def extract_internal_field(report: str, field: str) -> str:
    pattern = rf"^{re.escape(field)}:\s*(.+)$"

    for line in str(report or "").splitlines():
        match = re.search(pattern, line.strip(), flags=re.I)

        if match:
            return match.group(1).strip()

    return ""


def extract_internal_score(report: str) -> float | None:
    score_text = extract_internal_field(report, "Score")

    if score_text:
        return safe_float(score_text)

    for line in str(report or "").splitlines():
        if "score" in line.lower():
            value = safe_float(line)

            if value is not None:
                return value

    return None


def consensus_bucket(metrics: dict) -> str:
    consensus = str(metrics.get("analyst_consensus") or "").lower()

    strong_buy = safe_int(metrics.get("strong_buy_count"))
    buy = safe_int(metrics.get("buy_count"))
    hold = safe_int(metrics.get("hold_count"))
    sell = safe_int(metrics.get("sell_count"))
    strong_sell = safe_int(metrics.get("strong_sell_count"))

    bullish = strong_buy + buy
    bearish = sell + strong_sell

    if "strong buy" in consensus:
        return "Strong Buy"

    if consensus == "buy" or " buy" in consensus:
        return "Buy"

    if "hold" in consensus:
        return "Hold"

    if "strong sell" in consensus:
        return "Strong Sell"

    if "sell" in consensus:
        return "Sell"

    if bullish > max(hold + bearish, 0):
        return "Buy"

    if hold >= bullish and hold >= bearish and hold > 0:
        return "Hold"

    if bearish > bullish:
        return "Sell"

    return "Unavailable"


def external_read(metrics: dict) -> str:
    bucket = consensus_bucket(metrics)
    upside = safe_float(metrics.get("price_target_upside"))

    if bucket in {"Strong Buy", "Buy"} and upside is not None and upside < 0:
        return "• Analysts rate it bullish, but the price target implies downside. Treat as mixed."

    if bucket == "Strong Buy":
        return "• External analyst consensus is strongly bullish. Confirm with valuation, volume, filings, and macro risk."

    if bucket == "Buy":
        return "• External analyst consensus leans bullish. Useful support, but not a standalone buy signal."

    if bucket == "Hold":
        return "• External analyst consensus is neutral. Require stronger Smart Money confirmation."

    if bucket in {"Sell", "Strong Sell"}:
        return "• External analyst consensus is bearish. Treat as a risk flag."

    return "• External analyst consensus is unavailable or mixed."


def conflict_check(metrics: dict, internal_report: str = "") -> str:
    bucket = consensus_bucket(metrics).lower()

    internal_action = extract_internal_field(internal_report, "Action")
    internal_risk = extract_internal_field(internal_report, "Risk")
    internal_signal = extract_internal_field(internal_report, "Signal")
    internal_score = extract_internal_score(internal_report)

    action_lower = internal_action.lower()
    risk_lower = internal_risk.lower()
    signal_lower = internal_signal.lower()

    bullish_external = bucket in {"strong buy", "buy"}
    bearish_external = bucket in {"sell", "strong sell"}

    cautious_internal = any(
        term in " ".join([action_lower, risk_lower, signal_lower])
        for term in ["watch", "avoid", "caution", "high", "elevated", "weak", "speculative"]
    )

    bullish_internal = any(
        term in " ".join([action_lower, signal_lower])
        for term in ["buy", "accumulate", "strong", "high conviction"]
    )

    if bullish_external and cautious_internal:
        return "• Conflict: analysts are bullish, but the internal Smart Money read is cautious. Validate risk, volume, and filings before acting."

    if bearish_external and bullish_internal:
        return "• Conflict: analysts are bearish, but internal Smart Money signals look stronger. Check why Wall Street disagrees."

    if bullish_external and internal_score is not None and internal_score < 65:
        return "• Conflict: analyst consensus is bullish, but internal score is below confirmation range."

    if bullish_external and any(term in risk_lower for term in ["high", "elevated", "speculative"]):
        return "• Caution: bullish analyst read is offset by elevated internal risk."

    if bullish_external and bullish_internal:
        return "• Alignment: analyst consensus and internal Smart Money read both lean constructive."

    if bucket == "hold":
        return "• Neutral overlay: analysts are not giving strong confirmation. Internal signals should drive the decision."

    if bearish_external:
        return "• Risk overlay: analyst consensus is negative. Require unusually strong internal confirmation."

    return "• Cross-check: compare this external consensus against the internal analyst read above."


def build_stockanalysis_vote_mix(metrics: dict) -> str:
    strong_buy = metrics.get("strong_buy_count", "")
    buy = metrics.get("buy_count", "")
    hold = metrics.get("hold_count", "")
    sell = metrics.get("sell_count", "")
    strong_sell = metrics.get("strong_sell_count", "")
    total = metrics.get("analyst_total", "")

    return "\n".join(
        [
            f"• Strong Buy: {strong_buy or 'N/A'}",
            f"• Buy: {buy or 'N/A'}",
            f"• Hold: {hold or 'N/A'}",
            f"• Sell: {sell or 'N/A'}",
            f"• Strong Sell: {strong_sell or 'N/A'}",
            f"• Total Analysts: {total or 'N/A'}",
        ]
    )


def build_stockanalysis_analyst_overlay(
    symbol: str,
    internal_report: str = "",
    force_refresh: bool = False,
) -> str:
    symbol = clean_symbol(symbol)

    if not symbol:
        return (
            "StockAnalysis Analyst Overlay\n"
            "Status: unavailable\n"
            "• Missing symbol."
        )

    try:
        data = fetch_stockanalysis_data(symbol, force_refresh=force_refresh)
    except Exception as error:
        return (
            f"StockAnalysis Analyst Overlay: {symbol}\n"
            "Status: unavailable\n"
            f"• Error: {type(error).__name__}: {error}"
        )

    metrics = data.get("metrics", {}) if isinstance(data, dict) else {}

    if not isinstance(metrics, dict):
        metrics = {}

    consensus = metrics.get("analyst_consensus", "")
    price_target = metrics.get("price_target", "")
    upside = metrics.get("price_target_upside", "")

    return f"""
StockAnalysis Analyst Overlay: {symbol}
Source: {data.get("source", "StockAnalysis.com") if isinstance(data, dict) else "StockAnalysis.com"}
Fetched: {data.get("fetched_at", "unknown") if isinstance(data, dict) else "unknown"}

External Consensus
• Consensus: {consensus or "Unavailable"}
• Rating Bucket: {consensus_bucket(metrics)}
• Price Target: {price_target or "Unavailable"}
• Implied Upside/Downside: {upside or "Unavailable"}

Buy / Hold / Sell Mix
{build_stockanalysis_vote_mix(metrics)}

External Read
{external_read(metrics)}

Smart Money Cross-Check
{conflict_check(metrics, internal_report)}

Use:
/stockdata {symbol}
/stock {symbol}
/scorecard {symbol}
/risk {symbol}
/filing {symbol}
""".strip()