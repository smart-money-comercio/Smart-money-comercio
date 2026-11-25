"""Read the dated FOMC meeting record through its matching release notice."""

from datetime import datetime
from html.parser import HTMLParser
import math
import re
from urllib.parse import urljoin

from src.intelligence import discount_minutes
from src.intelligence.policy_analysis import rate_facts, release_clock
from src.intelligence.special_alert_sources import NY, timestamp


HOST = "https://www.federalreserve.gov"
HEADING = "Minutes of the Federal Open Market Committee"
MEETING = (r"(?P<month>[A-Z][a-z]+) (?P<start>\d{1,2})\s*[-–—]\s*"
           r"(?:(?P<end_month>[A-Z][a-z]+) )?(?P<end>\d{1,2}), (?P<year>20\d\d)")
SECTION = "Committee Policy Actions"
STABILITY = "Staff Review and Policymakers' Discussion of Financial Stability"
NUMBERS = dict(zip(("one", "two", "three", "four", "five", "six"), range(1, 7)))
DISSENT = re.compile(
    r"\b(one|two|three|four|five|six|[1-6]) members? voted against the decision to "
    r"(maintain|raise|lower) the target range for the federal funds rate, preferring "
    r"(?:an? )?(increase|decrease) of (\d{1,3}) basis points? in the target range at this meeting\.", re.I)
AI = re.compile(
    r"(?:In their discussion of financial stability, )?(almost all|most|many|several|some|a few) participants (?:commented on|discussed) "
    r"(?:the )?risks associated with a scenario in which (?:the )?returns on (?:AI|artificial intelligence) investment "
    r"(?:turned out to be disappointing to investors|disappointed investors)\.", re.I)


def is_minutes(story):
    return discount_minutes.matches(story) or (story.get("source") == "Federal Reserve" and story.get("title", "").startswith(HEADING + ", "))


def reference(story):
    if discount_minutes.matches(story):
        return discount_minutes.reference(story)
    title = story.get("title", "")
    match = re.fullmatch(re.escape(HEADING) + ", " + MEETING, title)
    at = timestamp(story.get("published"))
    if not is_minutes(story) or not match or not at:
        raise ValueError("Fed minutes require a dated meeting and release notice")
    year = match["year"]
    start = datetime.strptime(f"{match['month']} {match['start']}, {year}", "%B %d, %Y").date()
    end = datetime.strptime(f"{match['end_month'] or match['month']} {match['end']}, {year}", "%B %d, %Y").date()
    released = at.astimezone(NY).date()
    if (not start <= end < released or (end-start).days > 4
            or not re.fullmatch(re.escape(HOST) + f"/newsevents/pressreleases/monetary{released:%Y%m%d}[a-z]\\.htm", story["url"])):
        raise ValueError("Fed minutes meeting and release dates do not match the original notice")
    return end, HOST + f"/monetarypolicy/fomcminutes{end:%Y%m%d}.htm"


class Page(HTMLParser):
    blocks = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "li", "section", "blockquote", "title"}

    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.hidden = [], [], 0
        self.feed(body)
        self.lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines() if line.strip()]

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag in self.blocks:
            self.parts.append("\n")
        if tag == "a":
            self.links.append(dict(attrs).get("href") or "")

    def handle_endtag(self, tag):
        if not self.hidden and tag in self.blocks:
            self.parts.append("\n")
        if tag in {"script", "style", "nav", "footer"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(re.sub(r"\s+", " ", data))


def read_time(payload, expected_url, published, now, *, binary=False):
    stamp = payload.get("fetched_at_epoch")
    if (payload.get("status") != "ok" or payload.get("final_url", payload.get("url")) != expected_url
            or not isinstance(payload.get("body"), bytes if binary else str) or type(stamp) not in (float, int) or not math.isfinite(stamp)
            or not -60 <= now.timestamp()-stamp <= 21600 or stamp < published.timestamp()-60):
        raise ValueError("Fed minutes page unavailable, redirected or outside the observation window")
    return stamp


def decision_facts(line):
    statement = line.strip(' "“”')
    if not re.match(r"^(?:The )?(?:Committee|Federal Open Market Committee|FOMC) (?:decided|voted|agreed) to ", statement, re.I):
        return []
    return rate_facts(statement)


def facts(story, text):
    if discount_minutes.matches(story):
        return discount_minutes.facts(story, text)
    _, doc_url = reference(story)
    dates = story["title"].split(", ", 1)[1]
    if story.get("document_url") != doc_url:
        raise ValueError("Fed minutes require the original meeting document")
    lines = text.splitlines()
    if len(lines) < 3 or lines[0] != dates or lines.count(SECTION) != 1:
        raise ValueError("Fed minutes excerpt has a different meeting or section")
    boundary = lines.index(SECTION)
    stability = lines[2:boundary] if lines[1] == STABILITY else []
    if boundary != 1 and not stability:
        raise ValueError("Unexpected Fed minutes excerpt sections")
    policy = lines[boundary+1:]
    candidates = [row for line in policy for row in decision_facts(line)]
    actions = {(row["field"], row["value"]) for row in candidates}
    if len(actions) != 2:
        raise ValueError("Fed minutes lack an unambiguous committee decision and target range")
    results = candidates[:2]
    action = results[0]["value"]
    dissents = [(m, line) for line in policy if (m := DISSENT.fullmatch(line))]
    if len(dissents) == 1:
        match, line = dissents[0]
        if ({"maintain": "held", "raise": "raised", "lower": "lowered"}[match[2].lower()] == action
                and 0 < int(match[4]) <= 100):
            n = NUMBERS.get(match[1].lower()) or int(match[1])
            results.append({"field": "dissent", "value": f"{n} {match[3].lower()} {int(match[4])}", "evidence": line})
    risk = [(m, line) for line in stability if (m := AI.fullmatch(line))]
    if len(risk) == 1:
        results.append({"field": "ai_risk_discussion", "value": risk[0][0][1].lower(), "evidence": risk[0][1]})
    return results


def read(row, notice, fetch, now, budget):
    story = {"source": "Federal Reserve", "url": row["link"], "title": row["title"], "published": row["published"]}
    end, url = reference(story)
    published = timestamp(row["published"])
    first = read_time(notice, story["url"], published, now)
    page = Page(notice["body"])
    def norm(value):
        return re.sub("[–—]", "-", value)
    date_line = published.astimezone(NY).strftime("%B %d, %Y").replace(" 0", " ")
    clocks = [s for s in page.lines if s.startswith("For release at")]
    if (norm(story["title"]) not in [norm(s) for s in page.lines] or date_line not in page.lines or len(clocks) != 1
            or release_clock(date_line + " " + clocks[0]) != published
            or url not in {urljoin(story["url"], link) for link in page.links}):
        raise ValueError("Fed release title, publication clock or minutes link did not match")
    if budget is not None and not budget.take():
        raise ValueError("Fed minutes document deferred by the shared refresh budget")
    document = fetch(url)
    binary = discount_minutes.matches(story)
    second = read_time(document, url, published, now, binary=binary)
    if binary:
        excerpt = discount_minutes.decision_section(document["body"], end)
        facts({**story, "document_url": url}, excerpt)
        return {"title": row["title"], "url": row["link"], "published": row["published"], "text": excerpt,
                "document_url": url, "checked_at_epoch": min(first, second)}
    lines = Page(document["body"]).lines
    dates = story["title"].split(", ", 1)[1]
    if not any(line == HEADING and any(norm(v) == norm(dates) for v in lines[i+1:i+4]) for i, line in enumerate(lines)):
        raise ValueError("Original Fed minutes do not identify the requested meeting")
    # The policy section can be far beyond the first 6,000 characters.
    body = "\n".join(lines)
    pattern = r"(?:^|\n)" + SECTION + r"(?=\s)"
    sections = re.split(pattern, body)
    if len(sections) != 2:
        raise ValueError("Fed minutes policy actions section missing or ambiguous")
    policy = re.split(r"\n(?:Notation Vote|Attendance|Footnotes|Return to text)\b", sections[1], maxsplit=1)[0]
    statements = re.split(r'(?<=[.!?])["”]?\s+|\n+', policy)
    decisions = [s.strip(' "“”') for s in statements if decision_facts(s)]
    dissents = [m[0] for s in statements if (m := DISSENT.fullmatch(s.strip(' "“”')))]
    first_section = sections[0]
    stability = re.search(r"Staff Review and Policymakers['’] Discussion of Financial Stability\s+(.+?)(?:\nDevelopments in Financial Markets|\nStaff Review of the Economic Situation|$)", first_section, re.S)
    risks = []
    if stability:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", stability[1]):
            if AI.fullmatch(sentence):
                risks.append(sentence)
    excerpt = "\n".join([dates, *([STABILITY, *risks] if risks else []), SECTION, *decisions, *dissents])
    from src.intelligence.story_analysis import MAX_EXCERPT
    if len(excerpt) > MAX_EXCERPT:
        raise ValueError("Fed minutes excerpt exceeds the retained evidence limit")
    facts({**story, "document_url": url}, excerpt)
    return {"title": row["title"], "url": row["link"], "published": row["published"], "text": excerpt,
            "document_url": url, "checked_at_epoch": min(first, second)}


def review(evidence):
    if evidence["source_url"].endswith(".pdf"):
        return discount_minutes.review(evidence)
    fields = {row["field"]: row["value"] for row in evidence["facts"]}
    end = datetime.strptime(evidence["source_url"].split("fomcminutes")[1][:8], "%Y%m%d")
    when = f"{end:%B} {end.day}"
    verb = fields["policy_action"]
    decision = f"At the meeting that ended {when}, the Fed {verb} its target rate range " + ("at " if verb == "held" else "to ") + fields["policy_target_range"] + "."
    split = ""
    opening = ""
    if dissent := fields.get("dissent"):
        count, direction, size = dissent.split()
        people = ("One voter" if count == "1" else next(key.capitalize() for key, value in NUMBERS.items() if value == int(count)) + " voters")
        change = {"25": "quarter-point", "50": "half-point"}.get(size, size + "-basis-point")
        preference = change + (" increase" if direction == "increase" else " cut")
        split = f"{people} preferred a {preference}."
        stance = {"held": "held rates steady", "raised": "raised rates", "lowered": "cut rates"}[verb]
        opening = f"The Fed {stance} in {end:%B}. Its minutes show {people.lower()} favored a {preference}."
    detail = fields.get("ai_risk_discussion")
    risk = (f"{detail.capitalize()} participants discussed the risk that AI investments could disappoint investors." if detail else "")
    watch = ("Watch whether the companies funding new AI capacity earn enough from customers to cover its cost." if risk else
             "Watch the next inflation and employment releases for evidence that could change the case for rates.")
    return {"evidence": evidence, "facts": " ".join(s for s in (decision, split, risk) if s),
            "body": " ".join(s for s in (decision, risk or split, watch) if s), "why": (risk or split or decision),
            "opening": opening or (f"The Fed's {end:%B} minutes show policymakers weighed the risk of disappointing returns on AI investment." if risk else ""),
            "watch": watch}
