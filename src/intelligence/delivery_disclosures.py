"""Verify commercial availability and reported delivery facts in original bodies."""

import re

from src.intelligence.original_disclosures import UNCONFIRMED, sentences


EPYC = r"(?P<generation>\d{1,2})\s*(?P<ordinal>st|nd|rd|th)\s+Gen(?:eration)?\s+(?:AMD\s+)?EPYC[™®]?"
AVAILABLE = re.compile(r"\bAMD(?:\s+\([^)]{1,50}\))?\s+(?:today\s+)?(?:announced|announces)\s+(?:the\s+)?general availability of\s+(?:(?:its|the)\s+)?" + EPYC +
                       r"(?:\s+server)?(?:\s+(?P<socket>SP\d{1,2}))?(?:\s+server)?\s+(?:processors|CPUs)\b", re.I)
SHIPPING = re.compile(r"^(?:The\s+)?(?:systems|servers|platforms)\s+(?:powered by|based on|using)\s+(?P<product>[^,.!?]{1,120}?)\s+(?:are\s+(?:now\s+)?shipping|have begun shipping)\s+from\s+[^,.!?]{1,90}", re.I)
CLOUD_SOON = re.compile(r"\bcloud instances from Microsoft Azure and (?:OCI|Oracle Cloud Infrastructure) will be generally available soon\b", re.I)
COUNT = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
DELIVERED = re.compile(r"^(?:The company|Lockheed Martin) has delivered its (?P<count>" + COUNT + r")(?:st|nd|rd|th) GMLRS[®™]? rockets?\b", re.I)
RATE = re.compile(r"\s+and is now producing (?P<qualifier>nearly |about |approximately )?(?P<count>" + COUNT + r") rockets per year\b", re.I)
AHEAD = re.compile(r"\s*[,—–-]\s*a production rate achieved ahead of schedule\b", re.I)


def family(story):
    if story.get("kind") != "company":
        return ""
    title = story.get("title", "")
    symbol = story.get("publisher_symbol")
    if symbol == "AMD" and re.search(EPYC, title, re.I):
        return "server launch"
    if symbol == "LMT" and re.search(r"\bGMLRS\b.{0,45}\bproduction milestone\b", title, re.I):
        return "production milestone"
    return ""


def fact(field, value, row, **qualifiers):
    return {"field": field, "value": value, "evidence": row, **qualifiers}


def server_facts(story, rows):
    generation = re.search(EPYC, story["title"], re.I)["generation"]
    for index, row in enumerate(rows):
        launch = AVAILABLE.search(row)
        if not launch or len(row) > 650 or launch["generation"] != generation or re.search(UNCONFIRMED, row[:launch.end()], re.I):
            continue
        product = generation + launch["ordinal"].lower() + "-generation EPYC"
        if launch["socket"]:
            product += " " + launch["socket"].upper()
        product += " server processors"
        for position, shipping in enumerate(rows):
            match = SHIPPING.match(shipping)
            if not match or len(shipping) > 650 or re.search(UNCONFIRMED, match[0], re.I):
                continue
            named = re.search(EPYC, match["product"], re.I)
            if named and named["generation"] != generation:
                continue
            if not named and not (position == index + 1 and match["product"].casefold() == "the new cpus"):
                continue
            facts = [fact("product_availability", product, row, status="general availability"),
                     fact("system_shipments", "server vendor systems are shipping", shipping, status="shipping")]
            cloud = next((line for line in rows[position:position + 2] if len(line) <= 650 and CLOUD_SOON.search(line)), None)
            if cloud:
                facts.append(fact("cloud_rollout", "Microsoft Azure and Oracle Cloud availability expected soon", cloud,
                                  status="expected", timing="soon"))
            return facts
    return []


def production_facts(rows):
    matches = []
    for row in rows:
        delivered = DELIVERED.match(row)
        rate = RATE.match(row, delivered.end()) if delivered else None
        if not rate or len(row) > 650:
            continue
        count = int(delivered["count"].replace(",", ""))
        pace = int(rate["count"].replace(",", ""))
        if count <= 0 or pace <= 0:
            continue
        qualifier = (rate["qualifier"] or "").lower()
        facts = [fact("delivery_milestone", f"{count:,}", row, unit="cumulative deliveries"),
                 fact("annual_production_rate", qualifier + f"{pace:,}", row, unit="units per year",
                      status="reported current rate")]
        if AHEAD.match(row, rate.end()):
            facts.append(fact("production_schedule", "ahead of schedule", row, status="reported achieved rate"))
        matches.append(facts)
    values = {tuple((value["field"], value["value"]) for value in fields) for fields in matches}
    return matches[0] if len(values) == 1 else []


def extract(story, text):
    category = family(story)
    if not category:
        return None
    rows = sentences(text)
    if category == "server launch":
        facts = server_facts(story, rows)
        return ("product", "available", facts) if facts else None
    facts = production_facts(rows)
    return ("product", "production", facts) if facts else None


def summary(evidence, *, speech=False):
    values = {row["field"]: row["value"] for row in evidence["facts"]}
    if evidence["stage"] == "available":
        text = "AMD said its " + values["product_availability"] + " are generally available. Server vendors are shipping systems."
        if "cloud_rollout" in values:
            text += " AMD expects Microsoft Azure and Oracle Cloud instances to be available soon."
        return text
    program = "G M L R S" if speech else "GMLRS"
    text = f"Lockheed Martin reported {program} delivery number {values['delivery_milestone']} and current production of {values['annual_production_rate']} units per year."
    if "production_schedule" in values:
        text += " It reached that rate ahead of schedule."
    return text


def review(evidence):
    if evidence["stage"] == "available":
        why = "Shipping systems put customer adoption and server margins in focus."
        watch = "Watch cloud availability and what AMD reports about server sales and margins."
    else:
        why = "The reported pace gives a measure of delivery execution. Funded work and production costs will determine the effect on earnings."
        watch = "Watch funded deliveries and any change in program costs."
    return {"evidence": evidence, "facts": summary(evidence), "why": why, "watch": watch}
