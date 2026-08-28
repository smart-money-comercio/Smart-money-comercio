import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_DIR = PROJECT_ROOT / "data" / ".tmp_quality"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


alert_memory = TEMP_DIR / "daily_ai_alert_memory.json"
news_memory = TEMP_DIR / "daily_ai_news_memory.json"
stockanalysis_cache = TEMP_DIR / "daily_ai_stockanalysis_cache.json"

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
                        "alert_count": 8,
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
                        "mode": "all",
                        "fingerprint": "daily-ai-fixture",
                        "news_regime": "Rates / Treasury pressure",
                        "risk_regime": "Cautious",
                        "portfolio_impact": "Risk-control watch; require confirmation for high-multiple growth.",
                        "top_themes": [
                            "Rates / Yields",
                            "Treasury / Debt",
                            "AI / Semiconductors",
                            "China / Trade",
                        ],
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
        from src.intelligence.daily_ai_summary_context import build_integrated_daily_ai_summary
        from src.intelligence.intelligence_context_registry import collect_intelligence_context

        blocks = collect_intelligence_context()
        summary = build_integrated_daily_ai_summary(
            base_summary="Signal:\nBase fallback.\n\nImplication:\nBase.\n\nValidation:\nBase."
        )

    except Exception as error:
        print("Daily AI Summary Integration Check")
        print("Status: FAIL")
        print("")
        print(f"Import/build failed: {type(error).__name__}: {error}")
        return 1

    block_features = [block.feature for block in blocks]

    require("Alert Monitor" in block_features, "missing Alert Monitor provider", errors)
    require("News Intelligence" in block_features, "missing News Intelligence provider", errors)
    require("StockAnalysis Cache" in block_features, "missing StockAnalysis Cache provider", errors)
    require("Alert Settings" in block_features, "missing Alert Settings provider", errors)

    require("Signal:" in summary, "missing Signal section", errors)
    require("Implication:" in summary, "missing Implication section", errors)
    require("Validation:" in summary, "missing Validation section", errors)
    require("Context Stack:" in summary, "missing Context Stack", errors)
    require("Suggested Commands:" in summary, "missing Suggested Commands", errors)
    require("Alert Monitor" in summary, "summary missing Alert Monitor feature", errors)
    require("News Intelligence" in summary, "summary missing News Intelligence feature", errors)
    require("StockAnalysis Cache" in summary, "summary missing StockAnalysis feature", errors)
    require("NVDA" in summary, "summary missing NVDA", errors)
    require("Rates / Treasury pressure" in summary, "summary missing regime context", errors)
    require("/newsintel" in summary, "summary missing /newsintel command", errors)
    require("/alerts" in summary, "summary missing /alerts command", errors)
    require("/stockdata SYMBOL" in summary, "summary missing /stockdata command", errors)

    print("Daily AI Summary Integration Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print("Providers Loaded:")
    for feature in block_features:
        print(f"- {feature}")

    print("")
    print("Integrated Summary Preview:")
    print(summary)

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())