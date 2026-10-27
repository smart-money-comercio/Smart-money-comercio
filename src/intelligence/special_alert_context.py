"""Cache-only bridge from event evidence to the agent and delivered reports."""

from __future__ import annotations

from datetime import datetime, timezone

from src.intelligence import special_alert_store as store
from src.intelligence.special_alert_sources import clean, timestamp


def current_evidence(events: list[dict]) -> list[dict]:
    from src.config.special_alerts import settings
    from src.intelligence.special_alert_engine import confirmed_company
    if not settings()["confirmed_only"]:
        return events
    return [event for event in events if event.get("kind") != "company" or confirmed_company(event.get("evidence", {}))]


def active_events(symbol: str = "", now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    try:
        return current_evidence(store.recent_events(now.timestamp(), symbol.upper()))
    except Exception:
        return []


def event_fact(event: dict) -> str:
    if event["kind"] == "ipo":
        from src.intelligence.ipo_monitor import checked, STAGES
        evidence = event["evidence"]
        try:
            issuer = checked(evidence)
        except (ValueError, KeyError, TypeError, AttributeError):
            return "IPO source evidence unavailable; review /specialalerts before using this event."
        at = timestamp(evidence["published"]).strftime("%Y-%m-%d %H:%M UTC")
        return f"{at}: {issuer['name']} — {STAGES[evidence['ipo']['stage']]} ({evidence['source']}; original source)."
    if event["kind"] == "company":
        evidence = event["evidence"]
        time = timestamp(evidence["published"]).strftime("%Y-%m-%d %H:%M UTC")
        label = "company announcement" if evidence.get("official") else "headline report; unconfirmed by company"
        return f"{time}: {clean(evidence['title'], 150)} ({label}; {clean(evidence['source'], 65)})."
    evidence = event["evidence"]
    rows = [evidence[s] for s in ("^GSPC", "^IXIC") if s in evidence]
    time = timestamp(rows[0]["asof"]).strftime("%Y-%m-%d %H:%M UTC")
    moves = "; ".join(f"{row['name']} {row['change']:+.2f}%" for row in rows)
    return f"{time}: {moves} (Yahoo chart; may be delayed)."


def agent_interpretation(event: dict) -> str:
    review = event.get("agent_review", "")
    for line in review.splitlines():
        if line.startswith("Interpretation: "):
            return clean(line.removeprefix("Interpretation: "), 230)
    return "Agent review unavailable; validate the sourced event before changing conviction."


def build_event_review(symbol: str = "") -> str:
    events = active_events(symbol)
    if not events:
        return ""
    return "Special Alerts Agent\n" + "\n".join(
        event_fact(event) + "\nAgent interpretation: " + agent_interpretation(event)
        for event in events[:2])


def special_alert_context_provider():
    from src.intelligence.intelligence_context_registry import IntelligenceContextBlock
    events = active_events()
    if not events:
        return None
    market = any(event["kind"] == "market" for event in events)
    return IntelligenceContextBlock(
        feature="Special Alerts Agent", priority=105,
        signal=clean(" ".join(event_fact(event) for event in events[:2]), 500),
        implication=agent_interpretation(events[0]),
        validation="Confirm the original source, price/volume and near-term catalysts.",
        symbols=list(dict.fromkeys(s for event in events for s in event.get("symbols", []))),
        themes=["risk-off"] if market else [],
        risks=["Observed market selloff"] if market else [],
        commands=["/specialalerts", "/tickernews SYMBOL", "/risk SYMBOL"],
        metadata={"event_count": len(events), "agent_integrated": True,
                  "sources": [event_fact(event) for event in events], "score_changes": False},
    )


def attach_daily_special_alerts(report: str, max_chars: int = 7600, now: datetime | None = None) -> str:
    events = active_events(now=now)
    if not events:
        return report
    lines = report.splitlines()
    try:
        start = lines.index("Risk Notes") + 1
        end = lines.index("Smart Money Summary", start)
        sources = lines.index("Intelligence Used Today") + 1
    except ValueError:
        return report
    events.sort(key=lambda event: (event["kind"] == "market", event["level"]), reverse=True)
    event = events[0]
    original = [line for line in lines[start:end] if line.strip()][:1]
    for size in (350, 250, 160):
        replacement = ["• Agent event: " + clean(event_fact(event), size),
                       "• Agent interpretation: " + clean(agent_interpretation(event), size // 2)]
        candidate = lines[:start] + replacement + original + [""] + lines[end:]
        candidate[sources] += " Special Alerts Agent: active."
        text = "\n".join(candidate)
        if len(text) <= max_chars:
            return text
    return report


def daily_agent_event_review() -> str:
    # Let the workflow record a cache error rather than silently report zero events.
    events = current_evidence(store.recent_events(datetime.now(timezone.utc).timestamp()))
    if not events:
        return "0 active events in the special-alert evidence cache. No network fetch or Telegram send."
    return f"{len(events)} active sourced events reviewed by the analyst agent. " + clean(build_event_review(), 800)
