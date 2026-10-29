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


def company_read(story: dict) -> dict:
    review = investor_read(story)
    if copilot_reveal(story, review):
        return {**review, "why": "The commercial test is paid adoption and the cost of running multiple models.",
                "watch": "Watch customer uptake, pricing and AI-related revenue or margin disclosures."}
    if review["evidence"]["stage"] == "test milestone":
        return {**review, "why": "The capability could support future procurement; funded orders and production costs will determine the business impact.",
                "watch": "Watch repeat validation, procurement decisions, funded orders and delivery costs."}
    return review


def render_story(story: dict, zone, names: dict) -> str:
    from src.intelligence.news_editor import dated, primary_source
    from src.intelligence.policy_analysis import is_fomc_statement
    if not primary_source(story):
        raise ValueError("Broadcast narration needs an admitted original publisher")
    published = dated(story["published"]).astimezone(zone)
    day = f"{published:%B} {published.day}"
    if is_fomc_statement(story):
        review = investor_read(story)
        if not review["facts"]:
            raise ValueError("Broadcast policy narration needs verified decision facts")
        return (review["facts"][:-1] + f", according to its {day} statement. "
                + "Investor take: " + review["why"] + " " + next_check(review["watch"]))
    if story["kind"] == "company":
        symbol = story.get("publisher_symbol") or story.get("confirmed_by") or story["symbols"][0]
        company = names.get(symbol, symbol)
        review = company_read(story)
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
