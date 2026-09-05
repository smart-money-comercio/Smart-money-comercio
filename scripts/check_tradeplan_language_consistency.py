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
        from src.reports.daily_tradeplan_bridge import build_daily_tradeplan_snapshot_section
        from src.reports.top10_tradeplan_bridge import build_top10_tradeplan_snapshot_section
        from src.reports.tradeplans_report import build_tradeplans_report
        from src.scoring.scoring_engine import get_stock_scores

        scores = get_stock_scores()

        daily_snapshot = build_daily_tradeplan_snapshot_section(scores, limit=3)
        top10_snapshot = build_top10_tradeplan_snapshot_section(limit=5)
        tradeplans_report = build_tradeplans_report(5)

    except Exception as error:
        print("Trade Plan Language Consistency Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    for name, text in {
        "daily snapshot": daily_snapshot,
        "top10 snapshot": top10_snapshot,
        "tradeplans report": tradeplans_report,
    }.items():
        require("Trade Plan Snapshot" in text or "Smart Money Top Trade Plans" in text, f"{name} missing trade-plan title", errors)
        require("/tradeplan" in text, f"{name} missing /tradeplan command", errors)

    require("Top action reads" in daily_snapshot, "daily snapshot missing user-friendly action wording", errors)

    require("Action Bias:" in top10_snapshot, "top10 snapshot missing Action Bias", errors)
    require("Entry Style:" in top10_snapshot, "top10 snapshot missing Entry Style", errors)
    require("Validation Focus:" in top10_snapshot, "top10 snapshot missing Validation Focus", errors)
    require("Full Plan: /tradeplan" in top10_snapshot, "top10 snapshot missing full plan command", errors)

    require("Executive Read" in tradeplans_report, "tradeplans report missing Executive Read", errors)
    require("Purpose" in tradeplans_report, "tradeplans report missing Purpose", errors)
    require("Trade Plan Snapshots" in tradeplans_report, "tradeplans report missing Trade Plan Snapshots", errors)
    require("How To Use This" in tradeplans_report, "tradeplans report missing How To Use This", errors)
    require("Upgrade conviction only when" in tradeplans_report, "tradeplans report missing conviction guidance", errors)
    require("Research only. Not financial advice." in tradeplans_report, "tradeplans report missing disclaimer", errors)

    print("Trade Plan Language Consistency Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Daily Snapshot Characters: {len(daily_snapshot)}")
    print(f"Top10 Snapshot Characters: {len(top10_snapshot)}")
    print(f"Tradeplans Report Characters: {len(tradeplans_report)}")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())