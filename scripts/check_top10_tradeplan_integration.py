import inspect
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


def build_top10_report_safely() -> str:
    import src.reports.top10_report as top10_report
    from src.scoring.scoring_engine import get_stock_scores

    stocks = get_stock_scores()

    candidates = [
        "build_top10_report",
        "build_top10_intelligence_report",
        "build_top10_smart_money_report",
    ]

    for name in candidates:
        builder = getattr(top10_report, name, None)

        if not callable(builder):
            continue

        signature = inspect.signature(builder)
        required_params = [
            param
            for param in signature.parameters.values()
            if param.default is inspect.Parameter.empty
            and param.kind in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        ]

        if not required_params:
            return builder()

        if len(required_params) == 1:
            param_name = required_params[0].name

            if param_name in {"stocks", "scores", "items", "data", "stock_scores"}:
                return builder(stocks)

            return builder(stocks)

        raise RuntimeError(
            f"Unsupported Top 10 builder signature for {name}: {signature}"
        )

    raise RuntimeError(
        "No supported Top 10 report builder found. Expected one of: "
        + ", ".join(candidates)
    )


def main() -> int:
    errors: list[str] = []

    try:
        from src.reports.top10_tradeplan_bridge import build_top10_tradeplan_snapshot_section

        snapshot = build_top10_tradeplan_snapshot_section(limit=5)
        top10_report = build_top10_report_safely()

    except Exception as error:
        print("Top 10 Trade Plan Integration Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    require(isinstance(snapshot, str) and snapshot.strip(), "snapshot returned empty text", errors)
    require(isinstance(top10_report, str) and top10_report.strip(), "top10 report returned empty text", errors)

    require("Trade Plan Snapshot" in snapshot, "standalone snapshot missing title", errors)
    require("Action Bias:" in snapshot, "standalone snapshot missing action bias", errors)
    require("Risk:" in snapshot, "standalone snapshot missing risk", errors)
    require("Full Plan: /tradeplan" in snapshot, "standalone snapshot missing full tradeplan command", errors)

    require("Trade Plan Snapshot" in top10_report, "/top10 report missing Trade Plan Snapshot", errors)
    require("Action Bias:" in top10_report, "/top10 report missing action bias", errors)
    require("Full Plan: /tradeplan" in top10_report, "/top10 report missing full tradeplan command", errors)
    require("Research only. Not financial advice." in top10_report, "/top10 report missing disclaimer", errors)

    print("Top 10 Trade Plan Integration Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print(f"Top 10 Report Characters: {len(top10_report)}")
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