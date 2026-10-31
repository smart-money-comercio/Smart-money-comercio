"""Narrow, reproducible facts from an admitted EIA solar/storage report."""

import re
from urllib.parse import urlsplit


def solar_storage_report(story):
    host = (urlsplit(story.get("url", "")).hostname or "").lower()
    return (story.get("source") == "EIA" and story.get("kind") == "macro"
            and (host == "eia.gov" or host.endswith(".eia.gov"))
            and bool(re.search(r"\bsolar\b", story.get("title", ""), re.I))
            and bool(re.search(r"\bco.located battery storage\b", story.get("title", ""), re.I)))


def storage_facts(text):
    pattern = (r"As of ([A-Z][a-z]+ 20\d{2}), ((?:over|more than|about|approximately) )?"
               r"(\d+(?:\.\d+)?)% of new utility-scale solar capacity added this year "
               r"is co-located with operable battery storage, compared with (\d+(?:\.\d+)?)% in (20\d{2})")
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        match = re.search(pattern, sentence)
        if (not match or len(sentence) > 600 or re.search(r"\b(not|no|could|may|might|forecast|projected|hypothetical)\b", sentence, re.I)
                or not 0 <= float(match[3]) <= 100 or not 0 <= float(match[4]) <= 100
                or int(match[5]) >= int(match[1][-4:])):
            continue
        values = (("solar_storage_period", match[1]),
                  ("solar_storage_share", (match[2] or "") + match[3] + "%"),
                  ("solar_storage_comparison", match[4] + "% in " + match[5]))
        return [{"field": key, "value": value, "evidence": sentence} for key, value in values]
    return []


def storage_narration(evidence):
    facts = {row["field"]: row["value"] for row in evidence["facts"]}
    if not all(key in facts for key in ("solar_storage_period", "solar_storage_share", "solar_storage_comparison")):
        return ""
    return ("EIA reports that, as of " + facts["solar_storage_period"] + ", " + facts["solar_storage_share"]
            + " of new utility-scale solar capacity added that year was paired with operable battery storage, compared with "
            + facts["solar_storage_comparison"])


STORAGE_WHY = "For investors, the question is whether pairing storage with solar improves project economics after installation and operating costs."
STORAGE_WATCH = "Compare storage costs, power-sale contracts and project returns; this industry trend does not establish profits for any listed company."
