"""Offline behavioral checks for company follow-up and the spoken news edition."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack, closing, redirect_stdout
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
from src.reports import daily_report
from src.reports.daily_news_brief import TITLE, HEADERS, MAX_NEWS_CHARS, build_daily_news_brief, validate_news_brief
from src.reports.report_quality import split_report_sections, validate_daily_report_quality

NOW = datetime(2026, 10, 25, 17, tzinfo=timezone.utc)
DAYS = [date(2026, 10, day) for day in (26, 27, 28, 29, 30)]


def announcement(symbol="MSFT", official=False, **overrides):
    evidence = {"title": "Example company introduces a new research platform", "source": "example.com",
                "url": "https://example.com/announcement", "official": official,
                "published": (NOW - timedelta(hours=1)).isoformat()}
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
        text = build_daily_news_brief(research)
        self.assertIn("Market data: unavailable", text)
        self.assertNotIn("0.52 percent", text)
        self.assertNotIn("18-symbol", text)

    def test_earnings_are_estimates_and_fed_times_have_publisher_evidence(self):
        text = build_daily_news_brief(self.research())
        self.assertIn("estimated earnings calendar", text)
        self.assertIn("Company confirmation is pending", text)
        self.assertIn("Federal Reserve's interest-rate decision", text)
        self.assertIn("02:00 PM EDT", text)

    def test_headline_only_development_is_not_rewritten_as_company_confirmation(self):
        self.event()
        text = build_daily_news_brief(self.research())
        self.assertIn("An unconfirmed headline report", text)
        self.assertIn("attributed to example.com", text)
        self.assertIn("published October 25", text)
        self.assertNotIn("A sourced company announcement", text)

    def test_official_development_keeps_the_execution_follow_up(self):
        self.event(announcement(official=True))
        text = build_daily_news_brief(self.research())
        self.assertIn("A sourced company announcement", text)
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
        self.assertFalse(validate_news_brief(text.replace("Company confirmation is pending.", ""))["passes"])

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
        event = {"url": "https://example.com/one", "source": "example.com", "official": False,
                 "published": (NOW - timedelta(minutes=5)).isoformat(),
                 "title": "Long but bounded development " * 5}
        for index, row in enumerate(brief["rows"][:2]): row["events"] = [{**event, "url": event["url"] + str(index)}]
        text = build_daily_news_brief(self.research(), brief)
        self.assertLessEqual(len(text), MAX_NEWS_CHARS)
        self.assertTrue(text.endswith("Research only. Not financial advice."))
        self.assertIn("unconfirmed headline report", text)

    def test_quality_command_labels_the_news_profile_and_its_actual_limit(self):
        from src.commands import reportcheck_commands
        text = build_daily_news_brief(self.research())
        with patch.object(reportcheck_commands, "build_daily_report", return_value=text): card = reportcheck_commands.build_daily_report_quality_card()
        self.assertIn("Smart Money Daily News Brief Quality", card)
        self.assertIn("/ 3800", card)
        self.assertIn("Status: PASS", card)


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
