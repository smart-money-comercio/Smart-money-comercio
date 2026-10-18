"""One cache-only, explanatory research backdrop shared by the bot's reports."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re

from src.intelligence.research_store import (
    PROJECT_ROOT, ResearchError, eligible_claims, parse_time, read_documents, utc_now,
)


TYPE_LABELS = {"observation": "Observation", "estimate": "Estimate", "forecast": "Forecast", "opinion": "Opinion"}
MARKET_CACHE = PROJECT_ROOT / "data/morning_brief_cache.json"
MAX_MARKET_AGE_SECONDS = 6 * 60 * 60


def enabled() -> bool:
    return os.getenv("RESEARCH_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def source_label(claim: dict) -> str:
    pages = ",".join(str(p) for p in claim["pages"])
    return f"{claim['source']['label']}, p{pages}"


def claim_line(claim: dict) -> str:
    as_of = parse_time(claim["as_of"]).date().isoformat()
    return f"{TYPE_LABELS[claim['type']]} ({as_of}): {claim['text']} [{source_label(claim)}]"


def load_market_payload() -> dict:
    try:
        payload = json.loads(MARKET_CACHE.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def market_observations(payload: dict) -> dict[str, float]:
    payload = payload if isinstance(payload, dict) else {}
    raw_moves = payload.get("market_moves", [])
    if not isinstance(raw_moves, list):
        raw_moves = []
    moves = {}
    for row in raw_moves:
        if not isinstance(row, dict) or row.get("error"):
            continue
        move = row.get("move")
        if type(move) in (int, float) and math.isfinite(move):
            moves[str(row.get("symbol", "")).upper()] = move
    return moves


def market_check(payload: dict, now: datetime | None = None, symbol: str = "") -> str:
    now = parse_time(now or utc_now())
    payload = payload if isinstance(payload, dict) else {}
    try:
        raw = payload.get("cached_at")
        if type(raw) not in (int, float) or not math.isfinite(raw):
            raise ValueError
        observed = datetime.fromtimestamp(raw, timezone.utc)
        age = (now - observed).total_seconds()
    except (ValueError, TypeError, OverflowError, OSError):
        return "Market check: unavailable; current yields, price and volume need confirmation."
    if age < -300:
        return "Market check: unavailable; the market-cache timestamp is in the future."
    if age > MAX_MARKET_AGE_SECONDS:
        return f"Market check: stale cache ({observed.date().isoformat()}); refresh before using this backdrop."
    moves = market_observations(payload)
    labels = []
    # The source cache measures last-session/daily price moves, not a Treasury yield.
    symbol = str(symbol or "").upper().replace("$", "")
    if symbol and symbol in moves:
        labels.append(f"{symbol} {moves[symbol]:+.2f}%")
    if "^IXIC" in moves:
        labels.append(f"Nasdaq {moves['^IXIC']:+.2f}%")
    elif "^GSPC" in moves:
        labels.append(f"S&P 500 {moves['^GSPC']:+.2f}%")
    if "TLT" in moves:
        labels.append(f"TLT {moves['TLT']:+.2f}% (bond-price proxy)")
    if not labels:
        return "Market check: unavailable; this cache has no usable price or bond-proxy observations."
    stamp = observed.strftime("%m-%d %H:%M UTC")
    return f"Market check ({stamp} cache): {'; '.join(labels)}. Yields unverified."


def build_research_context(symbol: str = "", market_payload: dict | None = None,
                           now: datetime | None = None, documents: list[dict] | None = None) -> dict:
    now = parse_time(now or utc_now())
    result = {"status": "disabled", "claims": [], "counts": {}, "issues": 0,
              "market_check": "", "as_of": now.isoformat()}
    if not enabled():
        return result
    try:
        documents = read_documents() if documents is None else documents
        claims, counts = eligible_claims(documents, now, symbol)
        result.update(status="active" if claims else "inactive", claims=claims, counts=counts,
                      issues=sum(len(document.get("issues", [])) for document in documents))
        result["market_check"] = market_check(load_market_payload() if market_payload is None else market_payload, now, symbol)
    except (ResearchError, OSError, TypeError, KeyError):
        result["status"] = "unavailable"
    return result


def research_context_provider():
    from src.intelligence.intelligence_context_registry import IntelligenceContextBlock
    context = build_research_context()
    if context["status"] != "active":
        return None
    claim = context["claims"][0]
    # Historical opinions must not become live theme/risk votes in the existing registry.
    return IntelligenceContextBlock(
        feature="Document Research", priority=55, signal=claim_line(claim),
        implication="Dated research background; validate it against current observations.",
        validation="Use /research, /scorecard SYMBOL, /volume SYMBOL and /tradeplan SYMBOL.",
        commands=["/research", "/tradeplan SYMBOL"],
        metadata={"eligible_claims": len(context["claims"]), "source": source_label(claim),
                  "research_status": context["status"]},
    )


def build_market_backdrop(symbol: str = "", context: dict | None = None) -> str:
    context = build_research_context(symbol=symbol) if context is None else context
    if context["status"] == "disabled":
        return ""
    if context["status"] != "active":
        status = "temporarily unavailable" if context["status"] == "unavailable" else "no eligible dated research"
        return f"Market Backdrop\nDocument research: {status}."
    return "Market Backdrop\n" + claim_line(context["claims"][0]) + "\n" + context["market_check"]


def attach_daily_research(report: str, context: dict, max_chars: int = 7600) -> str:
    """Run after the legacy summary rewrites. Respect existing section/length budgets."""
    if context["status"] != "active":
        return report
    lines = report.splitlines()
    try:
        start = lines.index("Theme Read") + 1
        end = next(i for i in range(start, len(lines)) if lines[i] == "Market Snapshot")
        source_index = lines.index("Intelligence Used Today") + 1
    except (ValueError, StopIteration):
        return report
    previous = [line for line in lines[start:end] if line.strip()][:1]
    replacement = ["• Research " + claim_line(context["claims"][0]), "• " + context["market_check"]] + previous
    candidate_lines = lines[:start] + replacement + [""] + lines[end:]
    # Record actual contribution, rather than claiming that every registered source was used.
    contribution = " Document Research: active."
    if source_index < len(candidate_lines) and candidate_lines[source_index].strip():
        candidate_lines[source_index] += contribution
    else:
        return report
    candidate = "\n".join(candidate_lines)
    if len(candidate) > max_chars:
        # Leave the already-validated report intact if no room remains. No false active label.
        return report
    return candidate


def validate_research_output(report: str) -> list[str]:
    errors = []
    active = "Document Research: active." in report
    research_lines = [line for line in report.splitlines() if line.startswith("• Research ")]
    if active and (not research_lines or not any("• Market check" in line for line in report.splitlines())):
        errors.append("Active document research is missing its dated context or market check.")
    for line in research_lines:
        if not re.search(r"Research (Observation|Estimate|Forecast|Opinion) \(\d{4}-\d{2}-\d{2}\): .*\[[^\]]+, p\d", line):
            errors.append("Research context is missing its claim type, date or page reference.")
    if research_lines and not active:
        errors.append("Research contribution is missing from Intelligence Used Today.")
    return errors


def build_research_report(symbol: str = "") -> str:
    context = build_research_context(symbol=symbol)
    lines = ["Document Research", f"Status: {context['status'].upper()}"]
    if context["status"] == "active":
        lines.append(f"Eligible events: {len(context['claims'])}")
        for claim in context["claims"][:4]:
            lines += ["", claim_line(claim)]
        lines += ["", context["market_check"]]
    if context["status"] in {"active", "inactive"}:
        counts = context["counts"]
        lines += ["", f"Archived/withheld: {counts.get('expired', 0)} expired; {counts.get('withheld', 0)} ambiguous; {counts.get('future', 0)} not yet available.",
                  f"Source issues recorded: {context['issues']}"]
    if context["status"] == "unavailable":
        lines += ["", "Research data could not be validated. Existing records were preserved."]
    lines += ["", "Context only. Validate current yields, earnings, price and volume before acting.",
              "Use /research SYMBOL for a company-specific read.", "Research only. Not financial advice."]
    return "\n".join(lines)
