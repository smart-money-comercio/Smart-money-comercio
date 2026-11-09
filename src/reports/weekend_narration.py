"""Explicit weekend narration revision; archived revision 1 is left intact."""

from datetime import date
import re

from src.intelligence import weekend_inputs as evidence, company_schedule
from src.intelligence.daily_brief_analysis import NAMES
from src.utils.speech_text import normalize

REVISION = 2


def revision(inputs):
    value = inputs.get("narration_revision", 1)
    if type(value) is not int or value not in {1, REVISION}:
        raise ValueError("Unknown Weekend Outlook narration revision")
    return value


def calendar(packet, periods):
    start, end = date.fromisoformat(periods["next_start"]), date.fromisoformat(periods["next_end"])
    lines = [f"For {start:%B} {start.day} through {end:%B} {end.day}, here are the verified calendar entries."]
    entries = []
    for row in packet["macro"]:
        at = evidence.clock(row["at"]).astimezone(evidence.NY)
        entries.append((at.isoformat(), f"{at:%A}, {at:%B} {at.day}: {row['event']} at {at:%I:%M %p %Z}, according to {row['publisher']}."))
    for row in packet["company"]:
        entries.append((row["event_at"] or row["event_date"], company_schedule.narration(row, evidence.NY, NAMES)))
    if entries:
        lines.extend(text for _, text in sorted(entries))
        lines.append("Our verified calendar is incomplete, so other events may be missing. Estimated earnings dates are excluded.")
    else:
        lines = [f"For the week of {start:%B} {start.day}, no publisher-verified releases or company events qualified for this edition's calendar. Coverage is incomplete; additional events may be scheduled."]
    return "\n".join(lines)


def spoken(text):
    # The Air Force uses both Mk21A and Mark 21A for the same designation:
    # https://www.af.mil/Portals/1/documents/1/annual_report_web.pdf (p. 28).
    text = re.sub(r"\bMk[- ]?21A\b", "Mark twenty-one A", text, flags=re.I)
    text = re.sub(r"\bDefense Enterprise Accounting and Management System\s*\(DEAMS\)",
                  "Defense Enterprise Accounting and Management System", text)
    text = re.sub(r"\bDEAMS\b", "D E A M S", text)
    def agency(match):
        before = text[:match.start()].rstrip()
        article = "The" if not before or before.endswith((".", "!", "?")) else "the"
        return article + " U.S. Department of Labor"
    text = re.sub(r"\b(?:the\s+)?DOL\b", agency, text, flags=re.I)
    return normalize(text, brand_names=True, agency_names=True, disclosure_names=True)
