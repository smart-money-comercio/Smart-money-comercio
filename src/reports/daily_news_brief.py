"""A short spoken-friendly edition of the same validated research report."""

from __future__ import annotations

from datetime import datetime
from itertools import combinations, product
import re
from zoneinfo import ZoneInfo

from src.intelligence.calendar_context import checked_time, publishers
from src.intelligence.company_catalyst_context import build_company_catalyst_brief
from src.intelligence import news_editor as editor
from src.intelligence.daily_brief_analysis import analyze_report, retained_review
from src.intelligence.market_brief import MIN_MARKET_WORDS, MAX_MARKET_WORDS, story_topics, word_count
from src.utils.report_consistency import report_greeting, validate_report_greeting


TITLE = "Smart Money Daily News Brief"
MAX_NEWS_CHARS = 3800
NARRATION_WORDS_PER_MINUTE = 180
MIN_NARRATION_SECONDS = 60
MIN_NARRATION_WORDS = 180
HEADERS = ["Market Update", "Companies in Focus", "Global and Defense Watch", "What's Ahead", "What We're Watching", "Research Notes"]
IPO_HEADER = "IPO & Capital Markets"
ALL_HEADERS = [IPO_HEADER] + HEADERS
NAMES = {"MSFT": "Microsoft", "NVDA": "Nvidia", "PLTR": "Palantir", "TSLA": "Tesla",
         "TSM": "Taiwan Semiconductor", "AVGO": "Broadcom", "AVAV": "AeroVironment", "CRWD": "CrowdStrike",
         "AAPL": "Apple", "AMZN": "Amazon", "GOOG": "Alphabet", "GOOGL": "Alphabet", "META": "Meta Platforms",
         "AMD": "Advanced Micro Devices", "INTC": "Intel", "NOC": "Northrop Grumman", "LMT": "Lockheed Martin",
         "KTOS": "Kratos Defense", "CACI": "CACI International"}


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


def market_takeaway(moves: dict, is_open: bool) -> str:
    """Lead with an observation, keeping causes outside the price evidence."""
    indexes = [float(moves[key].rstrip("%")) for key in ("S&P", "Nasdaq", "Russell") if key in moves]
    if len(indexes) < 3:
        return "Market coverage is incomplete; this edition separates the available figures from company news and the calendar."
    if float(moves["Nasdaq"].rstrip("%")) <= -2:
        return "The Nasdaq's decline leads this edition's market update."
    if float(moves.get("Oil", "0%").rstrip("%")) >= 1.5:
        return "Oil and inflation are on the watch list alongside stocks."
    if all(value > 0 for value in indexes):
        return "The indexes we track are higher in this snapshot." if is_open else "The latest session brought gains across the indexes we track."
    if all(value < 0 for value in indexes):
        return "The indexes we track are lower in this snapshot." if is_open else "The latest session brought declines across the indexes we track."
    return "The latest snapshot shows a mixed picture across U.S. indexes."


def market_outlook(moves: dict, breadth) -> str:
    """Offer conditional follow-up questions, never an inferred market cause."""
    if not all(key in moves for key in ("S&P", "Nasdaq", "Russell")):
        return "Our view: A complete, dated market snapshot is the next useful check before drawing a broad market conclusion."
    if float(moves["Nasdaq"].rstrip("%")) <= -2:
        return "Our view: Watch whether the Nasdaq stabilizes and more watchlist names recover. A single rebound would leave the question of a lasting recovery open."
    if float(moves.get("Oil", "0%").rstrip("%")) >= 1.5:
        return "Our view: Higher energy costs can put pressure on company margins. Watch whether that appears in earnings guidance and whether upcoming inflation reports change the outlook."
    if breadth and int(breadth[2]) > int(breadth[1]) and all(float(moves[key].rstrip("%")) > 0 for key in ("S&P", "Nasdaq", "Russell")):
        return "Our view: Index gains are not shared by most names in this research watchlist. Watch whether participation broadens in the next session."
    return "Our view: Watch whether market leadership holds through the next round of earnings and economic releases."


def company_followup(stories: list[dict]) -> list[str]:
    companies = [story for story in stories if story["kind"] == "company"]
    if any(re.search(r"\b(?:china|export)\b", story["title"], re.I) for story in companies):
        return ["For the companies in these reports, the follow-up is their own disclosure on regional sales and export access."]
    if any(re.search(r"\b(?:AI|cloud|data.center)\b", story["title"], re.I) for story in companies):
        return ["For AI and cloud companies, watch whether spending plans translate into reported revenue and margins."]
    return []


def calendar_implication(families: set[str]) -> str:
    if "fomc_decision" in families:
        return "Why it matters: Watch the Fed's guidance on the rate outlook and what it could mean for growth-company financing and valuations."
    if families & {"cpi", "ppi", "pce"}:
        return "Why it matters: Inflation releases will test the cost backdrop and expectations for interest rates; the figures and policy response are still ahead."
    if families & {"jobs", "claims", "jolts", "eci"}:
        return "Why it matters: Labor releases offer a check on demand and wage pressure. Watch the trend alongside company guidance."
    if "gdp" in families:
        return "Why it matters: Growth data offer a check on demand. Compare the release with company guidance before changing the outlook."
    return ""


def spoken_text(text: str) -> str:
    """Extract the spoken copy, excluding display metadata and research links."""
    output, speaking = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"(?:Hello|Good (?:morning|afternoon|evening))\.", stripped):
            speaking = True
        if stripped == "Research Notes":
            break
        if speaking and stripped and stripped not in ALL_HEADERS:
            output.append(re.sub(r"https?://\S+|/[A-Za-z][A-Za-z0-9_]*", "", stripped))
    return "\n\n".join(output)


def narration_metrics(text: str) -> dict:
    words = len(re.findall(r"\b[^\W_]+(?:['’\-][^\W_]+)*\b", spoken_text(text)))
    return {"spoken_words": words, "estimated_narration_seconds": round(words * 60 / NARRATION_WORDS_PER_MINUTE, 1),
            "narration_wpm": NARRATION_WORDS_PER_MINUTE, "min_narration_words": MIN_NARRATION_WORDS,
            "min_narration_seconds": MIN_NARRATION_SECONDS}


def market_detail(moves: dict, breadth) -> list[str]:
    """Derive extra context from the same dated observations when it is needed."""
    labels = {"S&P": "S&P 500", "Nasdaq": "Nasdaq Composite", "Russell": "Russell 2000"}
    values = [(label, float(moves[key].rstrip("%"))) for key, label in labels.items() if key in moves]
    details = []
    if len(values) >= 2:
        strongest, weakest = max(values, key=lambda item: item[1]), min(values, key=lambda item: item[1])
        if strongest[1] == weakest[1]:
            details.append("The available index returns were equal in this snapshot, so this measure does not distinguish a leader among those indexes.")
        else:
            details.append(f"Among the quoted indexes, the {strongest[0]} had the strongest return and the {weakest[0]} the weakest. The gap between them was {strongest[1] - weakest[1]:.2f} percentage points.")
    if breadth:
        up, down, total = map(int, breadth.groups())
        if total > 0 and 0 <= up + down <= total:
            details.append(f"That represents {100 * up / total:.1f} percent advancing and {100 * down / total:.1f} percent declining within the quoted watchlist. These percentages describe the companies we follow, rather than every listed U.S. stock.")
    return details


def validate_news_brief(text: str) -> dict:
    lines = text.splitlines()
    missing = [header for header in HEADERS if header not in lines]
    duplicates = [header for header in ALL_HEADERS if lines.count(header) > 1]
    qualification = []
    for paragraph in text.split("\n\n"):
        lowered = paragraph.lower()
        if "earnings calendar lists" in lowered or "company confirmation is pending" in lowered:
            qualification.append("Unconfirmed company dates are excluded from the news edition")
        if "headline report" in lowered or "headline-only" in lowered:
            qualification.append("Original-source reports are required; unconfirmed headline stories are excluded")
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
    narration = narration_metrics(text)
    narration_errors = [] if narration["spoken_words"] >= MIN_NARRATION_WORDS else [
        f"Narration minimum not met: {narration['spoken_words']} spoken words; need {MIN_NARRATION_WORDS} for {MIN_NARRATION_SECONDS} seconds at {NARRATION_WORDS_PER_MINUTE} words per minute."]
    market_lines = []
    if "Market Update" in lines:
        for line in lines[lines.index("Market Update") + 1:]:
            if line in ALL_HEADERS:
                break
            market_lines.append(line)
    market_words = word_count("\n".join(market_lines))
    market_errors = [] if MIN_MARKET_WORDS <= market_words <= MAX_MARKET_WORDS else [
        f"Market segment needs {MIN_MARKET_WORDS}–{MAX_MARKET_WORDS} spoken words for 15–30 seconds; found {market_words}."]
    return {"format": "news", "chars": len(text), "max_chars": MAX_NEWS_CHARS, "missing_headers": missing,
            "duplicate_headers": duplicates, "removed_headers_present": [], "what_changed_bullets": 0,
            "ai_summary_ok": not missing, "risk_consistency_errors": [], "greeting_errors": greeting,
            "research_context_errors": qualification, "source_qualification_errors": qualification,
            **narration, "narration_errors": narration_errors,
            "market_spoken_words": market_words, "market_estimated_seconds": round(market_words * 60 / NARRATION_WORDS_PER_MINUTE, 1),
            "market_segment_errors": market_errors,
            "passes": bool(text.strip()) and len(text) <= MAX_NEWS_CHARS and not (missing or duplicates or greeting or qualification or narration_errors or market_errors)}


def build_daily_news_brief(research_report: str, catalyst_brief: dict | None = None) -> str:
    from src.reports.report_quality import describe_quality_failure, split_report_sections, validate_daily_report_quality
    quality = validate_daily_report_quality(research_report)
    if quality.get("format") == "news":
        raise ValueError("The underlying research report did not pass quality review: expected the detailed research format")
    if not quality["passes"]:
        raise ValueError("The underlying research report did not pass quality review: " + describe_quality_failure(quality))
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
    executive = sections["Executive Summary"]
    moves = dict(re.findall(r"(S&P|Nasdaq|Russell|VIX|Oil|TLT)\s+([+-]?\d+(?:\.\d+)?%)", executive))
    if quote_day is None:
        moves = {}
    prefix = f"{TITLE}\nDate: {dated[1]}\nGenerated: {generated[1]} {generated[2]}\nMarket data: {data_label}\n\n{report_greeting(now)}"
    breadth = re.search(r"Breadth: (\d+) up / (\d+) down / (\d+) quoted", snapshot)
    brief = catalyst_brief if catalyst_brief is not None else build_company_catalyst_brief(now=now)
    plan = editor.build_editorial_plan(brief, now)
    story_paragraphs = {story["id"]: editor.render_story(story, zone, NAMES) for story in editor.selected_stories(plan)}
    no_company_story = "No new source-confirmed company report met the editorial checks for this edition."
    ahead = []
    # The cached Nasdaq rows are estimates, not issuer-confirmed schedules.
    # Keep them in /calendar and /catalysts rather than narrating them as news.
    families = {"fomc_decision": "the Federal Reserve's interest-rate decision", "cpi": "consumer inflation", "ppi": "producer inflation",
                "jobs": "the employment report", "pce": "PCE inflation and personal income", "gdp": "gross domestic product",
                "claims": "weekly jobless claims", "eci": "employment costs", "jolts": "job openings"}
    macro, used, macro_families = [], set(), []
    for row in sorted(brief.get("macro", []), key=lambda value: value["event_at"]):
        if row.get("time_status") not in {"verified", "cached"}:
            continue
        family = publishers.category(row["eventName"])
        if family not in families or family in used:
            continue
        used.add(family)
        macro_families.append(family)
        at = checked_time(row["event_at"]).astimezone(zone)
        status = "A previously checked, cached schedule lists" if row["time_status"] == "cached" else "The publisher schedule lists"
        macro.append(f"{status} {families[family]} for {at.strftime('%A, %B %d at %I:%M %p %Z')}."
                     + (" Recheck the publisher because live coverage is limited." if row["time_status"] == "cached" else ""))
    ahead.extend(macro[:2])
    implication = calendar_implication(set(macro_families[:2]))
    if implication:
        ahead.append(implication)
    if not ahead:
        ahead.append("The available company announcements and calendars did not establish a dated catalyst. Check company sources before planning around an event.")
    if plan["issues"]:
        ahead.append("Calendar or company-news coverage is incomplete; unverified dates and times remain uncertain.")
    notes = ["The full research edition includes the company rankings, trade-plan conditions and risk checks behind this brief: /fullreport · /tradeplans",
             "Sources and full evidence: /storylog · /catalysts · /calendar · /specialalerts", "Research only. Not financial advice."]
    initial_stories = sorted(editor.selected_stories(plan), key=editor.news_order)
    from src.intelligence.company_focus import history_context
    focus_history = history_context(now)
    chosen = None
    last_result = None
    # At most three stories: try the fuller, higher-priority editions first.
    # Each attempt starts from all sourced market/calendar context.
    for count in range(len(initial_stories), -1, -1):
        for indexes, focus_limit in product(combinations(range(len(initial_stories)), count), (3, 2, 1)):
            retained = [initial_stories[index] for index in indexes]
            analysis = analyze_report(research_report, retained, presentation="news", focus_context={**focus_history, "limit": focus_limit})
            insights = analysis["insights"]
            if not (analysis["evidence"]["moves"] or analysis["evidence"]["companies"] or retained or macro):
                raise ValueError("Insufficient admitted evidence for a daily news edition")
            market_body = [row["text"] for row in insights if row["section"] == "market"]
            company_body = []
            global_body = []
            ipo_body = []
            for story in sorted(retained, key=editor.news_order):
                body = ipo_body if story.get("ipo") or story.get("sec_filing") else global_body if story["kind"] == "macro" or "defense" in story_topics(story) else company_body
                body.append(story_paragraphs[story["id"]])
            company_body += [row["text"] for row in insights if row["section"] == "company"]
            if not company_body:
                company_body.append("Company-specific evidence is limited in this edition; current original disclosures are the next check.")
            if brief.get("market_events"):
                global_body.append("An active market-alert record reports " + brief["market_events"][0]["fact"]
                                   + " This is dated price evidence; it does not establish the cause of the move.")
            global_body += [row["text"] for row in insights if row["section"] == "global"]
            ahead_body = list(ahead)
            if not any(story["kind"] == "company" for story in retained) and not analysis["evidence"]["companies"]:
                company_body.append(no_company_story)
            watching = [row["text"] for row in insights if row["section"] == "watch"]
            if not watching:
                watching.append(market_outlook(moves, breadth if quote_day else None))
            watching += company_followup(retained)
            notes_body = list(notes)
            if not any(story["kind"] == "company" for story in retained) and analysis["evidence"]["companies"]:
                notes_body.insert(-1, no_company_story)
            groups = list(zip(HEADERS, (market_body, company_body, global_body, ahead_body, watching, notes_body)))
            if ipo_body:
                groups.insert(0, (IPO_HEADER, ipo_body))
            if retained:
                lead = min(retained, key=editor.news_order)
                lead_header = IPO_HEADER if lead.get("ipo") or lead.get("sec_filing") else "Global and Defense Watch" if lead["kind"] == "macro" or "defense" in story_topics(lead) else "Companies in Focus"
                groups.sort(key=lambda group: (0 if group[0] == lead_header else 1 if group[0] == "Market Update" else 2, ALL_HEADERS.index(group[0])))

            def render():
                return prefix + "\n\n" + "\n\n".join(header + "\n" + "\n\n".join(body) for header, body in groups)

            text = render()
            extras = [(ahead_body, paragraph) for paragraph in macro[2:]]
            extras += [(watching, paragraph) for paragraph in market_detail(moves, breadth if quote_day else None)]
            for body, paragraph in extras:
                if narration_metrics(text)["spoken_words"] >= MIN_NARRATION_WORDS:
                    break
                body.append(paragraph)
                text = render()

            protected = set(story_paragraphs.values()) | {no_company_story} | {
                row["text"] for row in insights if row["id"] not in {"model_support", "company_price", "participation"}}
            if brief.get("market_events"):
                protected.update(paragraph for paragraph in global_body if paragraph.startswith("An active market-alert record reports "))
            if plan["issues"]:
                protected.add("Calendar or company-news coverage is incomplete; unverified dates and times remain uncertain.")
            for body, minimum in ((company_body, 1), (ahead_body, 2), (watching, 1)):
                while len(text) > MAX_NEWS_CHARS and len(body) > minimum:
                    removable = [index for index in range(1, len(body)) if body[index] not in protected]
                    removed = False
                    for index in reversed(removable):
                        paragraph = body.pop(index)
                        candidate = render()
                        if narration_metrics(candidate)["spoken_words"] >= MIN_NARRATION_WORDS:
                            text, removed = candidate, True
                            break
                        body.insert(index, paragraph)
                    if not removed:
                        break
            result = validate_news_brief(text)
            if last_result is None or result["spoken_words"] > last_result["spoken_words"]:
                last_result = result
            if result["passes"]:
                chosen = (text, retained, analysis)
                break
        if chosen:
            break
    if not chosen:
        errors = last_result["missing_headers"] + last_result["research_context_errors"] + last_result["greeting_errors"] + last_result["narration_errors"] + last_result["market_segment_errors"]
        if last_result["chars"] > MAX_NEWS_CHARS:
            errors.append(f"A complete {MIN_NARRATION_WORDS}-word narration does not fit the {MAX_NEWS_CHARS}-character budget.")
        raise ValueError("News brief quality review failed: " + "; ".join(errors))
    text, retained, analysis = chosen
    plan["lead_story_id"] = min(retained, key=editor.news_order)["id"] if retained else ""
    retained_ids = {story["id"] for story in retained}
    for story in initial_stories:
        if story["id"] not in retained_ids:
            story.update(decision="skip", reason="Narration length budget; sufficient spoken context and complete source qualifications retained")
    editor.review_and_record(plan, text, story_paragraphs, research_report, analyst_review=retained_review(analysis, text))
    return text
