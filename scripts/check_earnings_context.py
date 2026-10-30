"""Offline SEC backup, provenance and dated earnings-context contracts."""

from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_event_news import quote
from scripts.check_alphabet_sources import earnings_pdf
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.intelligence import alphabet_earnings as earnings, news_editor as editor, news_editor_store as store
from src.intelligence import news_live_sources as feeds, market_event_desk as events, daily_brief_analysis as analysis
from src.reports.daily_news_brief import build_daily_news_brief, validate_news_brief

TITLE = "Alphabet Announces Third Quarter 2026 Results"
ACCESSION = "0001652044-26-000001"
BASE = "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000001/"
PRIMARY, EXHIBIT = BASE + "goog-fixture.htm", BASE + "fixture-ex991.htm"


class EarningsContextChecks(IsolatedChecks):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(feeds, "CACHE_FILE", self.root / "news.json"))
        self.stack.enter_context(patch.dict(os.environ, {"SEC_USER_AGENT": "Offline Fixture admin@fixture.test"}))

    def metadata(self, hours=30):
        released = (NOW-timedelta(hours=hours)).date().isoformat()
        return {"cik": "0001652044", "name": "Alphabet Inc.", "tickers": ["GOOG", "GOOGL"],
                "filings": {"recent": {"accessionNumber": [ACCESSION], "form": ["8-K"],
                    "acceptanceDateTime": [(NOW-timedelta(hours=hours)).isoformat()], "primaryDocument": ["goog-fixture.htm"],
                    "reportDate": [released], "items": ["2.02,9.01"]}}}

    def primary(self, link=EXHIBIT):
        return ('<html><ix:nonnumeric name="dei:EntityCentralIndexKey">0001652044</ix:nonnumeric>'
                '<ix:nonnumeric name="dei:EntityRegistrantName">ALPHABET INC.</ix:nonnumeric>'
                '<ix:nonnumeric name="dei:DocumentType">8-K</ix:nonnumeric>'
                '<ix:nonnumeric name="dei:TradingSymbol">GOOG</ix:nonnumeric>'
                '<ix:nonnumeric name="dei:TradingSymbol">GOOGL</ix:nonnumeric>'
                '<div>Item 2.02 Results of Operations and Financial Condition. Alphabet issued its earnings press release, attached as Exhibit 99.1.</div>'
                '<div>Item 9.01 Financial Statements and Exhibits.</div><table><tr><td>99.1</td><td><a href="'
                + link + '">Press release of Alphabet Inc.</a></td></tr></table></html>')

    def exhibit(self, hours=30):
        day = (NOW-timedelta(hours=hours)).strftime("%B %d, %Y").replace(" 0", " ")
        return ('<div>Exhibit 99.1</div><h2>'+TITLE+'</h2><p>MOUNTAIN VIEW, Calif. – '+day
                +' – Alphabet Inc. (NASDAQ: GOOG, GOOGL) announced financial results for the quarter ended September 30, 2026.</p>'
                '<p>Consolidated Alphabet revenues increased to $12.5 billion.</p>'
                '<p>Consolidated Alphabet operating margin was 31.8%.</p>'
                '<p>Net income available to common stockholders was $2.6 billion and EPS was $2.12.</p>'
                '<p>Sundar Pichai, CEO, said: this is an offline test fixture.</p>')

    def payload(self, url, body):
        return {"status": "ok", "url": url, "final_url": url, "body": body, "fetched_at_epoch": NOW.timestamp()}

    def retrieve(self, overrides=None, hours=30):
        values = {earnings.SUBMISSIONS: json.dumps(self.metadata(hours)), PRIMARY: self.primary(), EXHIBIT: self.exhibit(hours)}
        values.update(overrides or {}); calls = []
        def fetch(url):
            calls.append(url); value = values[url]
            return value if isinstance(value, dict) else self.payload(url, value)
        return earnings.retrieve(NOW, fetch), calls

    def seed(self, payload=None):
        payload = payload or self.retrieve()[0]
        feeds.CACHE_FILE.write_text(json.dumps({earnings.SUBMISSIONS: payload}))
        return payload

    def report(self, rechecked=True, symbol="GOOGL"):
        if rechecked:
            events.review_quotes({symbol: quote(symbol)}, lambda _: quote(symbol), NOW)
        return self.research(replacements={"Watchlist Movers": f"Largest regular-session movers:\n• {symbol}: $88.00 (-12.00%)"})

    def render(self, rechecked=True, symbol="GOOGL"):
        self.seed(); report = self.report(rechecked, symbol)
        with patch.object(editor, "cache_candidates", return_value=([], [])), patch.object(feeds, "fetch_url", side_effect=AssertionError("No fetch while rendering")):
            return build_daily_news_brief(report), report

    def test_official_submissions_primary_and_linked_exhibit_take_only_three_reads(self):
        payload, calls = self.retrieve()
        self.assertEqual(calls, [earnings.SUBMISSIONS, PRIMARY, EXHIBIT])
        record = earnings.checked(payload["record"], NOW)
        self.assertEqual(record["source"], "SEC EDGAR")
        self.assertEqual(record["release_date"], self.metadata()["filings"]["recent"]["reportDate"][0])
        self.assertEqual(record["published"], (NOW-timedelta(hours=30)).isoformat())
        self.assertEqual(len(earnings.results_facts(record["text"], record["title"])), 3)

    def test_wrong_metadata_issuer_is_rejected_before_document_reads(self):
        for key, value in (("cik", "1234"), ("name", "Unrelated Inc."), ("tickers", ["OTHER"])):
            metadata = self.metadata(); metadata[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.retrieve({earnings.SUBMISSIONS: json.dumps(metadata)})

    def test_primary_identity_form_and_share_classes_are_bound_to_alphabet(self):
        for body in (self.primary().replace("0001652044", "0000001234"),
                     self.primary().replace("ALPHABET INC.", "UNRELATED INC."),
                     self.primary().replace(">8-K<", ">10-Q<"), self.primary().replace(">GOOGL<", ">OTHER<")):
            with self.subTest(body=body[:60]), self.assertRaises(ValueError): self.retrieve({PRIMARY: body})

    def test_cross_issuer_external_and_ambiguous_exhibits_are_not_followed(self):
        for link in (EXHIBIT.replace("1652044/", "1234/"), "https://example.test/release.htm", EXHIBIT+"?x=1"):
            with self.subTest(link=link), self.assertRaises(ValueError): self.retrieve({PRIMARY: self.primary(link)})
        duplicate = self.primary().replace("</table>", '<tr><td>99.1</td><td><a href="'+BASE+'other.htm">Other release</a></td></tr></table>')
        with self.assertRaises(ValueError): self.retrieve({PRIMARY: duplicate})

    def test_each_response_must_keep_its_exact_requested_authority(self):
        for url, body in ((earnings.SUBMISSIONS, json.dumps(self.metadata())), (PRIMARY, self.primary()), (EXHIBIT, self.exhibit())):
            payload = self.payload(url, body); payload["final_url"] = "https://example.test/redirect"
            with self.subTest(url=url), self.assertRaises(ValueError): self.retrieve({url: payload})

    def test_future_naive_and_missing_acceptance_clocks_are_not_guessed(self):
        for clock in ((NOW+timedelta(hours=1)).isoformat(), "2026-10-25T10:00:00", ""):
            metadata = self.metadata(); metadata["filings"]["recent"]["acceptanceDateTime"] = [clock]
            with self.subTest(clock=clock), self.assertRaises(ValueError): self.retrieve({earnings.SUBMISSIONS: json.dumps(metadata)})

    def test_old_filings_stop_after_the_metadata_read(self):
        payload, calls = self.retrieve(hours=73)
        self.assertIsNone(payload["record"])
        self.assertEqual(calls, [earnings.SUBMISSIONS])

    def test_results_item_and_release_period_must_agree(self):
        for body in (self.primary().replace("Item 2.02", "Item 8.01"), self.primary().replace("Exhibit 99.1", "Exhibit 99.2")):
            with self.assertRaises(ValueError): self.retrieve({PRIMARY: body})
        for body in (self.exhibit().replace("September 30, 2026", "June 30, 2026"), self.exhibit().replace("October 24, 2026", "October 23, 2026")):
            with self.assertRaises(ValueError): self.retrieve({EXHIBIT: body})

    def test_no_current_results_summary_is_inferred_from_a_tables_only_exhibit(self):
        with self.assertRaises(ValueError): self.retrieve({EXHIBIT: '<h2>'+TITLE+'</h2><table><tr><td>$12.5 billion</td></tr></table>'})

    def test_response_and_cache_observation_clocks_remain_bounded(self):
        for stamp in (NOW.timestamp()-21601, NOW.timestamp()+61, float("nan"), True):
            payload = self.payload(EXHIBIT, self.exhibit()); payload["fetched_at_epoch"] = stamp
            with self.subTest(stamp=stamp), self.assertRaises(ValueError): self.retrieve({EXHIBIT: payload})

    def test_a_refetch_cannot_make_an_older_filing_fresh(self):
        record = self.retrieve()[0]["record"]
        later = NOW+timedelta(hours=43); record["observed"] = later.isoformat()
        with self.assertRaises(ValueError): earnings.checked(record, later)

    def test_altered_text_title_or_document_reference_loses_its_proof(self):
        original = self.retrieve()[0]["record"]
        for key, value in (("text", original["text"].replace("$12.5", "$99.5")), ("title", TITLE.replace("Third", "Second")),
                           ("url", EXHIBIT.replace("1652044/", "1234/")), ("release_date", "2026-10-23")):
            record = deepcopy(original); record[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): earnings.checked(record, NOW)

    def test_dated_context_enriches_the_rechecked_move_without_becoming_fresh_news(self):
        text, _ = self.render(); record = store.read_editions(report=text)[0]
        self.assertIn("Alphabet — recent earnings context", text)
        self.assertIn("$12.5 billion (third quarter 2026)", text)
        self.assertIn("31.8% (third quarter 2026)", text)
        self.assertIn("SEC 8-K accepted October 24 UTC", text)
        self.assertIn("do not establish the cause of the price move", text)
        self.assertFalse(editor.selected_stories(record))
        self.assertTrue(validate_news_brief(text)["passes"])
        self.assertIn("earnings follow-through", text)

    def test_pending_quotes_do_not_admit_earnings_context(self):
        text, _ = self.render(False)
        self.assertNotIn("$12.5 billion", text)
        self.assertNotIn("recent earnings context:", text)

    def test_another_companys_move_does_not_activate_alphabet_context(self):
        text, _ = self.render(symbol="MSFT")
        self.assertNotIn("$12.5 billion", text)

    def test_small_moves_do_not_activate_context(self):
        payload = self.seed(); event = {"symbol": "GOOGL", "status": "rechecked", "reported_move": -4.9}
        values, _ = earnings.candidates([], {earnings.SUBMISSIONS: payload}, NOW, [event])
        self.assertEqual(values, [])

    def test_rendering_does_not_change_the_source_cache_or_ranking_memory(self):
        self.seed(); report = self.report(); cache = feeds.CACHE_FILE.read_bytes(); ranking = self.ranking.read_bytes()
        with patch.object(editor, "cache_candidates", return_value=([], [])), patch.object(earnings, "refresh", side_effect=AssertionError("Refresh during rendering")):
            text = build_daily_news_brief(report)
        self.assertIn("$12.5 billion", text)
        self.assertEqual(feeds.CACHE_FILE.read_bytes(), cache)
        self.assertEqual(self.ranking.read_bytes(), ranking)

    def test_context_is_recorded_with_original_clocks_and_urls_in_the_story_log(self):
        text, _ = self.render()
        for symbol in ("GOOG", "GOOGL"):
            log = editor.build_editor_status(symbol, history=True)
            self.assertIn("DATED EARNINGS CONTEXT", log)
            self.assertIn("SEC acceptance:", log)
            self.assertIn(EXHIBIT, log)
            self.assertIn("not counted as a fresh news story", log)
        self.assertIn("Recent earnings context", editor.build_editor_status())

    def test_changed_context_fact_or_narration_fails_same_edition_review(self):
        text, research = self.render(); record = store.read_editions(report=text)[0]
        reviewed = deepcopy(record["analyst_review"])
        reviewed["earnings_context"][0]["text"] += " Invented profit."
        with self.assertRaises(ValueError): analysis.validate_review(reviewed, research, text, [])
        reviewed = deepcopy(record["analyst_review"])
        row = next(row for row in reviewed["insights"] if row["id"].startswith("company_focus_") and "$12.5" in row["text"])
        row["text"] = row["text"].replace("$12.5", "$99.5")
        with self.assertRaises(ValueError): analysis.validate_review(reviewed, research, text, [])

    def test_fresh_original_results_avoid_duplicate_dated_context(self):
        from scripts.check_news_editor import candidate
        payload = self.seed(); record = payload["record"]
        event = {"symbol": "GOOGL", "status": "rechecked", "reported_move": -12}
        story = candidate("GOOGL"); story["event_evidence"] = {"event": "earnings"}
        self.assertEqual(earnings.retain([record], NOW, [event], [story], {"selected": [{"symbol": "GOOGL"}]}), [])

    def test_sec_contact_is_required_without_making_a_network_request(self):
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Your Name your-email@example.com", "SEC_API_USER_AGENT": ""}), patch.object(feeds, "fetch_url") as fetch:
            result = earnings.refresh()
        fetch.assert_not_called(); self.assertEqual(result["status"], "error")
        self.assertIn("SEC_USER_AGENT", result["error"])

    def test_backup_429_keeps_the_original_cooldown_on_forced_refresh(self):
        error = HTTPError(earnings.SUBMISSIONS, 429, "Slow down", {"Retry-After": "1800"}, None)
        with patch.object(feeds.time, "time", return_value=NOW.timestamp()), patch.object(feeds, "urlopen", side_effect=error) as request:
            first = earnings.refresh(); again = earnings.refresh(True)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(first["retry_after_epoch"], NOW.timestamp()+1800)
        self.assertEqual(again["retry_after_epoch"], first["retry_after_epoch"])

    def test_successful_backup_uses_the_configured_sec_contact_and_caches_parsed_evidence(self):
        raw = {earnings.SUBMISSIONS: json.dumps(self.metadata()), PRIMARY: self.primary(), EXHIBIT: self.exhibit()}
        def fetch(url, *args, **kwargs):
            self.assertEqual(kwargs["user_agent"], "Offline Fixture admin@fixture.test")
            return self.payload(url, raw[url])
        class Clock(type(NOW)):
            @classmethod
            def now(cls, zone=None): return NOW
        with patch.object(earnings, "datetime", Clock), patch.object(feeds, "fetch_url", side_effect=fetch) as request:
            result = earnings.refresh()
        self.assertEqual(request.call_count, 3)
        self.assertEqual(result["body"], "")
        self.assertEqual(earnings.health(result, NOW)["status"], "available")

    def issuer(self):
        title, text, _ = earnings.summary(earnings.visible(self.exhibit()))
        return {"source": "Alphabet Investor Relations", "publisher_symbol": "GOOG", "official": True,
                "title": title, "source_excerpt": text, "excerpt_scope": "original release excerpt",
                "published": (NOW-timedelta(hours=30)).isoformat(), "source_checked_at": NOW.isoformat(),
                "url": "https://abc.xyz/investor/news/news-details/2026/Alphabet-Announces-Third-Quarter-2026-Results-Fixture/default.aspx",
                "document_url": "https://s206.q4cdn.com/479360582/files/doc_news/2026/Oct/24/attachments/2026q3-alphabet-earnings-release.pdf",
                "symbols": ["GOOG"], "kind": "company"}

    def test_original_issuer_context_is_preferred_for_the_same_results_day(self):
        payload = self.retrieve()[0]
        event = {"symbol": "GOOGL", "status": "rechecked", "reported_move": -12}
        values, _ = earnings.candidates([self.issuer()], {earnings.SUBMISSIONS: payload}, NOW, [event])
        self.assertEqual(len(values), 1); self.assertEqual(values[0]["route"], "issuer")

    def test_native_issuer_clock_and_release_period_cannot_be_changed(self):
        raw = self.issuer()
        for change in ({"published": NOW.isoformat()}, {"url": raw["url"].replace("Third", "Second"),
                        "document_url": raw["document_url"].replace("2026q3", "2026q2")}):
            with self.subTest(change=change), self.assertRaises(ValueError): earnings.from_issuer({**raw, **change}, NOW)

    def test_older_issuer_results_can_be_read_as_context_without_extending_fresh_news(self):
        from src.intelligence import alphabet_source as source_reader
        from email.utils import format_datetime
        raw = self.issuer(); source = next(row for row in feeds.NEWS_SOURCES if row.get("format") == "alphabet")
        rss = '<rss><channel><item><title>'+TITLE+'</title><link>'+raw['url']+'</link><pubDate>'+format_datetime(NOW-timedelta(hours=30))+'</pubDate></item></channel></rss>'
        page = '<h3>'+TITLE+'</h3><span class="evergreen-news-date-text">October 24, 2026</span><a href="'+raw['document_url']+'">Results</a>'
        values = {source_reader.FEED: rss, raw["url"]: page, raw["document_url"]: earnings_pdf(date="October 24, 2026")}
        calls = []
        def fetch(url):calls.append(url);return self.payload(url, values[url])
        payload = source_reader.retrieve(source, fetch, NOW)
        self.assertEqual(len(calls), 3); self.assertTrue(payload["articles"][0]["release_body_verified"])
        self.assertEqual(feeds.describe_source(source, payload, NOW)["fresh"], 0)
        from src.intelligence import company_catalyst_context
        with patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "GOOG,GOOGL"}):
            plan = editor.build_editorial_plan(company_catalyst_context.build_company_catalyst_brief(), NOW, [raw])
        self.assertFalse(editor.selected_stories(plan))
        self.assertEqual(plan["candidates"][0]["source_check"], "hold")

    def test_stale_backup_evidence_cannot_be_used_despite_a_recent_cache_timestamp(self):
        payload = self.retrieve()[0]; payload["record"]["observed"] = (NOW-timedelta(hours=7)).isoformat()
        values, coverage = earnings.candidates([], {earnings.SUBMISSIONS: payload}, NOW,
            [{"symbol": "GOOGL", "status": "rechecked", "reported_move": -12}])
        self.assertEqual(values, []); self.assertEqual(coverage["status"], "limited")

    def test_normal_refresh_invokes_the_backup_and_exposes_separate_health(self):
        source = next(row for row in feeds.NEWS_SOURCES if row.get("format") == "alphabet")
        payload = self.retrieve()[0]
        class Clock(type(NOW)):
            @classmethod
            def now(cls, zone=None): return NOW
        with patch.object(feeds, "NEWS_SOURCES", [source]), patch.object(feeds, "datetime", Clock), patch.object(feeds, "fetch_source", return_value={"status":"error"}), patch.object(earnings, "refresh", return_value=payload) as backup:
            context = feeds.fetch_news_live_context(True)
        backup.assert_called_once_with(True)
        self.assertEqual(context["earnings_backup"]["status"], "available")
        self.assertEqual(context["source_results"][0]["status"], "limited")
        self.assertIn("Alphabet SEC earnings context: available", feeds.format_source_status(context))

    def test_failed_refresh_preserves_still_verified_context_without_resetting_its_clock(self):
        payload = self.retrieve()[0]; payload["fetched_at_epoch"] -= 3600
        payload["record"]["observed"] = (NOW-timedelta(hours=1)).isoformat(); self.seed(payload)
        class Clock(type(NOW)):
            @classmethod
            def now(cls, zone=None): return NOW
        error = HTTPError(earnings.SUBMISSIONS, 429, "Slow down", {}, None)
        with patch.object(earnings, "datetime", Clock), patch.object(feeds.time, "time", return_value=NOW.timestamp()), patch.object(feeds, "urlopen", side_effect=error):
            result = earnings.refresh()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["retained_record"]["observed"], payload["record"]["observed"])
        selected, coverage = earnings.candidates([], {earnings.SUBMISSIONS: result}, NOW,
            [{"symbol":"GOOGL", "status":"rechecked", "reported_move":-12}])
        self.assertEqual(coverage["status"], "limited")
        self.assertTrue(selected[0]["cached_after_failure"])
        self.assertIn("previously verified cached context", earnings.narration(selected[0], {"reported_move":-12}))

    def test_retained_context_cannot_outlive_its_original_observation(self):
        record = self.retrieve()[0]["record"]
        payload = {"status":"error", "error":"HTTPError 429", "fetched_at_epoch":(NOW+timedelta(hours=7)).timestamp(), "retained_record":record}
        selected, _ = earnings.candidates([], {earnings.SUBMISSIONS: payload}, NOW+timedelta(hours=7),
            [{"symbol":"GOOGL", "status":"rechecked", "reported_move":-12}])
        self.assertEqual(selected, [])

    def test_conflicting_original_figures_withhold_context(self):
        issuer = self.issuer(); issuer["source_excerpt"] = issuer["source_excerpt"].replace("$12.5", "$13.5")
        values, health = earnings.candidates([issuer], {earnings.SUBMISSIONS:self.retrieve()[0]}, NOW,
            [{"symbol":"GOOGL", "status":"rechecked", "reported_move":-12}])
        self.assertEqual(values, []); self.assertIn("Conflicting", health["reason"])

    def test_a_known_amendment_prevents_reuse_of_the_previous_context(self):
        self.seed(); metadata = self.metadata(); metadata["filings"]["recent"]["form"] = ["8-K/A"]
        class Clock(type(NOW)):
            @classmethod
            def now(cls, zone=None): return NOW
        with patch.object(earnings, "datetime", Clock), patch.object(feeds, "fetch_url", return_value=self.payload(earnings.SUBMISSIONS,json.dumps(metadata))):
            result = earnings.refresh(True)
        self.assertTrue(result["withhold_context"]); self.assertNotIn("retained_record", result)
        values, _ = earnings.candidates([self.issuer()], {earnings.SUBMISSIONS:result}, NOW,
            [{"symbol":"GOOGL", "status":"rechecked", "reported_move":-12}])
        self.assertEqual(values, [])

    def test_optional_context_does_not_force_a_fresh_story_out_of_the_character_budget(self):
        from scripts.check_news_editor import candidate
        from src.reports import daily_news_brief as news
        self.seed(); research = self.report()
        values = [candidate("MSFT"), candidate("NVDA"), candidate("LMT", title="Lockheed Martin wins a new defense contract")]
        with patch.object(editor, "cache_candidates", return_value=(values, [])):
            with patch.object(earnings, "cached_context", return_value=([], {"status":"available", "reason":"fixture"})):
                original = build_daily_news_brief(research)
            count = len(editor.selected_stories(store.read_editions(report=original)[0]))
            with patch.object(news, "MAX_NEWS_CHARS", len(original)):
                updated = build_daily_news_brief(research)
        self.assertEqual(len(editor.selected_stories(store.read_editions(report=updated)[0])), count)
        self.assertLessEqual(len(updated), len(original))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--windows-socketpair", action="store_true"); args = parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair: stack.enter_context(patch.object(socket, "socketpair", portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(EarningsContextChecks)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    passed = result.wasSuccessful() and not traffic["blocked"]
    print(f"Earnings Context Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())
