"""Offline results/guidance, source-age and native voiceover integration checks."""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import json
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_news_editor import candidate
from scripts.check_semiconductor_news import PresentationChecks, payload, rss
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.intelligence import company_earnings as earnings, news_live_sources as feeds, news_original_sources as originals
from src.intelligence import news_editor as editor, news_editor_store as store, daily_brief_analysis as analysis
from src.intelligence.story_analysis import build_evidence, checked_evidence
from src.reports import daily_news_brief as news, daily_voiceover as voice

TITLE = "Intel Reports Third-Quarter 2026 Financial Results"
URL = "https://www.intc.com/news-events/press-releases/detail/123/intel-reports-third-quarter-2026-financial-results"
INTEL = next(row for row in feeds.NEWS_SOURCES if row.get("company_symbol") == "INTC")
SUMMARY = ("News Summary\nThird-quarter revenue was $12.5 billion, up 4% year-over-year (YoY).\n"
           "Third-quarter earnings per share (EPS) attributable to Intel was $0.20; non-GAAP EPS attributable to Intel was $0.31.\n"
           "Forecasting fourth-quarter 2026 revenue of $13.0 billion to $14.0 billion; forecasting fourth-quarter EPS of $0.22.\n"
           "SANTA CLARA, Calif.--(BUSINESS WIRE)--\nIntel Corporation today reported third-quarter 2026 financial results.")


def source(hours=30):
    clock = (NOW-timedelta(hours=hours)).isoformat()
    text = TITLE + "\n" + (NOW-timedelta(hours=hours)).strftime("%B %d, %Y").replace(" 0", " ") + "\n" + SUMMARY
    return candidate("INTC", title=TITLE, source="Intel Investor Relations", url=URL, published=clock,
                     source_excerpt=text, excerpt_scope="original release excerpt", evidence_checked_at=NOW.isoformat())


class CompanyEarningsChecks(IsolatedChecks):
    research_moves = PresentationChecks.research_moves

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(feeds, "CACHE_FILE", self.root / "company-news.json"))

    def render(self, raw=None, pending=False):
        report = self.research_moves(pending)
        with patch.object(editor, "cache_candidates", return_value=([raw or source()], [])):
            text = news.build_daily_news_brief(report)
        return text, store.read_editions(report=text)[0]

    def record(self, **changes):
        value = source(); value.update(changes)
        return earnings.from_issuer(value, NOW)

    def test_reported_revenue_and_forecast_keep_different_explicit_periods(self):
        record = self.record(); facts = earnings.intel_facts(record["text"], record["title"])
        self.assertEqual([(row["value"], row["period"], row["basis"]) for row in facts],
            [("$12.5 billion", "third quarter 2026", "reported"), ("$13.0 billion to $14.0 billion", "fourth quarter 2026", "forecast")])
        self.assertTrue(all(row["evidence"] in record["text"] for row in facts))
        self.assertFalse(any("eps" in row["field"] for row in facts))

    def test_tables_management_comments_and_adjusted_eps_do_not_supply_facts(self):
        raw = source(); base = raw["source_excerpt"]
        facts = earnings.intel_facts(base + "\nCEO: Revenue was $999 billion.\nRevenue ($B) Q3 2026 Q3 2025 $999 $888", TITLE)
        self.assertEqual([row["value"] for row in facts], ["$12.5 billion", "$13.0 billion to $14.0 billion"])
        self.assertEqual(earnings.intel_facts(TITLE + "\nRevenue ($B) Q3 2026 $999", TITLE), [])

    def test_duplicate_current_figures_are_withheld(self):
        text = source()["source_excerpt"].replace("News Summary\n", "News Summary\nThird-quarter revenue was $99.0 billion.\n")
        self.assertEqual(earnings.intel_facts(text, TITLE), [])

    def test_wrong_heading_year_issuer_or_reporting_period_is_not_repaired(self):
        for old, new in (("third-quarter 2026 financial results", "second-quarter 2026 financial results"),
                         ("Intel Corporation today", "Another Corporation today"), ("News Summary", "Forecast Summary")):
            raw = source(); raw["source_excerpt"] = raw["source_excerpt"].replace(old, new)
            with self.subTest(new=new), self.assertRaises(ValueError): earnings.from_issuer(raw, NOW)

    def test_wrong_next_quarter_year_units_or_reversed_range_are_withheld(self):
        for old, new in (("fourth-quarter 2026 revenue", "fourth-quarter 2025 revenue"),
                         ("fourth-quarter 2026 revenue", "second-quarter 2026 revenue"),
                         ("$14.0 billion", "$14.0 million"), ("$13.0 billion", "$15.0 billion")):
            self.assertEqual(earnings.intel_facts(source()["source_excerpt"].replace(old, new), TITLE), [])

    def test_prior_or_negated_revenue_is_not_current_revenue(self):
        for prefix in ("Previously, ", "Not ", "Forecasting ", "Adjusted "):
            text = source()["source_excerpt"].replace("Third-quarter revenue was", prefix+"Third-quarter revenue was")
            self.assertEqual(earnings.intel_facts(text, TITLE), [])

    def test_fourth_to_first_quarter_outlook_requires_next_year(self):
        title = TITLE.replace("Third", "Fourth")
        text = source()["source_excerpt"].replace(TITLE, title).replace("third-quarter", "fourth-quarter").replace("Third-quarter", "Fourth-quarter")
        text = text.replace("Forecasting fourth-quarter 2026 revenue", "Forecasting first-quarter 2027 revenue")
        self.assertEqual(earnings.intel_facts(text, title)[1]["period"], "first quarter 2027")
        self.assertEqual(earnings.intel_facts(text.replace("first-quarter 2027 revenue", "first-quarter 2026 revenue"), title), [])

    def test_feed_only_or_other_publisher_text_cannot_establish_context(self):
        for key, value in (("official", False), ("excerpt_scope", "publisher feed excerpt"),
                           ("source", "Another publisher"), ("publisher_symbol", "AMD")):
            raw = source(); raw[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): earnings.from_issuer(raw, NOW)

    def test_lookalike_or_wrong_release_url_and_naive_clock_are_rejected(self):
        for changes in ({"url":URL.replace("www.intc.com", "www.intc.com.attacker.test")},
                        {"url":URL.replace("third-quarter", "second-quarter")}, {"url":URL+"?source=other"},
                        {"published":"2026-10-24T11:00:00"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.record(**changes)

    def test_both_original_age_and_observation_are_bounded(self):
        record = self.record()
        for delta in (timedelta(hours=7), timedelta(hours=43), timedelta(hours=-31)):
            with self.subTest(delta=delta), self.assertRaises(ValueError): earnings.checked(record, NOW+delta)
        stale = source(); stale["evidence_checked_at"] = (NOW-timedelta(hours=7)).isoformat()
        with self.assertRaises(ValueError): earnings.from_issuer(stale, NOW)

    def test_refetch_does_not_turn_old_results_into_fresh_context(self):
        old = source(73)
        self.assertEqual(old["evidence_checked_at"], NOW.isoformat())
        with self.assertRaises(ValueError): earnings.from_issuer(old, NOW)

    def test_heading_visible_date_and_text_hash_are_frozen(self):
        original = self.record()
        for key, value in (("text", original["text"].replace("$12.5", "$99.5")), ("title", TITLE.replace("Third", "Second")),
                           ("release_date", "2026-10-23"), ("publisher_clock", (NOW-timedelta(hours=29)).isoformat())):
            record = deepcopy(original); record[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): earnings.checked(record, NOW)
        raw = source(); raw["source_excerpt"] = raw["source_excerpt"].replace("October 24", "October 23")
        with self.assertRaises(ValueError): earnings.from_issuer(raw, NOW)

    def test_native_publication_day_survives_utc_midnight(self):
        clock = "2026-10-23T23:30:00-04:00"
        raw = source(); raw["published"] = clock; raw["source_excerpt"] = raw["source_excerpt"].replace("October 24", "October 23")
        record = earnings.from_issuer(raw, NOW)
        self.assertEqual(record["release_date"], "2026-10-23")
        self.assertTrue(record["published"].startswith("2026-10-24"))

    def test_new_results_refresh_reuses_one_detail_read_and_remains_old_news(self):
        raw = source(); calls = []
        body = '<article><h1>'+TITLE+'</h1>'+''.join('<p>'+line+'</p>' for line in raw["source_excerpt"].splitlines()[1:])+'</article>'
        value = originals.enrich_feed(INTEL, payload(INTEL["url"], rss(TITLE,URL,raw["published"])), feeds.parse_rss_items,
            lambda url: (calls.append(url) or payload(url, body)), NOW)
        self.assertEqual(calls, [URL])
        candidates, _ = editor.cache_candidates(NOW, ["INTC"], cache={INTEL["url"]:value})
        self.assertEqual(earnings.from_issuer(candidates[0], NOW)["symbol"], "INTC")
        health = feeds.describe_source(INTEL, value, NOW)
        self.assertEqual(health["fresh"], 0)
        plan = editor.build_editorial_plan({"rows":[{"symbol":"INTC","events":[]}],"issues":[]}, NOW, candidates)
        self.assertFalse(editor.selected_stories(plan)); self.assertEqual(plan["candidates"][0]["decision"], "wait")

    def test_only_supported_results_can_use_the_context_age_window(self):
        for title, hours in ((TITLE,73), ("Intel announces a new product",30), ("Intel to report quarterly financial results",30)):
            calls = []
            originals.enrich_feed(INTEL,payload(INTEL["url"],rss(title,URL,(NOW-timedelta(hours=hours)).isoformat())),
                feeds.parse_rss_items,lambda url:calls.append(url),NOW)
            self.assertFalse(calls)

    def test_dated_context_enriches_brief_without_increasing_fresh_story_count(self):
        text, record = self.render()
        self.assertIn("Intel — recent earnings context", text)
        self.assertIn("third quarter 2026 revenue of $12.5 billion", text)
        self.assertIn("fourth quarter 2026 revenue of $13.0 billion to $14.0 billion", text)
        self.assertIn("not a reported result", text); self.assertIn("do not establish the cause", text)
        self.assertFalse(editor.selected_stories(record)); self.assertTrue(news.validate_news_brief(text)["passes"])
        self.assertIn("Intel's earnings follow-through", text)

    def test_contextualized_company_leaves_peer_group_without_duplicating_prices(self):
        _, record = self.render(); review = record["analyst_review"]
        group = next(row["text"] for row in review["insights"] if row["id"] == "company_focus_moves")
        self.assertNotIn("Intel", group); self.assertIn("ASML", group); self.assertIn("Advanced Micro Devices", group)
        self.assertEqual(sum("Shares fell 28.6 percent" in row["text"] for row in review["insights"]), 1)

    def test_pending_small_or_other_company_move_cannot_admit_context(self):
        _, record = self.render(pending=True)
        self.assertFalse(record["analyst_review"]["evidence"].get("earnings_context"))
        for event in ({"symbol":"INTC","status":"rechecked","reported_move":-4.9},
                      {"symbol":"AMD","status":"rechecked","reported_move":-28}):
            values, _, _ = earnings.cached_context([source()], NOW, [event])
            self.assertEqual(values, [])

    def test_context_for_an_unfeatured_issuer_is_dropped(self):
        result = earnings.retain([self.record()],NOW,[{"symbol":"INTC","status":"rechecked","reported_move":-28}],[],{"selected":[{"symbol":"AMD"}]})
        self.assertEqual(result, [])

    def test_same_clock_conflicting_original_results_are_withheld(self):
        other = source(); other["source_excerpt"] = other["source_excerpt"].replace("$12.5", "$13.5")
        values, _, health = earnings.cached_context([source(),other],NOW,[{"symbol":"INTC","status":"rechecked","reported_move":-28}])
        self.assertEqual(values, []); self.assertIn("Conflicting", health[0]["reason"])

    def test_a_newer_unread_results_release_prevents_fallback_to_older_results(self):
        newer = source(29); newer["source_excerpt"] = "Unread original results"
        values, _, health = earnings.cached_context([source(),newer],NOW,[{"symbol":"INTC","status":"rechecked","reported_move":-28}])
        self.assertEqual(values,[]); self.assertEqual(health[0]["status"],"limited")

    def test_forecast_comparison_handles_units_and_never_claims_a_consensus_miss(self):
        for amount, expected in (("$12.0 billion","above"),("$16.0 billion","below"),("$14.0 billion",None),
                                 ("$13500.0 million",None),("$16000.0 million","below")):
            raw=source(); raw["source_excerpt"]=raw["source_excerpt"].replace("$12.5 billion",amount)
            text=earnings.intel_narration(earnings.from_issuer(raw,NOW))
            if expected: self.assertIn("entire forecast range is "+expected,text)
            else: self.assertNotIn("entire forecast range",text)
            self.assertNotIn("miss",text); self.assertNotIn("caused",text)

    def test_context_health_and_story_log_show_exact_issuer_periods_and_source(self):
        self.render()
        status = editor.build_editor_status(); log = editor.build_editor_status("INTC",history=True)
        self.assertIn("Company earnings context: INTC — available",status)
        self.assertIn("Dated earnings context: INTC",status)
        self.assertIn("DATED EARNINGS CONTEXT — Intel",log); self.assertIn(URL,log)
        self.assertIn("fourth quarter 2026 | forecast",log)
        self.assertNotIn("DATED EARNINGS CONTEXT — Intel",editor.build_editor_status("AMD",history=True))

    def test_missing_summary_is_a_visible_context_gap_not_invented_analysis(self):
        raw = source(); raw["source_excerpt"] = "Headline only"
        _, record = self.render(raw)
        self.assertFalse(record["analyst_review"]["evidence"].get("earnings_context"))
        self.assertIn("Company earnings context: INTC — limited",editor.build_editor_status())

    def test_rendering_does_not_fetch_or_change_rankings(self):
        before = self.ranking.read_bytes()
        with patch.object(feeds,"fetch_url",side_effect=AssertionError("No source read during rendering")):
            _, record = self.render()
        self.assertEqual(before,self.ranking.read_bytes()); self.assertFalse(record["analyst_review"]["score_changes"])

    def test_voiceover_and_episode_keep_spoken_forecast_and_per_issuer_source(self):
        _, record = self.render(); profile = voice.checked(record,NOW); episode = voice.episode(record,NOW)
        self.assertTrue(profile["quality"]["passes"]); self.assertEqual(episode["voiceover_schema"],2)
        self.assertIn("third quarter two thousand twenty six revenue",profile["script"])
        self.assertIn("thirteen billion dollars to fourteen billion dollars",profile["script"])
        self.assertNotIn("thirteen dollars to",profile["script"])
        self.assertIn("not a reported result",profile["script"])
        self.assertIn("Management forecast",profile["script"])
        scene = next(row for row in profile["segments"] if row["heading"] == "Companies in Focus" and "earnings_INTC" in row["source_ids"])
        self.assertIn("fourth quarter 2026 revenue forecast: $13.0 billion to $14.0 billion".capitalize(),[line.capitalize() for line in scene["bullets"]])
        self.assertIn(URL,json.dumps(episode["sources"]))
        self.assertTrue(episode["review_required"]); self.assertEqual(profile["script"].count("Intel fell twenty eight point six percent"),1)
        company_scenes = [row for row in profile["segments"] if row["heading"] == "Companies in Focus"]
        self.assertIn("Intel fell",company_scenes[0]["narration"])
        self.assertIn("earnings_INTC",profile["segments"][0]["source_ids"])
        self.assertIn("earnings_INTC",next(row for row in profile["segments"] if row["heading"]=="What We're Watching")["source_ids"])

    def test_changed_record_facts_narration_or_visuals_fail_frozen_edition_review(self):
        text, record = self.render(); changed = deepcopy(record["analyst_review"])
        changed["earnings_context"][0]["text"] = changed["earnings_context"][0]["text"].replace("$12.5","$99.5")
        with self.assertRaises(ValueError): analysis.validate_review(changed,record["research_text"],text,[])
        for key in ("narration","bullets"):
            altered = deepcopy(record); scene = next(row for row in altered["voiceover"]["segments"] if row["heading"] == "Companies in Focus" and "earnings_INTC" in row["source_ids"])
            scene[key] = "Invented company profit" if key=="narration" else ["Invented company profit"]
            with self.subTest(key=key), self.assertRaises(ValueError): voice.checked(altered,NOW)

    def test_fresh_results_use_versioned_facts_and_do_not_repeat_as_dated_context(self):
        text, record = self.render(source(1)); selected = editor.selected_stories(record)
        self.assertEqual(len(selected),1); self.assertEqual(selected[0]["event_evidence"]["schema"],7)
        self.assertEqual(len(selected[0]["event_evidence"]["facts"]),2)
        self.assertFalse(record["analyst_review"]["evidence"]["earnings_context"])
        self.assertIn("third quarter 2026 revenue of $12.5 billion",text)
        self.assertNotIn("Intel — recent earnings context",text)
        self.assertTrue(voice.checked(record,NOW)["quality"]["passes"])

    def test_previous_evidence_schema_keeps_its_original_fields_and_wording(self):
        raw = source(); old = build_evidence(raw,raw["source_excerpt"],"original release excerpt",schema=4)
        raw["event_evidence"] = old
        self.assertEqual(checked_evidence(raw),old)
        self.assertEqual(old["facts"],[{"field":"reported_revenue","value":"$12.5 billion (Third-quarter)",
            "evidence":"Third-quarter revenue was $12.5 billion, up 4% year-over-year (YoY)."}])

    def test_two_issuer_contexts_link_opening_and_watch_to_the_company_actually_discussed(self):
        from scripts.check_earnings_context import EarningsContextChecks
        from scripts.check_event_news import quote
        from src.intelligence import market_event_desk as events
        moves={"INTC":-12.0,"GOOGL":-28.0}
        events.review_quotes({symbol:quote(symbol,value) for symbol,value in moves.items()},lambda symbol:quote(symbol,moves[symbol]),NOW)
        report=self.research(replacements={"Watchlist Movers":"Largest regular-session movers:\n"+
            "\n".join("• "+symbol+": $88.00 ("+str(value)+"%)" for symbol,value in moves.items())})
        with patch.object(editor,"cache_candidates",return_value=([source(),EarningsContextChecks().issuer()],[])):
            text=news.build_daily_news_brief(report)
        record=store.read_editions(report=text)[0]
        self.assertEqual({value["symbol"] for value in record["analyst_review"]["evidence"]["earnings_context"]},{"GOOG","INTC"})
        profile=voice.checked(record,NOW)
        self.assertIn("Alphabet",profile["segments"][0]["narration"])
        self.assertEqual(profile["segments"][0]["source_ids"],["earnings_GOOG"])
        self.assertEqual(next(row for row in profile["segments"] if row["heading"]=="What We're Watching")["source_ids"],["earnings_GOOG"])


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--windows-socketpair",action="store_true"); args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair: stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(CompanyEarningsChecks))
    passed=result.wasSuccessful() and not traffic["blocked"]
    print(f"Company Earnings Context Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__=="__main__": raise SystemExit(main())
