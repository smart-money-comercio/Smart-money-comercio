"""Concise narration derived from admitted source facts; full titles stay in the log."""

import re

from src.intelligence.story_analysis import investor_read


def next_check(text: str) -> str:
    text = text.strip()
    return "Next, " + text[0].lower() + text[1:] if text else ""


def copilot_reveal(story: dict, review: dict) -> bool:
    return (story.get("publisher_symbol") == "MSFT" and review["evidence"]["event"] == "product"
            and review["evidence"]["stage"] == "reveal"
            and bool(re.search(r"^(?:Introducing (?:the )?(?:Microsoft )?Copilot harness|Microsoft introduces? (?:the )?(?:Microsoft )?Copilot harness)\b", story["title"], re.I))
            and bool(re.search(r"\bmulti-model\b", story["title"], re.I)))


def _company_read_v1(story: dict) -> dict:
    review = investor_read(story)
    if review["evidence"]["schema"] in {10, 12}:
        return review
    if copilot_reveal(story, review):
        return {**review, "why": "The commercial test is paid adoption and the cost of running multiple models.",
                "watch": "Watch customer uptake, pricing and AI-related revenue or margin disclosures."}
    if review["evidence"]["stage"] == "test milestone":
        return {**review, "why": "The capability could support future procurement; funded orders and production costs will determine the business impact.",
                "watch": "Watch repeat validation, procurement decisions, funded orders and delivery costs."}
    return review


def company_read(story: dict, *, business_version=0) -> dict:
    if type(business_version) is not int or not 0 <= business_version <= 7:
        raise ValueError("Unknown business narration version")
    review = _company_read_v1(story)
    if business_version:
        from src.intelligence.business_analysis import enhance
        return enhance(story, review)
    return review


def _render_story_v1(story: dict, zone, names: dict) -> str:
    from src.intelligence.news_editor import dated, primary_source
    from src.intelligence.policy_analysis import is_fomc_statement
    if not primary_source(story):
        raise ValueError("Broadcast narration needs an admitted original publisher")
    published = dated(story["published"]).astimezone(zone)
    day = f"{published:%B} {published.day}"
    if story.get("event_evidence", {}).get("schema") == 15:
        review = investor_read(story)
        return review["facts"] + f" The disclosure was published {day}. Investor take: " + review["why"] + " " + review["watch"]
    if story.get("event_evidence", {}).get("schema") == 14:
        review = investor_read(story)
        text = review["facts"] + f" The disclosure was published {day}."
        if review["evidence"]["stage"] == "available":
            text += " Investor take: " + review["why"] + " " + next_check(review["watch"])
        return text
    if story.get("event_evidence", {}).get("schema") in {12, 13}:
        from src.intelligence.disclosure_details import summary
        review = investor_read(story)
        text = summary(review["evidence"], names.get(story.get("publisher_symbol"), story["source"]))
        text += f" The disclosure was published {day}."
        if review["evidence"]["schema"] == 13:
            text += " Investor take: " + review["why"] + " " + next_check(review["watch"])
        return text
    if story.get("event_evidence", {}).get("schema") == 11:
        from src.intelligence.refinery_mix import summary
        review = investor_read(story)
        return summary(review["evidence"]) + f" The report was published {day}. Investor take: " + review["why"] + " " + next_check(review["watch"])
    if story.get("event_evidence", {}).get("schema") == 10:
        from src.intelligence.defense_program import summary
        review = investor_read(story)
        text = summary(review["evidence"], names.get(story["publisher_symbol"], story["publisher_symbol"]))
        return text + f" The disclosure was published {day}."
    if story.get("event_evidence", {}).get("schema") == 9:
        review = investor_read(story)
        if not review["facts"]:
            raise ValueError("Treasury narration needs original financing facts")
        return review["facts"] + f" The plan was announced {day}. Investor take: " + review["why"] + " " + next_check(review["watch"])
    if story.get("event_evidence", {}).get("schema") == 8:
        from src.intelligence.original_disclosures import summarize
        review = company_read(story) if story["kind"] == "company" else investor_read(story)
        name = names.get(story.get("publisher_symbol"), story["source"])
        summary = summarize(story, review["evidence"], name)
        if summary:
            return summary + f" The disclosure was published {day}. Investor take: " + review["why"] + " " + next_check(review["watch"])
    if is_fomc_statement(story):
        review = investor_read(story)
        if not review["facts"]:
            raise ValueError("Broadcast policy narration needs verified decision facts")
        return (review["facts"][:-1] + f", according to its {day} statement. "
                + "Investor take: " + review["why"] + " " + next_check(review["watch"]))
    if story.get("event_evidence", {}).get("event") == "solar storage":
        review = investor_read(story)
        if not review["facts"]:
            raise ValueError("Energy narration needs verified capacity facts")
        return (review["facts"][:-1] + f", according to its {day} report. "
                + "Investor take: " + review["why"] + " " + next_check(review["watch"]))
    if story["kind"] == "company":
        symbol = story.get("publisher_symbol") or story.get("confirmed_by") or story["symbols"][0]
        company = names.get(symbol, symbol)
        review = company_read(story)
        if review["evidence"]["schema"] == 7 and review["evidence"]["facts"]:
            from src.intelligence.company_earnings import intel_narration, intel_watch
            context = {"title": story["title"], "text": review["evidence"]["source_text"]}
            return "Intel: " + intel_narration(context, day=day) + " Investor take: compare the sales outlook with profitability and cash generation. " + intel_watch(context)
        fields = {row["field"]: row["value"] for row in review["evidence"]["facts"]}
        special = False
        if (symbol == "LMT" and fields.get("tested_capability") == "in-flight retargeting"
                and re.search(r"\bGMLRS\b", story["title"]) and re.search(r"\bArmy\b", story["title"])):
            text = f"{company} reported redirecting a GMLRS rocket in flight during an Army test, in its {day} announcement."
            special = True
        elif copilot_reveal(story, review):
            text = f"{company} introduced the Copilot harness for multi-model AI work in its {day} announcement."
            special = True
        else:
            text = f"{company}'s {day} announcement: “{story['title'].rstrip('.')}”" + ("" if story["title"].endswith(("?", "!")) else ".")
        if review["facts"] and not special:
            text += " " + review["facts"]
        from src.intelligence.market_brief import story_topics
        if "defense" not in story_topics(story):
            text += " Investor take: " + review["why"] + " " + next_check(review["watch"])
        return text
    return f"{story['source']}'s {day} announcement: “{story['title'].rstrip('.')}”. Review the original report for scope and context."


def render_story(story: dict, zone, names: dict, *, business_version=0) -> str:
    if type(business_version) is not int or not 0 <= business_version <= 7:
        raise ValueError("Unknown business narration version")
    text = _render_story_v1(story, zone, names)
    if business_version:
        from src.intelligence.business_analysis import enhance, narrative
        from src.intelligence.news_editor import dated
        published = dated(story["published"]).astimezone(zone)
        day = f"{published:%B} {published.day}"
        review = company_read(story, business_version=1) if story["kind"] == "company" else enhance(story, investor_read(story))
        return narrative(story, text, review, day, concise=business_version >= 2)
    return text
