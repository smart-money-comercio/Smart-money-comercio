import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_DIR = PROJECT_ROOT / "data" / ".tmp_quality"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


os.environ["NEWS_INTELLIGENCE_MEMORY_FILE"] = str(TEMP_DIR / "alert_news_memory.json")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []

    try:
        from src.intelligence.news_evolution import build_news_record, record_news_scan
        from src.reports.alert_news_bridge import (
            build_alert_news_overlay,
            build_alertstatus_news_summary,
            build_daily_alert_news_digest,
        )
    except Exception as error:
        print("Alert News Bridge Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Import failed: {type(error).__name__}: {error}")
        return 1

    fixture_context = {
        "fingerprint": "alert-news-bridge-fixture-001",
        "items": [{}, {}, {}, {}],
        "themes": {
            "Rates / Yields": 3,
            "Treasury / Debt": 2,
            "Oil / Energy": 1,
            "Geopolitical Risk": 2,
            "AI / Semiconductors": 2,
        },
        "tickers": {
            "NVDA": 2,
            "TLT": 2,
            "USO": 1,
        },
    }

    try:
        record = build_news_record(
            context=fixture_context,
            news_regime="Rates / Treasury pressure",
            risk_regime="Cautious",
            portfolio_impact="Risk-control watch; require confirmation for high-multiple growth.",
            alert_triggers=[
                "Theme alert: rates/yields pressure active.",
                "Ticker alert: NVDA headline cluster active.",
            ],
            mode="all",
            symbol="",
        )

        record_news_scan(record)

        overlay = build_alert_news_overlay(force_refresh=False)
        digest = build_daily_alert_news_digest(force_refresh=False)
        status = build_alertstatus_news_summary()

    except Exception as error:
        print("Alert News Bridge Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Build failed: {type(error).__name__}: {error}")
        return 1

    require("News Intelligence Overlay" in overlay, "overlay missing title", errors)
    require("News Alert Level:" in overlay, "overlay missing alert level", errors)
    require("Rates / Treasury pressure" in overlay, "overlay missing news regime", errors)
    require("News Alert Triggers" in overlay, "overlay missing triggers", errors)
    require("Ticker News Pressure" in overlay, "overlay missing ticker pressure", errors)
    require("NVDA" in overlay, "overlay missing NVDA ticker pressure", errors)

    require("News Overlay" in digest, "daily digest missing title", errors)
    require("Regime:" in digest, "daily digest missing regime", errors)
    require("News Triggers" in digest, "daily digest missing triggers", errors)

    require("News Intelligence:" in status, "alertstatus summary missing news intelligence", errors)
    require("Rates / Treasury pressure" in status, "alertstatus summary missing regime", errors)

    print("Alert News Bridge Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print("Reports Checked: /alerts overlay, /dailyalerts overlay, /alertstatus summary")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("")
    print("Alert/news bridge is healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())