"""Analyst narration grounded in the exact, already-built research edition."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import re

from src.agents.analyst_agent import review_daily_brief


SYMBOL = r"[A-Z][A-Z0-9.\-]{0,9}"
NUMBER = r"[+-]?\d+(?:\.\d+)?"
NAMES = {"MSFT": "Microsoft", "NVDA": "Nvidia", "PLTR": "Palantir", "TSLA": "Tesla",
         "TSM": "Taiwan Semiconductor", "AVGO": "Broadcom", "AVAV": "AeroVironment",
         "CRWD": "CrowdStrike", "AAPL": "Apple", "AMZN": "Amazon", "GOOG": "Alphabet",
         "GOOGL": "Alphabet", "META": "Meta Platforms", "AMD": "Advanced Micro Devices",
         "INTC": "Intel", "NOC": "Northrop Grumman", "LMT": "Lockheed Martin",
         "KTOS": "Kratos Defense", "CACI": "CACI International"}


def model_values(block: str, label: str, keys: tuple[str, ...], lower: float, upper: float) -> dict | None:
    pattern = r"^[ \t]*" + re.escape(label) + ": " + "; ".join(re.escape(key) + " (" + NUMBER + ")" for key in keys) + "$"
    rows = re.findall(pattern, block, re.M)
    if len(rows) != 1:
        return None
    values = tuple(map(float, rows[0]))
    return dict(zip(keys, values)) if all(math.isfinite(v) and lower <= v <= upper for v in values) else None


def report_evidence(report: str) -> dict:
    from src.reports.report_quality import split_report_sections
    sections = {header: "\n".join(lines[1:]) for header, lines in split_report_sections(report) if header}
    snapshot = sections.get("Market Snapshot", "")
    session = re.search(r"^Quote session: (\d{4}-\d{2}-\d{2})$", snapshot, re.M)
    moves = {}
    if session:
        for key, raw in re.findall(r"(S&P|Nasdaq|Russell|VIX|Oil|TLT)\s+(" + NUMBER + r")%", sections.get("Executive Summary", "")):
            value = float(raw)
            if math.isfinite(value):
                moves[key] = value
    breadth = re.search(r"^Breadth: (\d+) up / (\d+) down / (\d+) quoted$", snapshot, re.M)
    participation = None
    if session and breadth:
        up, down, total = map(int, breadth.groups())
        if total > 0 and up + down <= total:
            participation = {"up": up, "down": down, "total": total}
    companies = []
    for block in re.split(r"\n\s*\n", sections.get("Top Opportunities", "").strip()):
        ordinal = re.match(r"(\d+)\. ", block)
        if not ordinal or int(ordinal[1]) != len(companies) + 1:
            break
        match = re.match(r"\d+\. (" + SYMBOL + r") - Opportunity (" + NUMBER + r")/100 \| Structural (" + NUMBER + r")/100 \| (unchanged|(?:up|down) " + NUMBER + r")\s*$", block.splitlines()[0] if block else "")
        if not match:
            break
        symbol, opportunity, structural, change = match.groups()
        opportunity, structural = float(opportunity), float(structural)
        if not all(math.isfinite(v) and 0 <= v <= 100 for v in (opportunity, structural)) or any(row["symbol"] == symbol for row in companies):
            break
        delta = float(change.split()[-1]) if change != "unchanged" else 0.0
        if not math.isfinite(delta) or abs(delta) > 100 or (change.startswith("up") and delta <= 0) or (change.startswith("down") and delta >= 0):
            break
        basis = model_values(block, "Model adjustments", ("price", "news", "volume", "risk", "revision"), -100, 100)
        if basis:
            expected = min(100, max(0, structural + min(8, max(-8, sum(basis.values())))))
            if not session or abs(expected - opportunity) > 0.11:
                basis = None
        inputs = model_values(block, "Model inputs", ("core", "theme", "congress", "insiders"), 0, 100)
        price = re.search(r"^\s*Price: (" + NUMBER + r")% \|", block, re.M)
        score_risk = re.search(r"^\s*Score Risk: (Controlled|Balanced|Elevated) \|", block, re.M)
        plans = re.findall(r"^\d+\. " + re.escape(symbol) + r" — (.+)$", sections.get("Trade Plan Snapshot", ""), re.M)
        plan = plans[0] if len(plans) == 1 else ""
        plan_risk = re.search(r"\| Score Risk: (Controlled|Balanced|Elevated) \|", plan)
        if plan_risk and score_risk and plan_risk[1] != score_risk[1]:
            plan = ""
        setup = re.search(r"\| Setup Risk: (Low|Medium|High|Medium-High|Low-Medium) \|", plan)
        action = re.search(r"\| Action: (.+?) Entry:", plan)
        companies.append({"symbol": symbol, "name": NAMES.get(symbol, symbol), "opportunity": opportunity,
                          "structural": structural, "delta": delta,
                          "basis": basis, "inputs": inputs,
                          "price": float(price[1]) if session and price and math.isfinite(float(price[1])) else None,
                          "score_risk": score_risk[1] if score_risk else None,
                          "setup_risk": setup[1] if setup else None,
                          "action": "constructive" if action and action[1].startswith("Constructive") else
                                    "wait" if action and action[1].startswith(("Watchlist", "Wait", "Cautious", "Defensive")) else None})
        if len(companies) == 3:
            break
    leadership = re.search(r"Leadership: (" + SYMBOL + r") moved ahead of (" + SYMBOL + r")\.", sections.get("What Changed Today", ""))
    changed = None
    if leadership and companies and leadership[1] == companies[0]["symbol"] and leadership[2] in {row["symbol"] for row in companies[1:]}:
        changed = {"leader": leadership[1], "previous": leadership[2], "previous_name": NAMES.get(leadership[2], leadership[2])}
    return {"session": session[1] if session else None, "is_open": "Market Session: Open" in snapshot,
            "moves": moves, "breadth": participation,
            "companies": companies, "leadership": changed,
            "source_sections": [key for key in ("Executive Summary", "Market Snapshot", "What Changed Today", "Top Opportunities", "Trade Plan Snapshot") if sections.get(key)]}


def analyze_report(report: str, stories: list[dict] | None = None, *, presentation: str = "full", focus_context: dict | None = None, narration_version: int = 1, event_context: dict | None = None, reader_version: int = 0, reader_limit: int = 3, earnings_context: list | None = None) -> dict:
    if presentation not in {"full", "news"}:
        raise ValueError("Unknown analyst presentation")
    if type(narration_version) is not int or narration_version not in {1, 2} or narration_version == 2 and presentation != "news":
        raise ValueError("Unknown analyst narration version")
    if type(reader_version) is not int or reader_version not in {0, 1} or reader_version and (presentation != "news" or narration_version != 2):
        raise ValueError("Unknown reader brief version")
    if type(reader_limit) is not int or not 1 <= reader_limit <= 3:
        raise ValueError("Invalid reader watch-signal limit")
    evidence = report_evidence(report)
    if event_context is not None:
        from src.intelligence.market_event_desk import checked_context
        generated = re.search(r"^Generated: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\S+)$", report, re.M)
        from datetime import datetime
        from zoneinfo import ZoneInfo
        if presentation != "news" or generated is None:
            raise ValueError("Market event attention belongs to a dated news edition")
        now = datetime.strptime(generated[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo(generated[2]))
        evidence["market_event_context"] = deepcopy(checked_context(event_context, report, now))
        evidence["source_sections"].append("Market event checks")
    if narration_version == 2:
        evidence["narration_version"] = narration_version
    if reader_version:
        evidence["reader_version"] = reader_version
        evidence["reader_limit"] = reader_limit
    from src.intelligence import news_editor
    evidence["stories"] = []
    for story in stories or []:
        if story.get("decision") != "selected" or story.get("source_check") != "pass" or not news_editor.primary_source(story) or not news_editor.materiality(story):
            raise ValueError("Market interpretation requires admitted original-source stories")
        evidence["stories"].append({key: deepcopy(story[key]) for key in (
            "id", "title", "kind", "symbols", "source", "url", "published", "official", "publisher_symbol", "decision", "source_check")})
        if story.get("ipo"):
            from src.intelligence.ipo_monitor import checked
            checked(story)
            evidence["stories"][-1].update(ipo=deepcopy(story["ipo"]), source_checked_at=story["source_checked_at"])
        if story.get("sec_filing"):
            from src.intelligence.sec_research import checked
            checked(story)
            evidence["stories"][-1].update(sec_filing=deepcopy(story["sec_filing"]), source_checked_at=story["source_checked_at"])
        if story.get("discovery_evidence"):
            from src.intelligence.hourly_research import check_proof
            check_proof(story)
            evidence["stories"][-1].update(discovery_evidence=deepcopy(story["discovery_evidence"]), source_checked_at=story["source_checked_at"])
        if story["kind"] == "company" or story.get("event_evidence") is not None:
            from src.intelligence.story_analysis import checked_evidence
            checked_evidence(story)
            evidence["stories"][-1].update({key: deepcopy(story[key]) for key in (
                "event_evidence", "materiality", "evidence_checked_at", "source_checked_at") if key in story})
    if presentation == "news":
        evidence["stories"].sort(key=lambda story: story["id"])
    if evidence["stories"]:
        evidence["source_sections"].append("Verified story decisions")
    if focus_context is not None:
        if presentation != "news":
            raise ValueError("Dynamic company focus belongs to the news presentation")
        from src.intelligence.company_focus import select_focus
        evidence["company_focus"] = select_focus(report, evidence, focus_context)
        evidence["source_sections"].append("Company focus selection")
    if earnings_context is not None:
        if event_context is None or not reader_version:
            raise ValueError("Dated earnings context requires the news reader and verified market attention")
        from src.intelligence.alphabet_earnings import retain
        evidence["earnings_context"] = retain(earnings_context, now, event_context["events"], evidence["stories"], evidence.get("company_focus"))
        if evidence["earnings_context"]:
            evidence["source_sections"].append("Recent earnings context")
    value = {"schema": 1, "research_sha256": hashlib.sha256(report.encode()).hexdigest(),
             "evidence": evidence, "insights": review_daily_brief(deepcopy(evidence), presentation=presentation), "score_changes": False}
    if presentation != "full":
        value["presentation"] = presentation
    if focus_context is not None:
        value["focus_context"] = deepcopy(focus_context)
    if event_context is not None:
        value["event_context"] = deepcopy(event_context)
    if narration_version == 2:
        value["narration_version"] = narration_version
    if reader_version:
        value["reader_version"] = reader_version
        value["reader_limit"] = reader_limit
    if earnings_context is not None:
        value["earnings_context"] = deepcopy(earnings_context)
    return value


def retained_review(analysis: dict, report: str) -> dict:
    """Record only complete analyst passages that actually reached this edition."""
    result = deepcopy(analysis)
    result["insights"] = [row for row in result["insights"] if row["text"] in report]
    return result


def validate_review(analysis: dict, research_report: str, report: str, stories: list[dict] | None = None) -> None:
    expected = analyze_report(research_report, stories, presentation=analysis.get("presentation", "full"), focus_context=analysis.get("focus_context"), narration_version=analysis.get("narration_version", 1), event_context=analysis.get("event_context"), reader_version=analysis.get("reader_version", 0), reader_limit=analysis.get("reader_limit", 3), earnings_context=analysis.get("earnings_context"))
    if any(analysis.get(key) != expected.get(key) for key in ("schema", "research_sha256", "evidence", "score_changes", "focus_context", "narration_version", "event_context", "reader_version", "reader_limit", "earnings_context")):
        raise ValueError("Analyst brief evidence does not match this research edition")
    allowed = {row["id"]: row for row in expected["insights"]}
    seen = set()
    for row in analysis.get("insights", []):
        if not isinstance(row, dict) or row.get("id") in seen or allowed.get(row.get("id")) != row or report.count(row["text"]) != 1:
            raise ValueError("Analyst narration changed or lost its supporting evidence")
        seen.add(row["id"])
    required = {key for key, row in allowed.items() if key not in {"model_support", "company_price", "participation"} or row["text"] in report}
    if seen != required:
        raise ValueError("Available analyst evidence was omitted from the brief")
