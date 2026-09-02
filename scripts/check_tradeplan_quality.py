import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Keep quality checks deterministic and fast.
os.environ.setdefault("DAILY_REPORT_LIVE_QUOTES", "0")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []

    try:
        from src.reports.tradeplan_report import build_tradeplan_report

        report = build_tradeplan_report("NVDA")

    except Exception as error:
        print("Trade Plan Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    require("Smart Money Trade Plan: NVDA" in report, "missing trade plan title", errors)
    require("Current Read" in report, "missing Current Read section", errors)
    require("Score Breakdown" in report, "missing Score Breakdown section", errors)
    require("Why It Matters" in report, "missing Why It Matters section", errors)
    require("Entry Plan" in report, "missing Entry Plan section", errors)
    require("Confirmation Checklist" in report, "missing Confirmation Checklist section", errors)
    require("Risk Plan" in report, "missing Risk Plan section", errors)
    require("Smart Money Verdict" in report, "missing Smart Money Verdict section", errors)
    require("/scorecard NVDA" in report, "missing scorecard validation command", errors)
    require("/risk NVDA" in report, "missing risk validation command", errors)
    require("/volume NVDA" in report, "missing volume validation command", errors)
    require("/stockdata NVDA" in report, "missing stockdata validation command", errors)
    require("Research only. Not financial advice." in report, "missing disclaimer", errors)

    print("Trade Plan Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Characters: {len(report)}")
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