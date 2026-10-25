"""Offline checks for source fidelity, editorial selection and inspectable records."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack, closing
from copy import deepcopy
from datetime import timedelta
from email.utils import format_datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW, assert_fixture_connections_closed
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.intelligence import company_catalyst_context as companies, news_editor as editor, news_editor_store as store
from src.reports.daily_news_brief import build_daily_news_brief, MAX_NEWS_CHARS


def candidate(symbol="MSFT", **changes):
    value = {"kind": "company", "symbols": [symbol], "title": symbol + " introduces an example product",
             "url": "https://example.com/" + symbol, "published": (NOW - timedelta(minutes=15)).isoformat(),
             "source": "example.com", "official": False, "relevant": True,
             "source_checked_at": (NOW - timedelta(minutes=5)).isoformat()}
    value.update(changes)
    return value


class EditorChecks(IsolatedChecks):
    def brief(self):
        return companies.build_company_catalyst_brief()

    def plan(self, values):
        return editor.build_editorial_plan(self.brief(), NOW, values)

    def render(self, values):
        with patch.object(editor, "cache_candidates", return_value=(values, [])):
            return build_daily_news_brief(self.research())

    def cache(self, source=0, title="Microsoft introduces an example product", link="https://finance.yahoo.com/story", published=None, **changes):
        publication = format_datetime(NOW - timedelta(minutes=20)) if published is None else published
        body = f"<rss><channel><item><title>{escape(title)}</title><link>{escape(link)}</link><pubDate>{escape(publication)}</pubDate></item></channel></rss>"
        payload = {"status": "ok", "fetched_at_epoch": NOW.timestamp(), "body": body}
        payload.update(changes)
        path = Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"])
        path.write_text(json.dumps({editor.feeds.NEWS_SOURCES[source]["url"]: payload}))
        return path

    def test_diverse_core_companies_are_selected_without_rescoring(self):
        values = [candidate(symbol) for symbol in ("TSLA", "MSFT", "NVDA", "PLTR")]
        before = self.ranking.read_bytes()
        selected = editor.selected_stories(self.plan(values))
        self.assertEqual({story["symbols"][0] for story in selected}, {"MSFT", "NVDA", "PLTR"})
        self.assertEqual(self.ranking.read_bytes(), before)

    def test_duplicate_company_cannot_take_all_three_slots(self):
        values = [candidate(url="https://example.com/" + str(index), title="Microsoft launches product " + str(index)) for index in range(4)]
        values += [candidate("NVDA"), candidate("PLTR")]
        plan = self.plan(values)
        self.assertEqual({story["symbols"][0] for story in editor.selected_stories(plan)}, {"MSFT", "NVDA", "PLTR"})
        self.assertTrue(any("coverage diversity" in story["reason"] for story in plan["candidates"] if story["decision"] == "skip"))

    def test_same_article_tracking_links_do_not_make_new_stories(self):
        values = [candidate(url="https://example.com/a?utm_source=x&id=7"),
                  candidate("NVDA", url="https://example.com/a?id=7&utm_campaign=y", title="Nvidia mentioned in the same article")]
        plan = self.plan(values)
        self.assertEqual(len(editor.selected_stories(plan)), 1)
        self.assertIn("Duplicate article", next(story["reason"] for story in plan["candidates"] if story["decision"] == "skip"))

    def test_duplicate_headline_punctuation_is_not_independent_confirmation(self):
        plan = self.plan([candidate(), candidate("NVDA", title="MSFT introduces an example product!!!")])
        self.assertEqual(len(editor.selected_stories(plan)), 1)
        self.assertFalse(editor.selected_stories(plan)[0]["official"])

    def test_official_announcement_wins_over_a_duplicate_headline(self):
        plan = self.plan([candidate(), candidate(official=True, url="https://example.com/original")])
        self.assertTrue(editor.selected_stories(plan)[0]["official"])
        self.assertEqual(len(editor.selected_stories(plan)), 1)

    def test_newer_company_article_wins_equal_priority(self):
        values = [candidate(title="Older Microsoft story", url="https://example.com/old", published=(NOW - timedelta(hours=2)).isoformat()),
                  candidate(title="Newer Microsoft story", url="https://example.com/new")]
        self.assertEqual(editor.selected_stories(self.plan(values))[0]["title"], "Newer Microsoft story")

    def test_invalid_missing_naive_and_future_publication_times_are_held(self):
        for value in ("", "broken", "2026-10-25T12:00:00", (NOW + timedelta(hours=1)).isoformat()):
            plan = self.plan([candidate(published=value)])
            self.assertFalse(editor.selected_stories(plan))
            self.assertEqual(plan["candidates"][0]["decision"], "wait")

    def test_old_news_is_not_refreshed_by_a_recent_cache_fetch(self):
        self.cache(published=format_datetime(NOW - timedelta(days=4)))
        rows, _ = editor.cache_candidates(NOW, ["MSFT"])
        plan = self.plan(rows)
        self.assertFalse(editor.selected_stories(plan))
        self.assertIn("older than 24 hours", plan["candidates"][0]["reason"])

    def test_stale_future_nan_and_failed_cache_fetches_are_unavailable(self):
        for changes in ({"fetched_at_epoch": NOW.timestamp() - 22000}, {"fetched_at_epoch": NOW.timestamp() + 7200},
                        {"fetched_at_epoch": float("nan")}, {"status": "error"}):
            self.cache(**changes)
            rows, issues = editor.cache_candidates(NOW, ["MSFT"])
            self.assertEqual(rows, []); self.assertTrue(issues)

    def test_html_page_title_cannot_replace_a_dated_article(self):
        self.cache(body="<html><title>Microsoft Announces Huge News</title></html>")
        rows, issues = editor.cache_candidates(NOW, ["MSFT"])
        self.assertFalse(rows)
        self.assertTrue(any("no dated RSS" in issue for issue in issues))

    def test_oversized_or_corrupt_cache_cannot_supply_stories(self):
        path = self.cache()
        for raw in ("{", "x" * (editor.MAX_CACHE_BYTES + 1), "[]"):
            path.write_text(raw)
            rows, issues = editor.cache_candidates(NOW, ["MSFT"])
            self.assertFalse(rows); self.assertTrue(issues)

    def test_original_feed_date_is_retained_separately_from_fetch_time(self):
        self.cache()
        rows, _ = editor.cache_candidates(NOW, ["MSFT"])
        story = editor.selected_stories(self.plan(rows))[0]
        self.assertEqual(editor.dated(story["published"]), NOW - timedelta(minutes=20))
        self.assertEqual(editor.dated(story["source_checked_at"]), NOW)

    def test_publisher_authority_requires_original_publisher_link(self):
        for link, official in (("https://www.federalreserve.gov/newsevents/release.htm", True), ("https://other.example/release", False)):
            self.cache(source=2, title="Federal Reserve announces a policy review", link=link)
            rows, _ = editor.cache_candidates(NOW, [])
            self.assertEqual(rows[0]["official"], official)
            plan = self.plan(rows)
            self.assertEqual(bool(editor.selected_stories(plan)), official)

    def test_yahoo_headline_is_not_company_confirmation(self):
        self.cache(title="Microsoft confirms new cloud product")
        rows, _ = editor.cache_candidates(NOW, ["MSFT"])
        self.assertFalse(editor.selected_stories(self.plan(rows))[0]["official"])

    def test_government_mention_of_a_company_is_not_a_company_announcement(self):
        self.cache(source=2, title="Federal Reserve discusses Microsoft cloud systems", link="https://www.federalreserve.gov/release.htm")
        rows, _ = editor.cache_candidates(NOW, ["MSFT"])
        text = self.render(rows)
        self.assertIn("A publisher announcement from Federal Reserve", text)
        self.assertNotIn("A sourced company announcement", text)

    def test_unsafe_links_are_held_without_execution_or_fetching(self):
        for url in ("javascript:alert(1)", "http://example.com/news", "https://name:secret@example.com/news", "https://example.com:444/news", "https://[invalid", "https://example.com/a\nb"):
            plan = self.plan([candidate(url=url)])
            self.assertFalse(editor.selected_stories(plan))
            self.assertEqual(plan["candidates"][0]["source_check"], "hold")

    def test_relevance_uses_word_boundaries_for_symbols(self):
        self.assertEqual(editor.matched_symbols("Capital markets and digital funds", ["ITA", "CAT", "E"]), [])
        self.assertEqual(editor.matched_symbols("Palantir and Microsoft update AI tools", ["PLTR", "MSFT", "NVDA"]), ["PLTR", "MSFT"])
        self.assertEqual(editor.matched_symbols("$E earnings", ["E"]), ["E"])

    def test_outside_coverage_is_skipped_with_an_explicit_reason(self):
        plan = self.plan([candidate(relevant=False)])
        self.assertFalse(editor.selected_stories(plan))
        self.assertIn("Outside monitored", plan["candidates"][0]["reason"])

    def test_macro_news_leaves_room_for_company_coverage(self):
        values = [candidate(kind="macro", symbols=[], official=True, title="Fed policy review " + str(i), url="https://example.com/fed" + str(i)) for i in range(4)]
        values += [candidate("NVDA"), candidate("PLTR")]
        stories = editor.selected_stories(self.plan(values))
        self.assertEqual(sum(story["kind"] == "macro" for story in stories), 1)
        self.assertEqual(len(stories), 3)

    def test_fewer_than_three_stories_is_valid_without_filler(self):
        self.assertEqual(len(editor.selected_stories(self.plan([candidate()]))), 1)
        self.assertEqual(editor.selected_stories(self.plan([])), [])

    def test_alphabet_share_classes_share_one_company_slot(self):
        brief = self.brief()
        for symbol in ("GOOG", "GOOGL"):
            brief["rows"].append({"symbol": symbol, "events": []})
        plan = editor.build_editorial_plan(brief, NOW, [candidate("GOOG"), candidate("GOOGL")])
        self.assertEqual(len(editor.selected_stories(plan)), 1)

    def test_candidates_are_bounded_and_input_is_not_mutated(self):
        values = [candidate(url="https://example.com/" + str(i)) for i in range(220)]
        before = deepcopy(values)
        plan = self.plan(values)
        self.assertEqual(len(plan["candidates"]), editor.MAX_CANDIDATES)
        self.assertEqual(plan["truncated_candidates"], 40)
        self.assertEqual(values, before)

    def test_brief_retains_headline_attribution_date_and_research_focus(self):
        text = self.render([candidate()])
        self.assertIn("An unconfirmed headline report concerning Microsoft", text)
        self.assertIn("published October 25", text)
        self.assertIn("Company confirmation is pending", text)
        self.assertIn("Research focus:", text)
        self.assertNotIn("caused stocks to fall", text)

    def test_macro_headline_stays_a_headline_and_does_not_explain_market_cause(self):
        text = self.render([candidate(kind="macro", symbols=[], title="Oil market review")])
        self.assertIn("An unconfirmed headline report from example.com", text)
        self.assertIn("headline does not establish a market cause", text)

    def test_news_report_has_exactly_matching_record_and_six_stages(self):
        text = self.render([candidate(), candidate("NVDA"), candidate("PLTR")])
        record = store.read_editions(report=text)[0]
        self.assertEqual([step["name"] for step in record["stages"]], list(editor.STAGE_NAMES))
        self.assertEqual(record["report_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertIn("3 sourced stories selected", editor.review_daily_edition(text))
        self.assertIn("S&P -0.52%", record["market_evidence"]["moves"])

    def test_changed_narration_does_not_match_a_previous_audit(self):
        text = self.render([candidate()])
        with self.assertRaisesRegex(RuntimeError, "No editorial decision record"):
            editor.review_daily_edition(text + "Unreviewed text")

    def test_missing_or_altered_selected_fact_blocks_editorial_record(self):
        plan = self.plan([candidate()])
        story = editor.selected_stories(plan)[0]
        paragraph = editor.render_story(story, companies.calendar_context.report_zone(), {"MSFT": "Microsoft"})
        with self.assertRaisesRegex(ValueError, "Selected story evidence"):
            editor.review_and_record(plan, "Company facts were changed", {story["id"]: paragraph}, self.research())
        self.assertFalse(store.state_path().exists())

    def test_report_build_failure_on_audit_write_does_not_claim_success(self):
        with patch.object(store, "save_edition", side_effect=PermissionError("fixture")):
            with self.assertRaises(PermissionError): self.render([candidate()])

    def test_reading_status_and_history_has_no_database_or_source_writes(self):
        source = self.cache()
        text = self.render([candidate()])
        paths = [store.state_path(), self.db, self.ranking, source]
        before = {path: path.read_bytes() for path in paths}
        editor.build_editor_status(); editor.build_editor_status("MSFT", True); editor.review_daily_edition(text)
        for path in paths: self.assertEqual(path.read_bytes(), before[path])

    def test_missing_history_reader_does_not_create_a_database(self):
        path = self.root / "absent" / "editor.sqlite3"
        with patch.dict(os.environ, {"NEWS_EDITOR_STATE_FILE": str(path)}):
            self.assertIn("No recorded news edition", editor.build_editor_status())
        self.assertFalse(path.parent.exists())

    def test_readonly_or_corrupt_database_is_reported_as_unavailable(self):
        store.state_path().write_bytes(b"not a sqlite database")
        self.assertIn("Decision log unavailable", editor.build_editor_status())

    def test_status_calls_limited_sources_limited_instead_of_verified(self):
        self.render([candidate(published="")])
        status = editor.build_editor_status()
        self.assertIn("Source Check: LIMITED", status)
        self.assertIn("1 held", status)

    def test_story_log_keeps_selected_skipped_and_held_reasons(self):
        self.render([candidate(), candidate("NVDA", published=""), candidate("PLTR", relevant=False)])
        text = editor.build_editor_status(history=True)
        for marker in ("SELECTED", "SKIP", "WAIT", "Reason:", "Published:", "Source check:"):
            self.assertIn(marker, text)

    def test_company_history_filter_excludes_other_company_stories(self):
        self.render([candidate(), candidate("NVDA"), candidate("PLTR")])
        text = editor.build_editor_status("NVDA", True)
        self.assertIn("NVDA introduces", text)
        self.assertNotIn("MSFT introduces", text)

    def test_identical_editions_are_deduplicated_and_retention_is_bounded(self):
        text = self.render([candidate()])
        record = store.read_editions()[0]; record.pop("id"); record.pop("report_sha256")
        store.save_edition(record, text)
        self.assertEqual(len(store.read_editions()), 1)
        with patch.object(store, "MAX_EDITIONS", 2):
            for index in range(4):
                record["generated_at"] = (NOW + timedelta(minutes=index)).isoformat()
                store.save_edition(record, text + str(index))
        self.assertEqual(len(store.read_editions(200)), 2)

    def test_edition_retention_removes_records_older_than_thirty_days(self):
        text = self.render([candidate()])
        record = store.read_editions()[0]; record.pop("id"); record.pop("report_sha256")
        record["generated_at"] = (NOW + timedelta(days=31)).isoformat()
        store.save_edition(record, text + " later")
        records = store.read_editions(200)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["generated_at"], record["generated_at"])

    def test_corrupted_audit_payload_does_not_pass_the_report_review(self):
        text = self.render([candidate()])
        with closing(sqlite3.connect(store.state_path())) as db, db:
            raw = db.execute("SELECT record FROM editions").fetchone()[0]
            db.execute("UPDATE editions SET record=?", (raw.replace("MSFT introduces", "Unsupported claim"),))
        self.assertFalse(store.read_editions(report=text))
        with self.assertRaises(RuntimeError): editor.review_daily_edition(text)

    def test_original_alert_observation_time_is_not_replaced_by_render_time(self):
        self.event(observed=NOW - timedelta(minutes=10))
        brief = self.brief()
        value = next(row["events"][0] for row in brief["rows"] if row["events"])
        self.assertEqual(editor.dated(value["source_checked_at"]), NOW - timedelta(minutes=10))

    def test_length_budget_and_decision_log_agree_on_every_retained_story(self):
        values = [candidate(symbol, title=(symbol + " product development ") * 8, source="Example publisher " * 4) for symbol in ("MSFT", "NVDA", "PLTR")]
        text = self.render(values)
        self.assertLessEqual(len(text), MAX_NEWS_CHARS)
        record = store.read_editions(report=text)[0]
        for story in record["candidates"]:
            present = story["title"].rstrip(".") in text
            self.assertEqual(present, story["decision"] == "selected")
        self.assertIn("Company confirmation is pending", text)


class SQLiteCleanupChecks(unittest.TestCase):
    def test_audit_corruption_fixture_explicitly_closes_the_database(self):
        assert_fixture_connections_closed(self, EditorChecks("test_corrupted_audit_payload_does_not_pass_the_report_review"))


class CommandChecks(unittest.IsolatedAsyncioTestCase):
    async def test_storylog_normalizes_a_symbol_and_replies_only_to_the_request(self):
        from src.commands import news_editor_commands as commands
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(commands, "build_editor_status", return_value="Source decisions") as build:
            await commands.storylog_command(update, SimpleNamespace(args=["$nvda"]))
        build.assert_called_once_with("NVDA", True)
        self.assertIn("Source decisions", update.message.reply_text.await_args.kwargs["text"])

    async def test_invalid_story_filter_does_not_run_the_reader(self):
        from src.commands import news_editor_commands as commands
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(commands, "build_editor_status") as build:
            await commands.storylog_command(update, SimpleNamespace(args=["../bad"]))
        build.assert_not_called()

    async def test_editorstatus_only_reads_an_existing_edition(self):
        from src.commands import news_editor_commands as commands
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(commands, "build_editor_status", return_value="Six stages") as build:
            await commands.editorstatus_command(update, SimpleNamespace(args=[]))
        build.assert_called_once_with()

    async def test_long_story_decisions_are_delivered_in_complete_chunks(self):
        from src.commands import news_editor_commands as commands
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(commands, "build_editor_status", return_value="Public evidence and source checks.\n" * 200 + "END_OF_DECISIONS"):
            await commands.storylog_command(update, SimpleNamespace(args=[]))
        chunks = [call.kwargs["text"] for call in update.message.reply_text.await_args_list]
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 4096 for chunk in chunks))
        self.assertIn("END_OF_DECISIONS", chunks[-1])

    async def test_new_commands_are_registered(self):
        with patch("openai.OpenAI"):
            from src.commands import register_commands, news_editor_commands
        app = SimpleNamespace(add_handler=Mock()); register_commands.register_commands(app)
        callbacks = {name: call.args[0].callback for call in app.add_handler.call_args_list for name in call.args[0].commands}
        self.assertIs(callbacks["editorstatus"], news_editor_commands.editorstatus_command)
        self.assertIs(callbacks["storylog"], news_editor_commands.storylog_command)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--windows-socketpair", action="store_true"); args = parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:
            stack.enter_context(patch.object(socket, "socketpair", portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    passed = result.wasSuccessful() and not traffic["blocked"]
    print(f"News Editor Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    if traffic["blocked"]: print(f"FAIL: {len(traffic['blocked'])} unexpected provider connections blocked")
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())
