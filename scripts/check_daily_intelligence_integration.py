import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


os.environ.setdefault("DAILY_REPORT_LIVE_QUOTES", "0")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []

    try:
        from src.reports.daily_report import build_daily_report
        from src.reports.daily_intelligence_sources import build_daily_intelligence_sources_section

        report = build_daily_report()
        sources_section = build_daily_intelligence_sources_section()

    except Exception as error:
        print("Daily Intelligence Integration Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    required_daily_sections = [
        "Executive Summary",
        "Intelligence Used Today",
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
    ]

    for section in required_daily_sections:
        require(section in report, f"daily report missing {section}", errors)

    required_intelligence_terms = [
        "Smart Money Summary",
        "Trade Plan Snapshot",
        "News Intelligence",
        "Alert Monitor",
        "StockAnalysis",
        "Alert Settings",
        "Watchlist Evolution",
        "Market Memory",
    ]

    for term in required_intelligence_terms:
        require(term in sources_section, f"intelligence source section missing {term}", errors)
        require(term in report, f"daily report missing intelligence source {term}", errors)

    require("Signal:" in report, "Smart Money Summary missing Signal", errors)
    require("Implication:" in report, "Smart Money Summary missing Implication", errors)
    require("Validation:" in report, "Smart Money Summary missing Validation", errors)
    require("/tradeplan" in report, "daily report missing /tradeplan command", errors)
    require("/tradeplans" in report, "daily report missing /tradeplans command", errors)
    require("/contextstatus" in report, "daily report missing /contextstatus command", errors)
    require("/summarypreview" in report, "daily report missing /summarypreview command", errors)
    require("Research only. Not financial advice." in report, "daily report missing disclaimer", errors)

    print("Daily Intelligence Integration Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Daily Report Characters: {len(report)}")
    print(f"Intelligence Sources Characters: {len(sources_section)}")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())