import json
import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


os.environ.setdefault("DAILY_REPORT_LIVE_QUOTES", "0")


from src.intelligence.opportunity_ranker import (
    build_fastest_rising_section,
    build_top_opportunities_section,
    rank_daily_opportunities,
    today_key,
)


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []

    scores = [
        {
            "ticker": "MSFT",
            "final_score": 87.0,
            "risk_label": "Controlled",
            "action_label": "Review First",
            "volume_adjustment": 0,
            "signal_overlap": 4,
        },
        {
            "ticker": "NVDA",
            "final_score": 84.0,
            "risk_label": "Balanced",
            "action_label": "Watch Closely",
            "volume_adjustment": 1,
            "signal_overlap": 4,
        },
        {
            "ticker": "AVAV",
            "final_score": 80.0,
            "risk_label": "Balanced",
            "action_label": "Monitor",
            "volume_adjustment": 2,
            "signal_overlap": 3,
        },
    ]

    movers = [
        {
            "symbol": "MSFT",
            "change_percent": 0.2,
            "price": 500,
        },
        {
            "symbol": "NVDA",
            "change_percent": 2.2,
            "price": 200,
        },
        {
            "symbol": "AVAV",
            "change_percent": 2.5,
            "price": 300,
        },
    ]

    context = {
        "tickers": {
            "AVAV": 4,
            "NVDA": 2,
            "MSFT": 0,
        }
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        memory_path = Path(temp_dir) / "opportunity_memory.json"

        #
        # Seed a prior-report snapshot.
        # This makes the test deterministic and correctly tests
        # daily change instead of expecting same-day first-run history.
        #
        prior_memory = {
            "current_date": "2026-09-16-prior",
            "current": {
                "MSFT": {
                    "structural_score": 87.0,
                    "opportunity_score": 87.5,
                },
                "NVDA": {
                    "structural_score": 83.0,
                    "opportunity_score": 84.5,
                },
                "AVAV": {
                    "structural_score": 76.0,
                    "opportunity_score": 77.0,
                },
            },
            "previous_date": "",
            "previous": {},
        }

        memory_path.write_text(
            json.dumps(prior_memory, indent=2),
            encoding="utf-8",
        )

        ranked = rank_daily_opportunities(
            scores=scores,
            movers=movers,
            context=context,
            record_memory=False,
            memory_path=memory_path,
        )

        require(
            len(ranked) == 3,
            "ranking did not return all candidates",
            errors,
        )

        require(
            all("opportunity_score" in item for item in ranked),
            "opportunity_score missing",
            errors,
        )

        require(
            all("structural_score" in item for item in ranked),
            "structural_score missing",
            errors,
        )

        require(
            all("opportunity_delta" in item for item in ranked),
            "opportunity_delta missing",
            errors,
        )

        top_report = build_top_opportunities_section(
            ranked,
            limit=3,
        )

        rising = build_fastest_rising_section(
            ranked,
            limit=4,
        )

        avav = next(
            (
                item
                for item in ranked
                if str(item.get("ticker") or "").upper() == "AVAV"
            ),
            None,
        )

        require(
            "Opportunity" in top_report,
            "Top Opportunities missing opportunity score",
            errors,
        )

        require(
            "Structural" in top_report,
            "Top Opportunities missing structural score",
            errors,
        )

        require(
            "Why now:" in top_report,
            "Top Opportunities missing Why now",
            errors,
        )

        require(
            avav is not None,
            "AVAV missing from ranked opportunities",
            errors,
        )

        if avav is not None:
            require(
                float(avav.get("opportunity_delta") or 0) > 0,
                "AVAV opportunity delta did not improve",
                errors,
            )

        require(
            "AVAV" in rising,
            "Fastest-Rising section did not detect AVAV improvement",
            errors,
        )

        #
        # Also prove memory can be written successfully.
        #
        saved = rank_daily_opportunities(
            scores=scores,
            movers=movers,
            context=context,
            record_memory=True,
            memory_path=memory_path,
        )

        require(
            memory_path.exists(),
            "opportunity memory file was not written",
            errors,
        )

        require(
            len(saved) == 3,
            "record-memory ranking returned wrong candidate count",
            errors,
        )

        saved_memory = json.loads(
            memory_path.read_text(encoding="utf-8")
        )

        require(
            saved_memory.get("current_date") == today_key(),
            "saved opportunity memory has incorrect current date",
            errors,
        )

        require(
            "AVAV" in saved_memory.get("current", {}),
            "saved opportunity memory missing AVAV",
            errors,
        )

    daily_text = Path(
        "src/reports/daily_report.py"
    ).read_text(encoding="utf-8")

    require(
        "rank_daily_opportunities" in daily_text,
        "daily report missing dynamic opportunity ranker",
        errors,
    )

    require(
        "Fastest-Rising Opportunities" in daily_text,
        "daily report missing Fastest-Rising Opportunities",
        errors,
    )

    require(
        "build_top_opportunities_section" in daily_text,
        "daily report missing dynamic Top Opportunities builder",
        errors,
    )

    print("Opportunity Ranking Quality Check")
    print(f"Status: {'FAIL' if errors else 'PASS'}")
    print("")

    if errors:
        print("Errors:")

        for error in errors:
            print(f"- {error}")

        return 1

    print("Dynamic ranking, prior-report comparison, score memory, and report integration passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
