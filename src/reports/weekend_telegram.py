"""Saturday and Sunday Telegram presentations of checked weekly evidence."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from src.intelligence import business_analysis, calendar_sources, weekend_business, weekend_inputs, weekend_theme
from src.intelligence.daily_brief_analysis import NAMES
from src.reports import weekend_narration
from src.reports.weekend_outlook import day_label
from src.utils.market_quote_source import BENCHMARKS


SATURDAY = "Saturday Review"
SUNDAY = "Sunday Outlook"


def edition_name(now: datetime) -> str:
    weekday = now.astimezone(weekend_inputs.NY).weekday()
    if weekday == 5:
        return SATURDAY
    if weekday == 6:
        return SUNDAY
    raise ValueError("Build a weekend edition on Saturday or Sunday, New York time")


def render(record: dict, now: datetime) -> str:
    """Render a record already checked by the builder or delivery gate."""
    edition = edition_name(now)
    inputs = record["inputs"]
    if edition == SATURDAY:
        sections, sources = saturday_review(inputs)
    else:
        sections, sources = sunday_outlook(inputs)
    links = {}
    for label, url in sources:
        links.setdefault(url, label)
    if links:
        sections.append("Sources\n" + "\n".join(f"{label}\n{url}" for url, label in links.items()))
    sections.append("Research only. Not financial advice.")
    return f"Smart Money {edition}\n" + "\n\n".join(sections)


def review_stories(stories: list[dict]) -> list[dict]:
    """Choose two qualified weekday disclosures from different publishers."""
    publishers = {}
    for story in stories:
        if story["publication_label"] == "week disclosure":
            publisher = story["publisher_symbol"] or story["source"]
            publishers.setdefault(publisher, story)
    distinct = list(publishers.values())
    if len(distinct) <= 1:
        return distinct
    lead, *others = distinct
    topic = weekend_theme.group(lead)
    second = next((story for story in others if weekend_theme.group(story) != topic), others[0])
    return [lead, second]


def saturday_review(inputs: dict) -> tuple[list[str], list[tuple[str, str]]]:
    window = inputs["window"]
    baseline, end = (date.fromisoformat(window[key]) for key in ("baseline_date", "week_end"))
    markets = ["Market scorecard"]
    sources = []
    for row in inputs["prices"]:
        name = BENCHMARKS[row["symbol"]]
        if row["status"] != "available":
            markets.append(f"• {name} · Weekly closes unavailable")
            continue
        proof = row["proof"]
        markets.append(f"• {name} {proof['weekly_percent']:+.2f}% week · {proof['friday_percent']:+.2f}% Friday")
        sources.append((f"{name} · Yahoo chart", proof["url"]))
    markets.append(f"{baseline:%b} {baseline.day} close to {end:%b} {end.day} close. Price returns exclude dividends.")
    sections = [f"Week ended {day_label(window['week_end'])}", "\n".join(markets)]

    stories = []
    for row in review_stories(inputs["stories"]):
        published = weekend_inputs.clock(row["published"]).astimezone(weekend_inputs.NY)
        text = weekend_business.dated_summary(row, published)
        review = business_analysis.assess(row)
        if review:
            text += f"\nFollow-up · {review['decision_test']}"
        stories.append(text)
        sources.append((row["source"], row["url"]))
    ipo = inputs.get("ipo")
    if not stories and ipo:
        source = ipo["source"]
        published = weekend_inputs.clock(source["published"]).astimezone(weekend_inputs.NY)
        if published.date() <= end:
            stories.append(ipo["summary"])
            sources.append((source["source"], source["url"]))
    sections.append("What changed\n" + (
        "\n\n".join(stories) or "Publisher coverage was limited for completed-week business disclosures."
    ))
    return sections, sources


def time_label(at: datetime) -> str:
    return at.strftime("%I:%M %p %Z").lstrip("0")


def company_entry(row: dict) -> tuple[time, str]:
    name = NAMES.get(row["symbol"], row["symbol"])
    event = "earnings call" if row["event"] == "earnings conference call" else row["event"]
    if row["event_at"]:
        at = weekend_inputs.clock(row["event_at"]).astimezone(weekend_inputs.NY)
        return at.time(), f"• {time_label(at)} · {name} {event}"
    return time.max, f"• {name} {event} · Time unverified"


def sunday_outlook(inputs: dict) -> tuple[list[str], list[tuple[str, str]]]:
    window, packet = inputs["window"], inputs["calendar"]
    agenda = defaultdict(list)
    sources = []
    for row in packet["macro"]:
        at = weekend_inputs.clock(row["at"]).astimezone(weekend_inputs.NY)
        event = " ".join(row["event"].split()).rstrip(".")
        line = f"• {time_label(at)} · {event}"
        family = ("claims" if event == "Weekly jobless claims" and row["publisher"] == "DOL"
                  else calendar_sources.category(event, row["publisher"]))
        focus = weekend_narration.MACRO_FOCUS.get(family)
        if focus:
            line += f"\n  {focus[1]}"
        agenda[at.date()].append((at.time(), line))
        sources.append((row["publisher"], row["url"]))

    earnings_noted = set()
    for row in sorted(packet["company"], key=lambda row: (row["event_date"], not row["event_at"], row["event_at"])):
        day = date.fromisoformat(row["event_date"])
        at, line = company_entry(row)
        identity = (row["symbol"], day)
        if identity not in earnings_noted:
            focus = weekend_narration.EARNINGS_FOCUS.get(
                row["symbol"], "Compare reported sales and margins with the company's prior guidance."
            )
            line += f"\n  {focus}"
            earnings_noted.add(identity)
        agenda[day].append((at, line))
        sources.append((row["source"]["source"], row["source"]["url"]))

    days, missing = [], []
    start = date.fromisoformat(window["next_start"])
    for offset in range(5):
        day = start + timedelta(days=offset)
        if agenda[day]:
            rows = "\n".join(line for _, line in sorted(agenda[day]))
            days.append(f"{day:%A, %B} {day.day}\n" + rows)
        else:
            missing.append(day.strftime("%A"))
    coverage = "Publisher coverage is limited." if days else "No publisher-verified events in this edition."
    if days and missing:
        coverage += "\nDays without verified entries · " + ", ".join(missing)
    sections = [
        f"{day_label(window['next_start'])} to {day_label(window['next_end'])}",
        "Calendar and catalyst checks\n\n" + "\n\n".join([*days, coverage]),
    ]

    ipo = inputs.get("ipo")
    if ipo:
        source = ipo["source"]
        focus = "Watch for the final price, share count and expected net proceeds if the offering goes ahead."
        if source.get("weekend_prospectus_excerpt"):
            focus = "If the offering goes ahead, compare expected net proceeds and available cash with the commitments due over the disclosed twelve-month period."
        sections.append(f"Financing watch · {ipo['name']}\n{ipo['summary']}\n{focus}")
        sources.append((source["source"], source["url"]))
    for row in packet["later"]:
        _, line = company_entry(row)
        sections.append(f"Beyond this week\n{day_label(row['event_date'])}\n{line}")
        sources.append((row["source"]["source"], row["source"]["url"]))
    return sections, sources
