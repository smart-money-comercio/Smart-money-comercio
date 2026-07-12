from datetime import datetime
from zoneinfo import ZoneInfo

from src.reports.global_market_report import load_headlines


REPORT_TIMEZONE = "America/Lima"
MAX_HEADLINES_PER_GROUP = 4


IMPACT_ORDER = [
    "Rates / Inflation",
    "AI / Tech",
    "Energy",
    "China / Trade",
    "Defense / Geopolitical",
    "Dollar / Safety",
    "Market",
]


def clean_text(value, max_length: int = 180) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def group_headlines(headlines: list[dict]) -> dict:
    grouped = {}

    for item in headlines or []:
        impact = item.get("impact") or "Market"
        title = clean_text(item.get("title"), 180)
        source = clean_text(item.get("source"), 40)

        if not title:
            continue

        grouped.setdefault(impact, [])

        grouped[impact].append(
            {
                "title": title,
                "source": source or "Source",
            }
        )

    return grouped


def build_impact_readout(grouped: dict) -> str:
    if not grouped:
        return "No headline themes available right now."

    themes = []

    for impact in IMPACT_ORDER:
        if impact in grouped:
            themes.append(impact)

    for impact in grouped:
        if impact not in themes:
            themes.append(impact)

    readouts = []

    if "Rates / Inflation" in themes:
        readouts.append("Rates/inflation headlines can pressure growth, AI, small caps, and high-multiple names.")

    if "AI / Tech" in themes:
        readouts.append("AI/tech headlines may directly affect semiconductor, software, cybersecurity, and data-center themes.")

    if "Energy" in themes:
        readouts.append("Energy headlines can support oil-linked names but may raise inflation risk for the broader market.")

    if "China / Trade" in themes:
        readouts.append("China/trade headlines can affect semiconductors, industrials, emerging markets, and global risk appetite.")

    if "Defense / Geopolitical" in themes:
        readouts.append("Defense/geopolitical headlines can increase attention on drones, cybersecurity, defense primes, and strategic infrastructure.")

    if "Dollar / Safety" in themes:
        readouts.append("Dollar/safety headlines can signal risk-off behavior and pressure international or commodity-sensitive themes.")

    if not readouts:
        readouts.append("Headline risk is broad; use /global to confirm market regime before acting.")

    return "\n".join(f"• {line}" for line in readouts[:5])


def format_group(impact: str, items: list[dict]) -> str:
    lines = [f"{impact}"]

    for item in items[:MAX_HEADLINES_PER_GROUP]:
        source = item.get("source") or "Source"
        title = item.get("title") or "Untitled"
        lines.append(f"• {title} ({source})")

    return "\n".join(lines)


def format_grouped_headlines(grouped: dict) -> str:
    if not grouped:
        return "No headlines available right now."

    sections = []

    for impact in IMPACT_ORDER:
        if impact in grouped:
            sections.append(format_group(impact, grouped[impact]))

    for impact, items in grouped.items():
        if impact not in IMPACT_ORDER:
            sections.append(format_group(impact, items))

    return "\n\n".join(sections)


def build_headlines_report() -> str:
    now = datetime.now(ZoneInfo(REPORT_TIMEZONE))
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    try:
        headlines = load_headlines()
    except Exception as error:
        headlines = []
        load_error = type(error).__name__
    else:
        load_error = ""

    grouped = group_headlines(headlines)

    if load_error:
        headline_text = f"Unable to load headlines right now: {load_error}"
    else:
        headline_text = format_grouped_headlines(grouped)

    return f"""
📰 Smart Money Headlines
Generated: {timestamp} {REPORT_TIMEZONE}

Portfolio Impact Readout
{build_impact_readout(grouped)}

Headline Themes
{headline_text}

How To Use This
• Use /global to confirm market regime.
• Use /report for portfolio impact.
• Use /scorecard SYMBOL before making decisions.

Note
Headlines are research context only, not financial advice.
""".strip()