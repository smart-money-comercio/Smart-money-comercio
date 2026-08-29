import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_DIR = PROJECT_ROOT / "data" / ".tmp_quality"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


alert_memory = TEMP_DIR / "context_status_alert_memory.json"
news_memory = TEMP_DIR / "context_status_news_memory.json"
stockanalysis_cache = TEMP_DIR / "context_status_stockanalysis_cache.json"

os.environ["ALERT_MONITOR_MEMORY_FILE"] = str(alert_memory)
os.environ["NEWS_INTELLIGENCE_MEMORY_FILE"] = str(news_memory)
os.environ["STOCKANALYSIS_CACHE_FILE"] = str(stockanalysis_cache)


def write_fixture_files() -> None:
    alert_memory.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "checked_at": "2026-08-28 00:00:00",
                        "alert_regime": "Selective Opportunity / Risk-Control Watch",
                        "macro_regime": "Rates / Treasury pressure",
                        "risk_regime": "Cautious",
                        "critical_count": 2,
                        "warning_count": 4,
                        "highest_priority_symbols": ["NVDA", "PLTR"],
                        "new_priority_symbols": ["AVGO"],
                        "deteriorating_symbols": ["TSLA"],
                        "validation_symbols": ["AMD"],
                        "risk_symbols": ["TLT"],
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    news_memory.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "checked_at": "2026-08-28 00:00:00",
                        "news_regime": "Rates / Treasury pressure",
                        "risk_regime": "Cautious",
                        "portfolio_impact": "Risk-control watch; require confirmation for high-multiple growth.",
                        "top_themes": ["Rates / Yields", "Treasury / Debt", "AI / Semiconductors"],
                        "top_tickers": ["NVDA", "TLT", "QQQ"],
                        "headline_count": 12,
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    stockanalysis_cache.write_text(
        json.dumps(
            {
                "https://stockanalysis.com/stocks/nvda/forecast/": {
                    "symbol": "NVDA",
                    "metrics": {
                        "analyst_consensus": "Strong Buy",
                        "price_target": "$302.83",
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    write_fixture_files()
    errors: list[str] = []

    try:
        from src.reports.context_status_report import (
            build_contextstatus_report,
            build_summarypreview_report,
        )

        context_report = build_contextstatus_report()
        preview_report = build_summarypreview_report()

    except Exception as error:
        print("Context Status Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    require("Smart Money Context Status" in context_report, "missing context status title", errors)
    require("Providers Loaded:" in context_report, "missing provider count", errors)
    require("Alert Monitor" in context_report, "missing Alert Monitor provider", errors)
    require("News Intelligence" in context_report, "missing News Intelligence provider", errors)
    require("StockAnalysis Cache" in context_report, "missing StockAnalysis provider", errors)
    require("Alert Settings" in context_report, "missing Alert Settings provider", errors)

    require("Smart Money Summary Preview" in preview_report, "missing summary preview title", errors)
    require("Signal:" in preview_report, "summary preview missing Signal", errors)
    require("Implication:" in preview_report, "summary preview missing Implication", errors)
    require("Validation:" in preview_report, "summary preview missing Validation", errors)
    require("The daily read is" in preview_report, "summary preview missing professional wording", errors)

    print("Context Status Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print("Reports Checked: /contextstatus, /summarypreview")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())