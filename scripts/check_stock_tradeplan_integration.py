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
        from src.reports.stock_intelligence_report import build_stock_intelligence_report
        from src.reports.tradeplan_snapshot_report import build_tradeplan_snapshot_section

        stock_report = build_stock_intelligence_report("NVDA")
        snapshot = build_tradeplan_snapshot_section("NVDA")

    except Exception as error:
        print("Stock Trade Plan Integration Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    require("Trade Plan Snapshot" in snapshot, "standalone snapshot missing title", errors)
    require("Action Bias:" in snapshot, "standalone snapshot missing action bias", errors)
    require("Conviction:" in snapshot, "standalone snapshot missing conviction", errors)
    require("Risk Level:" in snapshot, "standalone snapshot missing risk level", errors)
    require("Entry Style:" in snapshot, "standalone snapshot missing entry style", errors)
    require("Validation Focus:" in snapshot, "standalone snapshot missing validation focus", errors)
    require("Full Plan: /tradeplan NVDA" in snapshot, "standalone snapshot missing full plan command", errors)

    require("Trade Plan Snapshot" in stock_report, "/stock report missing Trade Plan Snapshot", errors)
    require("Action Bias:" in stock_report, "/stock report missing action bias", errors)
    require("Full Plan: /tradeplan NVDA" in stock_report, "/stock report missing full tradeplan command", errors)
    require("Research only. Not financial advice." in stock_report, "/stock report missing disclaimer", errors)

    print("Stock Trade Plan Integration Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Stock Report Characters: {len(stock_report)}")
    print(f"Snapshot Characters: {len(snapshot)}")
    print("Symbol: NVDA")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())