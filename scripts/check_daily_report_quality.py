import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Keep deploy/preflight deterministic and fast.
# build_daily_report imports this setting at module import time, so set it early.
os.environ.setdefault("DAILY_REPORT_LIVE_QUOTES", "0")


from src.reports.daily_report import build_daily_report
from src.reports.report_quality import validate_daily_report_quality


SUMMARY_LABEL = "Smart Money Summary"


def format_list(items) -> str:
    if not items:
        return "None"

    return ", ".join(str(item) for item in items)


def get_validation_value(result: dict, *keys, default=None):
    for key in keys:
        if key in result:
            return result.get(key)

    return default


def format_quality_report(result: dict) -> str:
    missing = get_validation_value(
        result,
        "missing_required_headers",
        "missing_headers",
        "missing",
        default=[],
    )

    duplicates = get_validation_value(
        result,
        "duplicate_headers",
        "duplicates",
        default=[],
    )

    removed = get_validation_value(
        result,
        "removed_headers_present",
        "removed_present",
        "removed_headers",
        default=[],
    )

    chars = get_validation_value(
        result,
        "chars",
        "character_count",
        "length",
        default="unknown",
    )

    what_changed_bullets = get_validation_value(
        result,
        "what_changed_bullets",
        "what_changed_today_bullets",
        default="unknown",
    )

    # Keep backward-compatible result keys from report_quality.py.
    # Only the printed label changes.
    summary_ok = get_validation_value(
        result,
        "smart_money_summary_ok",
        "smart_money_summary_valid",
        "ai_summary_ok",
        "ai_summary_valid",
        default="unknown",
    )

    status = "PASS" if result.get("passes") else "FAIL"

    return f"""
Daily Report Quality Check
Status: {status}

Characters: {chars}
What Changed Bullets: {what_changed_bullets}
{SUMMARY_LABEL} Format OK: {summary_ok}

Missing Required Headers: {format_list(missing)}
Duplicate Headers: {format_list(duplicates)}
Removed Headers Present: {format_list(removed)}
""".strip()


def main() -> int:
    try:
        report = build_daily_report()
    except Exception as error:
        print("Daily Report Quality Check")
        print("Status: FAIL")
        print()
        print(f"Build Error: {type(error).__name__}: {error}")
        return 1

    if not isinstance(report, str) or not report.strip():
        print("Daily Report Quality Check")
        print("Status: FAIL")
        print()
        print("Build Error: build_daily_report returned an empty report.")
        return 1

    try:
        result = validate_daily_report_quality(report)
    except Exception as error:
        print("Daily Report Quality Check")
        print("Status: FAIL")
        print()
        print(f"Validation Error: {type(error).__name__}: {error}")
        return 1

    print(format_quality_report(result))

    if result.get("passes"):
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())