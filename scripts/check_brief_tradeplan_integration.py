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
        from src.reports.daily_tradeplan_bridge import build_daily_tradeplan_snapshot_section
        from src.scoring.scoring_engine import get_stock_scores

        stocks = get_stock_scores()
        snapshot = build_daily_tradeplan_snapshot_section(stocks, limit=3)
        report = build_daily_report()

    except Exception as error:
        print("Brief Trade Plan Integration Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    require("Trade Plan Snapshot" in snapshot, "standalone snapshot missing title", errors)
    require("Top action reads" in snapshot, "standalone snapshot missing purpose text", errors)
    require("/tradeplan" in snapshot, "standalone snapshot missing tradeplan command", errors)
    require("/tradeplans" in snapshot, "standalone snapshot missing tradeplans command", errors)

    require("Smart Money Summary" in report, "daily report missing Smart Money Summary", errors)
    require("Trade Plan Snapshot" in report, "daily report missing Trade Plan Snapshot", errors)
    require("Action Checklist" in report, "daily report missing Action Checklist", errors)
    require("/tradeplan" in report, "daily report missing tradeplan command", errors)
    require("/tradeplans" in report, "daily report missing tradeplans command", errors)
    require("Research only. Not financial advice." in report, "daily report missing disclaimer", errors)

    print("Brief Trade Plan Integration Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Daily Report Characters: {len(report)}")
    print(f"Snapshot Characters: {len(snapshot)}")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())