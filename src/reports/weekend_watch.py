"""Sunday market and business checks drawn from the admitted weekend inputs."""

from datetime import date
import re

from src.intelligence import weekend_inputs, weekend_theme
from src.utils.market_quote_source import BENCHMARKS


MILITARY_CONTEXT = re.compile(
    r"\b(?:military|defen[cs]e|army|navy|air force|space force|marine corps|department of war|DARPA|DoD|Pentagon)\b",
    re.IGNORECASE,
)
INNOVATION = (
    ("Military AI", re.compile(r"\b(?:AI|artificial intelligence|machine learning)\b", re.IGNORECASE),
     "Watch for funded agency work, paid deployments and renewals."),
    ("Drones and counter-drone", re.compile(
        r"\b(?:drones?|UAS|UAVs?|un(?:crewed|manned) (?:aircraft|aerial (?:systems?|vehicles?))|counter[- ]?UAS)\b",
        re.IGNORECASE,
    ), "Check committed funding, delivery schedules and disclosed production costs."),
    ("Cybersecurity", re.compile(r"\b(?:cybersecurity|cyber[ -](?:security|defen[cs]e|protection)|endpoint security)\b",
                                 re.IGNORECASE),
     "Watch for paid adoption, deployment milestones and renewal terms."),
)

DEVELOPMENTS = {
    ("contract", "order award"): "reported an order",
    ("contract", "award"): "announced a contract award",
    ("contract", "ceiling"): "reported a contract ceiling",
    ("contract", "cooperation"): "announced a cooperation agreement",
    ("product", "test milestone"): "reported a test milestone",
    ("product", "planned test"): "announced a planned test",
    ("product", "prototype"): "announced a prototype",
    ("product", "production"): "reported production progress",
    ("product", "initial purchases"): "reported initial customer purchases",
    ("product", "available"): "reported commercial availability",
    ("technology collaboration", "announced"): "announced a collaboration",
}
DEFENSE_FOLLOW_UP = {
    ("contract", "order award"): "Look for committed funding and a delivery timetable.",
    ("contract", "award"): "Look for obligated funding and a schedule for the work.",
    ("product", "test milestone"): "Watch for a funded order or an official production decision.",
    ("product", "production"): "Watch for funded deliveries and any change in program costs.",
    ("product", "initial purchases"): "Watch for repeat orders and disclosed order values.",
}


def premarket_watch(inputs: dict) -> tuple[str, list[tuple[str, str]]]:
    close = date.fromisoformat(inputs["window"]["week_end"])
    moves, sources = [], []
    for row in inputs["prices"]:
        if row["status"] == "available":
            proof = row["proof"]
            label = BENCHMARKS[row["symbol"]]
            moves.append(f"{label} {proof['friday_percent']:+.2f}%")
            sources.append((f"{label} · Yahoo chart", proof["url"]))
    closing = f"{close:%A, %b} {close.day} cash close · " + (
        " · ".join(moves) if moves else "Dated benchmark readings unavailable."
    )
    return (
        "Premarket watch\n" + closing + "\n"
        "Before the next U.S. open, compare S&P 500 and Nasdaq-100 futures with SPY, QQQ and the SMH chip ETF "
        "as fresh readings become available. Weakness concentrated in SMH and chip shares would keep the "
        "focus on semiconductors. Weakness in SPY as well would point to a wider move.\n"
        "Check the VIX, 10-year Treasury yield and crude oil for moves alongside stocks.\n"
        "Dated futures and ETF checks · /premarket history",
        sources,
    )


def innovation_topics(story: dict) -> set[str]:
    proof = story["event_evidence"]
    original_facts = " ".join(fact.get("evidence", fact["value"]) for fact in proof["facts"])
    evidence = f"{story['title']} {original_facts}"
    military = bool(MILITARY_CONTEXT.search(original_facts))
    return {
        label for label, pattern, _ in INNOVATION
        if pattern.search(evidence) and (label == "Cybersecurity" or military)
    }


def dated_development(story: dict) -> str:
    proof = story["event_evidence"]
    event = (proof["event"], proof["stage"])
    action = DEVELOPMENTS.get(event, "published a relevant update")
    fields = {row["field"]: row["value"] for row in proof["facts"]}
    if event == ("contract", "order award") and "order_value" in fields:
        action = f"reported an order valued at {fields['order_value']}"
    if event == ("contract", "award") and "contract_value" in fields:
        action = f"announced a contract award valued at {fields['contract_value']}"
    stamp = weekend_inputs.clock(story["published"]).astimezone(weekend_inputs.NY)
    return f"{weekend_theme.name(story)} {action} on {stamp:%b} {stamp.day}."


def defense_watch(stories: list[dict]) -> tuple[str, list[tuple[str, str]]]:
    candidates = [(story, innovation_topics(story)) for story in stories]
    used = set()
    lines = ["Military innovation"]
    sources = []
    for label, _, follow_up in INNOVATION:
        lead = next((story for story, topics in candidates if label in topics and story["id"] not in used), None)
        if lead:
            used.add(lead["id"])
            lines.append(f"• {label} · {dated_development(lead)}\n  {follow_up}")
            sources.append((lead["source"], lead["url"]))
        else:
            lines.append(f"• {label} · {follow_up}")
    if not sources:
        lines.append("Publisher coverage is limited for these technology areas.")
        for story in stories:
            proof = story["event_evidence"]
            event = (proof["event"], proof["stage"])
            if event in DEFENSE_FOLLOW_UP and weekend_theme.group(story) == "defense":
                lines.append(f"• Defense industry · {dated_development(story)}\n  {DEFENSE_FOLLOW_UP[event]}")
                sources.append((story["source"], story["url"]))
                break
    return "\n".join(lines), sources


def week_intelligence(families: set[str], earnings: bool) -> str:
    labor = families.intersection({"jobs", "claims", "jolts"})
    inflation = families.intersection({"cpi", "pce", "ppi"})
    if "fomc_minutes" in families and labor:
        policy = "The Fed minutes explain the discussion at the prior meeting. The new labor data give us a more recent check."
        if earnings:
            return policy + " Softer labor readings alongside weaker company sales guidance would raise concern about broader demand."
        return policy + " Watch whether the new labor readings reinforce the risks officials identified."
    if inflation and earnings:
        return (
            "Read the price data alongside company margin guidance. Broad cost pressure in the release and "
            "weaker margins in company outlooks would be two signs that higher costs are reaching earnings."
        )
    if labor and earnings:
        return (
            "Pair the labor release with company sales guidance. Weakness in both would raise concern about broader demand. "
            "If the signals diverge, check which customers and markets the company guidance covers."
        )
    if inflation and labor:
        return "Read inflation and labor together. Cooling inflation with steady hiring would support a more resilient growth outlook."
    return ""
