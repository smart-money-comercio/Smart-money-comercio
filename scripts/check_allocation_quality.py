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
        from src.reports.allocation_report import (
            build_allocation_report,
            build_allocation_snapshot_section,
        )
        from src.reports.daily_report import build_daily_report
        from src.scoring.scoring_engine import get_stock_scores

        scores = get_stock_scores()
        allocation_report = build_allocation_report()
        snapshot = build_allocation_snapshot_section(scores=scores)
        daily_report = build_daily_report()

    except Exception as error:
        print("Allocation Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    require("Portfolio Allocation Snapshot" in allocation_report, "allocation report missing title", errors)
    require("Current Posture" in allocation_report, "allocation report missing Current Posture", errors)
    require("Suggested Tilt" in allocation_report, "allocation report missing Suggested Tilt", errors)
    require("Why This Mix" in allocation_report, "allocation report missing Why This Mix", errors)
    require("Action Plan" in allocation_report, "allocation report missing Action Plan", errors)
    require("Research only. Not financial advice." in allocation_report, "allocation report missing disclaimer", errors)

    require("Portfolio Allocation Snapshot" in snapshot, "snapshot missing title", errors)
    require("Posture:" in snapshot, "snapshot missing posture", errors)
    require("Suggested Tilt:" in snapshot, "snapshot missing suggested tilt", errors)
    require("Action:" in snapshot, "snapshot missing action", errors)

    require("Portfolio Allocation Snapshot" in daily_report, "daily report missing Portfolio Allocation Snapshot", errors)
    require("/allocation" in daily_report, "daily report missing /allocation command", errors)
    require("Research only. Not financial advice." in daily_report, "daily report missing disclaimer", errors)

    print("Allocation Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Allocation Report Characters: {len(allocation_report)}")
    print(f"Snapshot Characters: {len(snapshot)}")
    print(f"Daily Report Characters: {len(daily_report)}")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
