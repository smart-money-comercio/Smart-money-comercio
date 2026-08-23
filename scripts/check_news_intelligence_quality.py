import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_DIR = PROJECT_ROOT / "data" / ".tmp_quality"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


os.environ["NEWS_INTELLIGENCE_MEMORY_FILE"] = str(TEMP_DIR / "news_intelligence_memory.json")
os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"] = str(TEMP_DIR / "news_live_source_cache.json")


def fake_context(force_refresh: bool = False) -> dict:
    items = [
        {
            "title": "Bond yields rise again after Treasury buyback effort",
            "description": "Long-term Treasury yields moved higher despite buyback support.",
            "source": "Fixture Market",
            "category": "market",
            "published": "fixture",
            "themes": ["Rates / Yields", "Treasury / Debt"],
            "tickers": ["TLT"],
            "importance": 8,
        },
        {
            "title": "Oil climbs as Iran geopolitical pressure rises",
            "description": "Energy markets price higher geopolitical risk.",
            "source": "Fixture Energy",
            "category": "energy",
            "published": "fixture",
            "themes": ["Oil / Energy", "Geopolitical Risk"],
            "tickers": ["USO"],
            "importance": 7,
        },
        {
            "title": "Nvidia and AI chip stocks remain active but rate-sensitive",
            "description": "Semiconductor leadership continues while yields pressure valuations.",
            "source": "Fixture Tech",
            "category": "technology",
            "published": "fixture",
            "themes": ["AI / Semiconductors", "Mega-Cap Tech", "Rates / Yields"],
            "tickers": ["NVDA", "QQQ"],
            "importance": 7,
        },
        {
            "title": "China trade and tariff tensions return to market focus",
            "description": "Investors watch China and trade-policy risk.",
            "source": "Fixture Trade",
            "category": "macro",
            "published": "fixture",
            "themes": ["China / Trade", "Geopolitical Risk"],
            "tickers": [],
            "importance": 6,
        },
    ]

    return {
        "source": "Fixture Live Market News",
        "fetched_at": "2026-08-22 00:00:00",
        "force_refresh": force_refresh,
        "items": items,
        "top_items": items,
        "themes": {
            "Rates / Yields": 2,
            "Treasury / Debt": 1,
            "Oil / Energy": 1,
            "Geopolitical Risk": 2,
            "AI / Semiconductors": 1,
            "Mega-Cap Tech": 1,
            "China / Trade": 1,
        },
        "tickers": {
            "TLT": 1,
            "USO": 1,
            "NVDA": 1,
            "QQQ": 1,
        },
        "fingerprint": "fixture-news-001",
        "source_results": [
            {
                "name": "Fixture Market",
                "category": "market",
                "status": "ok",
                "cache_hit": False,
                "item_count": len(items),
                "error": "",
            }
        ],
        "errors": [],
    }


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []

    try:
        import src.reports.news_intelligence_report as report
    except Exception as error:
        print("News Intelligence Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Import failed: {type(error).__name__}: {error}")
        return 1

    report.fetch_news_live_context = fake_context

    try:
        headlines = report.build_headlines_report(force_refresh=True)
        newsintel = report.build_news_intelligence_report(force_refresh=True)
        macronews = report.build_macro_news_report(force_refresh=True)
        tickernews = report.build_ticker_news_report("NVDA", force_refresh=True)
        memory = report.build_newsmemory_report()
    except Exception as error:
        print("News Intelligence Quality Check")
        print("Status: FAIL")
        print("")
        print(f"Report build failed: {type(error).__name__}: {error}")
        return 1

    require("Market Headlines" in headlines, "headlines report missing title", errors)
    require("Theme Snapshot" in headlines, "headlines report missing theme snapshot", errors)
    require("Market News Intelligence" in newsintel, "newsintel report missing title", errors)
    require("News Regime:" in newsintel, "newsintel report missing news regime", errors)
    require("What Changed" in newsintel, "newsintel report missing What Changed", errors)
    require("Evolving Read" in newsintel, "newsintel report missing Evolving Read", errors)
    require("Alert Triggers" in newsintel, "newsintel report missing alert triggers", errors)
    require("Macro News Intelligence" in macronews, "macronews report missing title", errors)
    require("NVDA Ticker News Intelligence" in tickernews, "tickernews report missing NVDA title", errors)
    require("News Memory" in memory, "newsmemory report missing title", errors)

    print("News Intelligence Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")
    print("Reports Checked: /headlines, /newsintel, /macronews, /tickernews, /newsmemory")

    if errors:
        print("")
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("")
    print("News intelligence source, memory, and reports are healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())