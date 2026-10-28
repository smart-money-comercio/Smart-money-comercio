"""Explicit FOMC decisions from admitted original statement text."""

from datetime import datetime, timedelta, timezone
from fractions import Fraction
import re
from zoneinfo import ZoneInfo


def is_fomc_statement(story: dict) -> bool:
    return (story.get("source") == "Federal Reserve"
            and bool(re.fullmatch(r"Federal Reserve issues FOMC statement\.?", story.get("title", ""), re.I)))


def release_clock(text: str) -> datetime:
    """Use the publisher's explicit release date, time and US Eastern offset."""
    dates = set(re.findall(r"\b([A-Z][a-z]+ \d{1,2}, 20\d{2})\b", text))
    clocks = set(re.findall(r"For release at\s+(\d{1,2}):(\d{2})\s*([ap])\.?m\.?\s+(EDT|EST)\b", text, re.I))
    if len(dates) != 1 or len(clocks) != 1:
        raise ValueError("Fed statement release date or zoned time unavailable or ambiguous")
    hour, minute, period, zone = clocks.pop()
    if not 1 <= int(hour) <= 12 or not 0 <= int(minute) <= 59:
        raise ValueError("Invalid Fed release clock")
    day = datetime.strptime(dates.pop(), "%B %d, %Y")
    offset = timedelta(hours=-4 if zone.upper() == "EDT" else -5)
    at = day.replace(hour=int(hour) % 12 + (12 if period.lower() == "p" else 0),
                     minute=int(minute), tzinfo=timezone(offset))
    if at.astimezone(ZoneInfo("America/New_York")).utcoffset() != offset:
        raise ValueError("Fed release timezone conflicts with its publication date")
    return at


def rate_facts(text: str) -> list[dict]:
    """Never infer a rate, an action or a surprise from a headline or forecast."""
    number = r"(?:\d{1,2}(?:\.\d+|[- ]\d/\d)?|\d/\d)"
    pattern = (r"\b(?:The )?(?:Committee|Federal Open Market Committee|FOMC)\s+"
               r"(?:decided|voted|agreed) to (maintain|keep|leave|raise|increase|lower|reduce|cut)\s+"
               r"(?:the )?target range for the federal funds rate\s+(?:unchanged\s+)?"
               r"(?:by\s+(?:\d(?:/\d)?|one-quarter|one-half|a quarter|a half)\s+percentage points?\s+)?"
               r"(?:at|to)\s+(" + number + r")\s*(?:to|–|—)\s*(" + number + r")\s+percent\b")
    decisions = []
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])|\n+", text):
        if len(sentence) > 650 or re.search(r"\b(?:not|no|could|may|might|would|expects?|preferred|forecast|previously|last meeting)\b", sentence, re.I):
            continue
        match = re.search(pattern, sentence, re.I)
        if not match:
            continue
        def value(raw):
            parts = re.split(r"[- ]", raw, maxsplit=1)
            if len(parts) == 1 and "/" in raw:
                return float(Fraction(raw))
            return float(parts[0]) + (float(Fraction(parts[1])) if len(parts) == 2 else 0)
        try:
            lower, upper = value(match[2]), value(match[3])
        except (ValueError, ZeroDivisionError):
            continue
        if not 0 <= lower < upper <= 25 or upper-lower > 1:
            continue
        action = "held" if match[1].lower() in {"maintain", "keep", "leave"} else "raised" if match[1].lower() in {"raise", "increase"} else "lowered"
        decisions.append((action, f"{lower:g} to {upper:g} percent", sentence))
    if len(decisions) != 1:
        return []
    action, target, quote = decisions[0]
    return [{"field": "policy_action", "value": action, "evidence": quote},
            {"field": "policy_target_range", "value": target, "evidence": quote}]
