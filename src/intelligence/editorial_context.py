"""Classify source announcements whose wording can imply a stronger event."""

import re


INTEL_TITLE = re.compile(r"^Intel\s*,\s*RadixArk\s+Collaborate\s+to\s+Advance\s+Open\s+AI\s+Inference\s+on\s+Intel\s+Platforms\.?$", re.I)
FED_CALENDAR = re.compile(r"^Federal Reserve announces (?:revised )?tentative schedule of Federal Open Market Committee meetings in 20\d\d\.?$", re.I)


def intel_inference(story):
    return story.get("publisher_symbol") == "INTC" and bool(INTEL_TITLE.fullmatch(story.get("title", "")))


def fed_calendar_notice(story):
    return story.get("source") == "Federal Reserve" and bool(FED_CALENDAR.fullmatch(story.get("title", "")))


def intel_facts(text):
    for line in re.split(r"\n+|(?<=[.!?])\s+(?=[A-Z])", text):
        if len(line) > 360 or not re.search(r"\bIntel announced a collaboration with RadixArk to optimi[sz]e SGLang\b", line, re.I):
            continue
        if re.search(r"\bopen.source (?:AI )?inference\b", line, re.I) and re.search(r"\bfor Intel platforms\b", line, re.I):
            return [{"field": "collaboration_partner", "value": "RadixArk", "evidence": line},
                    {"field": "optimization_target", "value": "SGLang inference software on Intel platforms", "evidence": line}]
    return []


def intel_review(evidence):
    return {"evidence": evidence,
            "facts": "Intel and RadixArk announced work to optimize SGLang, open-source software for running AI models, on Intel hardware.",
            "why": "Wider software support could make it easier for customers to run AI models on Intel hardware.",
            "watch": "Watch for those changes to ship in SGLang and for customers to report using them in production."}
