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
        from src.reports.tradeplans_report import build_tradeplans_report

        report = build_tradeplans_report(5)

    except Exception as error:
        print("Trade Plans Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    require("Smart Money Top Trade Plans" in report, "missing report title", errors)
    require("Purpose" in report, "missing Purpose section", errors)
    require("Top Ideas Reviewed:" in report, "missing top ideas count", errors)
    require("Action Bias:" in report, "missing action bias", errors)
    require("Entry Style:" in report, "missing entry style", errors)
    require("Validation Focus:" in report, "missing validation focus", errors)
    require("Full Plan: /tradeplan" in report, "missing full tradeplan command", errors)
    require("How To Use This" in report, "missing usage section", errors)
    require("/scorecard" in report, "missing scorecard validation command", errors)
    require("/risk" in report, "missing risk validation command", errors)
    require("/volume" in report, "missing volume validation command", errors)
    require("/tickernews" in report, "missing tickernews validation command", errors)
    require("/stockdata" in report, "missing stockdata validation command", errors)
    require("Research only. Not financial advice." in report, "missing disclaimer", errors)

    print("Trade Plans Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Characters: {len(report)}")
    print("Limit: 5")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())