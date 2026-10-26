"""Offline checks for source fidelity, editorial selection and inspectable records."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack, closing, nullcontext
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
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
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW, announcement, assert_fixture_connections_closed
from src.intelligence.special_alert_sources import OFFICIAL_DOMAINS
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.intelligence import company_catalyst_context as companies, news_editor as editor, news_editor_store as store
from src.reports.daily_news_brief import build_daily_news_brief, MAX_NEWS_CHARS


def candidate(symbol="MSFT", **changes):
    domain = OFFICIAL_DOMAINS.get(symbol, ("microsoft.com",))[0]
    value = {"kind": "company", "symbols": [symbol], "title": symbol + " introduces an example product",
             "url": "https://www." + domain + "/news/" + symbol, "published": (NOW - timedelta(minutes=15)).isoformat(),
             "source": domain, "official": True, "publisher_symbol": symbol, "relevant": True,
             "source_checked_at": (NOW - timedelta(minutes=5)).isoformat()}
    value.update(changes)
    return value


class EditorChecks(IsolatedChecks):
    def event(self, value=None, observed=NOW):
        return super().event(announcement(official=True) if value is None else value, observed)

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

    def test_hold_summary_separates_old_originals_and_unconfirmed_reports(self):
        values = [candidate(official=False), candidate("NVDA", official=False),
                  candidate("PLTR", published=(NOW - timedelta(days=2)).isoformat())]
        plan = self.plan(values)
        reasons = dict(editor.hold_reasons(plan["candidates"]))
        self.assertEqual(reasons["Original-source confirmation needed"], 2)
        self.assertEqual(reasons["Publication older than 24 hours"], 1)
        self.assertEqual(sum(reasons.values()), 3)
        self.assertFalse(editor.selected_stories(plan))

    def test_future_publications_and_stale_observations_are_distinct(self):
        plan = self.plan([candidate(published=(NOW + timedelta(days=1)).isoformat()),
                          candidate("NVDA", source_checked_at=(NOW - timedelta(hours=7)).isoformat())])
        reasons = dict(editor.hold_reasons(plan["candidates"]))
        self.assertEqual(reasons, {"Publication outside allowed time window": 1, "Source observation stale or invalid": 1})

    def test_incomplete_headlines_and_mismatched_publishers_have_clear_hold_reasons(self):
        plan = self.plan([candidate(title="Microsoft introduces a new cloud platform…"),
                          candidate("NVDA", url="https://finance.yahoo.com/story")])
        self.assertEqual(dict(editor.hold_reasons(plan["candidates"])),
                         {"Complete headline unavailable": 1, "Publisher identity mismatch": 1})

    def test_publication_timezone_and_link_problems_are_reported_without_substitution(self):
        plan = self.plan([candidate(published="2026-10-25T10:00:00"), candidate("NVDA", url="http://www.nvidia.com/news")])
        self.assertEqual(dict(editor.hold_reasons(plan["candidates"])),
                         {"Original publication time unavailable": 1, "Original link invalid": 1})

    def test_status_and_company_history_summarize_the_recorded_holds(self):
        text = self.render([candidate(official=False), candidate("NVDA", published=(NOW - timedelta(days=2)).isoformat())])
        status = editor.build_editor_status()
        self.assertIn("Original-source confirmation needed: 1", status)
        self.assertIn("Publication older than 24 hours: 1", status)
        history = editor.build_editor_status("NVDA", history=True)
        self.assertIn("Publication older than 24 hours: 1", history)
        self.assertNotIn("Original-source confirmation needed", history)
        self.assertIn("0 sourced stories selected", editor.review_daily_edition(text))

    def test_selected_and_skipped_stories_do_not_inflate_hold_counts(self):
        plan = self.plan([candidate(), candidate("NVDA", title="Why Nvidia shares could rebound?")])
        self.assertEqual(editor.hold_reasons(plan["candidates"]), [])
        self.assertTrue(editor.selected_stories(plan))

    def test_historical_combined_time_reason_is_not_mislabeled_as_only_old(self):
        reasons = editor.hold_reasons([{"decision": "wait", "reason": "Original publication time is future-dated or older than 24 hours"}])
        self.assertEqual(reasons, [("Publication outside allowed time window", 1)])

    def test_darpa_original_feed_is_admitted_only_with_an_original_agency_link(self):
        source = next(index for index, row in enumerate(editor.feeds.NEWS_SOURCES) if row["name"] == "DARPA")
        title = "DARPA demonstrates an autonomous flight prototype"
        self.cache(source, title=title, link="https://www.darpa.mil/news/flight-fixture")
        text = build_daily_news_brief(self.research())
        record = store.read_editions(report=text)[0]
        story = next(row for row in record["candidates"] if row["title"] == title)
        self.assertEqual(story["confirmed_by"], "DARPA")
        self.assertEqual(story["materiality"], "defense innovation")
        self.assertIn(title, text)
        self.cache(source, title=title, link="https://darpa.mil.example.com/news/flight-fixture")
        plan = editor.build_editorial_plan(self.brief(), NOW)
        self.assertFalse(editor.selected_stories(plan))

    def test_lockheed_original_feed_uses_the_monitored_issuer_provenance(self):
        source = next(index for index, row in enumerate(editor.feeds.NEWS_SOURCES) if row.get("company_symbol") == "LMT")
        title = "Lockheed Martin unveils a new autonomous defense system"
        self.cache(source, title=title, link="https://news.lockheedmartin.com/fixture-release")
        with patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "MSFT,NVDA,PLTR,LMT"}):
            text = build_daily_news_brief(self.research())
        story = next(row for row in store.read_editions(report=text)[0]["candidates"] if row["title"] == title)
        self.assertEqual(story["confirmed_by"], "LMT")
        self.assertIn("Lockheed Martin's company announcement", text)
        self.assertIn("Global and Defense Watch", text)

    def test_new_feed_fetch_time_does_not_replace_a_missing_original_date(self):
        source = next(index for index, row in enumerate(editor.feeds.NEWS_SOURCES) if row["name"] == "DARPA")
        title = "DARPA demonstrates an autonomous flight prototype"
        self.cache(source, title=title, link="https://www.darpa.mil/news/fixture", published="")
        text = build_daily_news_brief(self.research())
        self.assertNotIn(title, text)
        story = next(row for row in store.read_editions(report=text)[0]["candidates"] if row["title"] == title)
        self.assertEqual(story["decision"], "wait")

    def test_duplicate_company_cannot_take_all_three_slots(self):
        values = [candidate(url="https://www.microsoft.com/news/" + str(index), title="Microsoft launches product " + str(index)) for index in range(4)]
        values += [candidate("NVDA"), candidate("PLTR")]
        plan = self.plan(values)
        self.assertEqual({story["symbols"][0] for story in editor.selected_stories(plan)}, {"MSFT", "NVDA", "PLTR"})
        self.assertTrue(any("coverage diversity" in story["reason"] for story in plan["candidates"] if story["decision"] == "skip"))

    def test_same_article_tracking_links_do_not_make_new_stories(self):
        values = [candidate(url="https://www.microsoft.com/a?utm_source=x&id=7"),
                  candidate(url="https://www.microsoft.com/a?id=7&utm_campaign=y", title="Microsoft introduces another product in the same article")]
        plan = self.plan(values)
        self.assertEqual(len(editor.selected_stories(plan)), 1)
        self.assertIn("Duplicate article", next(story["reason"] for story in plan["candidates"] if story["decision"] == "skip"))

    def test_duplicate_headline_punctuation_is_not_independent_confirmation(self):
        plan = self.plan([candidate(), candidate("NVDA", title="MSFT introduces an example product!!!")])
        self.assertEqual(len(editor.selected_stories(plan)), 1)
        self.assertTrue(editor.selected_stories(plan)[0]["official"])

    def test_official_announcement_wins_over_a_duplicate_headline(self):
        plan = self.plan([candidate(official=False), candidate(url="https://www.microsoft.com/original")])
        self.assertTrue(editor.selected_stories(plan)[0]["official"])
        self.assertEqual(len(editor.selected_stories(plan)), 1)

    def test_newer_company_article_wins_equal_priority(self):
        values = [candidate(title="Microsoft introduces an older cloud product", url="https://www.microsoft.com/old", published=(NOW - timedelta(hours=2)).isoformat()),
                  candidate(title="Microsoft introduces a newer cloud product", url="https://www.microsoft.com/new")]
        self.assertEqual(editor.selected_stories(self.plan(values))[0]["title"], "Microsoft introduces a newer cloud product")

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
        story = self.plan(rows)["candidates"][0]
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
        plan = self.plan(rows)
        self.assertFalse(editor.selected_stories(plan))
        self.assertFalse(plan["candidates"][0]["official"])

    def test_government_mention_of_a_company_is_not_a_company_announcement(self):
        self.cache(source=2, title="Federal Reserve awards Microsoft a cloud contract", link="https://www.federalreserve.gov/release.htm")
        rows, _ = editor.cache_candidates(NOW, ["MSFT"])
        text = self.render(rows)
        self.assertIn("A publisher announcement from Federal Reserve", text)
        self.assertNotIn("company announcement", text)

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
        values = [candidate(kind="macro", symbols=[], title="Fed policy review " + str(i), source="Federal Reserve", url="https://www.federalreserve.gov/fed" + str(i)) for i in range(4)]
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
        values = [candidate(url="https://www.microsoft.com/news/" + str(i)) for i in range(220)]
        before = deepcopy(values)
        plan = self.plan(values)
        self.assertEqual(len(plan["candidates"]), editor.MAX_CANDIDATES)
        self.assertEqual(plan["truncated_candidates"], 40)
        self.assertEqual(values, before)

    def test_brief_retains_headline_attribution_date_and_research_focus(self):
        text = self.render([candidate()])
        self.assertIn("Microsoft's company announcement", text)
        self.assertIn("published October 25", text)
        self.assertIn("microsoft.com", text)
        self.assertNotIn("Research focus:", text)
        self.assertIn("Research focus:", editor.build_editor_status(history=True))
        self.assertNotIn("caused stocks to fall", text)

    def test_macro_headline_stays_a_headline_and_does_not_explain_market_cause(self):
        text = self.render([candidate(kind="macro", symbols=[], title="Oil inventories report released", source="EIA", url="https://www.eia.gov/report")])
        self.assertIn("A publisher announcement from EIA", text)
        self.assertNotIn("caused", text)

    def test_live_preview_roundups_are_logged_without_becoming_company_news(self):
        values = [candidate(title="Dow Jones Futures Due With Microsoft, Google, Amazon Ahead; Will Doom Or Bloom Control Market?", official=False),
                  candidate("TSLA", title="3 AI Infrastructure Stocks Riding The Tesla And SpaceX Compute Buildout", official=False),
                  candidate("NVDA", title="Nvidia (NVDA) Has Lost Its China AI Accelerator Market", official=False)]
        text = self.render(values)
        record = store.read_editions(report=text)[0]
        selected = [story for story in record["candidates"] if story["decision"] == "selected"]
        self.assertEqual(selected, [])
        self.assertNotIn(values[2]["title"], text)
        self.assertNotIn(values[0]["title"], text)
        self.assertNotIn(values[1]["title"], text)
        for story in record["candidates"][:2]:
            self.assertEqual(story["story_type"], "roundup")
            self.assertEqual(story["source_check"], "pass")
            self.assertIn("roundup", story["reason"])
        history = editor.build_editor_status(history=True)
        self.assertIn("Story type: roundup", history)
        self.assertIn(values[1]["title"], history)

    def test_numbered_product_releases_are_not_mistaken_for_stock_pick_lists(self):
        for title in ("Microsoft introduces 3 cloud tools", "Nvidia ships five new products", "Palantir reports results before market open"):
            with self.subTest(title=title):
                self.assertEqual(len(editor.selected_stories(self.plan([candidate(title=title)]))), 1)

    def test_company_source_does_not_make_a_tutorial_question_into_material_news(self):
        plan = self.plan([candidate(title="How can our new platform help customers?", official=True)])
        story = plan["candidates"][0]
        self.assertFalse(editor.selected_stories(plan))
        self.assertEqual(story["story_type"], "commentary")
        self.assertTrue(story["official"])

    def test_specific_company_news_takes_priority_over_high_ranked_commentary(self):
        values = [candidate(title="Why Microsoft shares could rebound?"), candidate("NVDA"), candidate("TSM"), candidate("PLTR")]
        plan = self.plan(values)
        self.assertEqual({story["symbols"][0] for story in editor.selected_stories(plan)}, {"NVDA", "TSM", "PLTR"})
        self.assertEqual(plan["candidates"][0]["story_type"], "commentary")

    def test_commentary_is_labeled_without_becoming_a_company_announcement(self):
        value = candidate(title="Why Microsoft shares could rebound?")
        text = self.render([value])
        self.assertNotIn(value["title"], text)
        history = editor.build_editor_status(history=True)
        self.assertIn(value["title"], history)
        self.assertIn("Story type: commentary", history)
        self.assertNotIn("company announcement", text)

    def test_no_eligible_company_story_is_stated_without_roundup_filler(self):
        text = self.render([candidate(title="5 AI Stocks to Buy This Week")])
        self.assertIn("No new source-confirmed company report", text)
        self.assertNotIn("5 AI Stocks", text)

    def test_one_story_qualification_cannot_cover_another_unqualified_paragraph(self):
        from src.reports.daily_news_brief import validate_news_brief
        text = self.render([candidate(), candidate("NVDA")])
        self.assertTrue(validate_news_brief(text)["passes"])
        bad = text + "\n\nA headline-only report, unconfirmed by the company."
        self.assertFalse(validate_news_brief(bad)["passes"])

    def test_publication_clock_and_source_title_are_retained_in_shorter_narration(self):
        value = candidate(title="Microsoft introduces a new cloud platform")
        text = self.render([value])
        self.assertIn("October 25 at 12:45 PM EDT", text)
        self.assertIn("“" + value["title"] + "”", text)
        self.assertIn("microsoft.com", text)
        self.assertNotIn("Research focus:", text)

    def test_length_cut_removes_the_dropped_storys_followup_from_narration(self):
        from src.reports import daily_news_brief as news
        value = candidate(title="Microsoft introduces a cloud platform for China " * 5, source="Microsoft original publisher " * 3)
        budget = len(self.render([])) + 80
        with patch.object(news, "MAX_NEWS_CHARS", budget):
            text = self.render([value])
        record = store.read_editions(report=text)[0]
        self.assertFalse(any(story["decision"] == "selected" for story in record["candidates"]))
        self.assertNotIn("regional sales and export access", text)
        self.assertIn("No new source-confirmed company report", text)
        self.assertIn("Narration length budget", record["candidates"][0]["reason"])
        self.assertLessEqual(len(text), budget)

    def test_posted_retrospective_and_personal_wealth_stories_do_not_fill_news_slots(self):
        values = [candidate(title="Apple's Market Cap Grew From $350 Billion to $4.6 Trillion During Tim Cook's 15 Years as CEO. Here's What That Growth Curve Means for Apple's Next Chapter Under", official=False),
                  candidate("TSLA", title="Elon Musk Became the First Person Ever Confirmed With a Net Worth Above $1 Trillion in June 2026. Here's Why That Milestone Still Matters for Tesla and SpaceX S", official=False),
                  candidate("NVDA", title="Nvidia (NVDA) Has Lost Its China AI Accelerator Market", official=False)]
        text = self.render(values)
        record = store.read_editions(report=text)[0]
        self.assertEqual([story["story_type"] for story in record["candidates"][:2]], ["retrospective", "personal wealth"])
        self.assertEqual([story["decision"] for story in record["candidates"]], ["skip", "skip", "wait"])
        self.assertNotIn(values[2]["title"], text)
        self.assertNotIn("$350 Billion", text)
        self.assertNotIn("Net Worth", text)

    def test_original_feed_headline_is_complete_without_changing_other_feed_displays(self):
        title = "Microsoft introduces a cloud platform for enterprise customers and partners " * 3 + "but will not launch it this year"
        source_index = next(index for index, value in enumerate(editor.feeds.NEWS_SOURCES) if value.get("company_symbol") == "MSFT")
        path = self.cache(title=title, source=source_index, link="https://blogs.microsoft.com/announcement")
        source = editor.feeds.NEWS_SOURCES[source_index]
        body = json.loads(path.read_text())[source["url"]]["body"]
        legacy = editor.feeds.parse_rss_items(body, source)[0]["title"]
        self.assertEqual(len(legacy), 180)
        self.assertTrue(legacy.endswith("..."))
        rows, _ = editor.cache_candidates(NOW, ["MSFT"])
        self.assertEqual(rows[0]["title"], title)
        text = self.render(rows)
        self.assertIn(title, text)
        self.assertIn("but will not launch it this year", text)
        record = store.read_editions(report=text)[0]
        self.assertEqual(record["candidates"][0]["title"], title)
        self.assertFalse(record["candidates"][0]["title_truncated"])

    def test_ellipsis_and_explicitly_shortened_titles_are_held(self):
        for changes in ({"title": "Microsoft releases a new cloud platform..."},
                        {"title": "Microsoft releases a new cloud platform…"}, {"title_truncated": True}):
            with self.subTest(changes=changes):
                story = self.plan([candidate(**changes)])["candidates"][0]
                self.assertEqual(story["decision"], "wait")
                self.assertEqual(story["source_check"], "hold")
                self.assertIn("Complete original headline", story["reason"])

    def test_oversized_title_is_bounded_and_cannot_hide_another_usable_story(self):
        plan = self.plan([candidate(title="Microsoft " + "x" * (editor.MAX_HEADLINE_CHARS + 1)), candidate("NVDA")])
        held = plan["candidates"][0]
        self.assertEqual(held["decision"], "wait")
        self.assertEqual(len(held["title"]), editor.MAX_HEADLINE_CHARS)
        self.assertTrue(held["title_truncated"])
        self.assertEqual([story["symbols"][0] for story in editor.selected_stories(plan)], ["NVDA"])

    def test_event_reader_does_not_cut_a_complete_title_at_150_characters(self):
        value = self.event()
        title = "Microsoft introduces an enterprise cloud platform for customers and partners " * 2 + "with commercial availability still pending"
        value["evidence"]["title"] = title
        self.event(value)
        event = next(row["events"][0] for row in self.brief()["rows"] if row["events"])
        self.assertEqual(event["title"], title)
        self.assertFalse(event["title_truncated"])
        self.assertIn(title, self.render([]))

    def test_legacy_event_at_the_unmarked_240_character_limit_is_not_narrated(self):
        value = self.event()
        value["evidence"]["title"] = ("Microsoft cloud platform development " * 10)[:240]
        self.event(value)
        event = next(row["events"][0] for row in self.brief()["rows"] if row["events"])
        self.assertTrue(event["title_truncated"])
        text = self.render([])
        self.assertIn("No new source-confirmed company report", text)
        self.assertNotIn("Microsoft cloud platform development", text)

    def test_original_event_title_restores_full_wording_when_supplied_separately(self):
        value = self.event()
        title = "Microsoft introduces a cloud product for customers and partners " * 4 + "with launch timing unconfirmed"
        value["evidence"].update(title=title[:240], original_title=title)
        self.event(value)
        event = next(row["events"][0] for row in self.brief()["rows"] if row["events"])
        self.assertEqual(event["title"], title)
        self.assertFalse(event["title_truncated"])
        self.assertIn(title, self.render([]))

    def test_malformed_original_event_title_is_not_turned_into_a_company_claim(self):
        value = self.event()
        value["evidence"]["original_title"] = {"unexpected": "structure"}
        self.event(value)
        event = next(row["events"][0] for row in self.brief()["rows"] if row["events"])
        self.assertTrue(event["title_truncated"])
        text = self.render([])
        self.assertNotIn("unexpected", text)
        self.assertIn("No new source-confirmed company report", text)

    def test_compensation_and_share_sales_are_kept_even_with_net_worth_mentions(self):
        for title in ("Tesla shareholders approve Musk pay package as his net worth rises",
                      "CEO reports stock sales as net worth falls"):
            with self.subTest(title=title):
                story = editor.selected_stories(self.plan([candidate("TSLA", title=title)]))[0]
                self.assertEqual(story["story_type"], "announcement")

    def test_a_personal_wealth_milestone_does_not_become_news_by_using_announces(self):
        plan = self.plan([candidate("TSLA", title="Elon Musk announces a new net worth milestone")])
        self.assertFalse(editor.selected_stories(plan))
        self.assertEqual(plan["candidates"][0]["story_type"], "personal wealth")

    def test_current_ceo_transition_is_kept_even_with_retrospective_context(self):
        for title in ("Apple appoints new CEO after Tim Cook's 15 years as CEO",
                      "Tim Cook steps down after 15 years as CEO"):
            with self.subTest(title=title):
                story = editor.selected_stories(self.plan([candidate(title=title)]))[0]
                self.assertEqual(story["story_type"], "announcement")

    def test_embedded_explanatory_hook_is_labeled_as_commentary(self):
        value = candidate(title="Microsoft Valuation Is Back in Focus. Here's What Investors Need to Know")
        text = self.render([value])
        self.assertNotIn(value["title"], text)
        self.assertIn("Story type: commentary", editor.build_editor_status(history=True))

    def test_editorial_review_rejects_a_selected_incomplete_headline(self):
        plan = self.plan([candidate()])
        story = editor.selected_stories(plan)[0]
        paragraph = editor.render_story(story, companies.calendar_context.report_zone(), {"MSFT": "Microsoft"})
        story["title_truncated"] = True
        with self.assertRaisesRegex(ValueError, "headline is incomplete"):
            editor.review_and_record(plan, paragraph, {story["id"]: paragraph}, self.research())
        self.assertFalse(store.state_path().exists())

    def test_apple_is_named_in_the_spoken_story_instead_of_only_using_a_ticker(self):
        brief = self.brief()
        brief["rows"].append({"symbol": "AAPL", "events": [], "calendar": {"dates": []}})
        value = candidate("AAPL", title="Apple announces an example product")
        with patch.object(editor, "cache_candidates", return_value=([value], [])):
            text = build_daily_news_brief(self.research(), brief)
        self.assertIn("Apple's company announcement", text)
        self.assertNotIn("AAPL's company announcement", text)
        self.assertIn(value["title"], text)

    def test_posted_bitcoin_bet_buy_question_and_unconfirmed_company_claim_are_excluded(self):
        values = [candidate(kind="macro", symbols=[], source="Yahoo Finance Market", url="https://finance.yahoo.com/bet", official=False,
                            title="Mike Alfred Says He Would Bet $1 Million Bitcoin Reaches $100,000 Before $60,000"),
                  candidate("CRWD", official=False, url="https://finance.yahoo.com/buy", title="Up Over 100% in 2026, Is CrowdStrike Still a Buy?"),
                  candidate("NVDA", official=False, url="https://finance.yahoo.com/china", title="Nvidia (NVDA) Has Lost Its China AI Accelerator Market")]
        text = self.render(values)
        record = store.read_editions(report=text)[0]
        self.assertFalse(any(row["decision"] == "selected" for row in record["candidates"]))
        for value in values:
            self.assertNotIn(value["title"], text)
        self.assertNotIn("headline-only", text)
        decisions = {row["title"]: row for row in record["candidates"]}
        self.assertEqual(decisions[values[0]["title"]]["story_type"], "speculation")
        self.assertEqual(decisions[values[1]["title"]]["decision"], "skip")
        self.assertEqual(decisions[values[2]["title"]]["decision"], "wait")

    def test_unconfirmed_earnings_report_cannot_fill_an_empty_news_slot(self):
        value = candidate("NVDA", title="Nvidia reports quarterly financial results", official=False, url="https://finance.yahoo.com/results")
        plan = self.plan([value])
        self.assertFalse(editor.selected_stories(plan))
        self.assertEqual(plan["candidates"][0]["confirmation_check"], "hold")

    def test_official_flag_alone_cannot_turn_an_unrelated_domain_into_confirmation(self):
        plan = self.plan([candidate(url="https://example.com/microsoft-release", official=True)])
        self.assertFalse(editor.selected_stories(plan))
        self.assertIn("publisher identity", plan["candidates"][0]["reason"])

    def test_material_company_reports_cover_the_main_investor_categories(self):
        values = {
            "product": "Microsoft unveils an enterprise AI platform",
            "earnings": "Microsoft reports quarterly financial results",
            "guidance": "Microsoft raises revenue guidance",
            "contract": "Microsoft wins a strategic cloud contract",
            "acquisition": "Microsoft agrees to acquire an example software company",
            "risk": "Microsoft discloses a major outage",
            "capital": "Microsoft authorizes a share repurchase program",
            "leadership": "Microsoft appoints a new CFO",
            "investment": "Microsoft announces a capital spending plan",
            "regulation": "Microsoft discloses a court ruling",
        }
        for category, title in values.items():
            with self.subTest(category=category):
                story = editor.selected_stories(self.plan([candidate(title=title)]))[0]
                self.assertEqual(story["materiality"], category)
                self.assertEqual(story["confirmed_by"], "MSFT")

    def test_original_agency_releases_supply_macro_news(self):
        values = [candidate(kind="macro", symbols=[], source="Federal Reserve", url="https://www.federalreserve.gov/release", title="Federal Reserve publishes FOMC meeting minutes"),
                  candidate(kind="macro", symbols=[], source="EIA", url="https://www.eia.gov/release", title="EIA releases oil inventory data")]
        selected = editor.selected_stories(self.plan(values))
        self.assertEqual({row["confirmed_by"] for row in selected}, {"Federal Reserve", "EIA"})

    def test_company_tutorials_and_routine_date_announcements_are_not_news_filler(self):
        for title in ("Microsoft shares five coding tips", "Microsoft announces its earnings date", "Microsoft will report quarterly results next week"):
            with self.subTest(title=title):
                self.assertFalse(editor.selected_stories(self.plan([candidate(title=title)])))

    def test_company_revenue_outlook_remains_news_with_company_attribution(self):
        story = editor.selected_stories(self.plan([candidate(title="Microsoft forecasts revenue growth next quarter")]))[0]
        self.assertEqual(story["materiality"], "guidance")
        self.assertEqual(story["confirmed_by"], "MSFT")

    def test_secondary_feed_linking_an_issuer_is_not_an_original_publication_record(self):
        self.cache(title="Microsoft introduces a cloud platform", link="https://blogs.microsoft.com/original")
        rows, _ = editor.cache_candidates(NOW, ["MSFT"])
        self.assertFalse(editor.selected_stories(self.plan(rows)))

    def test_primary_candidates_are_retained_before_the_unconfirmed_candidate_limit(self):
        values = [candidate(official=False, url="https://finance.yahoo.com/" + str(index)) for index in range(190)]
        values.append(candidate("NVDA"))
        plan = self.plan(values)
        self.assertEqual([row["confirmed_by"] for row in editor.selected_stories(plan)], ["NVDA"])
        self.assertEqual(len(plan["candidates"]), editor.MAX_CANDIDATES)

    def test_editorial_review_blocks_forced_selection_of_an_unconfirmed_report(self):
        plan = self.plan([candidate(official=False)])
        story = plan["candidates"][0]
        story.update(decision="selected", priority=90)
        paragraph = editor.render_story(story, companies.calendar_context.report_zone(), {"MSFT": "Microsoft"})
        with self.assertRaisesRegex(ValueError, "original-source report"):
            editor.review_and_record(plan, paragraph, {story["id"]: paragraph}, self.research())
        self.assertFalse(store.state_path().exists())

    def test_primary_company_feeds_are_derived_from_the_existing_official_registry(self):
        from src.intelligence.special_alert_company_sources import OFFICIAL_FEEDS
        sources = {source.get("company_symbol"): source for source in editor.feeds.NEWS_SOURCES if source.get("company_symbol")}
        for symbol in ("NVDA", "MSFT"):
            self.assertEqual(sources[symbol]["url"], OFFICIAL_FEEDS[symbol])
            index = editor.feeds.NEWS_SOURCES.index(sources[symbol])
            domain = OFFICIAL_DOMAINS[symbol][0]
            self.cache(source=index, title="Introducing a new enterprise AI platform", link="https://www." + domain + "/release")
            rows, _ = editor.cache_candidates(NOW, [symbol])
            selected = editor.selected_stories(self.plan(rows))
            self.assertEqual(selected[0]["confirmed_by"], symbol)

    def test_decision_log_explains_original_publisher_and_investor_relevance(self):
        self.render([candidate(title="Microsoft raises revenue guidance")])
        history = editor.build_editor_status(history=True)
        self.assertIn("Original publisher verified: MSFT", history)
        self.assertIn("Investor topic: guidance", history)

    def test_joint_company_report_is_attributed_to_the_original_publisher(self):
        value = candidate("NVDA", symbols=["NVDA", "MSFT"], source="microsoft.com", url="https://www.microsoft.com/partnership",
                          publisher_symbol="MSFT", title="Microsoft signs a strategic cloud partnership with Nvidia")
        text = self.render([value])
        self.assertIn("Microsoft's company announcement", text)
        self.assertNotIn("Nvidia's company announcement", text)

    def test_quiet_edition_passes_without_promoting_unconfirmed_news(self):
        from src.reports.daily_news_brief import validate_news_brief
        text = self.render([candidate(official=False)])
        self.assertTrue(validate_news_brief(text)["passes"])
        self.assertIn("No new source-confirmed company report", text)
        self.assertIn("0 sourced stories selected", editor.review_daily_edition(text))
        self.assertNotIn("estimated earnings calendar", text)

    def test_original_link_and_official_flag_need_original_publication_provenance(self):
        plan = self.plan([candidate(publisher_symbol="")])
        self.assertFalse(editor.selected_stories(plan))
        self.assertIn("publisher identity", plan["candidates"][0]["reason"])

    def test_secondary_feed_cannot_supply_original_issuer_publication_provenance(self):
        from src.intelligence import special_alert_sources as sources
        body = ("<rss><channel><item><title>Tesla unveils an AI vehicle platform</title>"
                "<link>https://ir.tesla.com/release</link><pubDate>" + format_datetime(NOW - timedelta(minutes=10))
                + "</pubDate></item></channel></rss>").encode()
        item = sources.parse_feed(body, ["TSLA"], "secondary feed")[0]
        self.assertTrue(item["official"])
        value = announcement("TSLA", official=True)
        value["evidence"] = item
        self.event(value)
        text = self.render([])
        self.assertNotIn(item["title"], text)

    def test_tesla_original_feed_provenance_survives_into_the_news_editor(self):
        from src.intelligence import special_alert_sources as sources
        body = ("<rss><channel><item><title>Tesla unveils an AI vehicle platform</title>"
                "<link>https://ir.tesla.com/release</link><pubDate>" + format_datetime(NOW - timedelta(minutes=10))
                + "</pubDate></item></channel></rss>").encode()
        with patch.object(sources, "request_bytes", return_value=body):
            items, _, _ = sources.tesla_ir_news(NOW, {"news_hours": 6})
        self.assertEqual(items[0]["publisher_symbol"], "TSLA")
        value = announcement("TSLA", official=True)
        value["evidence"] = items[0]
        self.event(value)
        self.assertIn(items[0]["title"], self.render([]))

    def test_fresh_publication_time_cannot_replace_a_missing_or_stale_source_observation(self):
        for checked in (None, (NOW - timedelta(hours=7)).isoformat(), (NOW + timedelta(hours=1)).isoformat()):
            with self.subTest(checked=checked):
                plan = self.plan([candidate(source_checked_at=checked)])
                self.assertFalse(editor.selected_stories(plan))
                self.assertEqual(plan["candidates"][0]["source_check"], "hold")

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
        values = [candidate(symbol, title=(symbol + " introduces an AI platform ") * 8, source="Original publisher " * 4) for symbol in ("MSFT", "NVDA", "PLTR")]
        text = self.render(values)
        self.assertLessEqual(len(text), MAX_NEWS_CHARS)
        record = store.read_editions(report=text)[0]
        for story in record["candidates"]:
            present = story["title"].rstrip(".") in text
            self.assertEqual(present, story["decision"] == "selected")
        self.assertNotIn("unconfirmed by the company", text)


class OriginalSourceChecks(IsolatedChecks):
    def source(self, symbol):
        return next(source for source in editor.feeds.NEWS_SOURCES if source.get("company_symbol") == symbol)

    def payload(self, body="", **changes):
        return {"status": "ok", "fetched_at_epoch": NOW.timestamp(), "body": body, **changes}

    def rss(self, title, url, published=None):
        published = published or (NOW - timedelta(minutes=20)).isoformat()
        return f"<rss><channel><item><title>{escape(title)}</title><link>{escape(url)}</link><pubDate>{escape(published)}</pubDate></item></channel></rss>"

    def service(self, **changes):
        row = {"Headline": "Palantir signs a new AI defense contract", "PressReleaseDate": (NOW - timedelta(hours=1)).strftime("%m/%d/%Y %H:%M:%S"),
               "LinkToDetailPage": "/news-details/2026/example/default.aspx", **changes}
        return json.dumps({"GetPressReleaseListResult": [row]})

    def metadata(self, title="Palantir signs a new AI defense contract", published=None):
        return '<script type="application/ld+json">' + json.dumps({"@type": "NewsArticle", "headline": title,
            "datePublished": published or (NOW - timedelta(hours=1)).isoformat()}) + '</script>'

    def test_core_and_leading_company_readers_are_configured(self):
        symbols = {row.get("company_symbol") for row in editor.feeds.NEWS_SOURCES}
        self.assertTrue({"MSFT", "NVDA", "PLTR", "AVGO", "AVAV", "KTOS", "CRWD", "TSLA", "TSM", "NOC", "LMT", "AAPL"} <= symbols)
        self.assertLessEqual(len(editor.feeds.NEWS_SOURCES), 24)

    def test_atom_keeps_original_publication_and_alternate_link(self):
        body = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Apple introduces an AI platform</title><link rel="alternate" href="https://www.apple.com/newsroom/release/"/><published>2026-10-25T16:00:00Z</published><updated>2026-10-25T16:59:00Z</updated></entry></feed>'
        item = editor.feeds.parse_rss_items(body, self.source("AAPL"), full_titles=True)[0]
        self.assertEqual(item["published"], "2026-10-25T16:00:00Z")
        self.assertEqual(item["link"], "https://www.apple.com/newsroom/release/")
        missing = body.replace('<published>2026-10-25T16:00:00Z</published>', '')
        self.assertEqual(editor.feeds.parse_rss_items(missing, self.source("AAPL"))[0]["published"], "")

    def test_palantir_reads_its_own_exact_release_metadata(self):
        from src.intelligence import news_original_sources as original
        source = self.source("PLTR")
        calls = []
        def fetch(url):
            calls.append(url)
            return self.payload(self.service() if "GetPressReleaseList?" in url else self.metadata(), url=url)
        payload = original.retrieve(source, fetch, NOW)
        item = original.cached_items(payload, source)[0]
        self.assertEqual(editor.dated(item["published"]), NOW - timedelta(hours=1))
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(url.startswith("https://investors.palantir.com/") for url in calls))

    def test_palantir_naive_service_date_remains_held_without_original_clock(self):
        from src.intelligence import news_original_sources as original
        def fetch(url):
            return self.payload(self.service() if "GetPressReleaseList?" in url else '<html><title>Release</title></html>', url=url)
        payload = original.retrieve(self.source("PLTR"), fetch, NOW)
        item = original.cached_items(payload, self.source("PLTR"))[0]
        with self.assertRaises(ValueError): editor.dated(item["published"])
        self.assertTrue(payload["publication_problems"])
        self.assertEqual(editor.feeds.describe_source(self.source("PLTR"), payload, NOW)["status"], "limited")

    def test_palantir_does_not_borrow_another_headlines_publication_time(self):
        from src.intelligence import news_original_sources as original
        def fetch(url):
            return self.payload(self.service() if "GetPressReleaseList?" in url else self.metadata(title="Different release"), url=url)
        item = original.cached_items(original.retrieve(self.source("PLTR"), fetch, NOW), self.source("PLTR"))[0]
        with self.assertRaises(ValueError): editor.dated(item["published"])

    def test_long_original_titles_are_matched_beyond_the_first_240_characters(self):
        from src.intelligence.special_alert_company_sources import publication_time
        title = "Palantir introduces a research platform " + "with enterprise support " * 12
        body = self.metadata(title=title + "for a different program").encode()
        with self.assertRaises(ValueError): publication_time(body, title)
        self.assertEqual(publication_time(self.metadata(title=title).encode(), title), NOW - timedelta(hours=1))

    def test_malformed_publisher_service_is_rejected_without_a_homepage_fallback(self):
        from src.intelligence import news_original_sources as original
        for body in ('[]', '{}', '{"GetPressReleaseListResult":null}', '<html><title>Palantir</title></html>'):
            with self.assertRaises(ValueError): original.service_items(body, self.source("PLTR"))

    def test_palantir_release_redirect_cannot_confirm_a_company_story(self):
        from src.intelligence import news_original_sources as original
        def fetch(url):
            return self.payload(self.service() if "GetPressReleaseList?" in url else self.metadata(), url=url,
                                final_url=url if "GetPressReleaseList?" in url else "https://example.com/copied-release")
        result = original.retrieve(self.source("PLTR"), fetch, NOW)
        self.assertTrue(any("outside the issuer" in problem for problem in result["publication_problems"]))
        with self.assertRaises(ValueError): editor.dated(result["articles"][0]["published"])

    def test_service_rejects_off_issuer_links_and_bounds_detail_requests(self):
        from src.intelligence import news_original_sources as original
        self.assertFalse(original.service_items(self.service(LinkToDetailPage="https://example.com/news-details/fake"), self.source("PLTR")))
        rows = [dict(Headline="Palantir signs a new AI defense contract", PressReleaseDate="10/25/2026 12:00:00",
                     LinkToDetailPage=f"/news-details/2026/release-{index}") for index in range(50)]
        calls = []
        def fetch(url):
            calls.append(url)
            return self.payload(json.dumps({"GetPressReleaseListResult": rows}) if "GetPressReleaseList?" in url else self.metadata(), url=url)
        payload = original.retrieve(self.source("PLTR"), fetch, NOW)
        self.assertEqual(len(payload["articles"]), 30)
        self.assertEqual(len(calls), 4)

    def test_new_year_service_requests_cover_the_previous_year(self):
        from src.intelligence import news_original_sources as original
        calls = []
        def fetch(url):
            calls.append(url)
            return self.payload('{"GetPressReleaseListResult":[]}', url=url)
        original.retrieve(self.source("PLTR"), fetch, datetime(2027, 1, 1, 0, 30, tzinfo=timezone.utc))
        self.assertEqual(len(calls), 2)
        self.assertTrue(any("year=2026" in url for url in calls))
        self.assertTrue(any("year=2027" in url for url in calls))

    def test_release_index_fetches_only_matching_issuer_article_paths(self):
        from src.intelligence import news_original_sources as original
        source = self.source("TSM")
        body = '<a href="/english/news/123">TSMC reports monthly revenue</a><a href="/english">Home</a><a href="https://example.com/english/news/456">Copied release</a>'
        calls = []
        def fetch(url):
            calls.append(url)
            return self.payload(body if url == source["url"] else self.metadata(title="TSMC reports monthly revenue"), url=url)
        result = original.retrieve(source, fetch, NOW)
        self.assertEqual(len(result["articles"]), 1)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(url.startswith("https://pr.tsmc.com/") for url in calls))

    def test_available_empty_feed_is_distinct_from_a_failed_or_undated_source(self):
        source = self.source("MSFT")
        empty = editor.feeds.describe_source(source, self.payload('<rss><channel/></rss>'), NOW)
        failed = editor.feeds.describe_source(source, self.payload(status="error", error="HTTPError 403"), NOW)
        missing = editor.feeds.describe_source(source, self.payload(self.rss("Microsoft introduces a platform", "https://blogs.microsoft.com/release").replace('<pubDate>','<unused>').replace('</pubDate>','</unused>')), NOW)
        self.assertEqual((empty["status"], empty["fresh"]), ("available", 0))
        self.assertEqual(failed["status"], "limited")
        self.assertIn("403", failed["reason"])
        self.assertEqual((missing["status"], missing["undated"]), ("limited", 1))

    def test_old_dated_reports_are_quiet_without_becoming_fresh(self):
        source = self.source("MSFT")
        body = self.rss("Microsoft introduces a platform", "https://blogs.microsoft.com/release", (NOW - timedelta(days=2)).isoformat())
        row = editor.feeds.describe_source(source, self.payload(body), NOW)
        self.assertEqual((row["status"], row["dated"], row["fresh"]), ("available", 1, 0))

    def test_source_health_rejects_stale_future_and_nonfinite_observation_clocks(self):
        for stamp in (NOW.timestamp() - 7 * 3600, NOW.timestamp() + 3600, float("nan"), True):
            row = editor.feeds.describe_source(self.source("MSFT"), self.payload('<rss><channel/></rss>', fetched_at_epoch=stamp), NOW)
            self.assertEqual(row["status"], "limited")
            self.assertEqual(row["checked_at"], "")

    def test_http_403_is_cached_with_backoff_even_for_forced_refresh(self):
        feeds = editor.feeds
        url = self.source("TSLA")["url"]
        error = HTTPError(url, 403, "Forbidden", {}, None)
        with patch.object(feeds, "CACHE_FILE", self.root / "fetch.json"), patch.object(feeds.time, "time", return_value=NOW.timestamp()), patch.object(feeds, "urlopen", side_effect=error) as request:
            first = feeds.fetch_url(url)
            second = feeds.fetch_url(url, force_refresh=True)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(first["body"], "")
            self.assertTrue(second["cache_hit"])
            self.assertGreater(first["retry_after_epoch"], NOW.timestamp())
            with patch.object(feeds.time, "time", return_value=NOW.timestamp() + 4000):
                feeds.fetch_url(url)
            self.assertEqual(request.call_count, 2)

    def test_concurrent_source_cache_updates_do_not_lose_other_publishers(self):
        feeds = editor.feeds
        with patch.object(feeds, "CACHE_FILE", self.root / "fetch.json"):
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(lambda number: feeds.set_cached_source("source-" + str(number), self.payload()), range(30)))
            self.assertEqual(len(feeds.load_cache()), 30)

    def test_oversized_response_cannot_supply_a_partial_publisher_feed(self):
        feeds = editor.feeds
        url = self.source("MSFT")["url"]
        response = SimpleNamespace(read=lambda limit: b"x" * limit, geturl=lambda: url)
        with patch.object(feeds, "CACHE_FILE", self.root / "fetch.json"), patch.object(feeds, "urlopen", return_value=nullcontext(response)):
            payload = feeds.fetch_url(url)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["body"], "")

    def test_long_retry_after_is_bounded_and_does_not_disable_backoff(self):
        feeds = editor.feeds
        url = self.source("MSFT")["url"]
        error = HTTPError(url, 429, "Slow down", {"Retry-After": "999999"}, None)
        with patch.object(feeds, "CACHE_FILE", self.root / "fetch.json"), patch.object(feeds.time, "time", return_value=NOW.timestamp()), patch.object(feeds, "urlopen", side_effect=error) as request:
            payload = feeds.fetch_url(url)
            feeds.fetch_url(url, force_refresh=True)
        self.assertEqual(payload["retry_after_epoch"] - payload["fetched_at_epoch"], 6 * 3600)
        self.assertEqual(request.call_count, 1)

    def test_empty_article_link_cannot_inherit_the_publishers_identity(self):
        from src.intelligence import news_original_sources as original
        self.assertFalse(original.authorized_response(self.source("MSFT"), {"url": ""}))
        self.assertFalse(original.authorized_response(self.source("MSFT"), {"url": "https://microsoft.com.example.com/fake"}))

    def test_legacy_news_context_does_not_treat_old_originals_as_fresh_signals(self):
        feeds = editor.feeds
        source = self.source("MSFT")
        old = self.rss("Microsoft introduces an old AI platform", "https://blogs.microsoft.com/old", (NOW - timedelta(days=2)).isoformat())
        fresh = self.rss("Microsoft introduces a new AI platform", "https://blogs.microsoft.com/new")
        body = old.replace('</channel></rss>', '') + fresh.split('<channel>', 1)[1]
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None): return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
        with patch.object(feeds, "NEWS_SOURCES", [source]), patch.object(feeds, "datetime", Clock), patch.object(feeds, "fetch_source", return_value=self.payload(body)):
            context = feeds.fetch_news_live_context()
        self.assertEqual(len(context["items"]), 1)
        self.assertIn("new AI platform", context["items"][0]["title"])

    def test_fresh_originals_are_scanned_before_a_large_old_publication_backlog(self):
        values = [candidate(url=f"https://www.microsoft.com/old-{index}", published=(NOW - timedelta(days=2)).isoformat()) for index in range(190)]
        values.append(candidate("PLTR", title="Palantir signs an AI defense contract"))
        plan = editor.build_editorial_plan(companies.build_company_catalyst_brief(), NOW, values)
        self.assertEqual(len(plan["candidates"]), 180)
        self.assertEqual(editor.selected_stories(plan)[0]["publisher_symbol"], "PLTR")
        self.assertEqual(plan["truncated_candidates"], 11)

    def test_source_health_and_filtered_history_are_recorded_without_network_or_cache_writes(self):
        source = self.source("MSFT")
        path = Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"])
        path.write_text(json.dumps({source["url"]: self.payload(self.rss("Microsoft introduces a new enterprise AI platform", "https://blogs.microsoft.com/release"))}))
        before = path.read_bytes()
        text = build_daily_news_brief(self.research())
        record = store.read_editions(report=text)[0]
        self.assertTrue(record["source_health"])
        with patch.object(editor.feeds, "fetch_source") as request:
            status = editor.build_editor_status()
            history = editor.build_editor_status("NVDA", True)
        request.assert_not_called()
        self.assertIn("Original sources:", status)
        self.assertIn("MSFT: available | 1 fresh / 1 dated", status)
        self.assertIn("Missing cached fetch", history)
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_source_health_cannot_be_read_as_a_valid_edition_record(self):
        text = build_daily_news_brief(self.research())
        record = store.read_editions(report=text)[0]
        record.pop("id")
        self.assertTrue(record["source_health"])
        record["source_health"][0]["fresh"] = "unverified"
        store.save_edition(record, text + " altered")
        self.assertFalse(store.read_editions(report=text + " altered"))

    def test_publisher_redirect_mismatch_is_visible_and_cannot_supply_news(self):
        source = self.source("MSFT")
        path = Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"])
        path.write_text(json.dumps({source["url"]: self.payload(self.rss("Microsoft introduces an AI platform", "https://blogs.microsoft.com/release"), final_url="https://example.com/fake-feed")}))
        rows, issues = editor.cache_candidates(NOW, ["MSFT"])
        self.assertFalse(rows)
        self.assertTrue(any("Publisher redirect mismatch" in issue for issue in issues))

    def test_daily_agent_refresh_includes_actual_source_coverage(self):
        from src.jobs import daily_agent_job as job
        row = editor.feeds.describe_source(self.source("MSFT"), self.payload('<rss><channel/></rss>'), NOW)
        with patch.object(job, "call_first_available", return_value="News report"), patch.object(editor.feeds, "cached_original_coverage", return_value=[row]):
            result = job.refresh_news_intelligence()
        self.assertIn("1/1 available", result)
        self.assertIn("0 fresh dated reports", result)


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
