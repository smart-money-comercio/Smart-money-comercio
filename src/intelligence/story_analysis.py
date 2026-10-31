"""Event-specific investor questions and conservative, traceable release facts."""

import hashlib
from html.parser import HTMLParser
import re


MAX_EXCERPT = 6000
SCOPES = {"headline only", "publisher feed excerpt", "original release excerpt"}
MONEY = r"(?:(?:approximately|about|up to|at least|more than|nearly)\s+)?(?<![A-Za-z])\$\d[\d,]*(?:\.\d+)?(?:\s*(?:billion|million|thousand)\b)?"


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.blocked = [], []

    def handle_starttag(self, tag, attrs):
        tag = tag.split(":")[-1]
        if tag in {"script", "style", "nav", "footer", "code", "pre"}:
            self.blocked.append(tag)
        if not self.blocked and tag in {"p", "div", "br", "li", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.split(":")[-1]
        if self.blocked and tag == self.blocked[-1]:
            self.blocked.pop()
        elif not self.blocked and tag in {"p", "div", "li", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


def release_text(value) -> str:
    if not isinstance(value, str):
        return ""
    parser = VisibleText()
    parser.feed(value[:100_000])
    text = "\n".join(" ".join(line.split()) for line in "".join(parser.parts).splitlines() if line.strip())
    text = re.split(r"\n(?:Forward[- ]Looking Statements|Safe Harbor|About [A-Z][^\n]{0,70})\n", text, maxsplit=1, flags=re.I)[0]
    if len(text) > MAX_EXCERPT:
        text = text[:MAX_EXCERPT]
        boundary = max(text.rfind(". "), text.rfind("\n"))
        text = text[:boundary + 1] if boundary >= 0 else ""
    return text.strip()


def event_type(title: str, fallback: str = "", *, version: int = 4) -> tuple[str, str]:
    title = str(title or "")
    if version >= 6 and re.search(r"\bsolar\b", title, re.I) and re.search(r"\bco.located battery storage\b", title, re.I):
        return "solar storage", "capacity report"
    if version >= 4 and re.fullmatch(r"Federal Reserve issues FOMC statement\.?", title, re.I):
        return "monetary policy", "rate decision"
    guidance = re.search(r"\b(raises?|cuts?|lowers?|reduces?|withdraws?|reaffirms?|maintains?|updates?)\b.{0,40}\b(guidance|revenue outlook|earnings outlook)\b", title, re.I)
    acquisition = re.search(r"\b(acquisitions?|acquir\w*|merger|buyout)\b", title, re.I)
    if guidance and (not acquisition or guidance.start() < acquisition.start()):
        return "guidance", "reaffirmed" if re.search(r"\b(reaffirms?|maintains?)\b", guidance[0], re.I) else "lowered" if re.search(r"\b(cuts?|lowers?|reduces?|withdraws?)\b", guidance[0], re.I) else "updated"
    if version >= 2 and re.search(r"\b(voluntary (?:exit|retirement) (?:offer|program)|layoffs?|job cuts|reduction in force|workforce restructur\w*|staff reductions?)\b", title, re.I):
        return "restructuring", "voluntary offer" if re.search(r"\bvoluntary\b", title, re.I) else "announced"
    corporate = not re.search(r"\b(contract|task order)\b", title, re.I) or re.search(r"\b(acquir\w*|merger|buyout|acquisition of|closes? .{0,80}acquisition|completes? .{0,80}acquisition)\b", title, re.I)
    if acquisition and corporate:
        if re.search(r"\b(terminat\w*|cancel\w*|abandons?|withdraws?)\b", title, re.I):
            return "acquisition", "terminated"
        closing = re.search(r"\b(closes?|closed|completes?|completed|finalizes?|finalized|completion of)\b.{0,100}\b(acquisition|merger|buyout)\b|\b(acquisition|merger)\b.{0,40}\b(completed|closed)\b", title, re.I)
        if closing:
            if re.search(r"\b(will|to|not)\s*$", title[:closing.start()], re.I) or re.search(r"\bnot\b", closing[0], re.I):
                return "acquisition", "proposed"
            return "acquisition", "completed"
        if re.search(r"\b(proposed|proposes?|plans?|agrees?|agreement|to acquire|will acquire|bid|offer)\b", title, re.I):
            return "acquisition", "proposed"
        if re.search(r"\b(acquires|acquired)\b", title, re.I):
            return "acquisition", "completed"
        return "acquisition", "announced"
    if re.search(r"\b(divests?|divestiture|sells? .{0,50}(?:business|unit|division))\b", title, re.I):
        return "divestiture", "proposed" if re.search(r"\b(agrees?|plans?|to sell|proposed)\b", title, re.I) else "reported"
    if re.search(r"\b(MOU|memorandum of understanding|letter of intent)\b", title, re.I):
        return "contract", "cooperation"
    if fallback == "contract" or re.search(r"\b(contract|strategic(?: [\w-]+){0,3} partnership|commercial agreement|task order)\b", title, re.I):
        if re.search(r"\b(loses?|lost|terminat\w*|cancel\w*)\b.{0,60}\b(contract|task order|agreement)\b", title, re.I):
            return "contract", "terminated"
        return "contract", "ceiling" if re.search(r"\b(up to|ceiling|maximum|potential value)\b", title, re.I) else "award"
    if fallback == "guidance" or re.search(r"\b(guidance|revenue outlook|earnings outlook)\b", title, re.I):
        return "guidance", "reaffirmed" if re.search(r"\b(reaffirms?|maintains?|unchanged)\b", title, re.I) else "lowered" if re.search(r"\b(cuts?|lowers?|reduces?|withdraws?)\b", title, re.I) else "updated"
    if fallback == "earnings" or re.search(r"\breports?\b.{0,70}\b(results|earnings|revenue|EPS)\b", title, re.I):
        return "earnings", "reported"
    if version >= 3:
        technical = re.search(r"\b(tests?|trials?|validat\w*|redirect\w*|retarget\w*)\b", title, re.I)
        defense = re.search(r"\b(defen[cs]e|Army|Navy|military|missiles?|rockets?|GMLRS|GMRLS|hypersonic|drones?|counter.drone|autonomous)\b", title, re.I)
        if technical and defense:
            planned = re.search(r"\b(plans?|planned|proposed|scheduled|prepares?|will|expects?)\b|\bto test\b", title, re.I)
            return "product", "planned test" if planned else "test milestone"
        expands = re.search(r"\b(expand\w*|scales?|scaling)\b", title, re.I)
        if expands and re.search(r"\bcollaborat\w*\b", title, re.I) and re.search(r"\b(models?|AI|chips?|cloud)\b", title, re.I):
            return "technology collaboration", "announced"
        if expands and re.search(r"\b(AI|cloud|compute|computing|GPU|CPU|infrastructure|data centers?)\b", title, re.I):
            return "capacity expansion", "announced"
    if fallback == "product" or re.search(r"\b(introduces?|unveils?|launch(?:es)?|prototype|demonstrat\w*|begins production|first deliveries)\b", title, re.I):
        if re.search(r"\b(prototype|concept|demonstrat\w*|flight test)\b", title, re.I):
            return "product", "prototype"
        if re.search(r"\b(begins production|starts production|first deliveries)\b", title, re.I):
            return "product", "planned" if re.search(r"\b(plans?|expects?|will|scheduled)\b", title, re.I) else "production"
        if re.search(r"\b(now available|now commercially available|begins shipping|starts shipping)\b", title, re.I):
            return "product", "available"
        return "product", "reveal"
    return fallback or "development", "reported"


def disclosed_facts(text: str, kind: str, stage: str = "", *, version: int = 4, title: str = "") -> list[dict]:
    if version >= 7 and kind == "earnings":
        from src.intelligence.company_earnings import intel_facts
        return [{"field": row["field"], "value": row["value"] + " (" + row["period"] + ", " + row["basis"] + ")",
                 "evidence": row["evidence"]} for row in intel_facts(text, title)]
    if version >= 6 and kind == "solar storage":
        from src.intelligence.energy_analysis import storage_facts
        return storage_facts(text)
    if version >= 5 and kind == "earnings":
        from src.intelligence.alphabet_source import results_facts
        return results_facts(text, title)
    if version >= 4 and kind == "monetary policy" and stage == "rate decision":
        from src.intelligence.policy_analysis import rate_facts
        return rate_facts(text)
    facts = []

    def add(field, value, sentence):
        if not any(row["field"] == field for row in facts) and len(facts) < 3 and len(sentence) <= 360:
            facts.append({"field": field, "value": value.strip(), "evidence": sentence})

    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z“\"])|\n+", text)
    for sentence in sentences:
        negative_check = re.sub(r"\bnot to exceed\b", "ceiling", sentence, flags=re.I)
        if not sentence or re.search(r"\b(previously|(?:last|prior|previous) (?:year|quarter|period)|historically|forward-looking|hypothetical|could|may|would|might|not|no|denies|rumou?r\w*)\b", negative_check, re.I):
            continue
        if kind == "product" and stage == "test milestone":
            if (re.search(r"\b(?:successfully redirected|demonstrated .{0,45}retarget\w*|validated .{0,45}retarget\w*)\b", sentence, re.I)
                    and re.search(r"\bin[\s\-\u2010\u2011\u2013]flight\b", sentence, re.I)
                    and not re.search(r"\b(plans?|expects?|will|intends?|if|failed|unsuccessful|aborted|cancelled)\b", sentence, re.I)):
                add("tested_capability", "in-flight retargeting", sentence)
        if kind == "capacity expansion" and re.search(r"\b(?:announced plans?|plans? to expand)\b", sentence, re.I):
            if re.search(r"\bmulti[\s\-\u2010\u2011\u2013]gigawatt\b", sentence, re.I):
                add("planned_capacity_scale", "multi-gigawatt scale", sentence)
        if kind in {"acquisition", "divestiture"}:
            match = re.search(r"\b(?:acquir\w*|acquisition|transaction|purchase|deal|consideration|sale)\b.{0,100}?\b(?:for|valued at|value of|price of|consideration of|at)\s+(" + MONEY + r")", sentence, re.I)
            if match and not re.match(r"\s*(?:[-–]|to|and)\s*\$?\d", sentence[match.end():]):
                field = "enterprise_value" if re.search(r"\benterprise value\b", sentence, re.I) else "equity_value" if re.search(r"\bequity value\b", sentence, re.I) else "transaction_value"
                qualification = re.search(r"\b(?:including|excluding)\s+(?:assumed\s+)?debt\b|\bsubject to [^.;]{1,55}adjustments\b", sentence, re.I)
                add(field, match[1] + (", " + qualification[0] if qualification else ""), sentence)
            if re.search(r"\b(financ\w*|funded|paid)\b", sentence, re.I) and not re.search(r"\b(not|no|could|may|would)\b", sentence, re.I):
                cash, debt, stock = (bool(re.search(pattern, sentence, re.I)) for pattern in (r"\bcash(?: on hand)?\b", r"\b(debt|borrowing\w*)\b", r"\b(stock|shares)\b"))
                if cash or debt or stock:
                    funding = " and ".join(label for label, present in (("cash", cash), ("debt", debt), ("stock", stock)) if present)
                    field = "financing_plan" if re.search(r"\b(expects?|plans?|intends?|will|anticipated|proposed)\b", sentence, re.I) else "financing"
                    add(field, funding, sentence)
            match = re.search(r"\b(anti[- ]submarine warfare|undersea warfare|sonar systems|cybersecurity|autonomous systems|data center infrastructure)\b", sentence, re.I)
            if match:
                add("business_focus", match[1].lower(), sentence)
        if kind == "contract" and stage != "terminated":
            match = re.search(r"\b(?:up to|not to exceed|ceiling of|maximum value of|potential value of)\s+(" + MONEY + r")", sentence, re.I)
            if match and re.search(r"\b(contract|award|task order|IDIQ|ceiling|not to exceed)\b", sentence, re.I) and not re.search(r"\b(addressable|market opportunity)\b", sentence, re.I):
                add("contract_ceiling", match[0], sentence)
            match = re.search(r"(" + MONEY + r")\s+(?:is |was |were |has been )?(?:being )?obligated\b|\b(?:obligated|funded)\s+(?:at award\s+)?(" + MONEY + r")", sentence, re.I)
            if match and not re.search(r"\b(not|no|expected|will|could|may|would|planned)\b", sentence, re.I):
                add("obligated_amount", match[1] or match[2], sentence)
        if kind == "earnings" and not re.search(r"\b(expects?|outlook|guidance|forecasts?|projects?|will|could|may|would)\b", sentence, re.I):
            match = re.search(r"\b(revenue|net sales|sales)\b.{0,45}?\b(?:of|was|were|totaled|reached|to)\s+(" + MONEY + r")", sentence, re.I)
            period = re.search(r"\b(?:(?:first|second|third|fourth)[- ]quarter|Q[1-4]|fiscal year)(?:\s+20\d{2})?\b", sentence, re.I)
            if match and period:
                add("reported_" + match[1].lower().replace(" ", "_"), match[2] + " (" + period[0] + ")", sentence)
        if kind == "restructuring":
            match = re.search(r"\bvoluntary (?:exit|retirement) (?:offer|program)\b", sentence, re.I)
            if match:
                add("program_type", match[0].lower(), sentence)
            match = re.search(r"\b(?:restructuring|severance) (?:charges?|costs?)\b.{0,35}?\b(?:of|at|totaling|totalled)\s+(" + MONEY + r")", sentence, re.I)
            if match and not re.match(r"\s*(?:[-–]|to|and)\s*\$?\d", sentence[match.end():]):
                field = "restructuring_cost_estimate" if re.search(r"\b(expects?|estimat\w*|plans?|anticipat\w*|will|up to)\b", sentence, re.I) else "restructuring_charge"
                add(field, match[1], sentence)
            match = re.search(r"\bannual(?:ized)? (?:cost )?savings\b.{0,25}?\b(?:of|at|totaling)\s+(" + MONEY + r")", sentence, re.I)
            if match and not re.match(r"\s*(?:[-–]|to|and)\s*\$?\d", sentence[match.end():]) and re.search(r"\b(target\w*|expects?|plans?|anticipat\w*|estimat\w*)\b", sentence, re.I):
                add("annual_savings_target", match[1], sentence)
    return facts


def build_evidence(story: dict, text: str = "", scope: str = "headline only", *, schema: int | None = None) -> dict:
    from src.intelligence.energy_analysis import solar_storage_report
    from src.intelligence.company_earnings import intel_period
    intel_results = story.get("publisher_symbol") == "INTC" and bool(intel_period(story["title"]))
    if schema is None:
        schema = 7 if intel_results else 6 if solar_storage_report(story) else 5 if story.get("publisher_symbol") in {"GOOG", "GOOGL"} and re.fullmatch(r"Alphabet (?:Announces|Reports) (?:First|Second|Third|Fourth) Quarter 20\d{2} Results", story["title"], re.I) else 4
    if type(schema) is not int or schema not in {1, 2, 3, 4, 5, 6, 7} or scope not in SCOPES or schema == 6 and not solar_storage_report(story) or schema == 7 and not intel_results:
        raise ValueError("Unknown original story evidence scope")
    text = release_text(text)
    kind, stage = event_type(story["title"], story.get("materiality", ""), version=schema)
    return {"schema": schema, "event": kind, "stage": stage, "scope": scope if text else "headline only",
            "source_url": story["url"], "published": story["published"], "source_text": text,
            "observed_at": story.get("evidence_checked_at", story.get("source_checked_at")),
            "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "facts": disclosed_facts(text, kind, stage, version=schema, title=story["title"])}


def checked_evidence(story: dict) -> dict:
    value = story.get("event_evidence")
    if value is None:
        return build_evidence(story)
    if not isinstance(value, dict) or value != build_evidence(story, value.get("source_text", ""), value.get("scope", "headline only"), schema=value.get("schema")):
        raise ValueError("Story facts or event stage do not match the admitted original evidence")
    return value


def investor_read(story: dict) -> dict:
    evidence = checked_evidence(story)
    kind, stage = evidence["event"], evidence["stage"]
    if kind == "monetary policy" and stage == "rate decision":
        action = next((row["value"] for row in evidence["facts"] if row["field"] == "policy_action"), "")
        why = {"held": "The hold keeps attention on how long financing costs stay at this level, including for debt-funded AI expansion and rate-sensitive valuations.",
               "raised": "Higher policy rates can increase refinancing pressure and the discount rates investors apply to future earnings.",
               "lowered": "Lower policy rates can ease financing pressure over time; the effect depends on lending rates, credit availability and business demand."}.get(action, "The policy outlook matters for borrowing costs and rate-sensitive valuations.")
        watch = "Watch the next inflation reading, Treasury yields and company financing plans."
    elif kind == "solar storage":
        from src.intelligence.energy_analysis import STORAGE_WHY, STORAGE_WATCH
        why, watch = STORAGE_WHY, STORAGE_WATCH
    elif kind == "acquisition":
        if stage == "completed":
            why = "After the reported close, integration and cash generation become the key investment checks."
            watch = "Look for integration costs, the acquired business's contribution and updated cash-flow guidance."
        elif stage == "terminated":
            why = "A cancelled transaction warrants revisiting the strategic and capital-allocation assumptions."
            watch = "Check any disclosed termination costs and management's revised plans."
        else:
            why = "The proposed acquisition could change the business mix; financing and closing conditions can affect the outcome."
            watch = "Check the purchase terms, financing, regulatory conditions and expected closing timetable."
    elif kind == "divestiture":
        why = "A disposal can change the revenue mix, cash position and earnings comparability."
        watch = "Check disclosed proceeds, transition costs and guidance for the retained businesses."
    elif kind == "contract":
        if stage == "terminated":
            why = "A reported contract loss warrants reviewing backlog, revenue assumptions and program exposure."
        elif stage == "cooperation":
            why = "An announced cooperation agreement outlines planned work; funded orders still require evidence."
        elif stage == "ceiling" or any(row["field"] == "contract_ceiling" for row in evidence["facts"]):
            why = "A contract ceiling sets a potential limit; it does not establish funded orders or booked revenue."
        else:
            why = "An award can support future work; its earnings impact depends on funding, scope and delivery execution."
        watch = "Check affected programs, any disclosed charges and management's revised guidance." if stage == "terminated" else "Check funded commitments and revenue timing, then task orders, delivery milestones, margins and revenue recognition."
    elif kind == "product":
        if stage == "test milestone":
            why = "The test puts technical validation and production readiness in focus. A test milestone alone does not establish funded orders or near-term revenue."
        elif stage == "planned test":
            why = "A planned test outlines the next validation step; successful results and funded demand still require evidence."
        elif stage == "prototype":
            why = "Technical progress warrants checking production readiness, funded demand and execution costs. A prototype alone does not establish orders or revenue."
        elif stage == "production":
            why = "Reported production or deliveries put manufacturing scale, product quality and costs in focus."
        elif stage == "planned":
            why = "An announced production plan still needs evidence of readiness, customer commitments and execution."
        elif stage == "available":
            why = "Commercial availability puts customer adoption, pricing and unit economics in focus."
        else:
            why = "A reveal establishes product direction; commercial timing, demand and execution costs still require evidence."
        watch = ("Watch repeat testing, procurement approvals, funded orders, integration costs and production timing." if stage in {"test milestone", "planned test"} else
                 "Watch customer commitments, commercial availability, pricing, margins and company guidance.")
    elif kind in {"capacity expansion", "technology collaboration"}:
        why = ("The expansion puts future infrastructure demand in focus; its commercial impact depends on deployment, financing and customer commitments." if kind == "capacity expansion" else
               "The collaboration puts adoption and implementation in focus; commercial commitments and revenue contribution still require evidence.")
        watch = "Check committed spending, power and supply constraints, rollout dates and any change to revenue or margin guidance."
    elif kind == "restructuring":
        why = ("A voluntary exit offer leaves the scale of departures dependent on employee participation. Cost savings and operational effects still need evidence." if stage == "voluntary offer" else
               "Workforce changes can affect costs and delivery capacity; announced reductions alone do not establish savings or stronger demand.")
        watch = "Check participation, disclosed severance costs, savings targets and timing, service capacity and any guidance change."
    elif kind == "guidance":
        why = "Reaffirmed guidance keeps the stated assumptions in place; delivery against them remains the test." if stage == "reaffirmed" else "A lower outlook warrants revisiting the demand, pricing and cost assumptions." if stage == "lowered" else "Updated guidance changes the forward assumptions to test against company execution."
        watch = "Compare the revised outlook with prior guidance and the next reported results; a price response is not established here."
    elif kind == "earnings":
        why = "Reported results update the business baseline; compare revenue, margins and cash flow to assess earnings quality."
        watch = "Compare with prior guidance and management's outlook, keeping GAAP and adjusted measures distinct."
    else:
        why = "The reported development warrants reviewing its effect on the business and capital commitments."
        watch = "Check company disclosures, timing, execution costs and any guidance change."
    labels = {"transaction_value": "Stated deal amount", "enterprise_value": "Announced enterprise value", "equity_value": "Announced equity value", "financing": "Financing described in the release", "financing_plan": "Financing plan described in the release",
              "business_focus": "Business focus described in the release", "contract_ceiling": "Announced ceiling",
              "obligated_amount": "Amount described as obligated", "reported_revenue": "Reported revenue",
              "reported_sales": "Reported sales", "reported_net_sales": "Reported net sales",
              "reported_operating_margin": "Reported operating margin", "reported_eps": "Reported earnings per share", "forecast_revenue": "Management's revenue forecast",
              "program_type": "Program described in the release", "restructuring_charge": "Restructuring cost described in the release",
              "restructuring_cost_estimate": "Estimated restructuring cost", "annual_savings_target": "Annual savings target",
              "tested_capability": "Capability demonstrated in the reported test", "planned_capacity_scale": "Announced expansion plan"}
    if kind == "monetary policy" and stage == "rate decision":
        values = {row["field"]: row["value"] for row in evidence["facts"]}
        facts = ("The Federal Reserve " + values["policy_action"] + " its federal funds target range "
                 + ("at " if values["policy_action"] == "held" else "to ") + values["policy_target_range"]) if "policy_target_range" in values else ""
    elif kind == "solar storage":
        from src.intelligence.energy_analysis import storage_narration
        facts = storage_narration(evidence)
    else:
        facts = "; ".join(labels[row["field"]] + ": " + row["value"] for row in evidence["facts"])
    return {"evidence": evidence, "facts": facts + "." if facts else "", "why": why, "watch": watch}
