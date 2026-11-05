"""Business context from completed development tests in original issuer releases."""

from datetime import timedelta
import re

from src.intelligence.special_alert_sources import company_url, timestamp


PUBLISHERS = {"LMT", "NOC", "AVAV", "KTOS", "RTX", "GD", "LHX", "HII"}
IDENTIFIER = r"[A-Z][A-Za-z]{0,5}[- ]?\d{1,4}[A-Za-z0-9-]{0,6}"
KINDS = r"reentry vehicle|aircraft|drone|uncrewed system|unmanned system|autonomous system"
UNCERTAIN = r"\b(?:not|no|could|may|might|would|cancelled|canceled|failed|hypothetical|previously|prior|earlier|recalled|alleged|reportedly)\b"


def applicable(story):
    from src.intelligence.story_analysis import event_type
    symbol = story.get("publisher_symbol", "")
    title = story.get("title", "")
    kind, stage = event_type(title, version=4)
    completed_test = (re.search(r"\b(?:complet\w*|conduct\w*|reports?)\b.{0,80}\b(?:flight test|test flight)\b", title, re.I)
                      and not re.search(r"\b(?:will|plans?|planned|expected)\b|\bto (?:complete|conduct|test)\b", title, re.I))
    return bool(story.get("kind") == "company" and symbol in PUBLISHERS and company_url(symbol, story.get("url", ""))
                and (completed_test or kind == "product" and stage in {"test milestone", "prototype"}))


def program_facts(story, text):
    if not applicable(story):
        return []
    from src.intelligence.original_disclosures import sentences, issuer_sentence
    rows = sentences(text)
    published = timestamp(story.get("published"))
    if published is None:
        raise ValueError("Defense program facts need an original zoned publication clock")
    publication_years = {published.year, (published-timedelta(days=1)).year}
    completions = []
    for index, row in enumerate(rows):
        match = re.search(r"\b(?:completed a test flight of|conducted (?:a )?(?:planned )?flight test of)\s+"
                          r"(?:its |the |an? )?(?:unarmed,?\s+)?(developmental|prototype)\s+(" + IDENTIFIER
                          + r")\s+(" + KINDS + r")\b", row, re.I)
        if not match or len(row) > 650 or re.search(UNCERTAIN, row, re.I):
            continue
        prefix = row[:match.start()]
        if not issuer_sentence(story, prefix) or re.search(r"\b(?:while|whereas|whose|which|supplier|competitor|said|says)\b", prefix, re.I):
            continue
        if any(int(value) not in publication_years for value in re.findall(r"\b20\d{2}\b", row)):
            continue
        completions.append((index, match, row))
    programs = {(m[2].casefold(), m[3].casefold()) for _, m, _ in completions}
    if len(programs) != 1:
        return []
    index, match, row = completions[0]
    program, kind, stage = match[2], match[3].lower(), match[1].lower()
    facts = [
        {"field":"program_name", "value":program + " " + kind, "evidence":row, "program":program, "kind":kind},
        {"field":"program_stage", "value":stage, "evidence":row, "status":"development stage; production readiness not established"},
        {"field":"development_test", "value":"company-reported completed flight test", "evidence":row,
         "status":"reported milestone; independent test verification not established"},
    ]
    customer = re.search(r"\b((?:U\.S\.|United States) (?:Air Force|Army|Navy|Marine Corps))\b", row)
    if customer:
        facts.append({"field":"program_customer", "value":customer[1], "evidence":row})
    # Later passages must still concern this program. A second program makes
    # unscoped contract and review references too ambiguous to attach.
    context = rows[index+1:]
    other_program = any(re.search(r"\b(?:" + IDENTIFIER + r")\s+(?:" + KINDS + r")\b", value, re.I)
                        and not re.search(r"\b" + re.escape(program) + r"\b", value, re.I) for value in context)
    if other_program:
        return facts
    amounts, gates = [], []
    for value in context:
        if len(value) > 650 or re.search(UNCERTAIN, value, re.I):
            continue
        amount = re.match(r"^Executed under (?:an? )?(?:existing )?prime (?:military )?contract valued at "
                          r"((?:(?:over|more than|approximately|up to) )?\$\d[\d,]*(?:\.\d+)?\s*(?:billion|million|B|M))\b", value)
        if amount and not re.match(r"\s*(?:[-–]|to|and)\s*\$?\d", value[amount.end():]):
            normalized = re.sub(r"(?<=\d)\s*B\b", " billion", amount[1])
            normalized = re.sub(r"(?<=\d)\s*M\b", " million", normalized)
            amounts.append((normalized, value))
        gate = re.search(r"\b(?:toward|towards|ahead of|preparing for) (?:a |the |system-level )?"
                         r"(Critical Design Review|Preliminary Design Review|Production Readiness Review)\b", value, re.I)
        if gate and re.search(r"\b(?:program|flight|test|design)\b", value, re.I):
            gates.append((gate[1].title(), value))
    for field, matches, qualifiers in (
        ("existing_program_contract", amounts, {"status":"existing program contract context; new award, obligation and revenue not established"}),
        ("next_program_gate", gates, {"status":"future program milestone; completion and date not established"}),
    ):
        if len({value.casefold() for value, _ in matches}) == 1:
            value, evidence = matches[0]
            facts.append({"field":field,"value":value,"evidence":evidence,**qualifiers})
    return facts


def material(facts):
    return {"program_name", "program_stage", "development_test"} <= {row["field"] for row in facts}


def summary(evidence, name):
    fields = {row["field"]:row["value"] for row in evidence["facts"]}
    if not material(evidence["facts"]):
        return ""
    text = name + " reported a completed flight test of its " + fields["program_stage"] + " " + fields["program_name"]
    text += (" with the " + fields["program_customer"] if "program_customer" in fields else "") + "."
    if "existing_program_contract" in fields:
        text += " The release cites an existing prime contract valued at " + fields["existing_program_contract"] + "."
    if "next_program_gate" in fields:
        text += " The program is working toward " + fields["next_program_gate"] + "."
    return text


def review(evidence):
    fields = {row["field"]:row["value"] for row in evidence["facts"]}
    why = "The test advances an existing development program. Funded delivery plans and development costs will help assess its path to production revenue."
    if "existing_program_contract" in fields:
        why += " The stated contract value is program context, not a new award."
    gate = fields.get("next_program_gate")
    watch = "Watch for " + ("the " + gate + " outcome, " if gate else "further test results, ") + "disclosed funding and a delivery timetable."
    return {"evidence":evidence, "facts":"; ".join(row["field"].replace("_"," ") + ": " + row["value"] for row in evidence["facts"]) + ".",
            "why":why, "watch":watch}
