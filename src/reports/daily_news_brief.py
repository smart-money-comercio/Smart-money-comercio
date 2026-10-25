"""A short spoken-friendly edition of the same validated research report."""

from __future__ import annotations

from datetime import datetime
import re
from zoneinfo import ZoneInfo

from src.intelligence.calendar_context import checked_time, publishers
from src.intelligence.company_catalyst_context import build_company_catalyst_brief
from src.intelligence import news_editor as editor
from src.utils.report_consistency import report_greeting, validate_report_greeting


TITLE = "Smart Money Daily News Brief"
MAX_NEWS_CHARS = 3800
HEADERS = ["Market Update", "Companies in Focus", "What's Ahead", "What We're Watching", "Research Notes"]
NAMES = {"MSFT": "Microsoft", "NVDA": "Nvidia", "PLTR": "Palantir", "TSLA": "Tesla",
         "TSM": "Taiwan Semiconductor", "AVGO": "Broadcom", "AVAV": "AeroVironment", "CRWD": "CrowdStrike"}


def name(symbol: str) -> str:
    return NAMES.get(symbol, symbol)


def direction(label: str, raw: str) -> str:
    value = float(raw.rstrip("%"))
    if value == 0:
        return label + " was unchanged"
    return f"{label} {'rose' if value > 0 else 'fell'} {abs(value):.2f} percent"


def sentence(values: list[str]) -> str:
    if len(values) < 2:
        return "".join(values)
    return " and ".join(values) if len(values) == 2 else ", ".join(values[:-1]) + ", and " + values[-1]


def display_day(raw: str) -> str:
    return datetime.strptime(raw, "%Y-%m-%d").strftime("%A, %B %d")


def validate_news_brief(text: str) -> dict:
    lines = text.splitlines()
    missing = [header for header in HEADERS if header not in lines]
    duplicates = [header for header in HEADERS if lines.count(header) > 1]
    qualification = []
    lower = text.lower()
    if "earnings calendar lists" in lower and ("estimate" not in lower or "confirmation is pending" not in lower):
        qualification.append("Earnings date confidence is missing")
    if "headline report" in lower and "unconfirmed" not in lower:
        qualification.append("Headline confirmation status is missing")
    if not text.startswith(TITLE + "\n"):
        missing.append(TITLE)
    if not re.search(r"^Generated: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \S+$", text, re.M):
        missing.append("Dated generation timestamp")
    if not re.search(r"^Date: [A-Z][a-z]+ \d{1,2}, \d{4}$", text, re.M):
        missing.append("Edition date")
    if not re.search(r"^Market data: (?:regular session \d{4}-\d{2}-\d{2}|completed regular session \d{4}-\d{2}-\d{2}|unavailable)\.?$", text, re.M):
        missing.append("Market-data session label")
    if "Research only. Not financial advice." not in text:
        missing.append("Research disclaimer")
    greeting = validate_report_greeting(text)
    return {"format": "news", "chars": len(text), "max_chars": MAX_NEWS_CHARS, "missing_headers": missing,
            "duplicate_headers": duplicates, "removed_headers_present": [], "what_changed_bullets": 0,
            "ai_summary_ok": not missing, "risk_consistency_errors": [], "greeting_errors": greeting,
            "research_context_errors": qualification, "source_qualification_errors": qualification,
            "passes": bool(text.strip()) and len(text) <= MAX_NEWS_CHARS and not (missing or duplicates or greeting or qualification)}


def build_daily_news_brief(research_report: str, catalyst_brief: dict | None = None) -> str:
    from src.reports.report_quality import split_report_sections, validate_daily_report_quality
    quality = validate_daily_report_quality(research_report)
    if quality.get("format") == "news" or not quality["passes"]:
        raise ValueError("The underlying research report did not pass quality review")
    sections = {header: "\n".join(lines[1:]) for header, lines in split_report_sections(research_report) if header}
    generated = re.search(r"^Generated: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\S+)$", research_report, re.M)
    dated = re.search(r"^Date: (.+)$", research_report, re.M)
    if generated is None or dated is None:
        raise ValueError("The research report needs a dated generation clock")
    now = datetime.strptime(generated[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo(generated[2]))
    zone = ZoneInfo(generated[2])
    snapshot = sections["Market Snapshot"]
    quote_day = re.search(r"^Quote session: (\d{4}-\d{2}-\d{2})$", snapshot, re.M)
    is_open = "Market Session: Open" in snapshot
    data_label = ("regular session " if is_open else "completed regular session ") + quote_day[1] if quote_day else "unavailable"
    prefix = f"{TITLE}\nDate: {dated[1]}\nGenerated: {generated[1]} {generated[2]}\nMarket data: {data_label}\n\n{report_greeting(now)}\nHere is your Smart Money Daily News Brief."
    executive = sections["Executive Summary"]
    moves = dict(re.findall(r"(S&P|Nasdaq|Russell|VIX|Oil|TLT)\s+([+-]?\d+(?:\.\d+)?%)", executive))
    if quote_day is None:
        moves = {}
    indices = [direction(label, moves[key]) for key, label in (("S&P", "the S&P 500"), ("Nasdaq", "the Nasdaq Composite"), ("Russell", "the Russell 2000")) if key in moves]
    if indices:
        session = ("During the " if is_open else "In the last completed U.S. regular session, ") + (display_day(quote_day[1]) if quote_day else "latest available snapshot")
        market = [session + (", " if not is_open else " session, ") + sentence(indices) + "."]
        if len(indices) < 3:
            market.append("Some major index returns were unavailable in the source snapshot.")
    else:
        market = ["Verified market returns are unavailable for this edition."]
    other = [direction(label, moves[key]) for key, label in (("VIX", "the VIX volatility index"), ("Oil", "oil"), ("TLT", "the TLT Treasury-bond fund")) if key in moves]
    if other:
        other_text = sentence(other)
        market.append(other_text[0].upper() + other_text[1:] + "." + (" TLT is a bond-price proxy; Treasury yields are not verified here." if "TLT" in moves else ""))
    breadth = re.search(r"Breadth: (\d+) up / (\d+) down / (\d+) quoted", snapshot)
    if breadth and quote_day:
        market.append(f"Within the {breadth[3]}-symbol research watchlist, {breadth[1]} finished higher and {breadth[2]} lower." if not is_open
                      else f"Within the {breadth[3]}-symbol research watchlist, {breadth[1]} are higher and {breadth[2]} lower.")
    rankings = re.findall(r"^\d+\. ([A-Z][A-Z0-9.\-]{0,9}) - Opportunity (\d+(?:\.\d+)?)/100 \| Structural (\d+(?:\.\d+)?)/100", sections["Top Opportunities"], re.M)[:3]
    brief = catalyst_brief if catalyst_brief is not None else build_company_catalyst_brief(now=now)
    plan = editor.build_editorial_plan(brief, now)
    story_paragraphs = {story["id"]: editor.render_story(story, zone, NAMES) for story in editor.selected_stories(plan)}
    if brief.get("market_events"):
        market.insert(1, "An active market-alert record reports " + brief["market_events"][0]["fact"]
                      + " This is dated price evidence; it does not establish the cause of the move.")
    leaders = [name(row[0]) for row in rankings]
    leader_text = ", ".join(leaders[:-1]) + " and " + leaders[-1] if len(leaders) > 1 else "".join(leaders)
    companies = [(leader_text + (" lead" if len(leaders) > 1 else " leads") + " Smart Money's research rankings. Fresh company, price and volume checks are still required.")
                 if rankings else "Company rankings were unavailable for this edition; no leading setup is being inferred."]
    for story in editor.selected_stories(plan):
        (companies if story["kind"] == "company" else market).append(story_paragraphs[story["id"]])
    dated_rows = sorted([row for row in brief["rows"] if row["calendar"]["dates"]], key=lambda row: row["calendar"]["dates"][0])
    ahead = []
    for row in dated_rows[:2]:
        calendar = row["calendar"]
        if calendar["status"] == "conflict":
            ahead.append(f"{name(row['symbol'])} has conflicting earnings-date estimates. Verify its investor-relations announcement.")
        else:
            ahead.append(f"Nasdaq's estimated earnings calendar lists {name(row['symbol'])} for {display_day(calendar['dates'][0])}, {calendar.get('time', 'time not supplied')}. Company confirmation is pending.")
    families = {"fomc_decision": "the Federal Reserve's interest-rate decision", "cpi": "consumer inflation", "ppi": "producer inflation",
                "jobs": "the employment report", "pce": "PCE inflation and personal income", "gdp": "gross domestic product",
                "claims": "weekly jobless claims", "eci": "employment costs", "jolts": "job openings"}
    macro, used = [], set()
    for row in sorted(brief.get("macro", []), key=lambda value: value["event_at"]):
        if row.get("time_status") not in {"verified", "cached"}:
            continue
        family = publishers.category(row["eventName"])
        if family not in families or family in used:
            continue
        used.add(family)
        at = checked_time(row["event_at"]).astimezone(zone)
        status = "A previously checked, cached schedule lists" if row["time_status"] == "cached" else "The publisher schedule lists"
        macro.append(f"{status} {families[family]} for {at.strftime('%A, %B %d at %I:%M %p %Z')}."
                     + (" Recheck the publisher because live coverage is limited." if row["time_status"] == "cached" else ""))
    ahead.extend(macro[:2])
    if not ahead:
        ahead.append("The available company announcements and calendars did not establish a dated catalyst. Check company sources before planning around an event.")
    if plan["issues"]:
        ahead.append("Calendar or company-news coverage is incomplete; unverified dates and times remain uncertain.")
    watching = ["For the next session, watch whether market leadership holds and how companies guide around scheduled releases. Confirm the research view with current price, volume and original announcements before acting."]
    notes = ["Sources and full evidence: /storylog · /fullreport · /catalysts · /calendar · /specialalerts", "Research only. Not financial advice."]
    groups = list(zip(HEADERS, (market, companies, ahead, watching, notes)))
    def render():
        return prefix + "\n\n" + "\n\n".join(header + "\n" + "\n\n".join(body) for header, body in groups)
    text = render()
    # Drop optional whole paragraphs rather than truncating spoken facts or qualifications.
    protected = set(story_paragraphs.values())
    if brief.get("market_events"):
        protected.add(market[1])
    for body, minimum in ((market, 1), (companies, 1), (ahead, 2)):
        while len(text) > MAX_NEWS_CHARS and len(body) > minimum:
            removable = [index for index in range(1, len(body)) if body[index] not in protected]
            if body is ahead and plan["issues"]:
                removable = [index for index in removable if index != len(body) - 1]
            if not removable:
                break
            body.pop(removable[-1])
            text = render()
    for story in reversed(editor.selected_stories(plan)):
        if len(text) <= MAX_NEWS_CHARS:
            break
        paragraph = story_paragraphs[story["id"]]
        (companies if story["kind"] == "company" else market).remove(paragraph)
        story.update(decision="skip", reason="Narration length budget; source qualification kept with remaining stories")
        text = render()
    result = validate_news_brief(text)
    if not result["passes"]:
        raise ValueError("News brief quality review failed: " + "; ".join(result["missing_headers"] + result["research_context_errors"] + result["greeting_errors"]))
    editor.review_and_record(plan, text, story_paragraphs, research_report)
    return text
