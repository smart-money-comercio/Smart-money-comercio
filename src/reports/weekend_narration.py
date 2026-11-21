"""Explicit weekend narration revision; archived revision 1 is left intact."""

from datetime import date, time
import re

from src.intelligence import weekend_inputs as evidence, company_schedule
from src.intelligence.calendar_sources import category
from src.intelligence.daily_brief_analysis import NAMES
from src.intelligence.weekend_theme import FRAMES
from src.utils.market_quote_source import BENCHMARKS
from src.utils.speech_text import normalize

REVISION = 2

QUESTIONS = {
    "reported_results": FRAMES["reported_results"]["question"],
    "payout": FRAMES["payout"]["question"],
    "ai": "Can paying demand keep up with what companies are spending on AI?",
    "business": "What would turn this week's business developments into higher sales or better margins?",
    "counterparty": "Which companies have a direct exposure to the payment restrictions?",
    "cyber": "What would show that customers are spending more on cybersecurity?",
    "defense": "Which defense milestones could turn into funded work?",
    "energy": "Do the latest disclosures point to a change in energy supply or operating costs?",
    "funding": "What could this week's policy and financing decisions mean for companies that need to raise cash?",
}

MACRO_FOCUS = {
    "fomc_decision": ("Fed rate decision", "Listen for what would lead the Fed to change rates and how long it expects to keep policy restrictive."),
    "fomc_minutes": ("Fed minutes", "Look for how policymakers weighed inflation against signs of a slowing economy."),
    "cpi": ("Consumer price index", "Watch whether inflation is easing across categories or remains concentrated in stubborn areas."),
    "pce": ("Personal income and outlays", "Look at inflation alongside personal spending to see whether demand is holding up."),
    "ppi": ("Producer price index", "Watch whether price pressure is spreading at the producer level, where it can show up in company costs."),
    "jobs": ("U.S. jobs report", "Compare hiring and wages for signs that labor demand is cooling."),
    "gdp": ("U.S. GDP", "Look at consumer spending and business investment for clues about what is driving growth."),
    "claims": ("Weekly jobless claims", "Look for a sustained change in new claims as an early read on layoffs."),
    "jolts": ("U.S. job openings", "See whether vacancies are falling, which can signal a cooling labor market."),
    "michigan_sentiment": ("Michigan consumer sentiment", "Watch household inflation expectations and whether consumers report more confidence in their finances."),
}

# Use confirmed earnings notices to name the business variable worth revisiting.
EARNINGS_FOCUS = {
    "NVDA": "Listen for its data center outlook and whether the company expects margins to hold as it ships new products.",
    "AMD": "Watch for data center sales, customer adoption and the margin outlook for its server and AI products.",
    "AVGO": "Look for its AI sales outlook and the timing of customer deployments.",
    "INTC": "Watch server sales and foundry costs for signs the business can improve its margins.",
    "MSFT": "Compare cloud growth with what the company expects to spend on data centers.",
    "AMZN": "Compare AWS growth with capital spending and the company's margin outlook.",
    "GOOG": "Compare Google Cloud growth with what Alphabet expects to spend on AI infrastructure.",
    "GOOGL": "Compare Google Cloud growth with what Alphabet expects to spend on AI infrastructure.",
    "TSM": "Watch demand for advanced chips and what the company says about capacity and margins.",
}


def revision(inputs):
    value = inputs.get("narration_revision", 1)
    if type(value) is not int or value not in {1, REVISION}:
        raise ValueError("Unknown Weekend Outlook narration revision")
    return value


def calendar(packet, periods):
    start, end = date.fromisoformat(periods["next_start"]), date.fromisoformat(periods["next_end"])
    lines = [f"For {start:%B} {start.day} through {end:%B} {end.day}, here are the verified calendar entries."]
    entries = []
    for row in packet["macro"]:
        at = evidence.clock(row["at"]).astimezone(evidence.NY)
        entries.append((at.isoformat(), f"{at:%A}, {at:%B} {at.day}: {row['event']} at {at:%I:%M %p %Z}, according to {row['publisher']}."))
    for row in packet["company"]:
        entries.append((row["event_at"] or row["event_date"], company_schedule.narration(row, evidence.NY, NAMES)))
    if entries:
        lines.extend(text for _, text in sorted(entries))
        lines.append("Our verified calendar is incomplete, so other events may be missing. Estimated earnings dates are excluded.")
    else:
        lines = [f"For the week of {start:%B} {start.day}, no publisher-verified releases or company events qualified for this edition's calendar. Coverage is incomplete; additional events may be scheduled."]
    return "\n".join(lines)


def event_copy(day, at, label, reason):
    when = f"{day:%A}, {day:%B} {day.day}"
    if at:
        when += f" at {at:%I:%M %p %Z}"
    text = f"{label} {when}."
    if not at:
        text += " The issuer gave a date only."
    return text + " " + reason


def featured_events(packet, theme, stories, ipo=None):
    """Choose verified events by relevance, then present them in calendar order."""
    from src.intelligence.weekend_theme import AI_ISSUERS

    theme_id = theme["id"] if theme else ""
    issuers = {story.get("publisher_symbol") for story in stories}
    entries = []
    for index, row in enumerate(packet["macro"]):
        family = "claims" if row["event"] == "Weekly jobless claims" and row["publisher"] == "DOL" else category(row["event"])
        if family not in MACRO_FOCUS:
            continue
        at = evidence.clock(row["at"]).astimezone(evidence.NY)
        label, reason = MACRO_FOCUS[family]
        connected = theme_id in {"ai", "ai_financing", "funding"} and family in {"fomc_decision", "fomc_minutes", "cpi", "pce", "ppi"}
        entries.append({"group": ("macro", family, at.date()), "rank": (2 if connected else 3, tuple(MACRO_FOCUS).index(family)),
                        "day": at.date(), "time": at.time(), "label": label,
                        "copy": event_copy(at.date(), at, label + " come out" if family in {"claims", "fomc_minutes"}
                                           else "The calendar lists " + label + " for", reason),
                        "source_id": f"calendar_{index}"})

    for index, row in enumerate(packet["company"]):
        symbol = row["symbol"]
        issuer = NAMES.get(symbol, symbol)
        day = date.fromisoformat(row["event_date"])
        at = evidence.clock(row["event_at"]).astimezone(evidence.NY) if row["event_at"] else None
        # Results and the call answer the same business question. Use the
        # timed call when both notices cover the same day.
        related = theme_id in {"ai", "ai_financing"} and symbol in AI_ISSUERS
        rank = 0 if symbol in issuers else 1 if related else 4
        label = issuer + " earnings"
        event = "earnings call" if row["event"] == "earnings conference call" else "results release"
        reason = EARNINGS_FOCUS.get(symbol, "Compare the sales and margin outlook with the company's previous guidance.")
        entries.append({"group": ("company", symbol, day), "rank": (rank, not at, event != "earnings call"),
                        "day": day, "time": at.time() if at else time.max, "label": label,
                        "copy": event_copy(day, at, f"{issuer}'s {event} is scheduled for", reason), "source_id": f"company_{index}"})

    def chronological(row):
        return row["day"], row["time"], row["label"], row["source_id"]

    unique = {}
    for row in sorted(entries, key=lambda row: (row["rank"], chronological(row))):
        unique.setdefault(row["group"], row)
    featured = sorted(list(unique.values())[:2 if ipo else 3], key=chronological)
    if ipo:
        label = ipo["name"] + " IPO terms"
        featured.append({"label": label, "copy": f"For {ipo['name']}, watch the final terms if the IPO proceeds. "
                         "Compare the expected net proceeds with the cash the company says it needs to fund growth.",
                         "source_id": "ipo_" + ipo["id"]})
    return featured


def opening(prices, question):
    def move(value):
        rounded = round(value, 2)
        if not rounded:
            return "was flat"
        verb = "rose" if rounded > 0 else "fell"
        return f"{verb} {abs(rounded):.2f} percent"

    available = {row["symbol"]: row["proof"] for row in prices if row["status"] == "available"}
    symbol = next((key for key in BENCHMARKS if key in available), "")
    if not symbol:
        return "The weekly benchmark figures are unavailable." + (f" {question}" if question else ""), []

    proof = available[symbol]
    label = "the " + BENCHMARKS[symbol]
    week, friday = move(proof["weekly_percent"]), move(proof["friday_percent"])
    if week != "was flat" and friday != "was flat" and week.split()[0] != friday.split()[0]:
        text = f"For the week, {label} {week} despite {'a gain' if friday.startswith('rose') else 'a drop'} of {friday.partition(' ')[2]} on Friday."
    else:
        text = f"For the week, {label} {week}. On Friday, it {friday}."
    return text + (f" {question}" if question else ""), ["market_" + symbol]


def driver_watch(theme):
    if theme["id"] in {"reported_results", "payout"}:
        return theme["stronger"] + " " + theme["weaker"]
    return {
        "ai": "For chipmakers and cloud providers, compare new sales guidance with the cost of adding and running capacity. Rising sales alongside stable margins would strengthen the business case. Higher spending and weaker margins would show that growth is becoming more expensive to deliver.",
        "defense": "Watch for follow-on orders with committed funding and delivery dates. Those details show when work could start contributing to sales. Delays or higher delivery costs could put pressure on margins.",
        "cyber": "Watch whether customers sign paid contracts, expand deployments or renew at higher spending levels. Check whether the extra sales cover the cost of supporting those customers.",
        "energy": "Compare the figures in the disclosure with more recent output and inventory data. Then look at company results for signs that changes in input costs are reaching margins.",
        "funding": "Watch the terms companies actually get when they raise money. The interest rate, maturity and amount raised help show what financing is available and what it will cost.",
        "counterparty": "Look for disclosures identifying which businesses use the affected payment channels and what it costs them to switch. That would help put a dollar figure on the exposure.",
        "business": "Look for the next company disclosure to quantify the demand behind the announcement. New orders, a delivery timetable or a change in margins would show how the development could affect earnings.",
    }[theme["id"]]


def spoken(text):
    # The Air Force uses both Mk21A and Mark 21A for the same designation:
    # https://www.af.mil/Portals/1/documents/1/annual_report_web.pdf (p. 28).
    text = re.sub(r"\bMk[- ]?21A\b", "Mark twenty-one A", text, flags=re.I)
    text = re.sub(r"\bDefense Enterprise Accounting and Management System\s*\(DEAMS\)",
                  "Defense Enterprise Accounting and Management System", text)
    text = re.sub(r"\bDEAMS\b", "D E A M S", text)
    def agency(match):
        before = text[:match.start()].rstrip()
        article = "The" if not before or before.endswith((".", "!", "?")) else "the"
        return article + " U.S. Department of Labor"
    text = re.sub(r"\b(?:the\s+)?DOL\b", agency, text, flags=re.I)
    return normalize(text, brand_names=True, agency_names=True, disclosure_names=True)
