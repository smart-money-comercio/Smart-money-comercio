"""Discount-window decisions from the final meeting in an original Board PDF."""

from datetime import datetime
from io import BytesIO
import re

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from src.intelligence.special_alert_sources import NY, timestamp


TITLE = "Minutes of the Board's discount rate meetings on "
HOST = "https://www.federalreserve.gov"
RATE = r"\d{1,2}(?:\.\d{1,3})?"
DECISION = re.compile(
    r"\bthe Board (?:also )?approved the establishment of (?:the primary credit rate|"
    r"the interest rate on discounts and advances made under the primary credit program "
    r"\(the primary credit rate\)) at the existing level of (" + RATE + r") percent\.", re.I)
BANK = r"(?:New York|Philadelphia|Boston|Cleveland|Richmond|Atlanta|Chicago|St\. Louis|Minneapolis|Kansas City|Dallas|San Francisco)"
GROUP = BANK + r"(?:(?:, (?:and )?| and )" + BANK + r")*"
VOTE = (r"(?:the )?directors of the Federal Reserve Banks? of (" + GROUP + r") had voted on "
        r"[A-Z][a-z]+ \d{1,2}(?:, 20\d\d)?")
REQUEST = re.compile(r"\b" + VOTE + r"(?:, and " + VOTE + r")?, to establish the primary credit rate at (" +
                     RATE + r") percent \(an increase from (" + RATE + r") percent\)\.", re.I)


def matches(story):
    return story.get("source") == "Federal Reserve" and story.get("title", "").startswith(TITLE)


def reference(story):
    at = timestamp(story.get("published"))
    dates = story["title"].removeprefix(TITLE)
    end = re.search(r"(?:^| and )([A-Z][a-z]+ \d{1,2}, 20\d\d)$", dates)
    if not matches(story) or not end or not at:
        raise ValueError("Board minutes require a dated final meeting")
    day = datetime.strptime(end[1], "%B %d, %Y").date()
    released = at.astimezone(NY).date()
    url = story["url"]
    if day >= released or not re.fullmatch(re.escape(HOST) + f"/newsevents/pressreleases/monetary{released:%Y%m%d}[a-z]\\.htm", url):
        raise ValueError("Board minutes release or meeting date mismatch")
    return day, url.replace("/pressreleases/", "/pressreleases/files/")[:-4] + "1.pdf"


def decision_section(raw, day):
    if not isinstance(raw, bytes) or not raw.startswith(b"%PDF-") or len(raw) > 2_000_000:
        raise ValueError("Invalid Board minutes PDF")
    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 12:
            raise ValueError("Board minutes exceed the page limit")
        text = " ".join(" ".join((page.extract_text() or "") for page in reader.pages).split())
    except (PyPdfError, OSError, IndexError, KeyError) as error:
        raise ValueError("Unreadable Board minutes") from error
    date_text = f"{day:%B} {day.day}, {day.year}"
    parts = re.split(r"\bApproved\.\s+" + re.escape(date_text) + r"\.", text, flags=re.I)
    if len(parts) != 2:
        raise ValueError("Board decision heading does not match the final meeting date")
    section = re.split(r"\bVoting for (?:this action|these actions):", parts[1], maxsplit=1, flags=re.I)
    if len(section) != 2:
        raise ValueError("Board decision section has no vote boundary")
    decisions = list(dict.fromkeys(m[0] for m in DECISION.finditer(section[0])))
    requests = [m[0] for m in REQUEST.finditer(section[0])]
    return "\n".join([date_text, *decisions, *requests])


def facts(story, text):
    day, url = reference(story)
    lines = text.splitlines()
    if story.get("document_url") != url or not lines or lines[0] != f"{day:%B} {day.day}, {day.year}":
        raise ValueError("Board minutes require a matching original PDF and dated decision")
    decisions = [m for line in lines[1:] if (m := DECISION.fullmatch(line))]
    if len({m[1] for m in decisions}) != 1:
        raise ValueError("Board primary credit decision unavailable or ambiguous")
    rate = decisions[0][1]
    result = [{"field": "primary_credit_rate_held", "value": rate, "evidence": decisions[0][0]}]
    requests = [m for line in lines[1:] if (m := REQUEST.fullmatch(line))]
    if len(requests) == 1:
        m = requests[0]
        banks = re.findall(BANK, (m[1] + ", " + (m[2] or "")), re.I)
        if len(set(banks)) == len(banks) and float(m[3]) > float(rate) == float(m[4]):
            result.append({"field": "requested_rate", "value": m[3], "count": len(banks), "evidence": m[0]})
    return result


def review(evidence):
    day = evidence["source_text"].splitlines()[0].split(",")[0]
    rate = evidence["facts"][0]["value"]
    first = f"On {day}, the Fed Board kept its primary lending rate for banks at {rate} percent."
    opening = f"On {day}, the cost of primary credit at the Fed's discount window held steady"
    second = ""
    if len(evidence["facts"]) == 2:
        opening += ", even as Reserve Bank directors sought an increase"
        vote = evidence["facts"][1]
        count = vote["count"]
        second = f" Directors at {count} Reserve {'Bank' if count == 1 else 'Banks'} had requested {vote['value']} percent."
    watch = "Watch the next Board decision for a change in what banks pay to borrow at the discount window."
    return {"evidence": evidence, "facts": first + second, "body": first + second, "opening": opening + ".",
            "why": "The primary credit rate sets the cost of borrowing at the Fed's discount window.", "watch": watch}
