"""Explicit maintenance designations and targeted financial sanctions.

Facts come from an admitted original body. Headline wording only selects a
reader; it cannot establish a designation, location, legal effect or revenue.
"""

import re

from src.intelligence.original_disclosures import issuer_sentence, sentences
from src.intelligence.special_alert_sources import company_url


UNCERTAIN = r"\b(?:not|no|could|may|might|would|cancelled|canceled|failed|hypothetical|previously|earlier|reportedly|last year|pending|subject to|provisional|awaiting)\b"
PLATFORM = r"\bC[-\u2011 ]?130(?:J(?:[- ]30)?)?(?: (?:Super )?Hercules)?\b"
COUNT = r"(?:[1-9]\d{0,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"


def family(story):
    title = story.get("title", "")
    symbol = story.get("publisher_symbol", "")
    if (story.get("kind") == "company" and symbol in {"NOC", "LMT", "RTX", "GD", "AVAV", "KTOS"}
            and company_url(symbol, story.get("url", "")) and re.search(PLATFORM, title, re.I)
            and re.search(r"\bcertified\b.{0,55}\b(?:maintenance )?depot\b", title, re.I)):
        return "maintenance"
    if (story.get("kind") == "macro" and story.get("source") == "U.S. Treasury"
            and re.search(r"\bsanctions?\b", title, re.I)
            and re.search(r"\bmoney services businesses\b", title, re.I)):
        return "financial sanctions"
    return ""


def safe(row):
    return len(row) <= 650 and not re.search(UNCERTAIN, row, re.I) and not re.search(r'["\u201c\u201d]', row)


def maintenance_facts(story, text):
    if family(story) != "maintenance":
        return []
    rows = sentences(text)
    designations, locations, scopes = [], [], []
    for index, row in enumerate(rows):
        match = re.search(r"\b(?:has been|was|is) (?:selected|designated|recognized) as (?:a |an? )?"
                          r"(Certified (?:(?:Continental )?U\.?S\.? )?(?:maintenance )?depot)\b.{0,35}"
                          r"(?:for )?(?:the )?(" + PLATFORM + r")", row, re.I)
        if match and safe(row):
            prefix = row[:match.start()]
            if issuer_sentence(story, prefix) and not re.search(r"\b(?:said|says|supplier|partner|competitor|whose|which|while)\b", prefix, re.I):
                platform = re.sub(r"^C[-\u2011 ]?130", "C-130", match[2], flags=re.I)
                designations.append((index, match[1], platform, row))
        if safe(row) and issuer_sentence(story, row) and re.search(PLATFORM, row, re.I) and re.search(r"\b(?:maintenance|depot)\b", row, re.I):
            location = re.search(r"\bat (?:the company['\u2019]s |its )?([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,3}), "
                                 r"([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,2}),? (?:facility|site)\b", row)
            if location:
                locations.append((location[1] + ", " + location[2], row))
    if len({(d.casefold(), p.casefold()) for _, d, p, _ in designations}) != 1 or len({v for v, _ in locations}) != 1:
        return []
    index, designation, platform, source = designations[0]
    location, location_source = locations[0]
    facts = [
        {"field":"maintenance_designation", "value":designation, "evidence":source,
         "status":"company-reported designation; funded orders not established"},
        {"field":"maintenance_platform", "value":platform, "evidence":source},
        {"field":"maintenance_location", "value":location, "evidence":location_source},
    ]
    for row in rows[index+1:index+3]:
        if (safe(row) and re.match(r"As a certified depot,", row, re.I)
                and issuer_sentence(story, row) and re.search(r"\bwill provide\b", row, re.I)
                and re.search(r"\brepair, overhaul (?:and|&) inspection\b", row, re.I)):
            scopes.append(("repair, overhaul and inspection", row))
    if len({v for v, _ in scopes}) == 1:
        value, source = scopes[0]
        facts.append({"field":"maintenance_scope", "value":value, "evidence":source,
                      "status":"planned services; completed work and revenue not established"})
    return facts


def sanctions_facts(story, text):
    if family(story) != "financial sanctions":
        return []
    rows = sentences(text)
    actions = []
    for index, row in enumerate(rows):
        match = re.search(r"\b(?:OFAC\)|OFAC|Treasury) (?:has )?(designated|sanctioned) (" + COUNT + r") "
                          r"(money services businesses) (?:based in|in) "
                          r"([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,3})(?= that\b| which\b| to\b|[,.])", row)
        if match and safe(row):
            actions.append((index, match, row))
    if len({(m[1], m[2], m[3], m[4]) for _, m, _ in actions}) != 1:
        return []
    index, match, source = actions[0]
    facts = [
        {"field":"sanctions_action", "value":match[1], "evidence":source},
        {"field":"sanctions_targets", "value":match[2] + " " + match[3], "evidence":source},
        {"field":"sanctions_jurisdiction", "value":match[4], "evidence":source},
    ]
    for row in rows[index+1:index+3]:
        if (safe(row) and re.match(r"(?:These companies|These businesses|The designated businesses)\b", row)
                and re.search(r"\bdigital assets\b", row, re.I) and re.search(r"\b(?:exchange|convert|transactions?)\b", row, re.I)):
            facts.append({"field":"sanctions_channel", "value":"digital-asset transactions", "evidence":row})
            break
    return facts


def material(facts, kind):
    fields = {row["field"] for row in facts}
    required = ({"maintenance_designation", "maintenance_platform", "maintenance_location"} if kind == "maintenance"
                else {"sanctions_action", "sanctions_targets", "sanctions_jurisdiction"})
    return required <= fields


def summary(evidence, name="Northrop Grumman"):
    fields = {row["field"]:row["value"] for row in evidence["facts"]}
    if evidence["schema"] == 12:
        designation = "certified U.S. depot" if re.search(r"\bU\.?S\.?\b", fields["maintenance_designation"]) else "certified depot"
        text = (name + " said its " + fields["maintenance_location"] + " facility was selected as a " + designation
                + " for the " + fields["maintenance_platform"] + " fleet.")
        if "maintenance_scope" in fields:
            text += " Planned services include " + fields["maintenance_scope"] + "."
        return text
    text = ("Treasury said OFAC " + fields["sanctions_action"] + " " + fields["sanctions_targets"]
            + " based in " + fields["sanctions_jurisdiction"] + ".")
    if "sanctions_channel" in fields:
        text += " The release describes their role in digital-asset transactions."
    return text


def review(evidence):
    if evidence["schema"] == 12:
        why = "The designation supports a potential aircraft-maintenance workload. Sales depend on service orders, site throughput and delivery costs."
        watch = "Watch for maintenance orders, site utilization, staffing costs and revenue timing."
        gaps = ["funded maintenance orders", "contract value", "revenue timing"]
    else:
        why = "The immediate business question is payment and counterparty exposure to the named firms. Effects on tracked companies require their own disclosures."
        watch = "Check disclosed payment channels and counterparty exposure to the designated firms."
        gaps = ["tracked-company exposure", "earnings impact"]
    return {"evidence":evidence,
            "facts":"; ".join(row["field"].replace("_", " ") + ": " + row["value"] for row in evidence["facts"]) + ".",
            "why":why, "watch":watch, "not_established":gaps}
