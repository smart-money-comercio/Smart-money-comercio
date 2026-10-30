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
        self.assertIn("Lockheed Martin's October 25 announcement", text)
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
        self.assertIn("Federal Reserve's October 25 announcement", text)
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
        self.assertIn("Microsoft's October 25 announcement", text)
        selected = editor.selected_stories(store.read_editions(report=text)[0])[0]
        self.assertEqual(selected["source"], "microsoft.com")
        self.assertEqual(selected["published"], (NOW-timedelta(minutes=15)).isoformat())
        self.assertNotIn("Research focus:", text)
        self.assertIn("Research focus:", editor.build_editor_status(history=True))
        self.assertNotIn("caused stocks to fall", text)

    def test_macro_headline_stays_a_headline_and_does_not_explain_market_cause(self):
        text = self.render([candidate(kind="macro", symbols=[], title="Oil inventories report released", source="EIA", url="https://www.eia.gov/report")])
        self.assertIn("EIA's October 25 announcement", text)
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
        self.assertIn("October 25", text)
        self.assertIn("“" + value["title"] + "”", text)
        story = editor.selected_stories(store.read_editions(report=text)[0])[0]
        self.assertEqual(story["published"], value["published"])
        self.assertEqual(story["source"], "microsoft.com")
        self.assertNotIn("Research focus:", text)

    def test_length_cut_removes_the_dropped_storys_followup_from_narration(self):
        from src.reports import daily_news_brief as news
        value = candidate(title="Microsoft introduces a cloud platform for China " * 15, source="Microsoft original publisher " * 3)
        budget = 2300
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
        self.assertIn("Apple's October 25 announcement", text)
        self.assertNotIn("AAPL's October 25 announcement", text)
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

    def test_original_task_order_awards_are_material_without_an_hourly_review(self):
        titles = (
            "CACI Awarded $185 Million U.S. Army Task Order to Advance Expeditionary Power and Mission Readiness",
            "CACI Secures U.S. Navy Task Order to Strengthen Electromagnetic Spectrum Dominance",
            "CACI wins a five-year task order for expeditionary power",
            "CACI receives two Army task orders for mission support",
        )
        with patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "CACI,MSFT,NVDA,TSLA"}):
            for title in titles:
                with self.subTest(title=title):
                    plan = self.plan([candidate("CACI", title=title)])
                    selected = editor.selected_stories(plan)
                    self.assertEqual(len(selected), 1)
                    self.assertEqual(selected[0]["materiality"], "contract")
                    self.assertEqual(selected[0]["story_type"], "announcement")
                    self.assertNotIn("research_review", selected[0])
                    self.assertEqual(selected[0]["event_evidence"]["event"], "contract")

    def test_task_order_forecasts_guides_and_opinions_do_not_become_awards(self):
        titles = ("CACI could be awarded a U.S. Army task order",
                  "CACI expects to receive a U.S. Army task order",
                  "CACI has not been awarded the Army task order",
                  "CACI receives no new Army task orders",
                  "CACI failed to secure an Army task order",
                  "CACI guide to task order management",
                  "How CACI wins task orders",
                  "Will CACI win a U.S. Army task order?")
        with patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "CACI,MSFT,NVDA,TSLA"}):
            for title in titles:
                with self.subTest(title=title):
                    self.assertFalse(editor.selected_stories(self.plan([candidate("CACI", title=title)])))

    def test_task_order_awards_still_need_original_sources_and_current_clocks(self):
        title = "CACI Awarded $185 Million U.S. Army Task Order"
        values = [candidate("CACI", title=title, official=False, url="https://finance.yahoo.com/example"),
                  candidate("CACI", title=title, published=(NOW-timedelta(hours=25)).isoformat()),
                  candidate("CACI", title=title, source_checked_at=(NOW-timedelta(hours=7)).isoformat())]
        with patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "CACI,MSFT,NVDA,TSLA"}):
            plan = self.plan(values)
        self.assertFalse(editor.selected_stories(plan))
        self.assertEqual(dict(editor.hold_reasons(plan["candidates"])),
                         {"Original-source confirmation needed": 1, "Publication older than 24 hours": 1,
                          "Source observation stale or invalid": 1})

    def test_fresh_caci_feed_award_enters_the_brief_after_hourly_evidence_expires(self):
        title = "CACI Awarded $185 Million U.S. Army Task Order to Advance Expeditionary Power and Mission Readiness"
        url = "https://investor.caci.com/2026-10-29-CACI-Awarded-185-Million-U-S-Army-Task-Order-to-Advance-Expeditionary-Power-and-Mission-Readiness"
        quote = "CACI announced it has been awarded a five-year task order valued at up to $185 million to support the U.S. Army's expeditionary power and mission readiness."
        source = next(row for row in editor.feeds.NEWS_SOURCES if row.get("company_symbol") == "CACI")
        body = ("<rss><channel><item><title>"+escape(title)+"</title><link>"+escape(url)+"</link><pubDate>"
                +escape(format_datetime(NOW-timedelta(hours=13)))+"</pubDate><description>"+escape(quote)+"</description></item></channel></rss>")
        path = Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"])
        path.write_text(json.dumps({source["url"]: {"status": "ok", "fetched_at_epoch": NOW.timestamp(), "body": body}}))
        cache_before = path.read_bytes(); rankings_before = self.ranking.read_bytes()
        from src.intelligence import hourly_research
        with patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "CACI,MSFT,NVDA,TSLA"}), patch.object(hourly_research, "approved", return_value=[]), patch.object(editor.feeds, "fetch_source", side_effect=AssertionError("Rendering must not fetch")):
            text = build_daily_news_brief(self.research())
        record = store.read_editions(report=text)[0]
        selected = editor.selected_stories(record)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["confirmed_by"], "CACI")
        self.assertEqual(selected[0]["materiality"], "contract")
        self.assertIn("material contract development", selected[0]["reason"])
        self.assertEqual(selected[0]["event_evidence"]["facts"][0]["field"], "contract_ceiling")
        self.assertIn("up to $185 million", text)
        self.assertIn("does not establish funded orders or booked revenue", text)
        self.assertEqual(path.read_bytes(), cache_before)
        self.assertEqual(self.ranking.read_bytes(), rankings_before)

    def test_task_order_fix_does_not_rewrite_an_earlier_skipped_edition(self):
        value = candidate("CACI", title="CACI Awarded $185 Million U.S. Army Task Order")
        with patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "CACI,MSFT,NVDA,TSLA"}):
            with patch.object(editor, "materiality", return_value=""):
                old_text = self.render([value])
            original = deepcopy(store.read_editions(report=old_text)[0])
            self.assertFalse(editor.selected_stories(original))
            new_text = self.render([value])
        self.assertEqual(editor.selected_stories(store.read_editions(report=new_text)[0])[0]["materiality"], "contract")
        self.assertEqual(store.read_editions(report=old_text)[0], original)

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
        self.assertIn("Microsoft's October 25 announcement", text)
        self.assertNotIn("Nvidia's October 25 announcement", text)

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
        self.assertLessEqual(len(editor.feeds.NEWS_SOURCES), 25)

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
        with patch.object(feeds, "NEWS_SOURCES", [source]), patch.object(feeds, "datetime", Clock), patch.object(feeds, "fetch_source", return_value=self.payload(body)), patch.object(feeds.originals, "enrich_feed", side_effect=lambda source, payload, *args: payload):
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


class PublicationCoverageChecks(IsolatedChecks):
    source = OriginalSourceChecks.source
    payload = OriginalSourceChecks.payload
    service = OriginalSourceChecks.service
    metadata = OriginalSourceChecks.metadata
    TITLE = "Treasury announces new AI export sanctions"
    URL = "https://home.treasury.gov/news/press-releases/sb0999/"
    TEXT = "Treasury announced new restrictions on designated entities. The release explains the covered transactions and the effective date of the measures."
    WIRE = "https://www.businesswire.com/news/home/20261025000001/en/"

    def treasury(self):
        return next(row for row in editor.feeds.NEWS_SOURCES if row["name"] == "U.S. Treasury")

    def listing(self, title=None, url=None, clock=None):
        return ('<div><span class="date-format"><time datetime="' + (clock or (NOW-timedelta(hours=1)).isoformat()) +
                '">Publisher date</time></span><h3 class="featured-stories__headline"><a href="' + (url or self.URL) + '">' +
                escape(title or self.TITLE) + '</a></h3></div>')

    def release(self, title=None, clock=None, text=None):
        return ('<meta property="og:title" content="' + escape(title or self.TITLE) + '">' +
                '<article><p>Navigation article must not enter the evidence.</p></article>' +
                '<div class="field--name-field-news-publication-date"><time datetime="' +
                (clock or (NOW-timedelta(hours=1)).isoformat()) + '">Publisher date</time></div>' +
                '<div class="field--name-field-news-body"><p>' + escape(text or self.TEXT) + '</p></div>')

    def retrieve_treasury(self, index=None, body=None, final=None):
        from src.intelligence.news_original_sources import retrieve
        source, calls = self.treasury(), []
        def fetch(url):
            calls.append(url)
            return self.payload((index if index is not None else self.listing()) if url == source["url"] else
                                (body if body is not None else self.release()), url=url,
                                final_url=final if final and url != source["url"] else url)
        return retrieve(source, fetch, NOW), calls

    def palantir(self, body=None, metadata=None, final=None):
        from src.intelligence.news_original_sources import retrieve
        source, calls = self.source("PLTR"), []
        if body is None:
            body = '<p>Palantir announced a funded defense contract. The company described deployment requirements and the commercial timing of the project.</p><a href="https://cts.businesswire.com/ct/CT?newsitemid=20261025000001&amp;url=x">Source</a>'
        def fetch(url):
            calls.append(url)
            content = self.service(Body=body) if "GetPressReleaseList?" in url else (metadata if metadata is not None else self.metadata())
            return self.payload(content, url=url, final_url=final if final and url == self.WIRE else url)
        return retrieve(source, fetch, NOW), calls

    def test_treasury_row_clock_cannot_be_borrowed_from_navigation_or_the_next_row(self):
        from src.intelligence.publisher_publication import treasury_items
        body = '<time datetime="2026-10-25T12:00:00Z"></time>' + self.listing() + self.listing("Treasury second release", clock="not-a-time")
        rows = treasury_items(body)
        self.assertEqual(rows[0]["published"], "")  # Conflicting duplicate URL remains unverified.
        rows = treasury_items(body.replace(self.URL + '">Treasury second', self.URL.replace("0999", "0998") + '">Treasury second'))
        self.assertEqual(editor.dated(rows[0]["published"]), NOW-timedelta(hours=1))
        self.assertEqual(rows[1]["published"], "")

    def test_treasury_naive_date_only_and_off_authority_rows_are_never_admitted(self):
        from src.intelligence.publisher_publication import treasury_items
        for clock in ("2026-10-25", "2026-10-25T12:00:00"):
            self.assertEqual(treasury_items(self.listing(clock=clock))[0]["published"], "")
        for url in ("https://home.treasury.gov.attacker.test/news/press-releases/sb0999/", "http://home.treasury.gov/news/press-releases/sb0999/", "https://home.treasury.gov/news/press-releases"):
            self.assertEqual(treasury_items(self.listing(url=url)), [])

    def test_treasury_index_and_body_match_without_reading_unrelated_articles(self):
        from src.intelligence.news_original_sources import cached_items
        payload, calls = self.retrieve_treasury()
        row = cached_items(payload, self.treasury())[0]
        self.assertEqual(calls, [self.treasury()["url"], self.URL])
        self.assertEqual(row["description"], self.TEXT)
        self.assertEqual(row["evidence_scope"], "original release excerpt")
        self.assertEqual(row["publication_url"], self.URL)
        self.assertEqual(editor.feeds.describe_source(self.treasury(), payload, NOW)["fresh"], 1)

    def test_treasury_page_mismatch_or_missing_body_withholds_the_report(self):
        for body in (self.release(title="Different release"), self.release(clock=(NOW-timedelta(hours=2)).isoformat()),
                     self.release().replace('field--name-field-news-body', 'site-description'), self.release(clock="2026-10-25")):
            payload, _ = self.retrieve_treasury(body=body)
            self.assertEqual(payload["articles"][0]["published"], "")
            self.assertTrue(payload["publication_problems"])

    def test_treasury_conflicting_machine_metadata_is_not_overridden_by_the_index(self):
        body = self.release() + self.metadata(title=self.TITLE, published=(NOW-timedelta(hours=2)).isoformat())
        self.assertEqual(self.retrieve_treasury(body=body)[0]["articles"][0]["published"], "")

    def test_treasury_redirect_must_retain_the_same_release_identity(self):
        for final in (self.URL.replace("0999", "0998"), "https://attacker.test/copied-release"):
            payload, _ = self.retrieve_treasury(final=final)
            self.assertEqual(payload["articles"][0]["published"], "")

    def test_treasury_detail_reads_are_bounded_and_skip_old_or_future_releases(self):
        index = ''.join(self.listing(url=self.URL.replace("0999", str(1000+i))) for i in range(12))
        _, calls = self.retrieve_treasury(index=index)
        self.assertEqual(len(calls), 4)
        for clock in ((NOW-timedelta(days=2)).isoformat(), (NOW+timedelta(hours=1)).isoformat()):
            _, calls = self.retrieve_treasury(index=self.listing(clock=clock))
            self.assertEqual(len(calls), 1)

    def test_treasury_success_survives_another_malformed_release(self):
        index = self.listing(clock="missing") + self.listing(url=self.URL.replace("0999", "0998"))
        payload, calls = self.retrieve_treasury(index=index)
        self.assertEqual(len(calls), 2)
        health = editor.feeds.describe_source(self.treasury(), payload, NOW)
        self.assertEqual((health["fresh"], health["undated"]), (1, 1))

    def test_treasury_unread_headline_cannot_enter_the_news_brief(self):
        payload, _ = self.retrieve_treasury()
        payload["articles"][0].pop("publication_url")
        payload["articles"][0]["description"] = ""
        path = Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"])
        path.write_text(json.dumps({self.treasury()["url"]: payload}))
        text = build_daily_news_brief(self.research())
        record = store.read_editions(report=text)[0]
        story = next(row for row in record["candidates"] if row["title"] == self.TITLE)
        self.assertEqual(story["decision"], "wait")
        self.assertIn("release body must match", story["reason"])

    def test_treasury_verified_report_and_clock_source_reach_the_cache_only_brief(self):
        payload, _ = self.retrieve_treasury()
        path = Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"])
        path.write_text(json.dumps({self.treasury()["url"]: payload})); before = path.read_bytes()
        with patch.object(editor.feeds, "fetch_source", side_effect=AssertionError("Rendering must not fetch")):
            text = build_daily_news_brief(self.research())
        story = next(row for row in store.read_editions(report=text)[0]["candidates"] if row["title"] == self.TITLE)
        self.assertEqual(story["decision"], "selected")
        self.assertEqual(story["publication_url"], self.URL)
        self.assertIn("Publication clock source: " + self.URL, editor.build_editor_status(history=True))
        self.assertEqual(path.read_bytes(), before)

    def test_palantir_uses_only_the_exact_issuer_linked_wire_title_and_zoned_clock(self):
        from src.intelligence.news_original_sources import cached_items
        payload, calls = self.palantir()
        row = cached_items(payload, self.source("PLTR"))[0]
        self.assertEqual(calls[1:], [self.WIRE])
        self.assertEqual(editor.dated(row["published"]), NOW-timedelta(hours=1))
        self.assertEqual(row["publication_url"], self.WIRE)
        self.assertIn("funded defense contract", row["description"])

    def test_palantir_wire_wrong_title_and_naive_clocks_remain_held(self):
        for metadata in (self.metadata(title="Different report"), self.metadata(published="2026-10-25T12:00:00")):
            payload, _ = self.palantir(metadata=metadata)
            self.assertIsNone(editor.timestamp_for_priority(payload["articles"][0]["published"]))
            self.assertTrue(payload["publication_problems"])

    def test_verified_old_or_future_wire_clocks_are_retained_but_never_become_fresh_news(self):
        for clock in ((NOW-timedelta(days=2)).isoformat(), (NOW+timedelta(hours=1)).isoformat()):
            payload, _ = self.palantir(metadata=self.metadata(published=clock))
            self.assertEqual(editor.dated(payload["articles"][0]["published"]), editor.dated(clock))
            path = Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"])
            path.write_text(json.dumps({self.source("PLTR")["url"]: payload}))
            text = build_daily_news_brief(self.research())
            story = next(row for row in store.read_editions(report=text)[0]["candidates"] if "Palantir signs" in row["title"])
            self.assertEqual(story["decision"], "wait")
            self.assertTrue("older than 24 hours" in story["reason"] or "future-dated" in story["reason"])

    def test_palantir_wire_redirect_cannot_switch_release_or_publisher(self):
        for final in (self.WIRE.replace("000001", "000002"), "https://businesswire.com.attacker.test/news/home/20261025000001/en/",
                      "https://www.businesswire.com:444/news/home/20261025000001/en/"):
            payload, _ = self.palantir(final=final)
            self.assertTrue(payload["publication_problems"])
            self.assertIsNone(editor.timestamp_for_priority(payload["articles"][0]["published"]))

    def test_palantir_conflicting_wire_links_do_not_trigger_any_wire_request(self):
        body = '<a href="https://cts.businesswire.com/ct/CT?newsitemid=20261025000001">one</a><a href="https://cts.businesswire.com/ct/CT?newsitemid=20261025000002">two</a>'
        payload, calls = self.palantir(body=body)
        self.assertEqual(len(calls), 1)
        self.assertTrue(payload["publication_problems"])

    def test_wire_identity_is_never_extracted_from_plain_text_or_lookalike_links(self):
        from src.intelligence.publisher_publication import linked_wire
        for body in ('newsitemid=20261025000001', '<a href="https://cts.businesswire.com.attacker.test/ct/CT?newsitemid=20261025000001">x</a>',
                     '<a href="http://cts.businesswire.com/ct/CT?newsitemid=20261025000001">x</a>'):
            self.assertEqual(linked_wire(body), "")

    def test_wire_does_not_become_a_general_company_authority(self):
        from src.intelligence.special_alert_sources import company_url
        self.assertFalse(company_url("PLTR", self.WIRE))
        self.assertFalse(editor.feeds.originals.authorized_response(self.source("PLTR"), {"url": self.WIRE}))

    def test_palantir_clock_provenance_is_recorded_separately_from_the_issuer_report(self):
        payload, _ = self.palantir()
        path = Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"])
        path.write_text(json.dumps({self.source("PLTR")["url"]: payload}))
        text = build_daily_news_brief(self.research())
        story = next(row for row in store.read_editions(report=text)[0]["candidates"] if "Palantir signs" in row["title"])
        self.assertEqual(story["decision"], "selected")
        self.assertEqual(story["publication_url"], self.WIRE)
        self.assertTrue(story["url"].startswith("https://investors.palantir.com/"))

    def test_old_structured_reader_cache_is_refreshed_without_changing_existing_bytes(self):
        source = self.source("PLTR")
        cached = self.payload(original_profile=1, articles=[])
        with patch.object(editor.feeds, "get_cached_source", return_value=cached), patch.object(editor.feeds.originals, "retrieve", return_value={**cached, "original_profile": 2}) as retrieve, patch.object(editor.feeds, "set_cached_source"):
            value = editor.feeds.fetch_source(source)
        retrieve.assert_called_once()
        self.assertEqual(value["original_profile"], 2)
        self.assertEqual(cached["original_profile"], 1)

    def test_apple_update_only_feed_explains_its_publication_limit(self):
        source = self.source("AAPL")
        body = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Apple introduces a product</title><link href="https://www.apple.com/newsroom/example/"/><updated>' + NOW.isoformat() + '</updated></entry></feed>'
        health = editor.feeds.describe_source(source, self.payload(body), NOW)
        self.assertEqual((health["fresh"], health["dated"], health["undated"]), (0, 0, 1))
        self.assertIn("update timestamps do not establish original publication", health["reason"])


class IssuerCoverageChecks(IsolatedChecks):
    payload = OriginalSourceChecks.payload
    rss = OriginalSourceChecks.rss
    TEXT = "The company announced a funded defense contract and described the deployment requirements. Delivery timing and production costs remain subject to the disclosed milestones."
    TITLE = "Kratos announces a funded defense contract"
    URL = "https://www.kratosdefense.com/newsroom/fixture-contract"

    def source(self, symbol):
        return next(row for row in editor.feeds.NEWS_SOURCES if row.get("company_symbol") == symbol and row["name"] in {
            "Broadcom Financial News", "AeroVironment Newsroom", "Kratos Newsroom"})

    def page(self, *, title=None, url=None, clock=None, metadata=None, heading=None, brand=None):
        title, url = title or self.TITLE, url or self.URL
        values = {"@type": "WebPage", "@id": url, "url": url, "name": title + " | Kratos Defense",
                  "datePublished": clock or (NOW-timedelta(hours=1)).isoformat()}
        values.update(metadata or {})
        return ('<meta property="og:title" content="' + escape(brand or title + " | Kratos Defense") + '">' +
                '<h1>' + escape(heading or title) + '</h1><script type="application/ld+json">' + json.dumps(values) + '</script>' +
                '<article><p>Unrelated article must not enter this release.</p></article>' +
                '<section class="wysiwyg-section space-lg-m"><p>' + self.TEXT + '</p></section>')

    def retrieve(self, *, page=None, final=None):
        source = self.source("KTOS"); calls = []
        index = '<a title="' + escape(self.TITLE) + '" href="' + self.URL + '"><span>October 25, 2026</span>' + escape(self.TITLE) + '<p>Index summary</p></a>'
        def fetch(url):
            calls.append(url)
            return self.payload(index if url == source["url"] else page if page is not None else self.page(), url=url,
                                final_url=final if final and url != source["url"] else url)
        return editor.feeds.originals.retrieve(source, fetch, NOW), calls

    def test_alternate_routes_preserve_the_blocked_feed_evidence_and_issuer_authorities(self):
        for symbol in ("AVGO", "AVAV", "KTOS"):
            rows = [row for row in editor.feeds.NEWS_SOURCES if row.get("company_symbol") == symbol]
            self.assertEqual(len(rows), 2)
            self.assertTrue(any(row["url"].endswith("/rss/news-releases.xml") for row in rows))
            source = self.source(symbol)
            self.assertTrue(editor.feeds.originals.authorized_response(source, {"url": source["url"]}))
            self.assertFalse(editor.feeds.originals.authorized_response(source, {"url": "https://example.com/copied-release"}))

    def test_kratos_index_retains_the_complete_title_without_date_or_summary_contamination(self):
        payload, calls = self.retrieve()
        row = editor.feeds.originals.cached_items(payload, self.source("KTOS"))[0]
        self.assertEqual(row["title"], self.TITLE)
        self.assertEqual(row["description"], self.TEXT)
        self.assertEqual(row["evidence_scope"], "original release excerpt")
        self.assertEqual(len(calls), 2)

    def test_kratos_webpage_date_requires_its_exact_url_heading_and_publisher_title(self):
        from src.intelligence.special_alert_company_sources import publication_time
        self.assertEqual(publication_time(self.page().encode(), self.TITLE, url=self.URL), NOW-timedelta(hours=1))
        for body in (self.page(metadata={"@id": self.URL + "-other"}), self.page(metadata={"url": self.URL + "-other"}),
                     self.page(heading="Different release"), self.page(brand="Different publisher")):
            with self.assertRaises(ValueError): publication_time(body.encode(), self.TITLE, url=self.URL)

    def test_unrelated_webpage_dates_and_new_modification_times_do_not_admit_a_release(self):
        from src.intelligence.special_alert_company_sources import publication_time
        for body in (self.page(clock="2026-10-25"), self.page(clock="2026-10-25T12:00:00"),
                     self.page(metadata={"datePublished": None, "dateModified": NOW.isoformat()})):
            with self.assertRaises(ValueError): publication_time(body.encode(), self.TITLE, url=self.URL)
        with self.assertRaises(ValueError): publication_time(self.page().encode(), self.TITLE)

    def test_kratos_publication_metadata_conflicts_cannot_be_overridden(self):
        from src.intelligence.special_alert_company_sources import publication_time
        body = self.page() + '<meta property="article:published_time" content="' + (NOW-timedelta(hours=2)).isoformat() + '">'
        with self.assertRaises(ValueError): publication_time(body.encode(), self.TITLE, url=self.URL)
        body = self.page() + self.page(clock=(NOW-timedelta(hours=2)).isoformat())
        with self.assertRaises(ValueError): publication_time(body.encode(), self.TITLE, url=self.URL)

    def test_kratos_webpage_with_an_incidental_headline_still_requires_matching_canonical_identity(self):
        from src.intelligence.special_alert_company_sources import publication_time
        body = self.page(metadata={"@id": self.URL + "-other", "url": self.URL + "-other", "headline": self.TITLE})
        with self.assertRaises(ValueError): publication_time(body.encode(), self.TITLE, url=self.URL)
        for url in ("https://www.kratosdefense.com.attacker.test/newsroom/fixture-contract", "http://www.kratosdefense.com/newsroom/fixture-contract"):
            with self.assertRaises(ValueError): publication_time(self.page().encode(), self.TITLE, url=url)

    def test_a_verified_clock_without_a_recognizable_release_body_stays_held(self):
        payload, _ = self.retrieve(page=self.page().replace("wysiwyg-section", "site-description"))
        self.assertTrue(payload["publication_problems"])
        self.assertEqual(editor.dated(payload["articles"][0]["published"]), NOW-timedelta(hours=1))
        self.assertEqual(editor.feeds.originals.cached_items(payload, self.source("KTOS"))[0]["description"], "")
        path = Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"]); path.write_text(json.dumps({self.source("KTOS")["url"]: payload}))
        with patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "KTOS"}): text = build_daily_news_brief(self.research())
        story = next(row for row in store.read_editions(report=text)[0]["candidates"] if row["title"] == self.TITLE)
        self.assertEqual(story["decision"], "wait")
        self.assertIn("release body must match", story["reason"])

    def test_cross_issuer_release_redirect_is_withheld(self):
        payload, _ = self.retrieve(final="https://www.broadcom.com/copied-kratos-release")
        self.assertTrue(payload["publication_problems"])
        self.assertFalse(payload["articles"][0]["published"])

    def test_broadcom_financial_index_requires_the_complete_release_metadata_and_body(self):
        source = self.source("AVGO"); title = "Broadcom announces AI networking deployment"
        url = "https://investors.broadcom.com/news-releases/news-release-details/fixture-network"
        page = '<script type="application/ld+json">' + json.dumps({"@type": "NewsArticle", "headline": title,
            "datePublished": (NOW-timedelta(hours=1)).isoformat()}) + '</script><article><p>' + self.TEXT + '</p></article>'
        def fetch(target):
            return self.payload('<a href="' + url + '">' + title + '</a>' if target == source["url"] else page, url=target)
        value = editor.feeds.originals.retrieve(source, fetch, NOW)
        row = editor.feeds.originals.cached_items(value, source)[0]
        self.assertEqual(row["description"], self.TEXT)
        self.assertEqual(editor.dated(row["published"]), NOW-timedelta(hours=1))
        self.assertTrue(row["requires_original_body"])

    def test_aerovironment_corporate_feed_keeps_full_original_text_and_zoned_clock(self):
        source = self.source("AVAV"); title = "AV announces a new counter-drone contract"
        url = "https://www.avinc.com/2026/10/25/fixture-contract/"
        body = self.rss(title, url).replace('</item>', '<description>' + self.TEXT + '</description></item>')
        row = editor.feeds.parse_article_items(self.payload(body), source, full_titles=True, full_text=True)[0]
        self.assertEqual(row["description"], self.TEXT)
        self.assertEqual(editor.dated(row["published"]), NOW-timedelta(minutes=20))
        self.assertEqual(row["link"], url)

    def test_old_alternate_reports_remain_quiet_even_with_a_new_cache_fetch(self):
        payload, _ = self.retrieve(page=self.page(clock=(NOW-timedelta(days=3)).isoformat()))
        health = editor.feeds.describe_source(self.source("KTOS"), payload, NOW)
        self.assertEqual((health["dated"], health["fresh"]), (1, 0))
        self.assertEqual(health["latest_publication"], (NOW-timedelta(days=3)).isoformat())

    def test_blocked_ir_and_healthy_corporate_source_are_both_visible_in_the_same_edition(self):
        payload, _ = self.retrieve(); source = self.source("KTOS")
        old = next(row for row in editor.feeds.NEWS_SOURCES if row["name"] == "Kratos Investor Relations")
        path = Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"])
        path.write_text(json.dumps({source["url"]: payload, old["url"]: self.payload(status="error", error="HTTPError 403")})); before = path.read_bytes()
        with patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "KTOS"}), patch.object(editor.feeds, "fetch_source", side_effect=AssertionError("Rendering must not fetch")):
            text = build_daily_news_brief(self.research())
        record = store.read_editions(report=text)[0]
        story = next(row for row in record["candidates"] if row["title"] == self.TITLE)
        self.assertEqual(story["decision"], "selected")
        health = {row["name"]: row for row in record["source_health"]}
        self.assertEqual(health[source["name"]]["status"], "available")
        self.assertIn("403", health[old["name"]]["reason"])
        self.assertEqual(path.read_bytes(), before)


class StoryAnalysisChecks(IsolatedChecks):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "MSFT,NVDA,PLTR,LMT,AVAV,KTOS"}))

    def story(self, title="Example Defense completes an undersea acquisition", text="", symbol="LMT"):
        return candidate(symbol, title=title, source_excerpt=text, excerpt_scope="publisher feed excerpt")

    def render(self, values):
        with patch.object(editor, "cache_candidates", return_value=(values, [])):
            return build_daily_news_brief(self.research())

    def profile(self, title, text=""):
        from src.intelligence.story_analysis import build_evidence
        return build_evidence(self.story(title, text), text, "publisher feed excerpt")

    def test_defense_retargeting_test_gets_procurement_and_production_analysis(self):
        from src.intelligence.story_analysis import investor_read
        story=self.story("Lockheed Martin Redirects In-flight GMRLS Rocket During U.S. Army Test",
            "Lockheed Martin successfully redirected an in-flight GMLRS rocket during a test.")
        text=self.render([story])
        self.assertIn("in-flight retargeting",text);self.assertIn("procurement approvals",text)
        self.assertIn("funded orders and production costs will determine the business impact",text)
        self.assertNotIn("warrants reviewing its effect on the business",text)
        self.assertTrue("test milestone"==investor_read(story)["evidence"]["stage"])

    def test_planned_defense_test_does_not_claim_a_result(self):
        from src.intelligence.story_analysis import investor_read
        story=self.story("Example plans a hypersonic missile test", "The company will test a proposed capability.")
        review=investor_read(story)
        self.assertEqual(review["evidence"]["stage"],"planned test")
        self.assertIn("planned test",review["why"]);self.assertFalse(review["evidence"]["facts"])

    def test_failed_conditional_or_negated_test_passages_do_not_establish_a_demonstrated_capability(self):
        title="Example redirects a rocket during an Army test"
        for source in ("The company has not successfully redirected an in-flight rocket.",
            "If the company successfully redirected an in-flight rocket, a milestone would follow.",
            "The test failed although the company successfully redirected an in-flight rocket."):
            self.assertFalse(self.profile(title,source)["facts"])

    def test_ai_capacity_expansion_keeps_its_planned_status_and_execution_checks(self):
        from src.intelligence.story_analysis import build_evidence,investor_read
        story=self.story("Nvidia and Oracle expand AI cloud infrastructure to multi-gigawatt scale",
            "Nvidia and Oracle announced plans to expand AI cloud infrastructure to multi-gigawatt scale.",symbol="NVDA")
        story["event_evidence"]=build_evidence(story,story["source_excerpt"],"publisher feed excerpt")
        review=investor_read(story)
        self.assertEqual(review["evidence"]["event"],"capacity expansion")
        self.assertEqual(review["evidence"]["facts"][0]["field"],"planned_capacity_scale")
        self.assertIn("customer commitments",review["why"]);self.assertIn("power and supply",review["watch"])
        self.assertNotIn("booked revenue",review["facts"])

    def test_collaboration_is_distinct_from_an_awarded_contract(self):
        from src.intelligence.story_analysis import investor_read
        review=investor_read(self.story("Nvidia and Meta expand collaboration on AI models",symbol="NVDA"))
        self.assertEqual(review["evidence"]["event"],"technology collaboration")
        self.assertNotIn("An award",review["why"])

    def test_schema_two_test_and_expansion_profiles_remain_readable(self):
        from src.intelligence.story_analysis import build_evidence,checked_evidence
        for title in ("Example redirects a rocket during an Army test","Nvidia and Oracle expand AI infrastructure"):
            story=self.story(title)
            story["event_evidence"]=build_evidence(story,"An original report excerpt with no additional disclosed amounts.","publisher feed excerpt",schema=2)
            self.assertEqual(checked_evidence(story),story["event_evidence"])
            self.assertNotEqual(build_evidence(story)["event"],story["event_evidence"]["event"])

    def test_new_capability_facts_cannot_be_added_or_rewritten_in_a_saved_profile(self):
        from src.intelligence.story_analysis import build_evidence,checked_evidence
        story=self.story("Example redirects a rocket during an Army test")
        story["event_evidence"]=build_evidence(story,"The company successfully redirected an in-flight rocket.","original release excerpt")
        self.assertTrue(story["event_evidence"]["facts"])
        story["event_evidence"]["facts"][0]["value"]="a newly funded production order"
        with self.assertRaises(ValueError):checked_evidence(story)

    def article(self, title, text, clock=None, day="October 25, 2026"):
        metadata = (f'<meta property="og:title" content="{escape(title)}"><meta property="article:published_time" content="{clock}">') if clock else ""
        return (f'<html><head>{metadata}</head><nav>Unrelated purchase price $999 billion.</nav><h1>{escape(title)}</h1>'
                f'<div class="wd_news_body"><p>Publisher dateline, {day}.</p><p>{text}</p></div></html>')

    def test_completed_acquisition_gets_integration_analysis_and_source_facts(self):
        text = self.render([self.story(text="The acquisition expands capabilities in anti-submarine warfare.")])
        self.assertIn("After the reported close", text)
        self.assertIn("integration costs", text)
        self.assertIn("anti-submarine warfare", text)
        self.assertNotIn("Contract ceilings", text)
        self.assertNotIn("regulatory conditions", text)
        record = store.read_editions(report=text)[0]
        story = editor.selected_stories(record)[0]
        self.assertEqual(story["materiality"], "acquisition")
        self.assertEqual(story["event_evidence"]["stage"], "completed")
        self.assertEqual(story["event_evidence"]["facts"][0]["field"], "business_focus")

    def test_proposed_and_cancelled_acquisitions_have_different_next_checks(self):
        proposed = self.render([self.story("Example Defense agrees to acquire a maritime business")])
        self.assertIn("closing conditions", proposed)
        self.assertNotIn("After the reported close", proposed)
        cancelled = self.render([self.story("Example Defense terminates its acquisition agreement")])
        self.assertIn("cancelled transaction", cancelled)
        self.assertIn("termination costs", cancelled)

    def test_future_or_negated_completion_is_not_reported_as_closed(self):
        from src.intelligence.story_analysis import event_type
        for title in ("Example Defense expects to complete the acquisition", "Example Defense will close the acquisition", "Example Defense has not completed its acquisition", "Example acquisition is not completed"):
            self.assertNotEqual(event_type(title)[1], "completed", title)

    def test_guidance_after_an_acquisition_is_classified_by_the_actual_change(self):
        from src.intelligence.story_analysis import event_type
        self.assertEqual(event_type("Example cuts revenue guidance following its acquisition"), ("guidance", "lowered"))
        self.assertEqual(event_type("Example completes an acquisition and updates guidance"), ("acquisition", "completed"))

    def test_deal_amount_preserves_approximation_and_debt_qualification(self):
        evidence = self.profile("Example agrees to acquire a business", "The acquisition was valued at approximately $1.25 billion, including assumed debt.")
        fact = evidence["facts"][0]
        self.assertEqual(fact["value"], "approximately $1.25 billion, including assumed debt")
        self.assertIn(fact["value"].split(",")[0], fact["evidence"])

    def test_financing_plans_are_labelled_as_plans_and_missing_terms_stay_absent(self):
        evidence = self.profile("Example agrees to acquire a business", "The transaction will be financed with cash and debt.")
        self.assertEqual(evidence["facts"][0]["field"], "financing_plan")
        text = self.render([self.story()])
        self.assertNotIn("Stated deal amount", text)
        self.assertNotIn("Financing described", text)

    def test_denied_or_ambiguous_deal_values_are_not_promoted_to_facts(self):
        for text in ("The acquisition was not valued at $500 million.", "The transaction was valued at $3 billion to $5 billion.", "The hypothetical acquisition was valued at $5 billion.", "The transaction could be valued at $500 million.", "The acquisition might expand undersea warfare capabilities."):
            self.assertFalse(self.profile("Example agrees to acquire a business", text)["facts"], text)

    def test_contract_ceiling_is_distinct_from_the_obligated_amount(self):
        text = self.render([self.story("Example Defense wins a production contract", "The contract has a ceiling of $500 million. At award, $15 million is obligated.", "KTOS")])
        self.assertIn("Announced ceiling: ceiling of $500 million", text)
        self.assertIn("Amount described as obligated: $15 million", text)
        self.assertIn("does not establish funded orders or booked revenue", text)
        profile = editor.selected_stories(store.read_editions(report=text)[0])[0]["event_evidence"]
        self.assertEqual({row["field"] for row in profile["facts"]}, {"contract_ceiling", "obligated_amount"})

    def test_not_to_exceed_is_a_ceiling_and_market_opportunity_is_not(self):
        profile = self.profile("Example wins a contract", "The contract value is not to exceed $200 million.")
        self.assertEqual(profile["facts"][0]["field"], "contract_ceiling")
        profile = self.profile("Example signs an MOU", "The addressable market opportunity has a potential value of $200 million.")
        self.assertFalse(profile["facts"])

    def test_cooperation_agreement_does_not_become_a_funded_order(self):
        text = self.render([self.story("Example Defense signs an MOU for autonomous systems", symbol="AVAV")])
        self.assertIn("cooperation agreement", text)
        self.assertIn("funded orders still require evidence", text)

    def test_contract_loss_does_not_get_an_award_or_growth_interpretation(self):
        text = self.render([self.story("Example Defense loses a production contract", "The contract previously had a ceiling of $500 million.", "KTOS")])
        self.assertIn("reported contract loss", text)
        self.assertNotIn("An award can support future work", text)
        self.assertNotIn("Announced ceiling", text)

    def test_procurement_acquisition_word_does_not_invent_a_corporate_merger(self):
        from src.intelligence.story_analysis import event_type
        self.assertEqual(event_type("Example wins a Defense Acquisition Council contract")[0], "contract")

    def test_prototype_and_actual_production_have_different_execution_questions(self):
        prototype = self.render([self.story("Example unveils an autonomous prototype system", symbol="AVAV")])
        production = self.render([self.story("Example begins production of an autonomous system", symbol="AVAV")])
        self.assertIn("prototype alone does not establish orders or revenue", prototype)
        self.assertIn("manufacturing scale", production)

    def test_planned_production_is_not_actual_delivery(self):
        from src.intelligence.story_analysis import event_type, investor_read
        value = self.story("Example announces plans for first deliveries of a system", symbol="AVAV")
        self.assertEqual(event_type(value["title"]), ("product", "planned"))
        self.assertIn("announced production plan", investor_read(value)["why"])

    def test_reported_revenue_keeps_its_period_and_excludes_future_guidance(self):
        value = self.profile("Example reports quarterly financial results", "Third-quarter revenue was approximately $8.4 billion. The company expects revenue of $9.0 billion next quarter.")
        self.assertEqual(len(value["facts"]), 1)
        self.assertEqual(value["facts"][0]["value"], "approximately $8.4 billion (Third-quarter)")
        self.assertFalse(self.profile("Example reports results", "Revenue was $8.4 billion.")["facts"])

    def test_reaffirmed_guidance_does_not_claim_the_outlook_changed(self):
        from src.intelligence.story_analysis import investor_read
        review = investor_read(self.story("Example reaffirms revenue guidance", symbol="MSFT"))
        self.assertIn("Reaffirmed guidance", review["why"])
        self.assertNotIn("changes the forward assumptions", review["why"])

    def test_raw_publication_excerpt_excludes_scripts_and_boilerplate(self):
        from src.intelligence.story_analysis import release_text
        text = release_text('<p>The acquisition expands undersea warfare capabilities.</p><script>The acquisition was valued at $99 billion.</script><h2>Forward-Looking Statements</h2><p>The acquisition was valued at $88 billion.</p>')
        self.assertNotIn("$99", text)
        self.assertNotIn("$88", text)

    def test_original_article_requires_matching_headline_and_publication_clock(self):
        from src.intelligence.news_original_sources import article_excerpt
        title = "Example completes an acquisition"
        published = (NOW - timedelta(minutes=20)).isoformat()
        body = self.article(title, 'The acquisition was valued at <b>$500 million</b>.', published)
        excerpt = article_excerpt(body, title, published)
        self.assertIn("valued at $500 million", excerpt)
        self.assertNotIn("$999", excerpt)
        with self.assertRaises(ValueError): article_excerpt(body, "Different headline", published)
        with self.assertRaises(ValueError): article_excerpt(body, title, NOW.isoformat())

    def test_date_only_page_can_use_its_matching_original_zoned_feed_clock(self):
        from src.intelligence.news_original_sources import article_excerpt
        title = "Example completes an acquisition"
        body = self.article(title, "The acquisition expands undersea warfare capabilities.")
        self.assertTrue(article_excerpt(body, title, format_datetime(NOW)))
        with self.assertRaises(ValueError): article_excerpt(body.replace("October 25", "October 24"), title, format_datetime(NOW))
        with self.assertRaises(ValueError): article_excerpt(body, title, "2026-10-25")

    def test_release_enrichment_is_bounded_and_keeps_the_feed_observation_time(self):
        from src.intelligence.news_original_sources import enrich_feed
        source = next(row for row in editor.feeds.NEWS_SOURCES if row.get("company_symbol") == "LMT")
        title = "Example completes an acquisition"
        url = "https://news.lockheedmartin.com/fixture"
        published = format_datetime(NOW - timedelta(minutes=20))
        rss = f'<rss><channel><item><title>{title}</title><link>{url}</link><pubDate>{published}</pubDate></item></channel></rss>'
        payload = {"status": "ok", "body": rss, "fetched_at_epoch": NOW.timestamp() - 100}
        calls = []
        def fetch(link):
            calls.append(link)
            return {"status": "ok", "url": link, "body": self.article(title, "The acquisition expands undersea warfare capabilities.", published), "fetched_at_epoch": NOW.timestamp()}
        enriched = enrich_feed(source, payload, editor.feeds.parse_rss_items, fetch, NOW)
        self.assertEqual(calls, [url])
        self.assertEqual(enriched["fetched_at_epoch"], payload["fetched_at_epoch"])
        self.assertEqual(enriched["release_evidence"][0]["published"], published)
        self.assertIs(enrich_feed(source, enriched, editor.feeds.parse_rss_items, fetch, NOW), enriched)

    def test_stale_or_unverified_feed_does_not_fetch_optional_article_details(self):
        from src.intelligence.news_original_sources import enrich_feed
        source = next(row for row in editor.feeds.NEWS_SOURCES if row.get("company_symbol") == "LMT")
        fetch = Mock()
        for payload in ({"status": "ok", "body": "", "fetched_at_epoch": NOW.timestamp() - 7 * 3600},
                        {"status": "ok", "body": "", "fetched_at_epoch": NOW.timestamp(), "final_url": "https://example.com/fake"}):
            self.assertIs(enrich_feed(source, payload, editor.feeds.parse_rss_items, fetch, NOW), payload)
        fetch.assert_not_called()

    def test_altered_fact_or_stage_cannot_pass_the_analyst_evidence_check(self):
        from src.intelligence.daily_brief_analysis import analyze_report
        plan = editor.build_editorial_plan(companies.build_company_catalyst_brief(), NOW, [self.story(text="The acquisition was valued at $500 million.")])
        story = editor.selected_stories(plan)[0]
        story["event_evidence"]["facts"][0]["value"] = "$999 billion"
        with self.assertRaisesRegex(ValueError, "do not match"):
            analyze_report(self.research(), [story])

    def test_dropped_story_cannot_leave_its_facts_or_interpretation_in_the_brief(self):
        from src.reports import daily_news_brief as news
        baseline = self.render([])
        story = self.story("Example announces an acquisition " + "with enterprise business details " * 20, "The acquisition was valued at $987 million.", "MSFT")
        with patch.object(editor, "cache_candidates", return_value=([story], [])), patch.object(news, "MAX_NEWS_CHARS", 2300):
            text = build_daily_news_brief(self.research())
        self.assertNotIn("$987", text)
        self.assertNotIn("The proposed acquisition", text)
        self.assertEqual(store.read_editions(report=text)[0]["analyst_review"]["evidence"]["stories"], [])

    def test_story_log_distinguishes_sourced_facts_from_agent_interpretation(self):
        text = self.render([self.story(text="The acquisition expands capabilities in anti-submarine warfare.")])
        status = editor.build_editor_status("LMT", True)
        self.assertIn("Stage: completed", status)
        self.assertIn("Evidence read: publisher feed excerpt", status)
        self.assertIn("Disclosed excerpt facts:", status)
        self.assertIn("Agent interpretation:", status)
        self.assertIn("Watch next:", status)
        self.assertTrue(store.read_editions(report=text))


class PolicyBriefChecks(IsolatedChecks):
    TITLE = "Federal Reserve issues FOMC statement"
    TARGET = "The Committee decided to maintain the target range for the federal funds rate at 3-3/4 to 4 percent."

    def source(self, **changes):
        return candidate(kind="macro", symbols=[], publisher_symbol="", source="Federal Reserve",
            title=self.TITLE, url="https://www.federalreserve.gov/newsevents/pressreleases/monetary20261025a.htm",
            published=NOW.replace(hour=16).isoformat(), source_excerpt=self.TARGET,
            excerpt_scope="original release excerpt", **changes)

    def body(self, wrapper='id="article"'):
        return (f'<html><head><meta property="og:title" content="{self.TITLE}"></head><body>'
                f'<nav>Navigation is not release evidence.</nav><div {wrapper}>'
                f'<p>October 25, 2026</p><h3>{self.TITLE}</h3><p>For release at 12:00 p.m. EDT</p>'
                f'<p>{self.TARGET}</p></div><footer>Footer is not release evidence.</footer></body></html>')

    def plan(self, source=None):
        return editor.build_editorial_plan(companies.build_company_catalyst_brief(), NOW, [source or self.source()])

    def test_fractional_rate_and_action_come_from_the_original_decision_sentence(self):
        from src.intelligence.policy_analysis import rate_facts
        facts = rate_facts(self.TARGET)
        self.assertEqual([row["value"] for row in facts], ["held", "3.75 to 4 percent"])
        self.assertTrue(all(row["evidence"] == self.TARGET for row in facts))

    def test_rate_increases_and_cuts_keep_their_direction(self):
        from src.intelligence.policy_analysis import rate_facts
        for verb, action in (("raise", "raised"), ("lower", "lowered")):
            self.assertEqual(rate_facts(self.TARGET.replace("maintain", verb).replace("at 3-3/4", "to 3.75"))[0]["value"], action)

    def test_decision_with_explicit_change_and_fractional_zero_bound_range(self):
        from src.intelligence.policy_analysis import rate_facts
        sentence=self.TARGET.replace("maintain", "lower").replace("at 3-3/4 to 4", "by 1/4 percentage point to 0 to 1/4")
        self.assertEqual([row["value"] for row in rate_facts(sentence)], ["lowered", "0 to 0.25 percent"])

    def test_forecasts_preferences_negation_and_unattributed_ranges_are_not_decisions(self):
        from src.intelligence.policy_analysis import rate_facts
        for text in (self.TARGET.replace("decided", "expects"), self.TARGET.replace("decided", "preferred"),
                     self.TARGET.replace("decided to", "decided not to"), "Analysts expect a target range of 3.75 to 4 percent."):
            self.assertEqual(rate_facts(text), [])

    def test_conflicting_or_implausible_decision_ranges_are_withheld(self):
        from src.intelligence.policy_analysis import rate_facts
        for text in (self.TARGET + "\n" + self.TARGET.replace("3-3/4 to 4", "4 to 4.25"),
                     self.TARGET.replace("3-3/4 to 4", "5 to 4"), self.TARGET.replace("3-3/4 to 4", "0 to 20")):
            self.assertEqual(rate_facts(text), [])

    def test_fed_body_supports_original_press_release_containers(self):
        from src.intelligence.news_original_sources import article_excerpt
        for wrapper in ('id="article"', 'class="col-xs-12 col-sm-8 col-md-8"'):
            excerpt = article_excerpt(self.body(wrapper), self.TITLE, NOW.replace(hour=16).isoformat(), publisher="Federal Reserve")
            self.assertIn(self.TARGET, excerpt)
            self.assertNotIn("Navigation", excerpt); self.assertNotIn("Footer", excerpt)

    def test_fed_container_fallback_does_not_extend_to_other_publishers(self):
        from src.intelligence.news_original_sources import article_excerpt
        with self.assertRaises(ValueError):
            article_excerpt(self.body(), self.TITLE, NOW.replace(hour=16).isoformat(), publisher="EIA")

    def test_fed_title_date_time_and_timezone_must_match(self):
        from src.intelligence.news_original_sources import article_excerpt
        for body in (self.body().replace(self.TITLE, "Different release"), self.body().replace("October 25", "October 24"),
                     self.body().replace("12:00", "11:00"), self.body().replace("EDT", "EST"),
                     self.body().replace("</h3>", "</h3><h3>" + self.TITLE + "</h3>")):
            with self.assertRaises(ValueError):
                article_excerpt(body, self.TITLE, NOW.replace(hour=16).isoformat(), publisher="Federal Reserve")

    def test_explicit_conflicting_metadata_is_not_overridden_by_the_feed(self):
        from src.intelligence.news_original_sources import article_excerpt
        body = self.body().replace("</head>", '<meta property="article:published_time" content="2026-10-25T15:00:00+00:00"></head>')
        with self.assertRaises(ValueError):
            article_excerpt(body, self.TITLE, NOW.replace(hour=16).isoformat(), publisher="Federal Reserve")

    def test_fed_refresh_enriches_one_statement_and_keeps_both_clocks(self):
        from src.intelligence.news_original_sources import enrich_feed
        source = next(row for row in editor.feeds.NEWS_SOURCES if row["name"] == "Federal Reserve")
        story = self.source(); published = format_datetime(NOW.replace(hour=16))
        rss = f'<rss><channel><item><title>{self.TITLE}</title><link>{story["url"]}</link><pubDate>{published}</pubDate></item></channel></rss>'
        payload = {"status":"ok", "body":rss, "fetched_at_epoch":NOW.timestamp()-30}
        fetch = Mock(return_value={"status":"ok", "url":story["url"], "body":self.body(), "fetched_at_epoch":NOW.timestamp()})
        enriched = enrich_feed(source, payload, editor.feeds.parse_rss_items, fetch, NOW)
        fetch.assert_called_once_with(story["url"])
        self.assertEqual(enriched["fetched_at_epoch"], payload["fetched_at_epoch"])
        self.assertEqual(enriched["release_evidence"][0]["published"], published)
        self.assertIs(enrich_feed(source, enriched, editor.feeds.parse_rss_items, fetch, NOW), enriched)

    def test_fed_refresh_ignores_calendar_and_non_statement_items(self):
        from src.intelligence.news_original_sources import enrich_feed
        source = next(row for row in editor.feeds.NEWS_SOURCES if row["name"] == "Federal Reserve")
        payload = {"status":"ok", "fetched_at_epoch":NOW.timestamp(), "body":f'<rss><channel><item><title>FOMC calendar</title><link>https://www.federalreserve.gov/calendar</link><pubDate>{format_datetime(NOW)}</pubDate></item></channel></rss>'}
        fetch = Mock()
        enrich_feed(source, payload, editor.feeds.parse_rss_items, fetch, NOW)
        fetch.assert_not_called()

    def test_statement_without_a_verified_decision_stays_held(self):
        for changes in ({"source_excerpt":""}, {"source_excerpt":"The Committee will discuss policy."}, {"excerpt_scope":"headline only"}):
            source = self.source(); source.update(changes)
            plan = self.plan(source)
            self.assertFalse(editor.selected_stories(plan))
            self.assertIn("decision text", plan["candidates"][0]["reason"])

    def test_old_excerpt_observation_cannot_publish_a_current_fed_headline(self):
        source = self.source(); source["evidence_checked_at"] = (NOW-timedelta(hours=7)).isoformat()
        self.assertFalse(editor.selected_stories(self.plan(source)))

    def test_publisher_feed_can_supply_the_actual_decision_without_an_extra_read(self):
        source = self.source(); source["excerpt_scope"] = "publisher feed excerpt"
        self.assertEqual(len(editor.selected_stories(self.plan(source))), 1)

    def test_policy_segment_explains_decision_and_financing_lens_separately_from_defense(self):
        from src.reports.daily_news_brief import POLICY_HEADER, validate_news_brief
        with patch.object(editor, "cache_candidates", return_value=([self.source()], [])):
            text = build_daily_news_brief(self.research())
        self.assertIn(POLICY_HEADER, text)
        self.assertIn("held its federal funds target range at 3.75 to 4 percent", text)
        self.assertIn("debt-funded AI expansion", text)
        self.assertNotIn("Review the original release for scope", text)
        defense = text.split("Global and Defense Watch\n",1)[1].split("\n\nWhat's Ahead",1)[0]
        self.assertNotIn("federal funds target range", defense)
        self.assertTrue(validate_news_brief(text)["passes"])

    def test_altered_policy_fact_or_analyst_wording_cannot_pass_review(self):
        from src.intelligence.daily_brief_analysis import analyze_report
        story = editor.selected_stories(self.plan())[0]
        story["event_evidence"]["facts"][1]["value"] = "0 to 0.25 percent"
        with self.assertRaises(ValueError):
            analyze_report(self.research(), [story])

    def test_historical_schema_three_profiles_keep_their_original_interpretation(self):
        from src.intelligence.story_analysis import build_evidence, checked_evidence
        story = self.source(); story["materiality"] = "monetary policy"
        story["event_evidence"] = build_evidence(story, self.TARGET, "original release excerpt", schema=3)
        self.assertEqual(checked_evidence(story)["facts"], [])


class BroadcastChecks(IsolatedChecks):
    COPILOT = "Introducing the Microsoft Copilot harness: Unlocking the potential of truly multi-model agentic work"
    GMLRS = "Lockheed Martin Advances Joint Fires Capability by Redirecting In-flight GMLRS Rocket During U.S. Army Test"

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ,{"SPECIAL_ALERT_SYMBOLS":"MSFT,NVDA,TSM,LMT,NOC,CACI,AMD"}))

    def source(self, symbol="MSFT", title=None, excerpt=""):
        return candidate(symbol,title=title or self.COPILOT,source_excerpt=excerpt,excerpt_scope="original release excerpt")

    def render(self, values):
        with patch.object(editor,"cache_candidates",return_value=(values,[])):
            return build_daily_news_brief(self.research())

    def test_copilot_brief_explains_product_and_commercial_test_without_reading_the_long_title(self):
        text=self.render([self.source()])
        self.assertIn("Microsoft introduced the Copilot harness for multi-model AI work",text)
        self.assertIn("paid adoption and the cost of running multiple models",text)
        self.assertIn("customer uptake, pricing and AI-related revenue or margin disclosures",text)
        self.assertNotIn(self.COPILOT,text)
        record=store.read_editions(report=text)[0]
        self.assertEqual(editor.selected_stories(record)[0]["title"],self.COPILOT)
        self.assertEqual(record["narration_version"],2)

    def test_concise_test_story_requires_a_sourced_demonstration_and_keeps_funding_conditional(self):
        text=self.render([self.source("LMT",self.GMLRS,"Lockheed Martin successfully redirected an in-flight GMLRS rocket during an Army test.")])
        self.assertIn("reported redirecting a GMLRS rocket in flight during an Army test",text)
        self.assertIn("could support future procurement",text)
        self.assertIn("funded orders and production costs",text)
        self.assertNotIn(self.GMLRS,text)
        self.assertEqual(editor.selected_stories(store.read_editions(report=text)[0])[0]["title"],self.GMLRS)

    def test_test_headline_alone_cannot_supply_the_condensed_capability_fact(self):
        text=self.render([self.source("LMT",self.GMLRS)])
        self.assertNotIn("reported redirecting a GMLRS rocket in flight",text)
        self.assertIn(self.GMLRS,text)

    def test_planned_test_does_not_become_a_completed_demonstration(self):
        title="Lockheed Martin Plans GMLRS Retargeting Test With Army"
        text=self.render([self.source("LMT",title,"Lockheed Martin plans to test in-flight GMLRS retargeting.")])
        self.assertIn(title,text)
        self.assertNotIn("reported redirecting",text)
        self.assertNotIn("Capability demonstrated",text)

    def test_copilot_recall_does_not_become_a_product_reveal(self):
        title="Microsoft recalls Copilot harness for multi-model AI work"
        text=self.render([self.source(title=title)])
        self.assertNotIn("introduced the Copilot harness",text)

    def test_follow_up_prefix_is_spoken_once_and_all_duration_checks_hold(self):
        from src.reports.daily_news_brief import validate_news_brief
        text=self.render([self.source()]);quality=validate_news_brief(text)
        self.assertNotIn("Watch next: Watch",text);self.assertNotIn("Watch next:",text)
        self.assertTrue(quality["passes"]);self.assertGreaterEqual(quality["spoken_words"],180)
        self.assertTrue(15<=quality["market_estimated_seconds"]<=30)

    def test_policy_product_and_defense_updates_fit_as_complete_stories_together(self):
        from src.reports.daily_news_brief import validate_news_brief
        values=[PolicyBriefChecks().source(),self.source(),
                self.source("LMT",self.GMLRS,"Lockheed Martin successfully redirected an in-flight GMLRS rocket during an Army test.")]
        text=self.render(values);record=store.read_editions(report=text)[0]
        self.assertEqual(len(editor.selected_stories(record)),3)
        self.assertTrue(validate_news_brief(text)["passes"])
        self.assertEqual(len(record["story_narrations"]),3)
        self.assertTrue(all(text.count(paragraph)==1 for paragraph in record["story_narrations"].values()))

    def test_sector_watch_qualifications_are_scoped_to_the_named_company(self):
        text=self.render([self.source()]);record=store.read_editions(report=text)[0]
        focus=record["analyst_review"]["evidence"]["company_focus"]
        sector=[row for row in focus["selected"] if row.get("basis")=="sector context"]
        self.assertTrue(sector)
        for row in sector:
            self.assertIn("No fresh "+row["name"]+" announcement is included in this edition.",text)
        self.assertNotIn("No fresh Microsoft announcement",text)

    def test_audit_retains_source_clock_original_title_and_exact_spoken_passage(self):
        value=self.source();text=self.render([value]);record=store.read_editions(report=text)[0]
        story=editor.selected_stories(record)[0]
        self.assertEqual(story["published"],value["published"])
        self.assertEqual(story["url"],value["url"]);self.assertEqual(story["source"],value["source"])
        self.assertEqual(text.count(record["story_narrations"][story["id"]]),1)

    def test_an_invented_broadcast_fact_cannot_be_saved_as_a_reviewed_edition(self):
        from src.intelligence.daily_brief_analysis import analyze_report,retained_review
        from zoneinfo import ZoneInfo
        from src.reports.daily_news_brief import NAMES
        plan=editor.build_editorial_plan(companies.build_company_catalyst_brief(),NOW,[self.source()])
        stories=editor.selected_stories(plan);story=stories[0]
        analysis=analyze_report(self.research(),stories,presentation="news",narration_version=2)
        fake=editor.render_story(story,ZoneInfo("America/New_York"),NAMES,style="broadcast")+" It guarantees $99 billion in revenue."
        text=fake+"\n\n"+"\n\n".join(row["text"] for row in analysis["insights"])
        with self.assertRaisesRegex(ValueError,"Broadcast wording"):
            editor.review_and_record(plan,text,{story["id"]:fake},self.research(),retained_review(analysis,text))

    def test_unknown_story_uses_its_complete_title_instead_of_an_invented_summary(self):
        title="Microsoft introduces an example research platform with enterprise controls"
        text=self.render([self.source(title=title)])
        self.assertIn("“"+title+"”",text)
        self.assertNotIn("…",text)

    def test_source_style_and_historical_analyst_versions_remain_available(self):
        from src.intelligence.daily_brief_analysis import analyze_report,validate_review
        context={"schema":2,"limit":3,"recent":[]}
        analysis=analyze_report(self.research(),presentation="news",focus_context=context)
        text="\n\n".join(row["text"] for row in analysis["insights"])
        validate_review(analysis,self.research(),text,[])
        plan=editor.build_editorial_plan(companies.build_company_catalyst_brief(),NOW,[self.source()])
        legacy=editor.render_story(editor.selected_stories(plan)[0],companies.calendar_context.report_zone(),{"MSFT":"Microsoft"})
        self.assertIn(self.COPILOT,legacy);self.assertIn("12:45 PM EDT",legacy)

    def test_unknown_narration_versions_and_unverified_publishers_are_rejected(self):
        from src.intelligence.daily_brief_analysis import analyze_report
        for version in (True,0,3):
            with self.assertRaises(ValueError):analyze_report(self.research(),presentation="news",narration_version=version)
        value=self.source();value["official"]=False
        with self.assertRaises(ValueError):editor.render_story(value,companies.calendar_context.report_zone(),{"MSFT":"Microsoft"},style="broadcast")

    def test_new_publishers_use_specific_issuer_authorities_and_original_feed_clocks(self):
        for symbol in ("AMD","CACI","NOC"):
            source=next(row for row in editor.feeds.NEWS_SOURCES if row.get("company_symbol")==symbol and not row.get("format"))
            self.assertTrue(editor.feeds.is_original_source(source))
            self.assertTrue(editor.feeds.originals.authorized_response(source,{"url":source["url"]}))
        source=next(row for row in editor.feeds.NEWS_SOURCES if row.get("company_symbol")=="AMD")
        rss='<rss><channel><item><title>AMD introduces an AI product</title><link>https://ir.amd.com/news-events/press-releases/detail/fixture</link><pubDate>Sun, 25 Oct 26 12:20:00 -0400</pubDate></item></channel></rss>'
        payload={"status":"ok","body":rss,"fetched_at_epoch":NOW.timestamp()}
        row=editor.feeds.describe_source(source,payload,NOW)
        self.assertEqual((row["status"],row["dated"],row["fresh"]),("available",1,1))

    def test_missing_new_feed_clock_is_not_replaced_with_the_fetch_time(self):
        source=next(row for row in editor.feeds.NEWS_SOURCES if row.get("company_symbol")=="CACI")
        payload={"status":"ok","body":'<rss><channel><item><title>CACI awarded a defense contract</title><link>https://investor.caci.com/fixture</link></item></channel></rss>',"fetched_at_epoch":NOW.timestamp()}
        row=editor.feeds.describe_source(source,payload,NOW)
        self.assertEqual((row["status"],row["fresh"],row["undated"]),("limited",0,1))

    def test_cross_issuer_redirect_and_lookalike_caci_domains_are_rejected(self):
        source=next(row for row in editor.feeds.NEWS_SOURCES if row.get("company_symbol")=="CACI")
        for url in ('https://investor.caci.com.evil.example/news','https://ir.amd.com/news','http://investor.caci.com/news'):
            self.assertFalse(editor.feeds.originals.authorized_response(source,{"final_url":url}))

    def test_fund_symbols_do_not_count_as_missing_company_publishers_and_failures_stay_visible(self):
        sources=[row for row in editor.feeds.NEWS_SOURCES if row.get("company_symbol")=="NOC"]
        rss='<rss><channel><item><title>Northrop Grumman introduces an example defense system</title><link>https://investor.northropgrumman.com/news-releases/fixture</link><pubDate>Sun, 25 Oct 2026 12:20:00 -0400</pubDate></item></channel></rss>'
        cache={sources[0]["url"]:{"status":"error","error":"Publisher index has no recognizable release links","fetched_at_epoch":NOW.timestamp()},
            sources[1]["url"]:{"status":"ok","body":rss,"fetched_at_epoch":NOW.timestamp()}}
        Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"]).write_text(json.dumps(cache))
        brief=companies.build_company_catalyst_brief()
        for symbol in ("VOO","ITA","SMH","ASML"):
            if symbol not in {row["symbol"] for row in brief["rows"]}:brief["rows"].append({"symbol":symbol,"events":[],"calendar":{"dates":[]}})
        with patch.object(editor.feeds,"NEWS_SOURCES",sources):plan=editor.build_editorial_plan(brief,NOW)
        health=plan["source_health"]
        self.assertEqual({row["status"] for row in health if row["symbol"]=="NOC"},{"available","limited"})
        self.assertFalse({"VOO","ITA","SMH"}&{row["symbol"] for row in health})
        self.assertTrue(any(row["symbol"]=="ASML" and row["status"]=="limited" for row in health))


class NewsFirstChecks(IsolatedChecks):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "MSFT,NVDA,PLTR,LMT,AVAV,KTOS"}))

    story = StoryAnalysisChecks.story
    profile = StoryAnalysisChecks.profile

    def render(self, values, report=None):
        with patch.object(editor, "cache_candidates", return_value=(values, [])):
            return build_daily_news_brief(report or self.research())

    # Reuse the isolated evidence fixture without rerunning the parent suite.
    def test_voluntary_offer_has_workforce_analysis_without_implied_departures(self):
        text = self.render([self.story("Introducing a Voluntary Exit Offer", "The company introduces a voluntary exit offer for eligible employees.", "MSFT")])
        self.assertIn("dependent on employee participation", text)
        self.assertIn("disclosed severance costs", text)
        self.assertNotIn("employees departed", text)
        self.assertNotIn("AI spending caused", text)
        row = editor.selected_stories(store.read_editions(report=text)[0])[0]
        self.assertEqual(row["materiality"], "restructuring")
        self.assertEqual(row["event_evidence"]["stage"], "voluntary offer")

    def test_cost_estimates_and_savings_targets_are_not_realized_results(self):
        value = self.profile("Example announces job cuts", "The company expects restructuring costs of $25 million. It targets annual savings of $40 million.")
        self.assertEqual([(row["field"], row["value"]) for row in value["facts"]], [("restructuring_cost_estimate", "$25 million"), ("annual_savings_target", "$40 million")])
        self.assertNotIn("restructuring_charge", {row["field"] for row in value["facts"]})

    def test_reported_workforce_cost_and_missing_terms_stay_distinct(self):
        value = self.profile("Example announces workforce restructuring", "The company recorded restructuring charges of $15 million.")
        self.assertEqual(value["facts"][0]["field"], "restructuring_charge")
        self.assertEqual(self.profile("Introducing a Voluntary Exit Offer", "Eligible employees may choose to leave.")["facts"], [])

    def test_speculation_negation_and_old_savings_do_not_become_current_costs(self):
        for text in ("The company may incur restructuring costs of $20 million.", "Last year, annual savings of $40 million were targeted.", "No restructuring costs of $25 million were recorded.", "Estimated restructuring costs of $25 million to $40 million are anticipated.", "The company targets annual savings of $10 million to $20 million."):
            self.assertFalse(self.profile("Example announces layoffs", text)["facts"])
        plan = editor.build_editorial_plan(companies.build_company_catalyst_brief(), NOW, extra_candidates=[candidate(title="Microsoft denies layoffs")])
        self.assertFalse(editor.selected_stories(plan))

    def test_workforce_buyout_is_distinct_from_acquiring_a_business(self):
        from src.intelligence.story_analysis import event_type
        self.assertEqual(event_type("Example agrees to acquire a business")[0], "acquisition")
        self.assertEqual(event_type("Example introduces a voluntary retirement program")[0], "restructuring")
        self.assertEqual(event_type("Example cuts revenue guidance after layoffs"), ("guidance", "lowered"))

    def test_company_news_and_its_analysis_lead_before_market_and_rankings(self):
        title = "Microsoft reports quarterly financial results"
        text = self.render([self.story(title, symbol="MSFT")])
        self.assertLess(text.index(title), text.index("Market Update"))
        self.assertLess(text.index("Investor take:"), text.index("Market Update"))
        self.assertIn("company rankings, trade-plan conditions and risk checks", text)

    def test_completed_defense_deal_leads_before_product_reveal(self):
        product = self.story("Microsoft introduces an AI product", symbol="MSFT")
        deal = self.story("Example Defense completes a maritime acquisition")
        text = self.render([product, deal])
        self.assertLess(text.index(deal["title"]), text.index("Market Update"))
        self.assertLess(text.index("After the reported close"), text.index("Market Update"))
        self.assertLess(text.index(deal["title"]), text.index(product["title"]))

    def test_guidance_story_takes_the_same_issuer_slot_before_a_product(self):
        values = [candidate(title="Microsoft introduces an AI product"), candidate(title="Microsoft cuts revenue guidance", url="https://blogs.microsoft.com/guidance")]
        text = self.render(values)
        self.assertIn(values[1]["title"], text)
        self.assertNotIn(values[0]["title"], text)

    def test_compact_rankings_keep_underlying_model_evidence_and_durations(self):
        from src.intelligence.daily_brief_analysis import analyze_report
        from src.reports.daily_news_brief import validate_news_brief
        from scripts.check_report_consistency import enriched_ranked_stocks
        report = self.research(ranked=enriched_ranked_stocks())
        text = self.render([], report=report)
        record = store.read_editions(report=text)[0]
        company = text.split("Companies in Focus\n")[1].split("\n\nGlobal and Defense Watch")[0]
        self.assertGreaterEqual(len(company.split("\n\n")), 2)
        self.assertNotIn("follows at", company)
        self.assertNotIn("Why it leads:", text)
        self.assertNotIn("In our longer-term model", text)
        self.assertIn("ranking_reason", {row["id"] for row in analyze_report(report)["insights"]})
        self.assertEqual(record["analyst_review"]["presentation"], "news")
        quality = validate_news_brief(text)
        self.assertTrue(quality["passes"], quality)
        self.assertGreaterEqual(quality["spoken_words"], 180)
        self.assertTrue(15 <= quality["market_estimated_seconds"] <= 30)

    def test_news_presentation_and_its_evidence_are_validated_together(self):
        from src.intelligence.daily_brief_analysis import analyze_report, retained_review, validate_review
        from scripts.check_report_consistency import enriched_ranked_stocks
        report = self.research(ranked=enriched_ranked_stocks())
        text = self.render([], report=report)
        review = store.read_editions(report=text)[0]["analyst_review"]
        validate_review(review, report, text)
        altered = deepcopy(review); altered["presentation"] = "full"
        with self.assertRaises(ValueError):
            validate_review(altered, report, text)
        with self.assertRaises(ValueError):
            analyze_report(report, presentation="unchecked")

    def test_previous_event_profiles_remain_readable_after_classification_changes(self):
        from src.intelligence.story_analysis import build_evidence, checked_evidence
        story = self.story("Introducing a Voluntary Exit Offer", symbol="MSFT")
        story["materiality"] = "product"
        story["event_evidence"] = build_evidence(story, schema=1)
        self.assertEqual(checked_evidence(story)["event"], "product")
        self.assertEqual(build_evidence(story)["event"], "restructuring")

    def test_reordering_selected_stories_keeps_the_same_news_evidence(self):
        from src.intelligence.daily_brief_analysis import analyze_report
        values = [self.story("Microsoft reports financial results", symbol="MSFT"), self.story("Nvidia introduces an AI product", symbol="NVDA"), self.story("Example Defense completes an acquisition")]
        text = self.render(values)
        record = store.read_editions(report=text)[0]
        selected = editor.selected_stories(record)
        first = analyze_report(self.research(), selected, presentation="news")
        second = analyze_report(self.research(), list(reversed(selected)), presentation="news")
        self.assertEqual(first, second)


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
