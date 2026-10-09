"""Offline regressions for risk meaning, candidate alignment, and greetings."""

import argparse
import os
import sys
import unittest
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DAILY_REPORT_LIVE_QUOTES", "0")

from src.intelligence.opportunity_ranker import build_top_opportunities_section, risk_adjustment
from src.reports.daily_tradeplan_bridge import build_daily_tradeplan_snapshot_section
from src.reports.report_quality import (
    REQUIRED_HEADERS,
    enforce_daily_report_quality,
    validate_daily_report_quality,
)
from src.reports.tradeplan_language import plain_tradeplan_read
from src.utils.report_consistency import (
    RISK_LABEL_GUIDE,
    report_greeting,
    score_risk_label,
    validate_report_greeting,
    validate_report_risks,
)


STOCKS = [
    {"ticker": "MSFT", "final_score": 87.3, "category": "AI / Cloud", "risk_label": "Controlled"},
    {"ticker": "TSM", "final_score": 85.4, "category": "Semiconductor", "risk_label": "Balanced"},
    {"ticker": "NVDA", "final_score": 80.1, "category": "AI / Chips", "risk_label": "Elevated"},
]


def ranked_stocks() -> list[dict]:
    # A daily price/catalyst ranking can differ from structural-score order.
    ranked = [deepcopy(STOCKS[index]) for index in (2, 0, 1)]
    for index, stock in enumerate(ranked):
        stock.update(structural_score=stock["final_score"], opportunity_score=92.0 - index * 3)
    return ranked


def risk_sections(stocks=None) -> dict[str, str]:
    stocks = deepcopy(STOCKS if stocks is None else stocks)
    return {
        "Top Opportunities": build_top_opportunities_section(stocks),
        "Trade Plan Snapshot": build_daily_tradeplan_snapshot_section(stocks),
    }


def quality_fixture() -> str:
    bodies = risk_sections()
    bodies["Trade Plan Snapshot"] = bodies["Trade Plan Snapshot"].split("\n", 1)[1]
    bodies["Smart Money Summary"] = "Signal: Mixed.\nImplication: Review.\nValidation: Confirm."
    bodies["What Changed Today"] = "• Leadership changed."
    blocks = [
        "📊 Smart Money AI Daily Report\nDaily Brief\nDate: October 06, 2026\n"
        "Generated: 2026-10-06 21:05:42 America/New_York\n\nGood evening."
    ]
    blocks.extend(header + "\n" + bodies.get(header, "Available.") for header in REQUIRED_HEADERS)
    return "\n\n".join(blocks)


class CoreConsistencyChecks(unittest.TestCase):
    def test_score_risk_uses_metadata(self):
        self.assertEqual(score_risk_label(STOCKS[0]), "Controlled")
        self.assertEqual(score_risk_label({"risk_label": "Speculative"}), "Speculative")

    def test_missing_risk_is_unavailable(self):
        for value in (None, "", " ", "N/A", "Unknown"):
            with self.subTest(value=value):
                self.assertEqual(score_risk_label({"risk_label": value}), "Unavailable")

    def test_distinct_risk_measures_are_preserved(self):
        read = plain_tradeplan_read(STOCKS[0])
        self.assertEqual(read["score_risk"], "Controlled")
        self.assertEqual(read["risk"], "Medium-High")
        weak = plain_tradeplan_read({"final_score": 60, "category": "Income", "risk_label": "Elevated"})
        self.assertEqual((weak["score_risk"], weak["risk"]), ("Elevated", "High"))

    def test_ranking_risk_adjustments_are_unchanged(self):
        for label, expected in (("Controlled", 0.75), ("Balanced", 0), ("Elevated", -1.5), ("High Risk", -1.5), ("Speculative", -2)):
            with self.subTest(label=label):
                self.assertEqual(risk_adjustment({"risk_label": label})[0], expected)

    def test_greeting_boundaries(self):
        for hour, expected in ((0, "Hello."), (4, "Hello."), (5, "Good morning."), (11, "Good morning."), (12, "Good afternoon."), (17, "Good afternoon."), (18, "Good evening."), (23, "Good evening.")):
            with self.subTest(hour=hour):
                self.assertEqual(report_greeting(datetime(2026, 10, 6, hour)), expected)

    def test_greeting_uses_report_clock_across_utc_midnight(self):
        instant = datetime(2026, 10, 7, 1, 5, tzinfo=timezone.utc)
        report_time = instant.astimezone(ZoneInfo("America/New_York"))
        self.assertEqual(report_time.day, 6)
        self.assertEqual(report_greeting(report_time), "Good evening.")

    def test_greeting_validation_rejects_wrong_time(self):
        self.assertEqual(validate_report_greeting(quality_fixture()), [])
        self.assertTrue(validate_report_greeting(quality_fixture().replace("Good evening.", "Good morning.")))

    def test_greeting_validation_rejects_missing_or_duplicate_greeting(self):
        for text in (quality_fixture().replace("Good evening.", ""), quality_fixture() + "\nGood evening."):
            self.assertTrue(validate_report_greeting(text))

    def test_greeting_validation_rejects_invalid_timestamp(self):
        self.assertTrue(validate_report_greeting(quality_fixture().replace("2026-10-06 21:05:42", "2026-10-32 21:05:42")))
        self.assertTrue(validate_report_greeting("Good evening."))

    def test_different_setup_risk_is_valid(self):
        self.assertEqual(validate_report_risks(risk_sections()), [])

    def test_conflicting_score_risk_is_rejected(self):
        sections = risk_sections()
        sections["Trade Plan Snapshot"] = sections["Trade Plan Snapshot"].replace("Score Risk: Controlled", "Score Risk: Elevated", 1)
        self.assertTrue(any("disagrees for MSFT" in error for error in validate_report_risks(sections)))

    def test_legacy_unqualified_risk_is_rejected(self):
        sections = risk_sections()
        sections["Top Opportunities"] = sections["Top Opportunities"].replace("Score Risk:", "Risk:")
        self.assertTrue(validate_report_risks(sections))

    def test_missing_setup_risk_is_rejected(self):
        sections = risk_sections()
        sections["Trade Plan Snapshot"] = sections["Trade Plan Snapshot"].replace("Setup Risk:", "Theme:")
        self.assertTrue(validate_report_risks(sections))

    def test_candidate_order_and_missing_candidates_are_rejected(self):
        for stocks in (list(reversed(STOCKS)), STOCKS[:2]):
            with self.subTest(stocks=stocks):
                sections = risk_sections()
                sections["Trade Plan Snapshot"] = build_daily_tradeplan_snapshot_section(stocks)
                self.assertTrue(validate_report_risks(sections))

    def test_duplicate_candidates_and_fields_are_rejected(self):
        sections = risk_sections([STOCKS[0], STOCKS[0]])
        self.assertTrue(validate_report_risks(sections))
        sections = risk_sections()
        sections["Top Opportunities"] += "\nScore Risk: Elevated"
        self.assertTrue(validate_report_risks(sections))

    def test_no_scoring_data_is_handled_without_invented_risk(self):
        self.assertEqual(validate_report_risks(risk_sections([])), [])
        stock = {"ticker": "TEST", "final_score": 82, "category": "Software"}
        sections = risk_sections([stock])
        self.assertIn("Score Risk: Unavailable", sections["Top Opportunities"])
        self.assertEqual(validate_report_risks(sections), [])

    def test_quality_check_survives_section_trimming(self):
        report = enforce_daily_report_quality(quality_fixture())
        result = validate_daily_report_quality(report)
        self.assertTrue(result["passes"], result)
        self.assertIn(RISK_LABEL_GUIDE, report)
        self.assertIn("Setup Risk: Medium-High", report)

    def test_quality_check_flags_risk_and_greeting_errors(self):
        report = quality_fixture().replace("Good evening.", "Good morning.")
        report = report.replace("Score Risk: Controlled", "Score Risk: Elevated", 1)
        result = validate_daily_report_quality(report)
        self.assertFalse(result["passes"])
        self.assertTrue(result["risk_consistency_errors"])
        self.assertTrue(result["greeting_errors"])


class BuilderConsistencyChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.reports import daily_report, scorecard_intelligence_report, tradeplan_report, tradeplan_snapshot_report
        from src.scoring import scoring_engine
        cls.daily = daily_report
        cls.scorecard = scorecard_intelligence_report
        cls.tradeplan = tradeplan_report
        cls.snapshot = tradeplan_snapshot_report
        cls.scoring = scoring_engine

    def test_report_tradeplan_scorecard_and_snapshot_share_risk_meaning(self):
        with patch.object(self.scoring, "get_stock_scores", return_value=deepcopy(STOCKS)), patch.object(self.scorecard, "get_stock_scores", return_value=deepcopy(STOCKS)):
            reports = [
                build_top_opportunities_section([STOCKS[0]]),
                self.tradeplan.build_tradeplan_report("MSFT"),
                self.scorecard.build_scorecard_intelligence_report("MSFT"),
                self.snapshot.build_tradeplan_snapshot_section("MSFT"),
            ]
        for report in reports:
            self.assertIn("Score Risk: Controlled", report)
        for report in reports[1:]:
            self.assertIn("Setup Risk: Medium-High", report)
            self.assertIn(RISK_LABEL_GUIDE, report)

    def test_uncovered_symbols_do_not_receive_balanced_or_medium_risk(self):
        with patch.object(self.scoring, "get_stock_scores", return_value=[]), patch.object(self.scorecard, "get_stock_scores", return_value=[]):
            reports = [self.tradeplan.build_tradeplan_report("MISSING"), self.scorecard.build_scorecard_intelligence_report("MISSING"), self.snapshot.build_tradeplan_snapshot_section("MISSING")]
        for report in reports:
            self.assertIn("Score Risk: Unavailable", report)
            self.assertIn("Setup Risk: Unavailable", report)

    def build_daily_fixture(self, when):
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return when.astimezone(tz) if tz else when.replace(tzinfo=None)

        replacements = {
            "datetime": FixedDatetime,
            "REPORT_TIMEZONE": "America/New_York",
            "MARKET_TIMEZONE": "America/New_York",
            "get_stock_scores": lambda: deepcopy(STOCKS),
            "load_global_context": lambda: dict.fromkeys(("vix", "oil", "tlt", "russell", "nasdaq", "sp500", "gold"), 0),
            "fetch_watchlist_quotes": lambda context: ([stock["ticker"] for stock in STOCKS], {}),
            "record_watchlist_evolution_day": lambda *args, **kwargs: None,
            "rank_daily_opportunities": lambda **kwargs: ranked_stocks(),
            "build_allocation_snapshot_section": lambda **kwargs: "Portfolio Allocation Snapshot\nPosture: Watchlist.",
            "build_what_changed_today": lambda **kwargs: "• Leadership changed.\n• Confirmation matters.\n• New themes emerging.",
            "build_optimized_theme_read": lambda **kwargs: "• Theme history is building.",
            "build_compact_defense_impact": lambda **kwargs: "",
            "build_executive_summary": lambda **kwargs: "• Focus: NVDA; confirm before acting.",
            "build_clean_ai_summary": lambda *args: "Signal: Mixed.\nImplication: Review.\nValidation: Confirm.",
            "build_compact_market_calendar": lambda symbols: "Earnings & Economic Calendar\nEconomic release times: timezone unverified.\nFull calendar: /weeklycalendar",
        }
        with ExitStack() as stack:
            for name, value in replacements.items():
                stack.enter_context(patch.object(self.daily, name, value))
            return self.daily.build_daily_report()

    def test_daily_snapshot_uses_daily_ranking_and_report_clock(self):
        report = self.build_daily_fixture(datetime(2026, 10, 7, 1, 5, tzinfo=timezone.utc))
        result = validate_daily_report_quality(report)
        self.assertTrue(result["passes"], result)
        self.assertIn("Generated: 2026-10-06 21:05:00 America/New_York", report)
        self.assertIn("Good evening.", report)
        self.assertNotIn("Good morning.", report)
        snapshot = report.split("\nTrade Plan Snapshot\n", 1)[1]
        self.assertIn("1. NVDA", snapshot)
        self.assertLess(snapshot.index("NVDA"), snapshot.index("MSFT"))
        self.assertIn("Score Risk: Controlled | Setup Risk: Medium-High", snapshot)

    def test_daily_greeting_changes_at_noon_and_evening(self):
        for hour in (8, 12, 18):
            when = datetime(2026, 10, 6, hour, tzinfo=ZoneInfo("America/New_York"))
            report = self.build_daily_fixture(when)
            self.assertIn(report_greeting(when), report)
            self.assertTrue(validate_daily_report_quality(report)["passes"])

    def test_reportcheck_exposes_conflicting_risk_and_greeting(self):
        from src.commands import reportcheck_commands
        report = quality_fixture().replace("Good evening.", "Good morning.")
        report = report.replace("Score Risk: Controlled", "Score Risk: Elevated", 1)
        with patch.object(reportcheck_commands, "build_daily_report", return_value=report):
            card = reportcheck_commands.build_daily_report_quality_card()
        self.assertIn("Status: CHECK", card)
        self.assertIn("Risk Consistency: CHECK", card)
        self.assertIn("Greeting: CHECK", card)
        self.assertIn("Score Risk disagrees", card)

    def test_deployment_quality_output_exposes_error_details(self):
        from scripts.check_daily_report_quality import format_quality_report
        result = validate_daily_report_quality(quality_fixture().replace("Good evening.", "Good morning."))
        output = format_quality_report(result)
        self.assertIn("Status: FAIL", output)
        self.assertIn("Greeting Errors: Greeting must be", output)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", action="store_true", help="Run dependency-free checks only.")
    args = parser.parse_args(argv)
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    suite.addTests(loader.loadTestsFromTestCase(CoreConsistencyChecks))
    if not args.core:
        suite.addTests(loader.loadTestsFromTestCase(BuilderConsistencyChecks))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(f"Report Consistency Check: {'PASS' if result.wasSuccessful() else 'FAIL'} ({result.testsRun} tests)")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
