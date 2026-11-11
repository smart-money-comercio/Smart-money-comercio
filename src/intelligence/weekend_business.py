"""A checked weekly business comparison and a concise spoken argument."""

from datetime import date

from src.intelligence import business_analysis as business
from src.intelligence.original_disclosures import sentences
from src.intelligence import weekend_theme as themes


def revision(inputs):
    value = inputs.get("business_version", 0)
    if type(value) is not int or value not in {0, business.VERSION}:
        raise ValueError("Unknown Weekend Outlook business analysis version")
    return value


def analyze(stories):
    reviews = []
    for story in stories:
        value = business.assess(story)
        if value:
            reviews.append({"story_id": story["id"], "analysis": value})
    return {"schema": business.VERSION, "reviews": reviews, "comparison": business.compare(stories)}


def checked(stories, value):
    if value != analyze(stories):
        raise ValueError("Weekend business analysis lost its admitted source fields")
    return value


def discussion(stories, theme, value):
    checked(stories, value)
    by_id = {row["story_id"]: row["analysis"] for row in value["reviews"]}
    comparison = value["comparison"]
    if comparison:
        return comparison["text"]
    parts = [] if value["reviews"] else [theme["case"]]
    for story in stories:
        review = by_id.get(story["id"])
        if review:
            why = review["why"]
            parts.append("For " + business.name(story) + ", " + why[0].lower() + why[1:])
        else:
            view = themes.business(story)
            parts.append("For " + view["name"] + ", " + view["why"][0].lower() + view["why"][1:])
    return "\n\n".join(parts)


def conditions(stories, theme, value):
    checked(stories, value)
    by_id = {row["story_id"]: row["analysis"] for row in value["reviews"]}
    parts = ["For now, use the disclosed work and milestones as a starting point, then test them against new funding and delivery commitments."]
    for story in stories:
        review = by_id.get(story["id"])
        if review:
            test = review["decision_test"]
            parts.append("For " + business.name(story) + ", " + test[0].lower() + test[1:])
    if not parts:
        parts = [theme[key] for key in ("base", "stronger", "weaker")]
    parts.append("Compare any new commitments with the costs and time needed to deliver them. Delays or higher delivery costs would weaken the commercial case.")
    return "\n\n".join(parts)


def dated_summary(story, stamp):
    label = "weekend update" if story["publication_label"] == "weekend update" else "disclosure"
    return f"In its {stamp:%B} {stamp.day} {label}, " + themes.summary(story)


def spoken_week(text, periods):
    rows = sentences(text)
    first = date.fromisoformat(periods["baseline_date"])
    last = date.fromisoformat(periods["week_end"])
    rows = [row for row in rows if not row.startswith(("The completed week ran from", "Weekly price returns compare", "Market prices describe the outcome"))]
    rows[0] = rows[0].removeprefix("Over that week, ")
    basis = f"Measured from the {first:%B} {first.day}, {first.year} close to the {last:%B} {last.day}, {last.year} close, "
    return basis + " ".join(rows).replace("Friday alone:", "On Friday,")
