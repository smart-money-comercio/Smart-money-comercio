import os
from typing import Any


MAX_DAILY_REPORT_CHARS = int(os.getenv("DAILY_REPORT_MAX_CHARS", "6200"))

REQUIRED_HEADERS = [
    "Executive Summary",
    "What Changed Today",
    "Theme Read",
    "Market Snapshot",
    "Portfolio Read",
    "Watchlist Movers",
    "Top Opportunities",
    "Risk Notes",
    "Smart Money Summary",
    "Trade Plan Snapshot",
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
    "Top Opportunities": 13,
    "Risk Notes": 4,
    "Smart Money Summary": 4,
    "Trade Plan Snapshot": 7,              # header + Signal / Implication / Validation
    "Action Checklist": 5,
    "Next Commands": 6,
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

            if header not in {"What Changed Today", "Theme Read", "Smart Money Summary", "Trade Plan Snapshot"}:
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
    "Trade Plan Snapshot",
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

    marker = "\nNotes\n"

    if marker in report:
        body, notes = report.split(marker, 1)
        room = MAX_DAILY_REPORT_CHARS - len(marker) - len(notes) - 120
        trimmed_body = body[:room].rstrip()
        return normalize_blank_lines(
            trimmed_body
            + "\n\nReport trimmed automatically to keep /report focused.\n"
            + marker
            + notes
        )

    return report[: MAX_DAILY_REPORT_CHARS - 80].rstrip() + "\n\nReport trimmed automatically."


def validate_daily_report_quality(report: str) -> dict:
    text = str(report or "")
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

    return {
        "chars": len(text),
        "max_chars": MAX_DAILY_REPORT_CHARS,
        "missing_headers": missing_headers,
        "duplicate_headers": duplicate_headers,
        "removed_headers_present": removed_headers_present,
        "what_changed_bullets": what_changed_bullets,
        "ai_summary_ok": ai_summary_ok,
        "passes": (
            len(text) <= MAX_DAILY_REPORT_CHARS
            and not missing_headers
            and not duplicate_headers
            and not removed_headers_present
            and what_changed_bullets <= 3
            and ai_summary_ok
        ),
    }


def enforce_daily_report_quality(report: str) -> str:
    cleaned = normalize_blank_lines(report)
    cleaned = remove_removed_and_duplicate_sections(cleaned)
    cleaned = cap_what_changed_bullets(cleaned)
    cleaned = enforce_ai_summary_shape(cleaned)
    cleaned = trim_section_lines(cleaned)
    cleaned = hard_trim_report(cleaned)

    return normalize_blank_lines(cleaned)