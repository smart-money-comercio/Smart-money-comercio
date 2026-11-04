"""Bounded, deterministic disclosure facts. Plans and observations stay distinct."""

import re


CALENDAR = r"\b(?:conference call|earnings call|investor conference|webcast)\b|\b(?:will|to) (?:report|release)\b.{0,60}\b(?:results|earnings)\b"
UNCONFIRMED = r"\b(?:could|may|might|would|rumou?r\w*|hypothetical|not|no|denies|failed|cancelled|previously)\b"
AMOUNT = r"\$\d[\d,]*(?:\.\d+)?\s*(?:billion|million|thousand)\b"
TECHNOLOGY = r"\b(?:NVIDIA\s+)?(?:Nemotron|Cosmos|Omniverse|Metropolis|Jetson|Blackwell|DGX|RTX PRO(?:\s+\d+)?)\b"
APPLICATIONS = (
    (r"resident[ -]service agents|municipal procedures", "resident services"),
    (r"traffic management|signal timing", "traffic management"),
    (r"video search and summarization|camera (?:streams|feeds)", "video analysis"),
    (r"digital twin|simulation and training", "digital twins"),
    (r"port operations|cargo routing", "port operations"),
    (r"shared AI infrastructure|AI infrastructure", "shared AI infrastructure"),
)
AWARD_CLAUSE = r"\b(?:has been awarded|was awarded|won|wins|awarded|secured|secures|received|receives)\b.{0,120}\b(?:contract|task order)\b"


def calendar_notice(title):
    return bool(re.search(CALENDAR, title, re.I))


def sentences(text):
    # Keep common abbreviations and decimal values inside their source sentence.
    text = re.sub(r"\b(?:U\.S\.|Inc\.|Corp\.|Va\.)", lambda m: m[0].replace(".", "\u2024"), text)
    return [value.replace("\u2024", ".").strip() for value in re.split(r"(?<=[.!?])\s+(?=[A-Z“\"])|\n+", text) if value.strip()]


def issuer_sentence(story, sentence):
    symbol = story.get("publisher_symbol", "")
    if not symbol:
        return False
    from src.intelligence.news_editor import ALIASES
    terms = ALIASES.get(symbol, [symbol])
    return any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", sentence, re.I) for term in terms)


def awarded(story, sentence):
    clause = re.search(AWARD_CLAUSE, sentence, re.I)
    prefix = sentence[max(0,clause.start()-150):clause.start()] if clause else ""
    checked = re.sub(r"\bnot to exceed\b", "ceiling", sentence, flags=re.I)
    return (bool(clause) and issuer_sentence(story, prefix)
            and not re.search(r"\b(?:which|whose|partner|supplier|subcontractor|whereas|while)\b", prefix, re.I)
            and not re.search(UNCONFIRMED + r"|\b(?:seeks?|bids?|expects?|plans?|proposed|will|to be awarded)\b", checked, re.I))


def event(story, text, kind, stage):
    if story.get("kind") == "company" and not calendar_notice(story["title"]):
        if kind in {"development", "operations", "contract"} and any(awarded(story, row) for row in sentences(text)):
            row = next(row for row in sentences(text) if awarded(story,row))
            return "contract", "ceiling" if re.search(r"\b(?:up to|ceiling|potential|maximum|not to exceed)\b",row,re.I) else "award"
    if (story.get("source") == "EIA" and re.search(r"\brefiner(?:y|ies|ing)\b", story["title"], re.I)
            and re.search(r"\b(?:crude oil|throughput|refinery inputs)\b", text, re.I)):
        return "refinery data", "dated observation"
    return kind, stage


def facts(story, text, kind, stage, previous):
    result = list(previous)

    def add(field, value, evidence, **qualifiers):
        if len(result) < 7 and not any(row["field"] == field for row in result) and len(evidence) <= 650:
            result.append({"field": field, "value": value, "evidence": evidence, **qualifiers})

    rows = sentences(text)
    if kind == "contract" and stage not in {"terminated", "cooperation"}:
        for row in rows:
            if awarded(story, row):
                clause = re.search(AWARD_CLAUSE, row, re.I)[0]
                amount = re.search(AMOUNT, clause, re.I)
                qualified = re.search(r"\b(?:up to|ceiling|potential|maximum|not to exceed)\b", row, re.I)
                range_value = amount and re.search(r"^\s*(?:[-–]|to|and)\s*\$?\d",clause[amount.end():])
                if amount and not qualified and not range_value and not re.search(r"\b(?:market opportunity|addressable|annual revenue)\b", row, re.I):
                    add("contract_value", amount[0], row, status="stated award value; obligation not established")
                term = re.search(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)[ -]year\b", clause, re.I)
                if term:
                    add("contract_term", term[0].lower(), row)
                customer = re.search(r"\b(?:by|from|with) (?:the )?((?:U\.S\. |United States )?(?:Air Force|Army|Navy|Marine Corps))\b", row)
                if customer:
                    add("contract_customer", customer[1], row)
            if re.search(r"\b(?:sustain\w*|moderniz\w*|support\w*)\b", row, re.I) and issuer_sentence(story, row):
                scope = re.search(r"\b(?:the\s+)?([A-Z][A-Za-z]+(?: (?:[A-Z][A-Za-z]+|and|of|the)){2,12} (?:System|Program|Platform))\s*\(([A-Z]{2,12})\)", row)
                if scope:
                    add("contract_scope", scope[1] + " (" + scope[2] + ")", row)

    if story.get("publisher_symbol") == "NVDA" and kind in {"capacity expansion", "technology collaboration", "development", "product"}:
        examples = []
        for row in rows:
            if re.search(UNCONFIRMED + r"|\b(?:said|says|believes?|vision|opportunity)\b", row, re.I):
                continue
            technology = list(dict.fromkeys(re.sub(r"^NVIDIA\s+", "", m[0], flags=re.I) for m in re.finditer(TECHNOLOGY, row, re.I)))
            application = next((label for pattern, label in APPLICATIONS if re.search(pattern, row, re.I)), "")
            location = re.match(r"In ([^,]{2,60})(?:,\s*(?:Poland|Spain|Malaysia|Taiwan))?,", row)
            implementation = re.search(r"\b(?:uses?|using|combines?|built|building|deploy\w*|scaling|running|integrates?)\b", row, re.I)
            if not technology or not application or not location or not implementation:
                continue
            status = ("planned" if re.search(r"\b(?:planned|plans?|will|expects?|scheduled)\b|\bto support\b.{0,90}\bby 20\d{2}\b", row, re.I)
                      else "under development" if re.search(r"\b(?:is|are) building\b|\bto build\b", row, re.I)
                      else "scaling" if re.search(r"\bscaling\b", row, re.I) else "in use")
            examples.append((status != "in use", row, technology, application, location[1], status))
        examples.sort(key=lambda row: row[0])
        for index, (_, row, technology, application, location, status) in enumerate(examples[:2]):
            add("deployment_example" if index == 0 else "deployment_example_2",
                location + ": " + ", ".join(technology[:2]) + "; " + application + "; " + status, row,
                location=location, technology=technology[:2], application=application, status=status)
        for row in rows:
            if not re.search(TECHNOLOGY, row, re.I) or re.search(UNCONFIRMED, row, re.I):
                continue
            target = re.search(r"\b([\d,]+\+?)\s+cameras\s+by\s+(20\d{2})\b", row, re.I)
            if target and re.search(r"\b(?:scaling|plans?|planned|to support|expects?)\b", row, re.I):
                add("rollout_target", target[1] + " cameras by " + target[2] + " (target)", row, status="target")
            commitment = re.search(r"\b(?:committed|signed|placed)\b.{0,70}" + AMOUNT + r".{0,45}\b(?:orders?|purchases?|spending)\b", row, re.I)
            if commitment and not re.search(r"\b(?:potential|expects?|plans?|will)\b", row, re.I):
                add("commercial_commitment", commitment[0], row, status="disclosed commitment; revenue timing unverified")

    if kind == "refinery data":
        # Only global observations; country-level changes cannot replace the aggregate.
        for paragraph in text.splitlines():
            if not re.search(r"\bGlobal\b.{0,35}\b(?:refinery|refineries|crude oil)\b", paragraph, re.I):
                continue
            anchor_year, anchor_evidence = None, ""
            for row in sentences(paragraph):
                if re.search(r"\b(?:expects?|forecast\w*|could|may|would|typically)\b", row, re.I):
                    continue
                match = re.search(r"\b(?:inputs|Throughput)\b.{0,20}\b(fell|declined|increased|rose)\s+by\s+(\d[\d,]*(?:\.\d+)?)\s+(million\s+)?(?:barrels per day\s*\(b/d\)|b/d)(?!\w)", row, re.I)
                period = re.search(r"\b(first|second|third|fourth) quarter(?: of (20\d{2}))?\b", row, re.I)
                if not match or not period or not (period[2] or anchor_year):
                    continue
                if not re.search(r"\bglobal\b", row, re.I) and not re.match(r"Throughput then\b", row, re.I):
                    continue
                direction = "decrease" if match[1].lower() in {"fell", "declined"} else "increase"
                value = match[2] + (" million" if match[3] else "") + " barrels per day"
                if period[2]:
                    anchor_year, anchor_evidence = period[2], row
                when = period[1].lower() + " quarter of " + (period[2] or anchor_year)
                source_evidence = row if period[2] else anchor_evidence + " " + row
                add("refinery_change" if not any(f["field"] == "refinery_change" for f in result) else "refinery_change_2",
                    value + " " + direction + " (" + when + ")", source_evidence,
                    change=value, direction=direction, period=when, status="historical observation")
            if any(row["field"] == "refinery_change" for row in result):
                break
    return result


def body_topic(story, evidence):
    if evidence.get("schema") != 8 or evidence.get("scope") != "original release excerpt" or not evidence.get("facts"):
        return ""
    if evidence["event"] == "contract" and any(row["field"] in {"contract_value", "contract_ceiling", "obligated_amount"} for row in evidence["facts"]):
        return "contract"
    if evidence["event"] == "refinery data":
        return "energy"
    return ""


def gaps(evidence):
    fields = {row["field"] for row in evidence["facts"]}
    if evidence["event"] == "contract":
        return [label for field, label in (("obligated_amount", "obligated funding"), ("revenue_timing", "revenue recognition timing")) if field not in fields]
    if any(field.startswith("deployment_example") for field in fields):
        return [label for field, label in (("commercial_commitment", "committed purchases"), ("revenue_timing", "Nvidia revenue timing"), ("margin", "margin contribution")) if field not in fields]
    return []


def summarize(story, evidence, name, *, for_speech=False):
    fields = {row["field"]: row for row in evidence["facts"]}
    if "deployment_example" in fields:
        row = fields["deployment_example"]
        technologies = " and ".join(row["technology"])
        status = {"planned": "planned use of", "under development": "work underway to use", "scaling": "a rollout using", "in use": "use of"}[row["status"]]
        text = f"{name} described {status} {technologies} for {row['application']} in {row['location']}."
        if "rollout_target" in fields:
            target = fields["rollout_target"]["value"].replace(" (target)", "")
            target = re.sub(r"\b([\d,]+)\+", r"at least \1", target)
            text += " A separate rollout aims to support " + target + "."
        return text
    if evidence["event"] == "contract" and "contract_value" in fields:
        term = fields.get("contract_term", {}).get("value", "")
        text = name + " disclosed a " + (term + ", " if term else "") + fields["contract_value"]["value"] + " contract award."
        if "contract_customer" in fields:
            text = text[:-1] + " from the " + fields["contract_customer"]["value"] + "."
        if for_speech:
            text = name + " disclosed a " + (term + " " if term else "") + "contract award"
            if "contract_customer" in fields:
                text += " from the " + fields["contract_customer"]["value"]
            text += " worth " + fields["contract_value"]["value"] + "."
        if "contract_scope" in fields:
            text += " The work covers " + fields["contract_scope"]["value"] + "."
        return text
    if evidence["event"] == "refinery data" and "refinery_change" in fields:
        row = fields["refinery_change"]
        text = f"EIA reported a {row['change']} {row['direction']} in global refinery inputs for the {row['period']}."
        if "refinery_change_2" in fields:
            row = fields["refinery_change_2"]
            text += f" It also reported a {row['change']} {row['direction']} for the {row['period']}."
        return text
    return ""


def interpretation(evidence, why, watch):
    fields = {row["field"] for row in evidence["facts"]}
    if "deployment_example" in fields:
        return ("These uses show where Nvidia's models and computing products are being applied. Adoption examples alone do not quantify Nvidia sales, customer spending or margins.",
                "Check paying customer commitments, hardware and software purchases, rollout progress and the cost of serving these workloads.")
    if evidence["event"] == "contract" and "contract_value" in fields:
        accounting = any("Accounting" in row["value"] for row in evidence["facts"] if row["field"] == "contract_scope")
        return (("Accounting-system modernization supports a multiyear services workload." if accounting else "The award describes a future workload.")
                + " Its stated value does not establish funding obligated today or revenue already earned.",
                "Check obligated funding, task orders, delivery costs, margins and when the company expects to recognize revenue.")
    if evidence["event"] == "refinery data":
        return ("The dated throughput figures inform the fuel-supply backdrop. They do not establish today's crude demand, refining margins or a current oil-price move.",
                "Compare current refinery runs, product inventories and fuel-price spreads before changing the energy outlook.")
    return why, watch
