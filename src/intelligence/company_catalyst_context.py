"""Company research priorities from dated caches; no fetch, scoring or delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from urllib.parse import urlsplit

from src.agents.analyst_agent import review_company_catalyst
from src.config.special_alerts import settings
from src.intelligence import calendar_context, special_alert_store
from src.intelligence.special_alert_context import event_fact
from src.intelligence.special_alert_sources import clean, timestamp
from src.intelligence.special_alert_universe import SYMBOL, company_universe
from src.utils.yahoo_quote import finite_number


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def score(value):
    value = finite_number(value)
    return value if value is not None and 0 <= value <= 100 else None


def valid_event(event: dict, now: datetime) -> dict | None:
    try:
        if not isinstance(event, dict) or event.get("kind") not in {"company", "market"}:
            return None
        expiry = event["expires"]
        if type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry < now.timestamp():
            return None
        evidence = event["evidence"]
        if not isinstance(evidence, dict):
            return None
        if event["kind"] == "company":
            published = timestamp(evidence["published"])
            if not -60 <= (now - published).total_seconds() <= 86400:
                return None
            url = evidence["url"]
            parts = urlsplit(url)
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                return None
            symbols = [item for item in event["symbols"] if isinstance(item, str) and SYMBOL.fullmatch(item)]
            if not symbols or not isinstance(evidence.get("title"), str) or not evidence["title"].strip():
                return None
            original_title = evidence.get("original_title", evidence["title"])
            title = clean(original_title if isinstance(original_title, str) else evidence["title"], 1001)
            shortened = bool(evidence.get("title_truncated")) or not isinstance(original_title, str) or len(title) > 1000
            # Older alert readers capped titles at 240 without a completeness flag.
            if "original_title" not in evidence and len(title) == 240:
                shortened = True
            event = {**event, "symbols": symbols, "evidence": {**evidence, "official": evidence.get("official") is True}}
            return {"kind": "company", "symbols": symbols, "fact": event_fact(event), "url": url,
                    "official": event["evidence"]["official"], "title": title[:1000], "title_truncated": shortened,
                    "publisher_symbol": evidence.get("publisher_symbol", ""),
                    "source": clean(evidence.get("source") or parts.hostname, 65), "published": published.isoformat(),
                    "source_checked_at": datetime.fromtimestamp(event["observed"], timezone.utc).isoformat()
                    if type(event.get("observed")) in (int, float) and math.isfinite(event["observed"]) else None}
        for symbol in ("^GSPC", "^IXIC"):
            row = evidence.get(symbol)
            if not isinstance(row, dict) or type(row.get("change")) not in (int, float) or not math.isfinite(row["change"]):
                return None
            if not -60 <= (now - timestamp(row["asof"])).total_seconds() <= 86400:
                return None
        return {"kind": "market", "symbols": [], "fact": event_fact(event), "url": "https://finance.yahoo.com/quote/%5EGSPC/"}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def earnings_context(symbol: str, snapshot: dict | None, now: datetime) -> dict:
    if snapshot is None:
        return {"status": "unavailable", "dates": [], "text": "Calendar evidence unavailable; check /calendar."}
    today = now.astimezone(calendar_context.publishers.NY).date().isoformat()
    matches = [row for row in snapshot["earnings"] if row.get("symbol") == symbol and row["source_date"] >= today]
    dates = sorted({row["source_date"] for row in matches})
    if len(dates) > 1:
        return {"status": "conflict", "dates": dates, "text": "Conflicting Nasdaq earnings estimates: " + ", ".join(dates) + "; company confirmation pending."}
    if dates:
        clocks = {str(row.get("time") or "").lower() for row in matches}
        clock = {"time-pre-market": "before market open", "time-after-hours": "after market close"}.get(
            next(iter(clocks)), "time not supplied") if len(clocks) == 1 else "timing inconsistent"
        return {"status": "estimated", "dates": dates, "time": clock,
                "text": f"{dates[0]} earnings {clock}; Nasdaq estimate, company confirmation pending."}
    complete = all(day["earnings_available"] for day in snapshot["days"])
    return {"status": "no_match" if complete else "incomplete", "dates": [],
            "text": "No earnings entry in the cached window; verify investor relations." if complete else "Earnings coverage incomplete; verify investor relations."}


def build_company_catalyst_brief(ranked: list[dict] | None = None, now: datetime | None = None) -> dict:
    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("Company catalyst clock needs a timezone")
    config = settings()
    coverage = company_universe({**config, "top_count": 0} if ranked is not None else config,
                                now=now, include_scores=True)
    if ranked is not None:
        values = {}
        for item in ranked:
            if not isinstance(item, dict):
                continue
            symbol = item.get("ticker") or item.get("symbol")
            if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol) or symbol in values:
                continue
            opportunity, structural = score(item.get("opportunity_score")), score(item.get("structural_score"))
            if opportunity is None or structural is None:
                continue
            values[symbol] = {"opportunity_score": opportunity, "structural_score": structural, "rank": len(values) + 1}
        coverage["ranked"] = list(values)[:config["top_count"]]
        coverage["symbols"] = list(dict.fromkeys(coverage["core"] + coverage["ranked"]))
        coverage["scores"] = {symbol: value for symbol, value in values.items() if symbol in coverage["symbols"]}
        coverage["ranking_date"] = now.astimezone(calendar_context.publishers.NY).date().isoformat() if values else None
        coverage["ranking_status"] = "This report's opportunity ranking" if values else "Opportunity ranking unavailable; core companies only"
    snapshot = calendar_context.read_snapshot(now=now)
    issues = []
    if snapshot is None:
        issues.append("Calendar evidence unavailable or expired")
    else:
        issues.extend(snapshot["issues"][:2])
    try:
        events = [value for event in special_alert_store.read_current_events(now.timestamp())
                  if (value := valid_event(event, now)) is not None]
        event_status = "Existing special-alert evidence cache read"
    except Exception as exc:
        events = []
        event_status = "Special-alert evidence unavailable (" + type(exc).__name__ + ")"
        issues.append(event_status)
    order = list(dict.fromkeys(coverage["ranked"] + coverage["core"]))
    rows = []
    for symbol in order:
        calendar = earnings_context(symbol, snapshot, now)
        company_events = [event for event in events if event["kind"] == "company" and symbol in event["symbols"]][:2]
        row = {"symbol": symbol, "core": symbol in coverage["core"], "score": coverage["scores"].get(symbol),
               "calendar": calendar, "events": company_events}
        row["review"] = review_company_catalyst(row)
        rows.append(row)
    days = sorted(day["date"] for day in snapshot["days"]) if snapshot else []
    return {"asof": now.isoformat(), "ranking_date": coverage["ranking_date"], "ranking_status": coverage["ranking_status"],
            "calendar_checked_at": snapshot["checked_at"] if snapshot else None, "calendar_days": days,
            "rows": rows, "market_events": [event for event in events if event["kind"] == "market"][:1],
            "macro": [dict(row) for row in snapshot["economic"] if row["time_status"] in {"verified", "cached"}
                      and calendar_context.checked_time(row["event_at"]) >= now] if snapshot else [],
            "event_status": event_status, "issues": issues,
            "has_evidence": any(row["calendar"]["dates"] or row["events"] for row in rows)}


def catalyst_note(row: dict) -> str:
    calendar = row["calendar"]
    if calendar["status"] == "conflict":
        return "earnings dates conflict; verify company announcement"
    if calendar["dates"]:
        return "earnings estimate " + calendar["dates"][0] + "; company confirmation pending"
    if row["events"]:
        return "company announcement to review" if row["events"][0]["official"] else "headline development; company confirmation pending"
    return "dated catalyst not established in cached coverage"


def build_company_catalyst_report(symbol: str = "") -> str:
    brief = build_company_catalyst_brief()
    rows = [row for row in brief["rows"] if row["symbol"] == symbol] if symbol else brief["rows"]
    lines = ["Company Catalyst Brief", "Checked: " + brief["asof"], brief["ranking_status"],
             "Coverage: " + ", ".join(row["symbol"] for row in brief["rows"])]
    if brief["ranking_date"]:
        lines.append("Rankings dated " + brief["ranking_date"] + "; research priority does not change numerical scores.")
    if brief["calendar_days"]:
        lines.append("US calendar window: " + brief["calendar_days"][0] + " to " + brief["calendar_days"][-1]
                     + "; checked " + str(brief["calendar_checked_at"]))
    for row in rows:
        values = row["score"]
        ranking = f" | Opportunity {values['opportunity_score']:.1f}/100 | Structural {values['structural_score']:.1f}/100" if values else " | Ranking unavailable"
        lines += ["", row["symbol"] + ranking, "Calendar: " + row["calendar"]["text"], "Review focus: " + row["review"]["focus"]]
        for event in row["events"]:
            lines += [event["fact"], event["url"]]
        if not row["events"]:
            lines.append("No matching active company event in the available evidence cache; news coverage may be incomplete.")
        if symbol:
            lines += ["Agent review: " + row["review"]["interpretation"], row["review"]["confirmation"]]
        lines.append(f"Next: /earnings {row['symbol']} · /volume {row['symbol']} · /risk {row['symbol']}")
    if not rows:
        lines += ["", symbol + " is outside the current brief coverage. Use /earnings and /tickernews for a separate review."]
    if brief["market_events"]:
        lines += ["", "Market context: " + brief["market_events"][0]["fact"], "Price data alone does not establish the cause."]
    lines += ["", brief["event_status"]]
    if brief["issues"]:
        lines.append("Coverage notes: " + "; ".join(clean(issue, 160) for issue in brief["issues"][:3]))
    lines += ["", "Price and volume require a fresh check. Earnings estimates and headline reports are not confirmation.", "Research only. Not financial advice."]
    return "\n".join(lines)


def daily_company_catalyst_review() -> str:
    brief = build_company_catalyst_brief()
    dated = sum(bool(row["calendar"]["dates"]) for row in brief["rows"])
    sourced = sum(bool(row["events"]) for row in brief["rows"])
    coverage = " Coverage notes: " + "; ".join(clean(issue, 120) for issue in brief["issues"][:2]) if brief["issues"] else ""
    return (f"{len(brief['rows'])} companies reviewed; {dated} with estimated earnings dates; {sourced} with active sourced developments. "
            + brief["ranking_status"] + ". Cached evidence only; numerical scores unchanged." + coverage)


def company_catalyst_context_provider():
    from src.intelligence.intelligence_context_registry import IntelligenceContextBlock
    brief = build_company_catalyst_brief()
    selected = [row for row in brief["rows"] if row["calendar"]["dates"] or row["events"]][:2]
    if not selected:
        return None
    return IntelligenceContextBlock(feature="Company Catalysts", priority=60,
        signal="; ".join(row["symbol"] + ": " + catalyst_note(row) for row in selected),
        implication="Confirm dated company evidence and fresh price/volume before changing conviction.",
        validation="Earnings dates are Nasdaq estimates; company confirmation remains separate from headline reports.",
        commands=["/catalysts", "/earnings SYMBOL", "/volume SYMBOL"],
        metadata={"cache_only": True, "score_changes": False, "ranking_date": brief["ranking_date"],
                  "calendar_checked_at": brief["calendar_checked_at"]})
