"""Explicit Treasury refunding plans; committee advice is kept separate."""

from datetime import datetime
from decimal import Decimal
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


AMOUNT = r"\$\d[\d,]*(?:\.\d+)?\s+billion"
QUALIFIED = r"(?:(?:approximately|about)\s+)?" + AMOUNT
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
WHY = "The financing plan sets the supply of government debt investors must absorb. Auction demand and yields will help assess financing conditions."
WATCH = "Watch the announced auctions, their yields and investor demand, alongside company borrowing costs."


def document_kind(story):
    try:
        url = urlsplit(story.get("url", ""))
        official = (url.scheme == "https" and url.hostname == "home.treasury.gov" and not url.username
                    and not url.password and url.port in (None, 443)
                    and re.fullmatch(r"/news/press-releases/[a-z]+\d+/?", url.path))
    except ValueError:
        return ""
    if story.get("source") != "U.S. Treasury" or not official:
        return ""
    title = story.get("title", "")
    if re.fullmatch(r"Quarterly Refunding Statement(?: of .+)?", title, re.I):
        return "policy statement"
    if re.fullmatch(r"Report to the Secretary of the Treasury from the Treasury Borrowing Advisory Committee", title, re.I):
        return "committee report"
    if re.fullmatch(r"Minutes of the Meeting of the Treasury Borrowing Advisory Committee .+", title, re.I):
        return "committee minutes"
    return ""


def financing_facts(story, text):
    if document_kind(story) != "policy statement":
        return []
    from src.intelligence.original_disclosures import sentences
    rows = sentences(re.sub(r"\b([ap])\.m\.", lambda m: m[1] + "\u2024m\u2024", text, flags=re.I))
    facts = []

    def add(field, matches, **qualifiers):
        # Conflicting statements never resolve by taking the first number.
        unique = {(value.casefold(), evidence) for value, evidence in matches}
        values = {value for value, _ in unique}
        if len(values) == 1 and len(unique) >= 1:
            value, evidence = matches[0]
            if len(evidence) <= 650:
                facts.append({"field": field, "value": value, "evidence": evidence,
                              "status": "announced plan; execution not established", **qualifiers})

    opening = []
    for row in rows:
        match = re.fullmatch(r"(?:WASHINGTON\s*[-–—]\s*)?(?:The U\.S\. Department of the Treasury|Treasury) is offering (" + QUALIFIED
                          + r") of Treasury securities to refund (" + QUALIFIED
                          + r") of privately-held Treasury notes and bonds maturing on " + MONTH + r" \d{1,2}, 20\d{2}\.", row, re.I)
        if match and not re.search(r"\b(?:not|no|previously|hypothetical|cancelled|proposed by|Committee recommends)\b", row, re.I):
            opening.append((match, row))
    add("refunding_offering", [(m[1], row) for m, row in opening])
    add("refunding_maturities", [(m[2], row) for m, row in opening])
    cash = []
    for row in rows:
        match = re.fullmatch(r"This issuance will raise new cash from private investors of (" + QUALIFIED + r")\.", row, re.I)
        if match:
            cash.append((match[1], row))
    # Bind the new-cash sentence to the same offering paragraph, not another plan.
    if len(opening) == 1:
        adjacent = text.find(opening[0][1]) + len(opening[0][1])
        cash = [(value, row) for value, row in cash if text[adjacent:].lstrip().startswith(row)]
    else:
        cash = []
    add("refunding_new_cash", cash)
    totals = {row["field"]: row["value"] for row in facts}
    def number(value):
        return Decimal(re.search(r"\$([\d,.]+)", value)[1].replace(",", ""))
    if len(totals) == 3 and number(totals["refunding_offering"]) != number(totals["refunding_maturities"]) + number(totals["refunding_new_cash"]):
        return []
    if not {"refunding_offering", "refunding_maturities"} <= totals.keys():
        return []
    for tenor, security in ((3, "note"), (10, "note"), (30, "bond")):
        tranches = []
        auctions = []
        for row in rows:
            match = re.fullmatch(r"A " + str(tenor) + r"-year " + security + r" in the amount of (" + AMOUNT
                                 + r"), maturing " + MONTH + r" \d{1,2}, 20\d{2};?\.?", row, re.I)
            if match:
                tranches.append((match[1], row))
            match = re.fullmatch(r"The " + str(tenor) + r"-year " + security
                                 + r" will be auctioned at (\d{1,2}:\d{2}) p\.m\. ET on (Monday|Tuesday|Wednesday|Thursday|Friday), ("
                                 + MONTH + r" \d{1,2}, 20\d{2})\.", row, re.I)
            if match:
                try:
                    day = datetime.strptime(match[3], "%B %d, %Y")
                    clock = datetime.strptime(match[1], "%I:%M")
                except ValueError:
                    continue
                publication = datetime.fromisoformat(story["published"].replace("Z", "+00:00"))
                if day.strftime("%A").casefold() == match[2].casefold() and 0 <= (day.date()-publication.date()).days <= 45:
                    auctions.append((f"{day:%B} {day.day}, {day.year} at {clock:%I:%M} PM ET", row))
        add(f"refunding_tranche_{tenor}", tranches, tenor=tenor)
        add(f"refunding_auction_{tenor}", auctions, tenor=tenor)
    return facts


def material(facts):
    return {"refunding_offering", "refunding_maturities"} <= {row["field"] for row in facts}


def link_related_documents(stories):
    groups = {}
    for story in stories:
        if story.get("source_check") != "pass" or story.get("event_evidence", {}).get("schema") != 9:
            continue
        day = datetime.fromisoformat(story["published"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).date()
        groups.setdefault(day, []).append(story)
    for rows in groups.values():
        policies = [row for row in rows if row["decision"] == "eligible" and document_kind(row) == "policy statement"]
        if not policies:
            continue
        preferred = max(policies, key=lambda row: (row["published"], row["id"]))
        related = [row for row in rows if row is not preferred]
        preferred["related_reports"] = [{key: row[key] for key in ("id", "title", "url", "published")} for row in related[:4]]
        for row in related:
            row.update(decision="skip", related_to=preferred["id"],
                       reason="Related Treasury refunding document; the official policy statement supplies the financing facts")


def summary(evidence, *, speech=False):
    values = {row["field"]: row["value"] for row in evidence["facts"]}
    if not material(evidence["facts"]):
        return ""
    text = "Treasury plans to offer " + values["refunding_offering"] + " in securities to refinance " + values["refunding_maturities"] + " in maturing debt."
    if "refunding_new_cash" in values:
        text += " The offering would raise " + values["refunding_new_cash"] + " in new cash."
    dates = [(tenor, values.get(f"refunding_auction_{tenor}", "").split(" at ")[0]) for tenor in (3, 10, 30)]
    if all(day for _, day in dates):
        year = dates[0][1][-4:]
        if all(day.endswith(year) for _, day in dates):
            if speech:
                text += (" The three-year note auction is scheduled for " + dates[0][1][:-6]
                         + ", the ten-year note auction for " + dates[1][1][:-6]
                         + " and the thirty-year bond auction for " + dates[2][1] + ".")
            else:
                text += " Its three-, ten- and thirty-year auctions are scheduled for " + ", ".join(day[:-6] for _, day in dates[:2]) + " and " + dates[2][1] + ", respectively."
    return text


def review(evidence):
    return {"evidence": evidence, "facts": summary(evidence), "why": WHY, "watch": WATCH}
