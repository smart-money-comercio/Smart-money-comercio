"""Shared wording and validation for risk reads and report greetings."""

import re
from datetime import datetime


RISK_LABEL_GUIDE = (
    "Score Risk reflects scoring support; "
    "Setup Risk reflects score and theme caution."
)


def score_risk_label(stock: dict) -> str:
    """Display the scoring engine's label without inventing a missing value."""
    label = str(stock.get("risk_label") or "").strip()
    if label.lower() in {"", "n/a", "none", "unknown", "unavailable"}:
        return "Unavailable"
    return label


def report_greeting(now: datetime) -> str:
    """Use the same local clock as the report's Generated timestamp."""
    if now.hour < 5:
        return "Hello."
    if now.hour < 12:
        return "Good morning."
    if now.hour < 18:
        return "Good afternoon."
    return "Good evening."


def validate_report_greeting(report: str) -> list[str]:
    match = re.search(
        r"^Generated:\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\S+\s*$",
        report,
        re.MULTILINE,
    )
    if not match:
        return ["Generated timestamp is missing or invalid."]
    try:
        generated = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ["Generated timestamp is invalid."]

    greetings = [
        line.strip().rstrip(".!")
        for line in report.splitlines()
        if line.strip().rstrip(".!")
        in {"Good morning", "Good afternoon", "Good evening", "Hello"}
    ]
    expected = report_greeting(generated).rstrip(".")
    if greetings != [expected]:
        return [f"Greeting must be '{expected}' for the Generated timestamp."]
    return []


def _risk_entries(text: str, section: str, errors: list[str]) -> dict:
    entries = {}
    current_symbol = None
    for line in text.splitlines():
        match = re.match(r"^\s*\d+\.\s+([A-Za-z0-9][A-Za-z0-9.^=-]*)\s+[-—|]", line)
        if match:
            current_symbol = match.group(1).upper()
            if current_symbol in entries:
                errors.append(f"{section}: duplicate candidate {current_symbol}.")
            entries[current_symbol] = {}
        if current_symbol is None:
            continue
        for label in ("Score Risk", "Setup Risk"):
            match = re.search(rf"\b{label}:\s*([^|,\n]+)", line)
            if match:
                value = match.group(1).strip()
                if label in entries[current_symbol]:
                    errors.append(f"{section}: duplicate {label} for {current_symbol}.")
                entries[current_symbol][label] = value
        if re.search(r"(?<!Score )(?<!Setup )\bRisk(?: Level)?:", line):
            errors.append(f"{section}: unqualified risk label for {current_symbol}.")
    return entries


def validate_report_risks(sections: dict[str, str]) -> list[str]:
    """Compare the same risk measure and candidate order across daily sections."""
    errors = []
    opportunities = _risk_entries(sections.get("Top Opportunities", ""), "Top Opportunities", errors)
    snapshots = _risk_entries(sections.get("Trade Plan Snapshot", ""), "Trade Plan Snapshot", errors)
    if list(opportunities) != list(snapshots):
        errors.append("Trade Plan Snapshot candidates must match Top Opportunities in the same order.")

    for symbol, fields in opportunities.items():
        if not fields.get("Score Risk"):
            errors.append(f"Top Opportunities: missing Score Risk for {symbol}.")
    for symbol, fields in snapshots.items():
        for label in ("Score Risk", "Setup Risk"):
            if not fields.get(label):
                errors.append(f"Trade Plan Snapshot: missing {label} for {symbol}.")
        source = opportunities.get(symbol, {}).get("Score Risk")
        displayed = fields.get("Score Risk")
        if source and displayed and source.casefold() != displayed.casefold():
            errors.append(f"Score Risk disagrees for {symbol}: {source} versus {displayed}.")
    return errors
