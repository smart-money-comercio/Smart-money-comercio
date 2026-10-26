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


def analyze_report(report: str, stories: list[dict] | None = None) -> dict:
    evidence = report_evidence(report)
    from src.intelligence import news_editor
    evidence["stories"] = []
    for story in stories or []:
        if story.get("decision") != "selected" or story.get("source_check") != "pass" or not news_editor.primary_source(story) or not news_editor.materiality(story):
            raise ValueError("Market interpretation requires admitted original-source stories")
        evidence["stories"].append({key: deepcopy(story[key]) for key in (
            "id", "title", "kind", "symbols", "source", "url", "published", "official", "publisher_symbol", "decision", "source_check")})
        if story["kind"] == "company":
            from src.intelligence.story_analysis import checked_evidence
            checked_evidence(story)
            evidence["stories"][-1].update({key: deepcopy(story[key]) for key in (
                "event_evidence", "materiality", "evidence_checked_at", "source_checked_at") if key in story})
    if evidence["stories"]:
        evidence["source_sections"].append("Verified story decisions")
    return {"schema": 1, "research_sha256": hashlib.sha256(report.encode()).hexdigest(),
            "evidence": evidence, "insights": review_daily_brief(deepcopy(evidence)), "score_changes": False}


def retained_review(analysis: dict, report: str) -> dict:
    """Record only complete analyst passages that actually reached this edition."""
    result = deepcopy(analysis)
    result["insights"] = [row for row in result["insights"] if row["text"] in report]
    return result


def validate_review(analysis: dict, research_report: str, report: str, stories: list[dict] | None = None) -> None:
    expected = analyze_report(research_report, stories)
    if any(analysis.get(key) != expected[key] for key in ("schema", "research_sha256", "evidence", "score_changes")):
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
