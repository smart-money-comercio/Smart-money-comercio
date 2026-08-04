import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_DIR = Path(tempfile.mkdtemp(prefix="smartmoney_intel_guardrail_"))

sys.path.insert(0, str(PROJECT_ROOT))


# Keep this check fast and safe for deploy/preflight.
os.environ.setdefault("DAILY_REPORT_LIVE_QUOTES", "0")

# Redirect runtime memory so the guardrail does not pollute production memory.
os.environ["TICKER_INTELLIGENCE_MEMORY_FILE"] = str(TEMP_DIR / "ticker_intelligence_memory.json")
os.environ["TOP10_EVOLUTION_MEMORY_FILE"] = str(TEMP_DIR / "top10_evolution_memory.json")
os.environ["VOLUME_INTELLIGENCE_MEMORY_FILE"] = str(TEMP_DIR / "volume_intelligence_memory.json")
os.environ["EARNINGS_INTELLIGENCE_MEMORY_FILE"] = str(TEMP_DIR / "earnings_intelligence_memory.json")
os.environ["AI_SUMMARY_MEMORY_FILE"] = str(TEMP_DIR / "ai_summary_memory.json")
os.environ["MARKET_MEMORY_FILE"] = str(TEMP_DIR / "daily_market_memory.json")
os.environ["WATCHLIST_EVOLUTION_MEMORY_FILE"] = str(TEMP_DIR / "watchlist_evolution_memory.json")


from src.utils.intelligence_quality import (  # noqa: E402
    DEFAULT_SYMBOL,
    format_intelligence_quality_report,
    run_intelligence_quality_check,
)


def main() -> int:
    symbol = os.getenv("INTELLIGENCE_GUARDRAIL_SYMBOL", DEFAULT_SYMBOL)

    payload = run_intelligence_quality_check(symbol)
    print(format_intelligence_quality_report(payload))

    return 0 if payload.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())