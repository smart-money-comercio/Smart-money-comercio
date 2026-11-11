"""Business implications tied to checked disclosure fields and event stages."""

from src.intelligence.story_analysis import checked_evidence, investor_read


VERSION = 1


def name(story):
    from src.intelligence.daily_brief_analysis import NAMES
    symbol = story.get("publisher_symbol")
    return "Eaton" if symbol == "ETN" else NAMES.get(symbol, symbol or story["source"])


def assess(story):
    from src.intelligence.news_editor import primary_source
    if not primary_source(story):
        raise ValueError("Business interpretation requires an original publisher")
    profile = checked_evidence(story)
    if profile["scope"] != "original release excerpt" or len(profile["facts"]) < 2:
        return None
    facts = {row["field"]: row["value"] for row in profile["facts"]}
    base = investor_read(story)
    kind = "source context"
    channel = "operating outlook"
    basis = list(facts)
    why, watch = base["why"], base["watch"]
    test = "Further original disclosures are needed to assess the scale and timing of the business effect."

    if profile["schema"] == 14:
        if profile["stage"] == "available":
            kind, channel = "commercial rollout", "server adoption and margins"
            test = "Reported server sales and margins would show how the launch is contributing to the business."
        else:
            kind, channel = "production milestone", "delivery volume and production costs"
            test = "Funded delivery schedules and program costs would clarify how the reported pace affects earnings."
    elif profile["schema"] == 12:
        kind, channel = "maintenance", "maintenance services"
        basis = [key for key in ("maintenance_designation", "maintenance_platform", "maintenance_location", "maintenance_scope") if key in facts]
        why = "The certification defines a maintenance role for the site. Sales depend on service orders and the cost of performing that work."
        watch = "Watch for maintenance orders, site capacity and a service timetable."
        test = "A disclosed service-order value and delivery schedule would make the scale of the opportunity clearer."
    elif profile["schema"] == 10:
        kind, channel = "development", "development to production"
        basis = [key for key in ("program_name", "program_stage", "development_test", "existing_program_contract", "next_program_gate") if key in facts]
        why = "The completed test advances the development program."
        if "existing_program_contract" in facts:
            why += " The cited contract value describes the existing program."
        watch = ("Watch the " + facts["next_program_gate"] + " outcome and the subsequent delivery plan."
                 if "next_program_gate" in facts else "Watch the next disclosed program gate and delivery plan.")
        test = (("The " + facts["next_program_gate"] + " outcome, followed by disclosed production funding and delivery commitments, would clarify the path to production work.")
                if "next_program_gate" in facts else "Disclosed production funding and delivery commitments would clarify the path from development to production work.")
    elif profile["event"] == "contract" and profile["stage"] == "award" and "contract_value" in facts:
        kind, channel = "award", "contracted workload"
        basis = [key for key in ("contract_value", "contract_term", "contract_customer", "contract_scope", "obligated_amount", "revenue_timing") if key in facts]
        why = "The stated award value"
        why += " and " + facts["contract_term"] + " term define the commercial scope." if "contract_term" in facts else " defines the commercial scope."
        why += " Its earnings contribution depends on funded work, delivery costs and revenue timing."
        watch = "Compare obligated funding and task orders with the company's revenue schedule."
        test = "Funding and a revenue schedule would make the award's near-term contribution clearer."
    elif "deployment_example" in facts:
        kind, channel = "deployment", "paid adoption and delivery economics"
        basis = [key for key in ("deployment_example", "deployment_example_2", "rollout_target", "commercial_commitment") if key in facts]
        why = "The disclosed uses identify workloads for the company's technology. The business test is how adoption translates into paying demand and the cost of serving it."
        watch = "Look for purchase commitments, rollout progress and disclosed revenue or service costs."
        test = "Disclosed purchases and revenue timing would connect the deployment evidence more directly to the business outlook."
    elif profile["schema"] == 13:
        kind, channel = "financial sanctions", "payment and counterparty exposure"
        basis = [key for key in ("sanctions_action", "sanctions_targets", "sanctions_jurisdiction", "sanctions_channel") if key in facts]
        why = "The first business check is payment and counterparty exposure to the named firms. Disclosed alternatives and costs would help establish the effect on a company."
        watch = "Check company disclosures for affected counterparties, payment routes and available alternatives."
        test = "Company-specific exposure and a stated operating or financial effect would make the investment relevance clearer."
    elif profile["schema"] == 11 or profile["event"] == "refinery data":
        kind, channel = "operating data", "fuel supply and refining economics"
        why = "The reported production mix provides historical context for fuel supply. More recent evidence is needed to assess refinery economics."
        watch = "Compare the reported period with current runs, inventories and fuel-price spreads."
        test = "More recent output and inventory evidence would help test whether the reported pattern continued."

    return {"schema": VERSION, "source_sha256": profile["source_sha256"], "source_url": profile["source_url"],
            "event": profile["event"], "stage": profile["stage"], "event_class": kind,
            "channel": channel, "basis_fields": basis, "why": why, "watch": watch, "decision_test": test}


def checked(story, value):
    if value != assess(story):
        raise ValueError("Business interpretation differs from its admitted disclosure fields")
    return value


def enhance(story, review):
    value = assess(story)
    if value is None:
        return review
    return {**review, "why": value["why"], "watch": value["watch"], "business_basis": value}


def compare(stories):
    from src.intelligence.market_brief import story_topics
    rows = [(story, assess(story)) for story in stories if "defense" in story_topics(story)]
    rows = [(story, value) for story, value in rows if value and value["event_class"] in {"award", "development", "maintenance"}]
    if len({value["event_class"] for _, value in rows}) < 2 or len({story.get("publisher_symbol") for story, _ in rows}) < 2:
        return None
    clauses = []
    for story, value in sorted(rows, key=lambda item: ({"award": 0, "development": 1, "maintenance": 2}[item[1]["event_class"]], name(item[0]))):
        label = name(story)
        if value["event_class"] == "award":
            clauses.append(label + "'s new award supplies a stated contract value and commercial scope. Its earnings contribution depends on funded work, delivery costs and revenue timing.")
        elif value["event_class"] == "development":
            text = label + "'s completed test advances a development program."
            if "existing_program_contract" in value["basis_fields"]:
                text += " The cited contract value is existing program context."
            clauses.append(text)
        else:
            clauses.append(label + "'s designation establishes a maintenance role for the site. Service orders and the cost of performing them are the next business checks.")
    text = ("The commercial evidence differs across these disclosures. " + " ".join(clauses)
            + " Compare subsequent funded work and delivery commitments to judge how each opportunity develops.")
    return {"schema": VERSION, "text": text,
            "sources": [{"story_id": story["id"], "source_sha256": value["source_sha256"],
                         "basis_fields": value["basis_fields"]} for story, value in rows]}


def narrative(story, legacy, review, day):
    """Smooth only known fact renderers; legacy titles retain their qualifications."""
    if story.get("event_evidence", {}).get("schema") not in range(8, 15):
        return legacy
    if story["event_evidence"]["schema"] == 8:
        from src.intelligence.original_disclosures import summarize
        if not summarize(story, story["event_evidence"], name(story)):
            return legacy
    facts = legacy.partition(" Investor take: ")[0]
    if not facts:
        return legacy
    for label in ("disclosure", "report"):
        suffix = f" The {label} was published {day}."
        if facts.endswith(suffix):
            facts = f"In its {day} {label}, " + facts.removesuffix(suffix)
            break
    from src.intelligence.market_brief import story_topics
    if "defense" in story_topics(story):
        return facts
    return facts + " " + review["why"] + " " + review["watch"]


def follow_through(story, review):
    why = review["why"]
    return "For " + name(story) + ", " + why[0].lower() + why[1:] + " " + review["watch"]
