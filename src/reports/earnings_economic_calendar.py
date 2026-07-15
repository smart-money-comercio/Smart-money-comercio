from typing import Any


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


WEEK_LABEL = "Week of July 14, 2026"


ECONOMIC_CALENDAR = {
    "Tuesday": [
        "CPI, month-on-month, June (-0.1% expected, +0.5% previously)",
        "Core CPI, month-on-month, June (+0.2% expected, +0.2% previously)",
        "CPI, year-on-year, June (+3.8% expected, +4.2% previously)",
        "Core CPI, year-on-year, June (+2.8% expected, +2.9% previously)",
        "Real average weekly earnings, year-on-year, June (-0.5% previously)",
        "Real average hourly earnings, year-on-year, June (-0.8% previously)",
        "ADP weekly employment change, week ended June 27 (+21,000 previously)",
        "NFIB small business optimism, June (95.5 expected, 95.3 previously)",
    ],
    "Wednesday": [
        "PPI final demand, month-on-month, June (-0.1% expected, +1.1% previously)",
        "PPI ex food and energy, month-on-month, June (+0.4% expected, +0.4% previously)",
        "PPI final demand, year-on-year, June (+6.2% expected, +6.5% previously)",
        "PPI ex food and energy, year-on-year, June (+5.2% expected, +4.9% previously)",
        "Empire manufacturing, July (8.6 expected, 5.7 previously)",
        "MBA mortgage applications, week ended July 10 (-2.2% previously)",
        "Fed Beige Book",
    ],
    "Thursday": [
        "New York Fed services business activity, July (-10.1 previously)",
        "Philadelphia Fed business outlook, July (15 expected, 10.3 previously)",
        "Retail sales advance, month-on-month, June (+0.3% expected, +0.9% previously)",
        "Retail sales ex auto, month-on-month, June (-0.1% expected, +0.8% previously)",
        "Initial jobless claims, week ended July 11 (215,000 previously)",
        "Continuing claims, week ended July 4 (1.814 million previously)",
        "NAHB housing market index, July (35 expected, 35 previously)",
        "Business inventories, May (+0.3% expected, +0.5% previously)",
    ],
    "Friday": [
        "Import price index, year-on-year, June (+6.7% previously)",
        "Export price index, year-on-year, June (+11.2% previously)",
        "Housing starts, month-on-month, June (+13% expected, -15.4% previously)",
        "Building permits, month-on-month, June preliminary reading (-0.7% expected, -0.9% previously)",
        "Industrial production, month-on-month, June (+0.2% expected, +0.1% previously)",
        "Manufacturing production, month-on-month, June (+0.2% expected, +0.0% previously)",
        "U. Mich. sentiment, July preliminary reading (51.3 expected, 49.5 previously)",
        "U. Mich. current conditions, July preliminary reading (48.5 expected, 47.7 previously)",
        "U. Mich. expectations, July preliminary reading (52 expected, 50.7 previously)",
        "U. Mich. 1-year inflation, July preliminary reading (+4.6% previously)",
        "U. Mich. 5-10 year inflation, July preliminary reading (+3.3% previously)",
    ],
}


EARNINGS_CALENDAR = {
    "Tuesday": [
        "JPMorgan Chase (JPM)",
        "Bank of America (BAC)",
        "Goldman Sachs (GS)",
        "Wells Fargo (WFC)",
        "Citigroup (C)",
        "Fastenal Company (FAST)",
    ],
    "Wednesday": [
        "ASML Holding N.V. (ASML)",
        "Johnson & Johnson (JNJ)",
        "Morgan Stanley (MS)",
        "BlackRock (BLK)",
        "The Progressive Corporation (PGR)",
        "Bank of New York Mellon (BNY)",
        "PNC Financial Services (PNC)",
        "Elevance Health (ELV)",
        "Kinder Morgan (KMI)",
        "Cintas Corporation (CTAS)",
        "United Airlines Holdings (UAL)",
        "M&T Bank Corporation (MTB)",
        "J.B. Hunt Transport Services (JBHT)",
        "First Horizon Corporation (FHN)",
        "ConAgra Brands (CAG)",
    ],
    "Thursday": [
        "Taiwan Semiconductor Manufacturing Company (TSM)",
        "UnitedHealth Group (UNH)",
        "GE Aerospace (GE)",
        "Netflix (NFLX)",
        "Abbott Laboratories (ABT)",
        "Intuitive Surgical (ISRG)",
        "Prologis (PLD)",
        "U.S. Bancorp (USB)",
        "State Street Corporation (STT)",
        "Citizens Financial Group (CFG)",
        "Wipro (WIT)",
        "Alcoa Corporation (AA)",
        "Vista Energy, S.A.B. de C.V. (VIST)",
    ],
    "Friday": [
        "The Travelers Companies (TRV)",
        "Truist Financial Corporation (TFC)",
        "Fifth Third Bancorp (FITB)",
        "Danske Bank A/S (DSN.F)",
        "Autoliv (ALV)",
    ],
}


def build_calendar_impact_summary() -> str:
    return """
Market Impact Summary:
• Inflation is the main macro event this week, with CPI on Tuesday and PPI on Wednesday likely to shape the rates narrative.
• Retail sales, jobless claims, housing data, and University of Michigan sentiment will help confirm whether the consumer is weakening or stabilizing.
• Bank earnings start the season and should give an early read on credit quality, loan demand, deposits, trading, and consumer stress.
• ASML and TSM are the most important AI/semi earnings events for the watchlist because they help confirm demand across the semiconductor supply chain.
• Netflix, UnitedHealth, GE Aerospace, and major financials can influence broader market tone beyond AI.
""".strip()


def build_portfolio_calendar_read() -> str:
    return """
Portfolio Read:
• Bullish setup: Softer CPI/PPI, stable retail sales, and constructive bank earnings would support a risk-on tone.
• Caution setup: Hot inflation plus weak consumer data would pressure growth stocks, rate-sensitive names, and lower-quality cyclicals.
• AI watch: ASML and TSM matter most for semiconductor sentiment, AI infrastructure demand, and chip-sector rotation.
• Financials watch: JPM, BAC, GS, WFC, C, MS, BLK, and regional banks will help show whether credit risk is contained or spreading.
""".strip()


def format_day_calendar(day: str) -> str:
    economic_items = ECONOMIC_CALENDAR.get(day, [])
    earnings_items = EARNINGS_CALENDAR.get(day, [])

    economic_text = "\n".join(f"• {item}" for item in economic_items) or "• None listed"
    earnings_text = ", ".join(earnings_items) if earnings_items else "None listed"

    return f"""
{day}
Economic Data:
{economic_text}

Earnings Calendar:
{earnings_text}
""".strip()


def build_earnings_economic_calendar_section() -> str:
    days = ["Tuesday", "Wednesday", "Thursday", "Friday"]

    day_sections = "\n\n".join(format_day_calendar(day) for day in days)

    return f"""
Earnings and Economic Calendar
{WEEK_LABEL}

{build_calendar_impact_summary()}

{day_sections}

{build_portfolio_calendar_read()}
""".strip()