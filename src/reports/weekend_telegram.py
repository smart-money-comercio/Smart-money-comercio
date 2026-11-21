"""Saturday and Sunday Telegram presentations of checked weekly evidence."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from src.intelligence import business_analysis, calendar_sources, weekend_business, weekend_inputs, weekend_theme
from src.intelligence.daily_brief_analysis import NAMES
from src.reports import weekend_narration, weekend_watch
from src.reports.weekend_outlook import day_label
from src.utils.market_quote_source import BENCHMARKS


SATURDAY = "Saturday Review"
SUNDAY = "Sunday Outlook"

EARNINGS_TAKEAWAYS = {
    "NVDA": (
        "Nvidia's earnings offer a test of whether AI demand is translating into profitable growth. "
        "Strong data center sales and steady gross margins would support that case. "
        "If sales rise and margins narrow, look for what management says about the cost of delivering that growth."
    ),
    "AMD": (
        "AMD's earnings give us a test of how its data center expansion is contributing to profits. "
        "Higher server and AI chip sales alongside steady margins would strengthen the case that the expansion is paying off."
    ),
    "INTC": (
        "Intel's earnings can show whether its server business is improving while it invests in manufacturing. "
        "Higher server sales alongside an improving foundry margin outlook would strengthen the case."
    ),
    "MSFT": (
        "Microsoft's earnings offer a test of whether cloud demand can support the cost of building data center capacity. "
        "Cloud growth alongside a steady margin outlook would strengthen the case for the investment."
    ),
    "AMZN": (
        "Amazon's earnings can show how AWS demand is translating into profits while Amazon expands capacity. "
        "Higher AWS sales and steady operating margins would support the case that demand is absorbing the added costs."
    ),
}

MACRO_TAKEAWAYS = {
    "fomc_decision": (
        "The Fed's decision could change the outlook for borrowing costs. "
        "Listen for which inflation or employment readings would move policymakers toward their next rate change."
    ),
    "fomc_minutes": (
        "The Fed minutes can show how much agreement there was about the next policy step. "
        "Pay attention to which data policymakers wanted to see before changing rates and how widely that view was shared."
    ),
    "cpi": (
        "The next inflation reading tests whether price pressures are cooling across the economy. "
        "Broad easing could give the Fed more flexibility. Persistent core services inflation would keep the timing of any rate change uncertain."
    ),
    "pce": (
        "This week's price and spending data test whether inflation can ease while demand holds up. "
        "Cooling inflation alongside steady real spending would support that view. Weak real spending would put the growth outlook in focus."
    ),
    "ppi": (
        "Producer prices offer an early check on costs that could reach company margins. "
        "Broad increases would make it important to see whether businesses can pass those costs on to customers."
    ),
    "jobs": (
        "The jobs report tests whether hiring is cooling gradually. "
        "Moderate hiring and slower wage growth would fit that picture. Weak hiring alongside rising unemployment would raise the risk of softer demand."
    ),
    "gdp": (
        "The GDP release can show how much growth came from household spending and business investment. "
        "Strength in both would support a more durable growth outlook. A large inventory contribution would make the next demand readings more important."
    ),
    "claims": (
        "Weekly jobless claims offer an early check on whether layoffs are spreading. "
        "A sustained rise across several releases would give us stronger evidence that labor demand is weakening."
    ),
    "jolts": (
        "The job openings report tests whether employers are pulling back on hiring. "
        "Fewer openings alongside fewer hires would point to weaker labor demand."
    ),
    "michigan_sentiment": (
        "Michigan's survey can show whether consumers are getting more comfortable with their finances and the inflation outlook. "
        "Improvement on both measures would give us a reason to look for stronger spending in the next hard data."
    ),
}


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
        sections, sources = sunday_outlook(inputs, record["theme"])
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
    # Give reported earnings priority over a routine payout when both are verified.
    for story in sorted(stories, key=lambda row: row["event_evidence"]["schema"] != 17):
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
            followup = review["watch"] if row["event_evidence"]["schema"] == 17 else review["decision_test"]
            text += f"\nFollow-up · {followup}"
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


def sunday_takeaway(inputs: dict, theme: dict | None) -> str:
    packet = inputs["calendar"]
    story_ids = set(theme["story_ids"]) if theme else set()
    stories = [story for story in inputs["stories"] if story["id"] in story_ids]
    featured = weekend_narration.featured_events(packet, theme, stories)
    lead = min(featured, key=lambda item: (item["rank"], item["day"], item["time"]), default=None)
    if lead:
        kind, key, _ = lead["group"]
        if kind == "company":
            if key in EARNINGS_TAKEAWAYS:
                return EARNINGS_TAKEAWAYS[key]
            issuer = NAMES.get(key, key)
            return (
                f"{issuer}'s earnings will test whether demand is improving its profit outlook. "
                "Stronger sales and steady margins would support that case. If sales rise and margins narrow, "
                "look for what drove the added costs and whether management expects them to persist."
            )
        return MACRO_TAKEAWAYS.get(
            key, f"{lead['label']} gives us a check on the economic outlook. "
            "Look at the size and breadth of the change for signs that the previous trend is shifting."
        )
    if packet["macro"]:
        first = min(packet["macro"], key=lambda row: weekend_inputs.clock(row["at"]))
        event = " ".join(first["event"].split()).rstrip(".")
        return f"The first verified release is {event}. Compare the result with the previous reading for signs that the trend is changing."
    if ipo := inputs.get("ipo"):
        return (
            f"{ipo['name']}'s indicative IPO terms put access to capital in focus. "
            "If the offering goes ahead, the final terms will help show how much cash it could add and when that funding might become available."
        )
    return "Publisher coverage is too limited to single out a catalyst for the coming week. Watch for original issuer notices and official release times."


def sunday_outlook(inputs: dict, theme: dict | None) -> tuple[list[str], list[tuple[str, str]]]:
    window, packet = inputs["window"], inputs["calendar"]
    agenda = defaultdict(list)
    premarket, sources = weekend_watch.premarket_watch(inputs)
    families = set()
    for row in packet["macro"]:
        at = weekend_inputs.clock(row["at"]).astimezone(weekend_inputs.NY)
        event = " ".join(row["event"].split()).rstrip(".")
        line = f"• {time_label(at)} · {event}"
        family = ("claims" if event == "Weekly jobless claims" and row["publisher"] == "DOL"
                  else calendar_sources.category(event, row["publisher"]))
        families.add(family)
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
        "The takeaway\n" + sunday_takeaway(inputs, theme),
        premarket,
        "Calendar and catalyst checks\n\n" + "\n\n".join([*days, coverage]),
    ]

    read = weekend_watch.week_intelligence(families, bool(packet["company"]))
    if read:
        sections.append("Week-ahead intelligence\n" + read)
    defense, defense_sources = weekend_watch.defense_watch(inputs["stories"])
    sections.append(defense)
    sources.extend(defense_sources)

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
