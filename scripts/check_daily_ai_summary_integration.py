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
            base_summary="Signal: Base fallback.\nImplication: Base.\nValidation: Base."
        )

    except Exception as error:
        print("Daily Smart Money Summary Integration Check")
        print("Status: FAIL")
        print("")
        print(f"Import/build failed: {type(error).__name__}: {error}")
        return 1

    block_features = [block.feature for block in blocks]

    # Provider checks: these verify the evolving registry is loaded.
    require("Alert Monitor" in block_features, "missing Alert Monitor provider", errors)
    require("News Intelligence" in block_features, "missing News Intelligence provider", errors)
    require("StockAnalysis Cache" in block_features, "missing StockAnalysis Cache provider", errors)
    require("Alert Settings" in block_features, "missing Alert Settings provider", errors)

    # Format checks: daily quality requires the compact three-line format.
    require("Signal:" in summary, "missing Signal section", errors)
    require("Implication:" in summary, "missing Implication section", errors)
    require("Validation:" in summary, "missing Validation section", errors)

    # Readability checks: the summary should sound professional, not diagnostic.
    require("The daily read is" in summary, "summary missing professional signal language", errors)
    require(
        "Focus first on" in summary or "Stay selective" in summary,
        "summary missing professional implication language",
        errors,
    )
    require(
        "Before acting, confirm" in summary,
        "summary missing professional validation language",
        errors,
    )

    # Regression checks: avoid technical/internal wording in the user-facing summary.
    require("Integrated features:" not in summary, "summary still contains technical integrated-features wording", errors)
    require("Integrated context includes" not in summary, "summary still contains technical integrated-context wording", errors)
    require("Context Stack:" not in summary, "summary still contains Context Stack wording", errors)
    require("Suggested Commands:" not in summary, "summary still contains Suggested Commands wording", errors)

    # Signal-source checks: make sure the important intelligence still appears in plain language.
    require("Rates / Treasury pressure" in summary, "summary missing market regime context", errors)
    require("NVDA" in summary, "summary missing priority symbol context", errors)
    require("/stockdata" in summary, "summary missing StockAnalysis validation command", errors)

    print("Daily Smart Money Summary Integration Check")
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