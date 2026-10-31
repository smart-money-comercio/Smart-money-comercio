import os
from typing import Any

from src.utils.report_consistency import validate_report_greeting, validate_report_risks
from src.intelligence.research_context import validate_research_output


MAX_DAILY_REPORT_CHARS = int(os.getenv("DAILY_REPORT_MAX_CHARS", "7600"))

REQUIRED_HEADERS = [
    "Portfolio Allocation Snapshot",
    "Intelligence Used Today",
    "Trade Plan Snapshot",
    "Executive Summary",
    "What Changed Today",
    "Theme Read",
    "Market Snapshot",
    "Earnings & Economic Calendar",
    "Portfolio Read",
    "Watchlist Movers",
    "Top Opportunities",
    "Fastest-Rising Opportunities",
    "Risk Notes",
    "Smart Money Summary",
    "Action Checklist",
    "Next Commands",
    "Notes",
]

REMOVED_HEADERS = {
    "Morning Brief",
    "Headline Setup",
    "Theme Scorecard",
    "Headlines",
}

UNIQUE_HEADERS = set(REQUIRED_HEADERS) | REMOVED_HEADERS

SECTION_HEADERS = UNIQUE_HEADERS | {
    "📊 Smart Money AI Daily Report",
    "Daily Brief",
    "Defense / AI Warfare Impact:",
}


SECTION_LINE_LIMITS = {
    "What Changed Today": 4,      # header + 3 bullets
    "Theme Read": 4,              # header + 3 bullets
    "Watchlist Movers": 8,
    # Ranking rows include captured model evidence. Keep each candidate's full
    # block, including Score Risk and its review command; the report-wide
    # character limit is still validated independently.
    "Fastest-Rising Opportunities": 6,
    "Risk Notes": 4,
    "Smart Money Summary": 4,              # header + Signal / Implication / Validation
    "Action Checklist": 5,
    "Next Commands": 10,
    "Trade Plan Snapshot": 6,
    "Intelligence Used Today": 2,
    "Portfolio Allocation Snapshot": 4,
}


def clean_text(value: Any) -> str:
    return "\n".join(line.rstrip() for line in str(value or "").splitlines()).strip()


def normalize_blank_lines(report: str) -> str:
    lines = clean_text(report).splitlines()
    output = []
    blank_count = 0

    for line in lines:
        if not line.strip():
            blank_count += 1

            if blank_count <= 1:
                output.append("")

            continue

        blank_count = 0
        output.append(line.rstrip())

    return "\n".join(output).strip()


def is_section_header(line: str) -> bool:
    return line.strip() in SECTION_HEADERS


def split_report_sections(report: str) -> list[tuple[str | None, list[str]]]:
    lines = normalize_blank_lines(report).splitlines()
    sections: list[tuple[str | None, list[str]]] = []

    current_header: str | None = None
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        if is_section_header(stripped):
            if current_lines:
                sections.append((current_header, current_lines))

            current_header = stripped
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_header, current_lines))

    return sections


def remove_removed_and_duplicate_sections(report: str) -> str:
    sections = split_report_sections(report)
    seen_headers = set()
    output_lines = []

    for header, lines in sections:
        if header in REMOVED_HEADERS:
            continue

        if header in UNIQUE_HEADERS:
            if header in seen_headers:
                continue

            seen_headers.add(header)

        output_lines.extend(lines)
        output_lines.append("")

    return normalize_blank_lines("\n".join(output_lines))


def trim_section_lines(report: str) -> str:
    sections = split_report_sections(report)
    output_lines = []

    for header, lines in sections:
        limit = SECTION_LINE_LIMITS.get(header)

        if limit and len(lines) > limit:
            kept = lines[:limit]

            if header not in {"What Changed Today", "Theme Read", "Smart Money Summary"}:
                kept.append("Briefly trimmed to keep /report focused.")

            lines = kept

        output_lines.extend(lines)
        output_lines.append("")

    return normalize_blank_lines("\n".join(output_lines))


def cap_what_changed_bullets(report: str) -> str:
    sections = split_report_sections(report)
    output_lines = []

    for header, lines in sections:
        if header != "What Changed Today":
            output_lines.extend(lines)
            output_lines.append("")
            continue

        header_line = lines[0]
        bullets = [line for line in lines[1:] if line.strip().startswith("•")]
        non_bullets = [
            line for line in lines[1:]
            if line.strip() and not line.strip().startswith("•")
        ]

        new_lines = [header_line]
        new_lines.extend(bullets[:3])

        if not bullets and non_bullets:
            new_lines.append("• " + " ".join(non_bullets)[:220])

        output_lines.extend(new_lines)
        output_lines.append("")

    return normalize_blank_lines("\n".join(output_lines))


def enforce_ai_summary_shape(report: str) -> str:
    sections = split_report_sections(report)
    output_lines = []

    for header, lines in sections:
        if header != "Smart Money Summary":
            output_lines.extend(lines)
            output_lines.append("")
            continue

        body = "\n".join(lines[1:])
        has_signal = "Signal:" in body
        has_implication = "Implication:" in body
        has_validation = "Validation:" in body

        if has_signal and has_implication and has_validation:
            output_lines.extend(lines[:4])
        else:
            output_lines.extend(
                [
                    "Smart Money Summary",
                    "Signal: Daily signal unavailable; use What Changed Today and Theme Read as the primary briefing layer.",
                    "Implication: Keep sizing disciplined until price, volume, and theme confirmation align.",
                    "Validation: Run /scorecard and /volume on the top-ranked idea before acting.",
                ]
            )

        output_lines.append("")

    return normalize_blank_lines("\n".join(output_lines))


def hard_trim_report(report: str) -> str:
    report = normalize_blank_lines(report)

    if len(report) <= MAX_DAILY_REPORT_CHARS:
        return report

    # Never slice through evidence, candidate/risk rows or the commands footer.
    # Compact whole secondary sections only, leaving the inputs used by the
    # news/voiceover review intact. Missing sections are not manufactured here.
    sections = split_report_sections(report)
    for header, compact_body in (
        ("Fastest-Rising Opportunities", "Full opportunity ranking: /top10"),
        ("Action Checklist", "Review the complete setup conditions: /tradeplans"),
        ("Portfolio Read", "Portfolio detail: /portfolio"),
        ("Portfolio Allocation Snapshot", "Allocation detail: /allocation"),
    ):
        for index, (name, lines) in enumerate(sections):
            if name != header:
                continue
            replacement = [lines[0], compact_body] + ([""] if not lines[-1].strip() else [])
            if len("\n".join(replacement)) < len("\n".join(lines)):
                sections[index] = (name, replacement)
            break
        report = normalize_blank_lines("\n".join(line for _, lines in sections for line in lines))
        if len(report) <= MAX_DAILY_REPORT_CHARS:
            return report

    # If the protected content itself cannot fit, keep it complete so strict
    # validation reports the length failure, rather than silently losing data.
    return report


def validate_daily_report_quality(report: str) -> dict:
    text = str(report or "")
    from src.reports.daily_news_brief import TITLE, validate_news_brief
    if text.startswith(TITLE + "\n"):
        return validate_news_brief(text)
    missing_headers = [
        header for header in REQUIRED_HEADERS
        if f"\n{header}\n" not in f"\n{text}\n"
    ]

    duplicate_headers = [
        header for header in UNIQUE_HEADERS
        if text.splitlines().count(header) > 1
    ]

    removed_headers_present = [
        header for header in REMOVED_HEADERS
        if f"\n{header}\n" in f"\n{text}\n"
    ]

    what_changed_block = ""

    if "What Changed Today" in text and "Theme Read" in text:
        what_changed_block = text.split("What Changed Today", 1)[1].split("Theme Read", 1)[0]

    what_changed_bullets = len(
        [
            line for line in what_changed_block.splitlines()
            if line.strip().startswith("•")
        ]
    )

    ai_summary_ok = all(
        label in text
        for label in ["Signal:", "Implication:", "Validation:"]
    )

    sections = {
        header: "\n".join(lines)
        for header, lines in split_report_sections(text)
        if header is not None
    }
    risk_consistency_errors = validate_report_risks(sections)
    greeting_errors = validate_report_greeting(text)
    research_context_errors = validate_research_output(text)

    return {
        "chars": len(text),
        "max_chars": MAX_DAILY_REPORT_CHARS,
        "missing_headers": missing_headers,
        "duplicate_headers": duplicate_headers,
        "removed_headers_present": removed_headers_present,
        "what_changed_bullets": what_changed_bullets,
        "ai_summary_ok": ai_summary_ok,
        "risk_consistency_errors": risk_consistency_errors,
        "greeting_errors": greeting_errors,
        "research_context_errors": research_context_errors,
        "passes": (
            len(text) <= MAX_DAILY_REPORT_CHARS
            and not missing_headers
            and not duplicate_headers
            and not removed_headers_present
            and what_changed_bullets <= 3
            and ai_summary_ok
            and not risk_consistency_errors
            and not greeting_errors
            and not research_context_errors
        ),
    }


def describe_quality_failure(result: dict) -> str:
    """Expose the failing checks without including the underlying report."""
    issues = []
    for key, label in (
        ("risk_consistency_errors", "Risk consistency"),
        ("missing_headers", "Missing sections"),
        ("duplicate_headers", "Duplicate sections"),
        ("removed_headers_present", "Obsolete sections"),
        ("greeting_errors", "Greeting"),
        ("research_context_errors", "Research context"),
    ):
        if result.get(key):
            issues.append(label + ": " + "; ".join(result[key]))
    if result.get("chars", 0) > result.get("max_chars", MAX_DAILY_REPORT_CHARS):
        issues.append(f"Length: {result['chars']} characters exceeds {result.get('max_chars', MAX_DAILY_REPORT_CHARS)}")
    if result.get("what_changed_bullets", 0) > 3:
        issues.append("What Changed Today exceeds three bullets")
    if not result.get("ai_summary_ok", True):
        issues.append("Smart Money Summary is missing Signal, Implication or Validation")
    return "; ".join(issues) or "Unspecified validation failure"


def enforce_daily_report_quality(report: str) -> str:
    cleaned = normalize_blank_lines(report)
    cleaned = remove_removed_and_duplicate_sections(cleaned)
    cleaned = cap_what_changed_bullets(cleaned)
    cleaned = enforce_ai_summary_shape(cleaned)
    cleaned = trim_section_lines(cleaned)
    cleaned = hard_trim_report(cleaned)

    return normalize_blank_lines(cleaned)
