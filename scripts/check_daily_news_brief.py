"""Offline behavioral checks for company follow-up and the spoken news edition."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack, closing, contextmanager, redirect_stdout
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from scripts.check_calendar_evidence import earnings, fed, fed_row
from scripts.check_report_consistency import BuilderConsistencyChecks
from src.intelligence import calendar_context as calendar, calendar_sources as publishers
from src.intelligence import company_catalyst_context as companies, special_alert_store as store, special_alert_universe as universe
from src.intelligence.special_alert_sources import OFFICIAL_DOMAINS
from src.reports import daily_report
from src.reports.daily_news_brief import TITLE, HEADERS, MAX_NEWS_CHARS, build_daily_news_brief, validate_news_brief
from src.reports.report_quality import split_report_sections, validate_daily_report_quality

NOW = datetime(2026, 10, 25, 17, tzinfo=timezone.utc)
DAYS = [date(2026, 10, day) for day in (26, 27, 28, 29, 30)]


def announcement(symbol="MSFT", official=False, **overrides):
    evidence = {"title": "Example company introduces a new research platform", "source": "example.com",
                "url": "https://example.com/announcement", "official": official,
                "published": (NOW - timedelta(hours=1)).isoformat()}
    if official:
        domain = OFFICIAL_DOMAINS.get(symbol, ("microsoft.com",))[0]
        evidence.update(source=domain, url="https://www." + domain + "/announcement", publisher_symbol=symbol)
    return {"key": symbol + "-event", "kind": "company", "symbols": [symbol], "level": 1,
            "expires": NOW.timestamp() + 3600, "evidence": evidence, "agent_review": "Interpretation: Verify the announcement.", **overrides}


class IsolatedChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="news brief with spaces ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ranking = self.root / "rankings.json"
        self.db = self.root / "events.sqlite3"
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"CALENDAR_STATE_FILE": str(self.root / "calendar.json"),
            "CALENDAR_SOURCE_CACHE_FILE": str(self.root / "publishers.json"), "SPECIAL_ALERT_STATE_FILE": str(self.db),
            "NEWS_EDITOR_STATE_FILE": str(self.root / "editor.sqlite3"), "NEWS_LIVE_SOURCE_CACHE_FILE": str(self.root / "news.json"),
            "REPORT_TIMEZONE": "America/New_York", "SPECIAL_ALERT_SYMBOLS": "TSLA,NVDA,MSFT,PLTR", "SPECIAL_ALERT_TOP_COUNT": "10"}))
        self.stack.enter_context(patch.object(companies, "utc_now", return_value=NOW))
        self.stack.enter_context(patch.object(calendar, "utc_now", return_value=NOW))
        self.stack.enter_context(patch.object(universe, "RANKING_PATH", self.ranking))
        values = {"MSFT": (90, 87), "NVDA": (89, 85), "TSM": (88, 86), "NOC": (80, 79), "PLTR": (70, 69)}
        self.ranking.write_text(json.dumps({"current_date": "2026-10-23", "current": {
            symbol: {"opportunity_score": opportunity, "structural_score": structural} for symbol, (opportunity, structural) in values.items()}}))
        self.seed_calendar()
        store.record_snapshot([], {}, NOW.timestamp())

    def seed_calendar(self, raw=None, when=NOW):
        if raw is None:
            raw = {(day, kind): [] for day in DAYS for kind in ("economic", "earnings")}
            raw[(DAYS[0], "earnings")] = [earnings("PLTR")]
            raw[(DAYS[2], "earnings")] = [earnings("MSFT"), earnings("TSLA")]
            raw[(DAYS[3], "earnings")] = [earnings("NVDA")]
        schedules = publishers.parse_fed_calendar(fed(fed_row(), fed_row(title="FOMC Press Conference", time="2:30 p.m.")))
        snapshot = calendar.normalize_snapshot(DAYS, raw, schedules, {"Fed": "available"}, when)
        calendar.save_snapshot(snapshot)
        return snapshot

    def event(self, value=None, observed=NOW):
        value = announcement() if value is None else value
        store.record_snapshot([value], {}, observed.timestamp())
        return value

    def research(self, now=NOW, replacements=None):
        report = BuilderConsistencyChecks.build_daily_fixture(SimpleNamespace(daily=daily_report), now)
        bodies = {"Executive Summary": "- Main theme: Oil / inflation risk.\n- Market moves: S&P -0.52%, Nasdaq -0.21%, Russell -0.29%, VIX +2.21%, Oil +4.32%, TLT -0.49%.",
                  "Market Snapshot": "Market Session: Closed — weekend. Price moves reflect the last completed regular session.\nQuote session: 2026-10-23\nTone: Defensive / mildly bearish\nBreadth: 7 up / 11 down / 18 quoted"}
        bodies.update(replacements or {})
        report = "\n\n".join((header + "\n" + bodies[header]) if header in bodies else "\n".join(lines)
                                 for header, lines in split_report_sections(report))
        self.assertTrue(validate_daily_report_quality(report)["passes"])
        return report


@contextmanager
def offline_news_fixture():
    """Exercise the real news renderer with isolated, explicitly synthetic inputs."""
    case = IsolatedChecks("research")
    case.setUp()
    try:
        research = case.research()
        with patch.object(daily_report, "build_research_report", return_value=research):
            yield case
    finally:
        case.doCleanups()


class CompanyChecks(IsolatedChecks):
    def test_core_companies_and_other_top_opportunities_are_all_covered(self):
        brief = companies.build_company_catalyst_brief()
        symbols = [row["symbol"] for row in brief["rows"]]
        for symbol in ("TSLA", "MSFT", "NVDA", "PLTR", "TSM", "NOC"):
            self.assertIn(symbol, symbols)
        self.assertEqual(symbols[:3], ["MSFT", "NVDA", "TSM"])
        self.assertEqual(brief["ranking_date"], "2026-10-23")

    def test_stale_or_future_rankings_keep_core_coverage_without_fake_scores(self):
        for day in ("2026-10-01", "2026-10-26"):
            value = json.loads(self.ranking.read_text()); value["current_date"] = day; self.ranking.write_text(json.dumps(value))
            brief = companies.build_company_catalyst_brief()
            self.assertEqual({row["symbol"] for row in brief["rows"]}, {"TSLA", "MSFT", "NVDA", "PLTR"})
            self.assertTrue(all(row["score"] is None for row in brief["rows"]))

    def test_invalid_numeric_rankings_cannot_become_high_priority(self):
        value = json.loads(self.ranking.read_text()); value["current"]["BAD"] = {"opportunity_score": float("nan"), "structural_score": 99}
        self.ranking.write_text(json.dumps(value))
        self.assertNotIn("BAD", [row["symbol"] for row in companies.build_company_catalyst_brief()["rows"]])

    def test_report_ranking_order_is_preserved_without_mutating_or_rescoring(self):
        ranked = [{"ticker": "NVDA", "opportunity_score": 91, "structural_score": 85}, {"ticker": "MSFT", "opportunity_score": 90, "structural_score": 87}]
        before = deepcopy(ranked); memory = self.ranking.read_bytes()
        brief = companies.build_company_catalyst_brief(ranked=ranked)
        self.assertEqual([row["symbol"] for row in brief["rows"]][:2], ["NVDA", "MSFT"])
        self.assertEqual(ranked, before); self.assertEqual(self.ranking.read_bytes(), memory)

    def test_no_calendar_is_distinct_from_no_matching_earnings(self):
        calendar.state_path().unlink()
        row = next(row for row in companies.build_company_catalyst_brief()["rows"] if row["symbol"] == "MSFT")
        self.assertEqual(row["calendar"]["status"], "unavailable")
        self.assertIn("unavailable", row["calendar"]["text"])

    def test_missing_earnings_feed_is_incomplete_coverage(self):
        self.seed_calendar({})
        row = companies.build_company_catalyst_brief()["rows"][0]
        self.assertEqual(row["calendar"]["status"], "incomplete")
        self.assertIn("coverage incomplete", row["calendar"]["text"])

    def test_conflicting_estimated_dates_are_not_collapsed_to_a_confirmed_date(self):
        self.seed_calendar({(DAYS[1], "earnings"): [earnings()], (DAYS[2], "earnings"): [earnings()]})
        row = companies.build_company_catalyst_brief()["rows"][0]
        self.assertEqual(row["calendar"]["status"], "conflict")
        self.assertEqual(row["review"]["focus"], "Resolve earnings date")

    def test_earnings_estimates_keep_the_company_confirmation_requirement(self):
        text = companies.build_company_catalyst_report("MSFT")
        self.assertIn("2026-10-28", text)
        self.assertIn("Nasdaq estimate, company confirmation pending", text)
        self.assertIn("Price and volume confirmation still need a fresh check", text)

    def test_event_belongs_only_to_the_named_company(self):
        self.event()
        rows = {row["symbol"]: row for row in companies.build_company_catalyst_brief()["rows"]}
        self.assertTrue(rows["MSFT"]["events"])
        self.assertFalse(rows["NVDA"]["events"])

    def test_official_and_headline_only_reports_keep_separate_labels(self):
        for official, label in ((False, "headline report; unconfirmed by company"), (True, "company announcement")):
            self.event(announcement(official=official))
            self.assertIn(label, companies.build_company_catalyst_report("MSFT"))

    def test_expired_or_future_published_news_does_not_supply_active_company_evidence(self):
        for value in (announcement(expires=NOW.timestamp() - 1), announcement(evidence={**announcement()["evidence"], "published": (NOW + timedelta(hours=1)).isoformat()})):
            self.event(value)
            row = companies.build_company_catalyst_brief()["rows"][0]
            self.assertFalse(row["events"])

    def test_unknown_origin_link_and_truthy_string_do_not_promote_confirmation(self):
        value = announcement(); value["evidence"]["url"] = "javascript:alert(1)"; self.event(value)
        self.assertFalse(companies.build_company_catalyst_brief()["rows"][0]["events"])
        value = announcement(); value["evidence"]["official"] = "true"; self.event(value)
        self.assertFalse(companies.build_company_catalyst_brief()["rows"][0]["events"][0]["official"])

    def test_missing_event_database_is_not_created_by_a_research_read(self):
        path = self.root / "absent" / "events.sqlite3"
        with patch.dict(os.environ, {"SPECIAL_ALERT_STATE_FILE": str(path)}):
            text = companies.build_company_catalyst_report()
        self.assertFalse(path.parent.exists())
        self.assertIn("Special-alert evidence unavailable", text)

    def test_cache_read_does_not_change_receipts_database_or_ranking_memory(self):
        self.event()
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (self.db, self.ranking, calendar.state_path())}
        companies.build_company_catalyst_report(); companies.company_catalyst_context_provider()
        for path, digest in before.items(): self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_malformed_event_does_not_hide_other_usable_events(self):
        self.event()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", ("bad", "company", "{", NOW.timestamp(), NOW.timestamp() + 60, 1))
        self.assertTrue(companies.build_company_catalyst_brief()["rows"][0]["events"])

    def test_company_context_adds_no_risk_votes_or_score_changes(self):
        block = companies.company_catalyst_context_provider()
        self.assertFalse(block.metadata["score_changes"])
        self.assertEqual(block.risks, []); self.assertEqual(block.themes, []); self.assertEqual(block.symbols, [])

    def test_symbol_outside_coverage_is_not_silently_scored(self):
        text = companies.build_company_catalyst_report("UNKNOWN")
        self.assertIn("outside the current brief coverage", text)
        self.assertNotIn("Opportunity 0", text)

    def test_agent_calendar_refresh_covers_five_business_days(self):
        snapshot = calendar.read_snapshot()
        with patch("src.reports.live_market_calendar._business_days", return_value=DAYS) as days, patch.object(calendar, "get_snapshot", return_value=snapshot):
            calendar.refresh_calendar_review()
        days.assert_called_once_with(5)

    def test_compact_calendar_collects_five_days_but_displays_only_two(self):
        from src.reports import live_market_calendar
        snapshot = deepcopy(calendar.read_snapshot())
        snapshot["earnings"].append({**snapshot["earnings"][0], "symbol": "NOC", "source_date": "2026-10-27", "display_date": "2026-10-27"})
        with patch.object(live_market_calendar, "_business_days", return_value=DAYS) as days, patch.object(calendar, "get_snapshot", return_value=snapshot) as fetch:
            text = live_market_calendar.build_compact_market_calendar(["MSFT"])
        days.assert_called_once_with(5); fetch.assert_called_once_with(DAYS)
        self.assertIn("Monday, Oct 26", text); self.assertIn("Tuesday, Oct 27", text)
        self.assertNotIn("Wednesday, Oct 28", text)

    def test_market_event_is_context_for_everyone_without_becoming_company_news(self):
        evidence = {symbol: {"name": name, "change": change, "asof": (NOW - timedelta(minutes=5)).isoformat()}
                    for symbol, name, change in (("^GSPC", "S&P 500", -2), ("^IXIC", "Nasdaq Composite", -3))}
        self.event({"key": "market", "kind": "market", "symbols": [], "level": 1, "expires": NOW.timestamp() + 600, "evidence": evidence})
        brief = companies.build_company_catalyst_brief()
        self.assertTrue(brief["market_events"])
        self.assertTrue(all(not row["events"] for row in brief["rows"]))
        text = build_daily_news_brief(self.research(), brief)
        self.assertIn("active market-alert record", text)
        self.assertIn("does not establish the cause", text)

    def test_read_only_reader_does_not_create_tables_in_a_missing_schema(self):
        self.db.unlink()
        with closing(sqlite3.connect(self.db)): pass
        text = companies.build_company_catalyst_report()
        self.assertIn("Special-alert evidence unavailable", text)
        with closing(sqlite3.connect(self.db)) as db: self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0], 0)

    def test_agent_company_review_keeps_source_gaps_visible(self):
        calendar.state_path().unlink()
        self.assertIn("Calendar evidence unavailable", companies.daily_company_catalyst_review())


def assert_fixture_connections_closed(test, case):
    """Hold references so garbage collection cannot conceal an open DB handle."""
    handles = []
    original_connect = sqlite3.connect
    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        handles.append(connection)
        return connection
    try:
        result = unittest.TestResult()
        with patch.object(sqlite3, "connect", side_effect=connect):
            case.run(result)
        test.assertTrue(result.wasSuccessful(), str(result.errors + result.failures))
        test.assertTrue(handles, "Fixture did not exercise SQLite")
        for connection in handles:
            with test.assertRaises(sqlite3.ProgrammingError, msg="SQLite fixture connection was not explicitly closed"):
                connection.execute("SELECT 1")
    finally:
        for connection in handles:
            connection.close()


class SQLiteCleanupChecks(unittest.TestCase):
    def test_database_fixtures_close_handles_without_relying_on_gc(self):
        for name in ("test_malformed_event_does_not_hide_other_usable_events",
                     "test_read_only_reader_does_not_create_tables_in_a_missing_schema"):
            with self.subTest(fixture=name):
                assert_fixture_connections_closed(self, CompanyChecks(name))
        class UnclosedTransaction(unittest.TestCase):
            def runTest(self):
                # A transaction context commits/rolls back but does not close.
                with sqlite3.connect(":memory:"):
                    pass
        with self.assertRaises(AssertionError):
            assert_fixture_connections_closed(self, UnclosedTransaction())


class NewsChecks(IsolatedChecks):
    def confirmed_news_without_prices(self):
        brief = companies.build_company_catalyst_brief()
        for row in brief["rows"][:3]:
            value = announcement(row["symbol"], official=True)["evidence"]
            row["events"] = [{**value, "symbols": [row["symbol"]], "source_checked_at": NOW.isoformat(),
                              "title": row["symbol"] + " reports quarterly financial results with revenue growth and an updated full-year earnings outlook"}]
        return brief

    def test_research_edition_passes_the_deployment_intelligence_check(self):
        from scripts import check_daily_intelligence_integration as check
        report = self.research()
        output = io.StringIO()
        with patch.object(daily_report, "build_research_report", return_value=report), redirect_stdout(output):
            result = check.main()
        self.assertEqual(result, 0, output.getvalue())
        self.assertIn("/summarypreview", report)
        self.assertIn("/catalysts", report)

    def test_news_brand_and_spoken_paragraphs_replace_the_long_tables(self):
        text = build_daily_news_brief(self.research())
        self.assertTrue(text.startswith(TITLE))
        self.assertLessEqual(len(text), MAX_NEWS_CHARS)
        self.assertNotIn("Opportunity 87", text)
        self.assertNotIn("Suggested Tilt:", text)
        self.assertFalse(any(line.startswith(("•", "[ ]")) for line in text.splitlines()))
        for header in HEADERS: self.assertIn(header, text.splitlines())

    def test_market_numbers_keep_their_direction_and_regular_session_date(self):
        text = build_daily_news_brief(self.research())
        self.assertIn("the S&P 500 fell 0.52 percent", text)
        self.assertIn("the Nasdaq Composite fell 0.21 percent", text)
        self.assertIn("oil rose 4.32 percent", text)
        self.assertIn("Market data: completed regular session 2026-10-23", text)
        self.assertIn("Friday, October 23", text)
        self.assertIn("18-symbol research watchlist", text)

    def test_intraday_language_does_not_call_the_open_session_finished(self):
        research = self.research(replacements={"Market Snapshot": "Market Session: Open — live session.\nQuote session: 2026-10-23\nBreadth: 8 up / 10 down / 18 quoted"})
        text = build_daily_news_brief(research)
        self.assertIn("During the Friday, October 23 session", text)
        self.assertIn("8 are higher", text)
        self.assertNotIn("finished higher", text)

    def test_undated_price_data_cannot_be_presented_as_a_current_market_move(self):
        research = self.research(replacements={"Market Snapshot": "Market Session: Closed.\nBreadth: 7 up / 11 down / 18 quoted"})
        text = build_daily_news_brief(research, self.confirmed_news_without_prices())
        self.assertIn("Market data: unavailable", text)
        self.assertNotIn("0.52 percent", text)
        self.assertNotIn("18-symbol", text)

    def test_earnings_are_estimates_and_fed_times_have_publisher_evidence(self):
        text = build_daily_news_brief(self.research())
        self.assertNotIn("estimated earnings calendar", text)
        self.assertNotIn("Company confirmation is pending", text)
        self.assertIn("Nasdaq estimate", companies.build_company_catalyst_report("MSFT"))
        self.assertIn("Federal Reserve's interest-rate decision", text)
        self.assertIn("02:00 PM EDT", text)

    def test_headline_only_development_is_not_rewritten_as_company_confirmation(self):
        self.event()
        text = build_daily_news_brief(self.research())
        self.assertNotIn("Example company introduces", text)
        self.assertNotIn("headline-only", text)
        self.assertNotIn("Microsoft's company announcement", text)

    def test_official_development_keeps_the_execution_follow_up(self):
        self.event(announcement(official=True))
        text = build_daily_news_brief(self.research())
        self.assertIn("Microsoft's company announcement", text)
        self.assertIn("Commercial timing and impact still require review", text)

    def test_cached_publisher_time_is_never_described_as_a_fresh_verification(self):
        brief = companies.build_company_catalyst_brief()
        for row in brief["macro"]: row["time_status"] = "cached"
        text = build_daily_news_brief(self.research(), brief)
        self.assertIn("previously checked, cached schedule", text)
        self.assertIn("live coverage is limited", text)

    def test_unknown_or_unverified_event_clocks_are_not_invented_for_narration(self):
        brief = companies.build_company_catalyst_brief(); brief["macro"] = []
        text = build_daily_news_brief(self.research(), brief)
        self.assertNotIn("09:45", text)
        self.assertNotIn("02:00 PM", text)
        brief["macro"] = [{"eventName": "FOMC Statement", "event_at": "2026-10-28T18:00:00+00:00", "time_status": "unverified"}]
        self.assertNotIn("02:00 PM", build_daily_news_brief(self.research(), brief))

    def test_quality_understands_the_news_profile_and_rejects_unqualified_dates(self):
        text = build_daily_news_brief(self.research())
        result = validate_daily_report_quality(text)
        self.assertEqual(result["format"], "news"); self.assertTrue(result["passes"])
        self.assertFalse(validate_news_brief(text + "\n\nNasdaq's estimated earnings calendar lists Microsoft. Company confirmation is pending.")["passes"])

    def test_one_estimated_earnings_date_cannot_supply_another_dates_qualification(self):
        text = build_daily_news_brief(self.research())
        self.assertNotIn("Company confirmation is pending.", text)
        self.assertFalse(validate_news_brief(text + "\n\nA headline-only report, unconfirmed by the company.")["passes"])

    def test_quality_rejects_wrong_greeting_missing_date_session_and_excess_length(self):
        text = build_daily_news_brief(self.research())
        for bad in (text.replace("Good afternoon.", "Good morning."), text.replace("Date:", "Edition:"), text.replace("Generated:", "Made:"),
                    text.replace("Market data:", "Quotes:"), text + "X" * MAX_NEWS_CHARS):
            self.assertFalse(validate_news_brief(bad)["passes"])

    def test_incomplete_underlying_research_is_not_polished_into_a_passing_news_brief(self):
        with self.assertRaisesRegex(ValueError, "underlying research report"):
            build_daily_news_brief(self.research().replace("Executive Summary", "Missing"))
        with self.assertRaises(ValueError): build_daily_news_brief(build_daily_news_brief(self.research()))

    def test_default_daily_builder_returns_news_and_keeps_detailed_builder_separate(self):
        research = self.research()
        with patch.object(daily_report, "build_research_report", return_value=research) as build:
            text = daily_report.build_daily_report()
        build.assert_called_once()
        self.assertTrue(text.startswith(TITLE))
        self.assertIn("Trade Plan Snapshot", research)
        self.assertIn("Full calendar", research)

    def test_large_company_titles_are_bounded_without_cutting_qualifications_mid_sentence(self):
        brief = companies.build_company_catalyst_brief()
        event = {"url": "https://www.microsoft.com/one", "source": "microsoft.com", "official": True,
                 "published": (NOW - timedelta(minutes=5)).isoformat(),
                 "title": "Microsoft introduces a cloud platform " * 5}
        for index, row in enumerate(brief["rows"][:2]):
            domain = OFFICIAL_DOMAINS[row["symbol"]][0]
            row["events"] = [{**event, "url": "https://www." + domain + "/one" + str(index),
                              "publisher_symbol": row["symbol"], "source_checked_at": NOW.isoformat(),
                              "title": row["symbol"] + " introduces a cloud platform " * 5}]
        text = build_daily_news_brief(self.research(), brief)
        self.assertLessEqual(len(text), MAX_NEWS_CHARS)
        self.assertTrue(text.endswith("Research only. Not financial advice."))
        self.assertIn("company announcement", text)
        self.assertNotIn("headline-only", text)

    def test_oil_theme_has_plain_language_outlook_without_a_claimed_market_cause(self):
        text = build_daily_news_brief(self.research())
        self.assertIn("Oil jumped 4.32 percent", text)
        self.assertIn("higher energy costs could put on margins", text)
        self.assertNotIn("caused", text.lower())
        self.assertNotIn("Here is your Smart Money Daily News Brief", text)

    def test_selloff_outlook_uses_dated_market_evidence(self):
        text = build_daily_news_brief(self.research(replacements={"Executive Summary": "- Main theme: Growth pressure.\n- Market moves: S&P -1.6%, Nasdaq -2.6%, Russell -0.4%, VIX +12%, Oil +0.4%, TLT +1%."}))
        self.assertIn("The Nasdaq's 2.60 percent decline", text)
        self.assertIn("growth-stock risk", text)
        self.assertNotIn("energy costs can put pressure", text)

    def test_index_gains_and_watchlist_declines_are_explained_with_scope(self):
        text = build_daily_news_brief(self.research(replacements={"Executive Summary": "- Main theme: Macro / earnings setup.\n- Market moves: S&P +0.5%, Nasdaq +0.4%, Russell +0.1%."}))
        self.assertIn("U.S. indexes advanced, but most of our research watchlist declined", text)
        self.assertIn("Weak participation", text)

    def test_undated_data_cannot_drive_the_theme_or_interpretation(self):
        text = build_daily_news_brief(self.research(replacements={"Market Snapshot": "Market Session: Closed.\nBreadth: 7 up / 11 down / 18 quoted"}), self.confirmed_news_without_prices())
        self.assertIn("Market coverage is incomplete", text)
        self.assertIn("Verified market returns are unavailable", text)
        self.assertNotIn("energy costs can put pressure", text)
        self.assertNotIn("Oil and inflation are on", text)

    def test_research_outlook_does_not_convert_a_bond_fund_into_verified_yields(self):
        text = build_daily_news_brief(self.research())
        self.assertIn("TLT is a bond-price proxy; Treasury yields are not verified", text)
        self.assertNotIn("Treasury yields rose", text)
        self.assertNotIn("Treasury yields fell", text)

    def test_quality_command_labels_the_news_profile_and_its_actual_limit(self):
        from src.commands import reportcheck_commands
        text = build_daily_news_brief(self.research())
        with patch.object(reportcheck_commands, "build_daily_report", return_value=text): card = reportcheck_commands.build_daily_report_quality_card()
        self.assertIn("Smart Money Daily News Brief Quality", card)
        self.assertIn("/ 3800", card)
        self.assertIn("Status: PASS", card)
        self.assertIn("60-second Minimum: PASS", card)
        self.assertIn("spoken words", card)

    def timed_fixture(self, words):
        prefix = f"{TITLE}\nDate: October 25, 2026\nGenerated: 2026-10-25 13:00:00 America/New_York\nMarket data: unavailable\n\nGood afternoon.\n\n"
        return prefix + "\n\n".join(header + ("\n" + " ".join(["spoken"] * (words - 2)) if index == 0 else "")
                                       for index, header in enumerate(HEADERS)) + "\nResearch only. Not financial advice."

    def test_179_spoken_words_fails_and_180_passes_the_one_minute_boundary(self):
        short, ready = validate_news_brief(self.timed_fixture(179)), validate_news_brief(self.timed_fixture(180))
        self.assertFalse(short["passes"])
        self.assertEqual(short["spoken_words"], 179)
        self.assertLess(short["estimated_narration_seconds"], 60)
        self.assertTrue(ready["passes"])
        self.assertEqual(ready["estimated_narration_seconds"], 60)

    def test_display_metadata_and_research_footer_cannot_supply_the_spoken_minimum(self):
        text = self.timed_fixture(160).replace("Good afternoon.", "Display metadata: " + "date " * 150 + "\n\nGood afternoon.")
        text += "\n" + "footer " * 150 + "/storylog https://example.com/research"
        result = validate_news_brief(text)
        self.assertEqual(result["spoken_words"], 160)
        self.assertTrue(result["narration_errors"])

    def test_spoken_copy_excludes_section_titles_commands_urls_and_notes(self):
        from src.reports.daily_news_brief import spoken_text
        text = "Title\nDate: 2026-10-25\n\nGood afternoon.\nMarket Update\nStocks changed. /report https://example.com\nResearch Notes\nLinks and disclaimer."
        self.assertEqual(spoken_text(text).split(), ["Good", "afternoon.", "Stocks", "changed."])

    def test_quiet_edition_uses_agent_analysis_rather_than_padding_for_duration(self):
        text = build_daily_news_brief(self.research())
        result = validate_news_brief(text)
        self.assertGreaterEqual(result["spoken_words"], 180)
        self.assertGreaterEqual(result["estimated_narration_seconds"], 60)
        self.assertIn("Nvidia leads our research ranking", text)
        self.assertIn("setup risk medium to high", text)
        self.assertNotIn("headline-only", text)

    def test_confirmed_calendar_context_is_used_before_other_duration_expansion(self):
        from src.reports import daily_news_brief as news
        brief = companies.build_company_catalyst_brief()
        brief["macro"] = [{"eventName": title, "event_at": f"2026-10-{day}T12:30:00+00:00", "time_status": "verified"}
                          for day, title in ((28, "Fed Interest Rate Decision"), (29, "Initial Jobless Claims"), (30, "CPI"))]
        baseline = news.narration_metrics(build_daily_news_brief(self.research(), brief))["spoken_words"]
        with patch.object(news, "MIN_NARRATION_WORDS", baseline + 10):
            text = build_daily_news_brief(self.research(), brief)
            self.assertGreaterEqual(news.narration_metrics(text)["spoken_words"], baseline + 10)
        self.assertIn("consumer inflation", text)

    def test_insufficient_evidence_is_withheld_instead_of_padding_or_adding_unconfirmed_news(self):
        from src.intelligence import news_editor_store
        brief = companies.build_company_catalyst_brief(); brief["macro"] = []
        report = self.research(replacements={"Market Snapshot": "Market Session: Closed.\nBreadth: 7 up / 11 down / 18 quoted"})
        with self.assertRaisesRegex(ValueError, "Narration minimum not met"):
            build_daily_news_brief(report, brief)
        self.assertFalse(news_editor_store.state_path().exists())

    def test_report_preflight_uses_real_duration_validation_with_isolated_inputs(self):
        from scripts import check_daily_report_quality as check
        before = self.ranking.read_bytes(); output = io.StringIO()
        with redirect_stdout(output):
            result = check.main(offline_fixture=True)
        self.assertEqual(result, 0, output.getvalue())
        self.assertIn("isolated offline fixture", output.getvalue())
        self.assertIn("spoken words", output.getvalue())
        self.assertEqual(before, self.ranking.read_bytes())

    def test_normal_quality_check_does_not_replace_short_live_copy_with_a_fixture(self):
        from scripts import check_daily_report_quality as check
        output = io.StringIO()
        with patch.object(check, "build_daily_report", return_value=self.timed_fixture(179)), redirect_stdout(output):
            self.assertEqual(check.main(), 1)
        self.assertIn("Narration minimum not met", output.getvalue())
        self.assertNotIn("isolated offline fixture", output.getvalue())

    def test_agent_preflight_keeps_live_status_unchanged(self):
        from scripts import check_daily_agent_quality as check
        from src.jobs import daily_agent_job
        live = self.root / "live-agent.json"; live.write_text('{"keep":"live status"}')
        output = io.StringIO()
        with patch.object(daily_agent_job, "STATUS_PATH", live), redirect_stdout(output):
            result = check.main(offline_fixture=True)
        self.assertEqual(result, 0, output.getvalue())
        self.assertEqual(live.read_text(), '{"keep":"live status"}')


class AnalystBriefChecks(IsolatedChecks):
    def investor_research(self, price="+1.5%", delta="up +4.0"):
        opportunities = f"""1. TSM - Opportunity 88.2/100 | Structural 86.2/100 | {delta}
   Price: {price} | News signals: 0
   Why now: structural support; earnings estimate 2026-10-29; company confirmation pending
   Score Risk: Balanced | Action: Watch Closely

2. MSFT - Opportunity 88.0/100 | Structural 87.3/100 | up +1.0
   Price: +0.7% | News signals: 0
   Score Risk: Controlled | Action: Review First

3. NVDA - Opportunity 85.3/100 | Structural 85.3/100 | unchanged
   Price: -0.6% | News signals: 0
   Score Risk: Balanced | Action: Watch Closely"""
        plans = "\n".join(f"{index}. {symbol} — Medium-High conviction, {score}/100 | Score Risk: {risk} | Setup Risk: Medium-High | Action: Constructive — favored on confirmed strength Entry: Use pullbacks or confirmed breakouts. Full plan: /tradeplan {symbol}"
                          for index, (symbol, score, risk) in enumerate((("TSM", 86.2, "Balanced"), ("MSFT", 87.3, "Controlled"), ("NVDA", 85.3, "Balanced")), 1))
        return self.research(replacements={"Top Opportunities": opportunities, "Trade Plan Snapshot": plans,
            "What Changed Today": "• Leadership: TSM moved ahead of MSFT.\n• New mover focus: AMD.\n• Tone stayed defensive / mildly bearish."})

    def test_ranking_change_and_price_support_reach_the_spoken_edition(self):
        text = build_daily_news_brief(self.investor_research())
        self.assertIn("Taiwan Semiconductor moved ahead of Microsoft", text)
        self.assertIn("at 88.2 out of 100", text)
        self.assertIn("rose 4 points versus the prior report", text)
        self.assertIn("Taiwan Semiconductor rose 1.5 percent", text)
        self.assertIn("adds price support", text)
        self.assertNotIn("earnings estimate 2026-10-29", text)

    def test_strong_rank_with_falling_price_gets_a_confirmation_caveat(self):
        text = build_daily_news_brief(self.investor_research(price="-4.5%", delta="down -2.0"))
        self.assertIn("fell 2 points versus the prior report", text)
        self.assertIn("Taiwan Semiconductor fell 4.5 percent", text)
        self.assertIn("still needs stronger price confirmation", text)
        self.assertNotIn("adds price support", text)

    def test_undated_company_prices_cannot_inflate_the_analysis(self):
        from src.intelligence.daily_brief_analysis import analyze_report
        report = self.investor_research().replace("Quote session: 2026-10-23", "Quote session unavailable")
        review = analyze_report(report)
        text = "\n".join(row["text"] for row in review["insights"])
        self.assertNotIn("Taiwan Semiconductor rose 1.5", text)
        self.assertEqual(review["evidence"]["moves"], {})
        self.assertIn("rose 4 points versus the prior report", text)

    def test_tradeplan_risk_and_action_belong_to_the_actual_leading_company(self):
        text = build_daily_news_brief(self.research())
        self.assertIn("Nvidia's setup risk medium to high, with elevated score risk", text)
        self.assertIn("Our trade plan for Nvidia calls for waiting", text)
        self.assertNotIn("Our trade plan for Nvidia favors confirmed strength", text)

    def test_controlled_score_risk_does_not_become_a_low_risk_setup(self):
        from src.intelligence.daily_brief_analysis import analyze_report
        report = self.investor_research().replace("Score Risk: Balanced", "Score Risk: Controlled")
        review = analyze_report(report)
        risk = next(row["text"] for row in review["insights"] if row["id"] == "setup_risk")
        self.assertIn("medium to high, with controlled score risk", risk)
        self.assertNotIn("low risk", risk)

    def test_structural_support_is_distinct_from_opportunity_priority(self):
        text = build_daily_news_brief(self.research())
        self.assertIn("ranking at 92 out of 100", text)
        self.assertIn("structural support score is 80.1", text)
        self.assertIn("rather than expected returns", text)

    def test_analyst_inputs_are_saved_with_the_matching_edition_and_status(self):
        from src.intelligence import news_editor, news_editor_store
        report = self.investor_research(); before = self.ranking.read_bytes()
        text = build_daily_news_brief(report)
        record = news_editor_store.read_editions(report=text)[0]
        review = record["analyst_review"]
        self.assertEqual(review["research_sha256"], hashlib.sha256(report.encode()).hexdigest())
        self.assertEqual(review["evidence"]["companies"][0]["symbol"], "TSM")
        self.assertGreaterEqual(len(review["insights"]), 4)
        self.assertTrue(all(text.count(row["text"]) == 1 for row in review["insights"]))
        self.assertFalse(review["score_changes"])
        self.assertEqual(before, self.ranking.read_bytes())
        self.assertIn("analyst insights grounded", news_editor.review_daily_edition(text))
        self.assertIn("Analyst inputs:", news_editor.build_editor_status())

    def test_invented_analyst_figures_or_altered_wording_are_rejected(self):
        from src.intelligence.daily_brief_analysis import analyze_report, retained_review, validate_review
        report = self.investor_research(); text = build_daily_news_brief(report)
        review = retained_review(analyze_report(report), text)
        altered = deepcopy(review); altered["evidence"]["companies"][0]["opportunity"] = 99.9
        with self.assertRaisesRegex(ValueError, "does not match"):
            validate_review(altered, report, text)
        with self.assertRaisesRegex(ValueError, "changed or lost"):
            validate_review(review, report, text.replace("rose 4 points", "rose 20 points"))
        omitted = deepcopy(review); omitted["insights"].pop()
        with self.assertRaisesRegex(ValueError, "omitted"):
            validate_review(omitted, report, text)

    def test_raw_headline_or_unconfirmed_date_cannot_enter_through_research_prose(self):
        report = self.investor_research().replace("Why now: structural support;", "Why now: Bitcoin will double tomorrow;")
        text = build_daily_news_brief(report)
        self.assertNotIn("Bitcoin", text)
        self.assertNotIn("2026-10-29", text)

    def test_broken_leader_row_does_not_promote_the_second_company_to_first(self):
        from src.intelligence.daily_brief_analysis import report_evidence
        report = self.investor_research().replace("Opportunity 88.2/100", "Opportunity NaN/100")
        self.assertEqual(report_evidence(report)["companies"], [])

    def test_inconsistent_change_sign_and_conflicting_tradeplan_are_not_narrated(self):
        from src.intelligence.daily_brief_analysis import report_evidence
        self.assertEqual(report_evidence(self.investor_research(delta="up -4.0"))["companies"], [])
        report = self.investor_research().replace("86.2/100 | Score Risk: Balanced", "86.2/100 | Score Risk: Elevated")
        row = report_evidence(report)["companies"][0]
        self.assertIsNone(row["setup_risk"]); self.assertIsNone(row["action"])

    def test_confirmed_calendar_has_an_investor_question_without_a_forecast(self):
        text = build_daily_news_brief(self.investor_research())
        self.assertIn("Why it matters: Watch the Fed's guidance", text)
        self.assertNotIn("will cut rates", text)
        self.assertNotIn("Treasury yields rose", text)

    def test_earnings_and_contract_news_have_different_investor_followups(self):
        from src.intelligence import news_editor
        from scripts.check_news_editor import candidate
        for title, expected in (("Microsoft reports quarterly financial results", "revenue, margins and cash flow"),
                                ("Microsoft signs a strategic cloud partnership", "funded commitments and revenue timing")):
            story = candidate(title=title)
            paragraph = news_editor.render_story(story, calendar.publishers.NY, {"MSFT": "Microsoft"})
            self.assertIn(expected, paragraph)
            self.assertIn(title, paragraph)

    def test_quiet_news_day_still_has_substantive_analysis_and_a_route_to_depth(self):
        from src.reports.daily_news_brief import narration_metrics
        text = build_daily_news_brief(self.investor_research())
        self.assertGreaterEqual(narration_metrics(text)["spoken_words"], 180)
        self.assertLessEqual(len(text), 3800)
        self.assertIn("trade-plan conditions and risk checks", text)
        self.assertIn("/fullreport · /tradeplans", text)
        self.assertNotIn("premium membership", text.lower())


class RankingRationaleChecks(IsolatedChecks):
    def ranked(self, changes=None, movers=None, counts=None, previous=None):
        from src.intelligence import opportunity_ranker as ranker
        scores = [dict(ticker=symbol, final_score=base, risk_label=risk, smart_score=core, defense_score=theme,
                       congress_score=congress, insider_score=insiders, volume_adjustment=0)
                  for symbol, base, risk, core, theme, congress, insiders in (
                      ("TSM", 86.2, "Balanced", 88, 83, 72, 50),
                      ("MSFT", 87.3, "Controlled", 89, 84, 78, 51.5),
                      ("NVDA", 85.3, "Balanced", 93, 68, 70, 50))]
        for row in scores:
            row.update((changes or {}).get(row["ticker"], {}))
        before = deepcopy(scores)
        memory = self.root / "rank-basis.json"
        if previous:
            memory.write_text(json.dumps({"current_date": "2026-10-22", "current": previous}))
        original = memory.read_bytes() if memory.exists() else None
        moves = movers or {"TSM": 1.5, "MSFT": 0.7, "NVDA": -0.6}
        ranked = ranker.rank_daily_opportunities(scores, [{"symbol": symbol, "change_percent": value} for symbol, value in moves.items()],
            {"tickers": counts or {"TSM": 0, "MSFT": 0, "NVDA": 0}}, record_memory=False, memory_path=memory)
        self.assertEqual(scores, before)
        self.assertEqual(memory.read_bytes() if memory.exists() else None, original)
        return ranked

    def research_with_basis(self, ranked=None):
        from src.intelligence.opportunity_ranker import build_top_opportunities_section
        report = AnalystBriefChecks.investor_research(self)
        ranked = self.ranked() if ranked is None else ranked
        body = build_top_opportunities_section(ranked)
        plans = "\n".join(f"{index}. {row['ticker']} — Medium-High conviction, {row['structural_score']}/100 | Score Risk: {row['risk_label']} | Setup Risk: Medium-High | Action: Constructive — favored on confirmed strength Entry: Use pullbacks or confirmed breakouts. Full plan: /tradeplan {row['ticker']}"
                          for index, row in enumerate(ranked[:3], 1))
        return "\n\n".join((header + "\n" + body) if header == "Top Opportunities" else (header + "\n" + plans) if header == "Trade Plan Snapshot" else "\n".join(lines)
                            for header, lines in split_report_sections(report))

    def test_captured_components_explain_the_real_ranking_without_rescoring(self):
        ranked = self.ranked()
        self.assertEqual([row["ticker"] for row in ranked][:2], ["TSM", "MSFT"])
        self.assertEqual([row["opportunity_score"] for row in ranked][:2], [88.2, 88.0])
        self.assertEqual(ranked[0]["opportunity_components"], {"price": 2, "news": 0, "volume": 0, "risk": 0, "revision": 0})
        self.assertEqual(ranked[1]["opportunity_components"]["risk"], 0.75)

    def test_narrow_lead_explains_price_support_and_the_runner_ups_stronger_base(self):
        text = build_daily_news_brief(self.research_with_basis())
        self.assertIn("displayed advantage over Microsoft is 0.2 points", text)
        self.assertIn("stronger price reading", text)
        self.assertIn("Microsoft retains stronger structural support, 87.3 versus 86.2", text)
        self.assertIn("a small change in the inputs could reverse it", text)

    def test_model_support_does_not_become_a_claim_about_fresh_trades_or_results(self):
        text = build_daily_news_brief(self.research_with_basis())
        self.assertIn("draws support from core research and the theme component", text)
        self.assertIn("The insider component does not add strong confirmation", text)
        self.assertIn("Company disclosures remain the test", text)
        for claim in ("insiders are buying", "Congress bought", "earnings grew", "revenue increased"):
            self.assertNotIn(claim, text)

    def test_missing_adjustments_do_not_get_invented_from_the_score_gap(self):
        from src.intelligence.daily_brief_analysis import analyze_report
        review = analyze_report(AnalystBriefChecks.investor_research(self))
        self.assertIsNone(review["evidence"]["companies"][0]["basis"])
        self.assertNotIn("ranking_reason", {row["id"] for row in review["insights"]})

    def test_inconsistent_and_duplicate_adjustment_lines_are_withheld(self):
        from src.intelligence.daily_brief_analysis import report_evidence
        report = self.research_with_basis()
        bad = report.replace("Model adjustments: price +2.00", "Model adjustments: price +5.00", 1)
        self.assertIsNone(report_evidence(bad)["companies"][0]["basis"])
        line = next(line for line in report.splitlines() if "Model adjustments:" in line)
        self.assertIsNone(report_evidence(report.replace(line, line + "\n" + line, 1))["companies"][0]["basis"])

    def test_nonfinite_or_out_of_range_model_inputs_are_not_narrated(self):
        from src.intelligence.daily_brief_analysis import report_evidence
        from src.intelligence.opportunity_ranker import ranking_basis_lines
        report = self.research_with_basis()
        for bad in ("core nan", "core 101.0", "core inf"):
            modified = report.replace("core 88.0", bad, 1)
            self.assertIsNone(report_evidence(modified)["companies"][0]["inputs"])
        item = self.ranked()[0]; item["opportunity_components"]["volume"] = float("nan")
        self.assertNotIn("Model adjustments:", ranking_basis_lines(item))

    def test_no_quote_session_means_no_dated_price_ranking_explanation(self):
        from src.intelligence.daily_brief_analysis import analyze_report
        review = analyze_report(self.research_with_basis().replace("Quote session: 2026-10-23", "Quote session unavailable"))
        self.assertIsNone(review["evidence"]["companies"][0]["basis"])
        self.assertNotIn("ranking_reason", {row["id"] for row in review["insights"]})

    def test_displayed_ties_do_not_get_a_fabricated_winning_driver(self):
        ranked = self.ranked(changes={"TSM": {"final_score": 86}})
        text = build_daily_news_brief(self.research_with_basis(ranked))
        self.assertIn("tied on the displayed opportunity score", text)
        self.assertNotIn("largest positive difference", text)

    def test_capped_scores_do_not_get_an_uncapped_causal_explanation(self):
        ranked = self.ranked(changes={"TSM": {"final_score": 94, "volume_adjustment": 10}, "MSFT": {"final_score": 90}})
        text = build_daily_news_brief(self.research_with_basis(ranked))
        self.assertIn("Score caps affect this comparison", text)
        self.assertNotIn("largest positive difference", text)

    def test_volume_and_news_inputs_are_explained_as_distinct_model_signals(self):
        for changes, counts, expected in (({"TSM": {"volume_adjustment": 3}}, None, "volume input"),
                                          (None, {"TSM": 4, "MSFT": 0, "NVDA": 0}, "Headline activity supplies")):
            ranked = self.ranked(changes=changes, movers={"TSM": 0.2, "MSFT": 0.7, "NVDA": -0.6}, counts=counts)
            text = build_daily_news_brief(self.research_with_basis(ranked))
            self.assertIn(expected, text)
            if counts:
                self.assertIn("does not verify a company announcement", text)

    def test_structural_revisions_are_not_mistaken_for_a_new_company_announcement(self):
        ranked = self.ranked(movers={"TSM": 0.2, "MSFT": 0.7, "NVDA": -0.6},
            previous={"TSM": {"structural_score": 80, "opportunity_score": 80}, "MSFT": {"structural_score": 87.3, "opportunity_score": 88}})
        text = build_daily_news_brief(self.research_with_basis(ranked))
        self.assertIn("Changes in structural model scores", text)
        self.assertNotIn("earnings grew", text)

    def test_both_score_inputs_and_ranking_explanation_are_auditable(self):
        from src.intelligence import news_editor_store
        report = self.research_with_basis(); text = build_daily_news_brief(report)
        review = news_editor_store.read_editions(report=text)[0]["analyst_review"]
        self.assertEqual(len(review["insights"]), 8)
        self.assertEqual(review["evidence"]["companies"][0]["basis"]["price"], 2)
        self.assertEqual(review["evidence"]["companies"][0]["inputs"]["core"], 88)
        self.assertEqual(review["research_sha256"], hashlib.sha256(report.encode()).hexdigest())

    def test_complete_verified_story_can_displace_optional_model_detail(self):
        from src.intelligence import news_editor, news_editor_store
        from src.reports import daily_news_brief as news
        from scripts.check_news_editor import candidate
        report = self.research_with_basis()
        with patch.object(news_editor, "cache_candidates", return_value=([], [])):
            baseline = build_daily_news_brief(report)
        story = candidate(title="Microsoft announces an expanded strategic cloud partnership for enterprise customers")
        budget = min(3800, len(baseline) + 100)
        with patch.object(news_editor, "cache_candidates", return_value=([story], [])), patch.object(news, "MAX_NEWS_CHARS", budget):
            text = build_daily_news_brief(report)
        record = news_editor_store.read_editions(report=text)[0]
        self.assertIn(story["title"], text)
        self.assertIn("Why it leads:", text)
        self.assertTrue(any(row["decision"] == "selected" for row in record["candidates"]))
        self.assertLess(len(record["analyst_review"]["insights"]), 8)
        self.assertTrue(news.validate_news_brief(text)["passes"])


class CommandChecks(unittest.IsolatedAsyncioTestCase):
    async def test_catalysts_command_normalizes_symbol_and_replies_without_a_channel_send(self):
        from src.commands import company_catalyst_commands as commands
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(commands, "build_company_catalyst_report", return_value="Company facts") as build:
            await commands.catalysts_command(update, SimpleNamespace(args=["$msft"]))
        build.assert_called_once_with("MSFT")
        self.assertIn("Company facts", update.message.reply_text.await_args.kwargs["text"])

    async def test_invalid_command_symbol_does_not_run_research(self):
        from src.commands import company_catalyst_commands as commands
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(commands, "build_company_catalyst_report") as build:
            await commands.catalysts_command(update, SimpleNamespace(args=["../bad"]))
        build.assert_not_called()
        self.assertIn("Use /catalysts", update.message.reply_text.await_args.args[0])

    async def test_fullreport_uses_the_detailed_research_builder(self):
        from src.commands import company_catalyst_commands as commands
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(commands, "build_research_report", return_value="Executive Summary\nDetailed evidence") as build:
            await commands.fullreport_command(update, SimpleNamespace(args=[]))
        build.assert_called_once()
        self.assertIn("Executive Summary", update.message.reply_text.await_args.kwargs["text"])

    async def test_long_company_coverage_reaches_the_user_in_complete_chunks(self):
        from src.commands import company_catalyst_commands as commands
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        report = "Company Catalyst Brief\n" + "Company evidence and source qualification.\n" * 160 + "END_OF_COVERAGE"
        with patch.object(commands, "build_company_catalyst_report", return_value=report):
            await commands.catalysts_command(update, SimpleNamespace(args=[]))
        chunks = [call.kwargs["text"] for call in update.message.reply_text.await_args_list]
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 4096 for chunk in chunks))
        self.assertIn("END_OF_COVERAGE", chunks[-1])

    async def test_newsbrief_alias_and_fullreport_have_distinct_registered_builders(self):
        with patch("openai.OpenAI"):
            from src.commands import register_commands, basic_commands, company_catalyst_commands
        app = SimpleNamespace(add_handler=Mock()); register_commands.register_commands(app)
        callbacks = {name: call.args[0].callback for call in app.add_handler.call_args_list for name in call.args[0].commands}
        self.assertIs(callbacks["newsbrief"], basic_commands.report)
        self.assertIs(callbacks["report"], basic_commands.report)
        self.assertIs(callbacks["fullreport"], company_catalyst_commands.fullreport_command)
        self.assertIs(callbacks["catalysts"], company_catalyst_commands.catalysts_command)


class WatchdogChecks(unittest.TestCase):
    def payload(self, characters, report_format=None):
        from src.reports import watchdog_report as watchdog
        status = {"success": True, "last_run": "2026-10-26T12:15:00Z", "report_characters": characters,
                  "steps": [{"name": "Quality Review", "status": "pass"}]}
        if report_format is not None:
            status["report_format"] = report_format
        with patch.object(watchdog, "read_json_file", return_value=status), patch.object(watchdog, "read_recent_log_lines", return_value=[]), patch.object(watchdog, "now_ny", return_value=datetime(2026, 10, 26, 14, tzinfo=watchdog.NY_TZ)):
            return watchdog.build_watchdog_payload()

    def test_concise_news_edition_is_healthy_below_the_legacy_length_floor(self):
        self.assertEqual(self.payload(1400, "news")["watchdog_status"], "PASS")

    def test_short_legacy_detailed_report_still_warns(self):
        self.assertEqual(self.payload(1400)["watchdog_status"], "WARNING")

    def test_empty_or_incomplete_news_still_warns(self):
        self.assertEqual(self.payload(120, "news")["watchdog_status"], "WARNING")


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--windows-socketpair", action="store_true"); args = parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:
            stack.enter_context(patch.object(socket, "socketpair", portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    passed = result.wasSuccessful() and not traffic["blocked"]
    print(f"Daily News Brief Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    if traffic["blocked"]: print(f"FAIL: {len(traffic['blocked'])} unexpected provider connections blocked")
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())
