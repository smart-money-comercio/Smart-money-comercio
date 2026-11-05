"""Offline behavior checks for the opening takeaway and useful watch signals."""

from contextlib import ExitStack
from copy import deepcopy
import argparse
import socket
import sys
from pathlib import Path
import json
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_event_news import quote
from scripts.check_news_editor import candidate
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.intelligence import daily_brief_analysis as analysis, market_event_desk as events, news_editor as editor, news_editor_store as store
from src.reports import daily_news_brief as news


def section(text, header):
    body = text.split(header + "\n", 1)[1]
    return body.split("\n\nResearch Notes", 1)[0] if header == "What We're Watching" else body.split("\n\n", 1)[0]


class ReaderChecks(IsolatedChecks):
    def render(self, values=None, report=None):
        with patch.object(editor, "cache_candidates", return_value=(values or [], [])):
            return news.build_daily_news_brief(report or self.research())

    def record(self, text):
        return store.read_editions(report=text)[0]

    def outlier(self, status=True):
        if status:
            events.review_quotes({"GOOGL": quote()}, lambda _: quote(), NOW)
        return self.research(replacements={"Watchlist Movers": "Largest regular-session movers:\n• GOOGL: $88.00 (-12.00%)"})

    def test_takeaway_follows_greeting_and_precedes_every_news_section(self):
        text = self.render()
        at = text.index("The takeaway:")
        self.assertLess(text.index("Good afternoon."), at)
        self.assertTrue(all(at < text.index(header + "\n") for header in news.HEADERS))
        self.assertIn("All three major indexes fell", text[:text.index("Market Update")])
        self.assertEqual(text.count("The takeaway:"), 1)

    def test_watch_explains_the_next_observation_and_why_it_matters(self):
        text = self.render(); watch = section(text, "What We're Watching")
        self.assertIn("18 stocks and funds we track", watch)
        self.assertIn("7 finished higher and 11 lower", watch)
        self.assertIn("In the next session, watch for fewer declines", watch)
        self.assertIn("reduce margins", watch)
        self.assertNotIn("disclosures, price and volume support these research ideas", watch)
        self.assertTrue(2 <= len(self.record(text)["analyst_review"]["insights"]) <= 20)

    def test_watch_uses_plain_language_instead_of_model_or_entry_jargon(self):
        watch = section(self.render(), "What We're Watching").lower()
        for phrase in ("setup risk", "score risk", "conviction", "alignment", "scorecard", "signal stack", "buy now"):
            self.assertNotIn(phrase, watch)

    def test_verified_large_move_leads_without_inventing_a_cause(self):
        text = self.render(report=self.outlier())
        opening = text.split("The takeaway:", 1)[1].split("\n\n", 1)[0]
        watch = section(text, "What We're Watching")
        self.assertIn("Alphabet fell 12.0 percent", opening)
        self.assertIn("Compare the move with original results and guidance", opening)
        self.assertNotIn("whether selling spreads", opening)
        self.assertIn("Alphabet's business outlook", watch)
        self.assertIn("price move alone cannot explain it", watch)
        self.assertNotIn("caused", text.lower())

    def test_pending_large_move_cannot_become_a_confirmed_opening_fact(self):
        text = self.render(report=self.outlier(False))
        opening = text.split("The takeaway:", 1)[1].split("\n\n", 1)[0]
        self.assertNotIn("Alphabet's sharp decline", opening)
        self.assertNotIn("12.0 percent", text)
        self.assertIn("Alphabet's price check", section(text, "What We're Watching"))
        self.assertIn("stock split could change the reading", text)

    def test_opposing_index_directions_are_explained_without_a_market_wide_claim(self):
        report = self.research(replacements={"Executive Summary": "- Main theme: Mixed.\n- Market moves: S&P -0.17%, Nasdaq -1.04%, Russell +1.22%, VIX -2.9%, Oil -1.56%, TLT +0.53%."})
        text = self.render(report=report)
        self.assertIn("Nasdaq fell while the Russell index rose", text)
        self.assertIn("Watch participation across the names we track", text)
        self.assertNotIn("all stocks are falling", text.lower())

    def test_higher_indexes_and_weak_watchlist_have_a_scoped_takeaway(self):
        report = self.research(replacements={"Executive Summary": "- Main theme: Growth.\n- Market moves: S&P +0.5%, Nasdaq +0.4%, Russell +0.1%."})
        text = self.render(report=report)
        self.assertIn("All three major indexes rose in the completed session", text)
        self.assertIn("Most names in our tracked group still finished lower", text)
        self.assertIn("Index gains are not shared by most names in this research watchlist", text)

    def test_closed_session_watch_preserves_completed_session_tense(self):
        watch = section(self.render(), "What We're Watching")
        self.assertIn("finished higher", watch)
        self.assertNotIn("are higher", watch)

    def test_missing_session_does_not_supply_a_current_price_or_breadth_claim(self):
        report = self.research(replacements={"Market Snapshot": "Market Session: Closed.\nBreadth: 7 up / 11 down / 18 quoted"})
        text = self.render([candidate()], report)
        self.assertIn("Market coverage is incomplete", text)
        self.assertIn("missing market check", section(text, "What We're Watching"))
        self.assertNotIn("7 finished higher", text)
        self.assertNotIn("Rising oil prices", text)

    def test_funded_work_and_start_dates_are_the_contract_follow_up(self):
        story = candidate("CACI", title="CACI awarded an Army contract valued at up to $185 million",
            source_excerpt="CACI announced a five-year Army task order valued at up to $185 million for expeditionary power systems.", excerpt_scope="original release excerpt")
        with patch.dict("os.environ", {"SPECIAL_ALERT_SYMBOLS": "MSFT,NVDA,TSM,CACI"}):
            text = self.render([story])
        watch = section(text, "What We're Watching")
        self.assertIn("CACI International's contract follow-through", watch)
        self.assertIn("committed funding and a start date", watch)
        self.assertIn("potential award can become sales", watch)
        self.assertNotIn("booked $185 million", text)

    def test_product_watch_explains_the_commercial_test(self):
        text = self.render([candidate("MSFT", title="Microsoft introduces a multi-model AI platform")])
        watch = section(text, "What We're Watching")
        self.assertIn("Microsoft's commercial test", watch)
        self.assertIn("paying customers and the cost of serving them", watch)
        self.assertIn("profits and cash generation", watch)

    def test_removed_or_unconfirmed_story_does_not_supply_a_business_watch(self):
        value = candidate("NVDA", official=False, title="Nvidia announces record quarterly earnings")
        text = self.render([value])
        self.assertNotIn("Nvidia's next results", section(text, "What We're Watching"))
        self.assertNotIn(value["title"], text)

    def test_opening_and_every_watch_signal_are_bound_to_the_research_edition(self):
        report = self.research(); text = self.render(report=report)
        record = self.record(text); reviewed = record["analyst_review"]
        self.assertEqual(reviewed["reader_version"], 3)
        self.assertTrue(2 <= sum(row["section"] == "watch" for row in reviewed["insights"]) <= 3)
        analysis.validate_review(reviewed, report, text, editor.selected_stories(record))
        altered = deepcopy(reviewed)
        altered["insights"][-1]["text"] = "Profits are guaranteed to rise."
        with self.assertRaises(ValueError): analysis.validate_review(altered, report, text, editor.selected_stories(record))
        with self.assertRaises(ValueError): analysis.validate_review(reviewed, report, text.replace("The takeaway:", "Opening:"), editor.selected_stories(record))

    def test_history_keeps_the_previous_narration_rules(self):
        report = self.research()
        reviewed = analysis.analyze_report(report, presentation="news", narration_version=2)
        self.assertNotIn("reader_version", reviewed)
        self.assertFalse(any(row["section"] == "intro" for row in reviewed["insights"]))
        old_text = "\n\n".join(row["text"] for row in reviewed["insights"])
        analysis.validate_review(reviewed, report, old_text)

    def test_new_narration_stays_within_character_and_spoken_duration_limits(self):
        for values in ([], [candidate()], [candidate(), candidate("NVDA"), candidate("LMT")]):
            text = self.render(values); result = news.validate_news_brief(text)
            self.assertTrue(result["passes"])
            self.assertLessEqual(result["chars"], 3800)
            self.assertGreaterEqual(result["estimated_narration_seconds"], 60)
            self.assertTrue(15 <= result["market_estimated_seconds"] <= 30)

    def test_cancelled_deal_and_cooperation_keep_their_distinct_next_checks(self):
        from src.intelligence.reader_brief import watching
        evidence = analysis.report_evidence(self.research())
        for stage, expected in (("terminated", "cancellation costs"), ("cooperation", "signed commercial terms")):
            story = {"id": "fixture", "kind": "company", "symbols": ["MSFT"], "publisher_symbol": "MSFT", "event_evidence": {"event": "contract", "stage": stage}}
            rows = watching({**evidence, "stories": [story]})
            text = next(row["text"] for row in rows if row["id"] == "watch_business")
            self.assertIn(expected, text.lower())
            self.assertNotIn("potential award can become sales", text)

    def test_ipo_watch_explains_valuation_and_dilution_without_assuming_trading(self):
        from src.intelligence.reader_brief import watching
        evidence = analysis.report_evidence(self.research())
        rows = watching({**evidence, "stories": [{"ipo": {"stage": "public filing"}}]})
        text = next(row["text"] for row in rows if row["id"] == "watch_ipo")
        self.assertIn("share count and new shares", text)
        self.assertIn("losses and funding needs", text)
        self.assertNotIn("available to trade", text)

    def test_invalid_reader_context_cannot_bypass_review(self):
        for options in ({"reader_version": 4}, {"reader_version": True}, {"reader_version": 1, "reader_limit": 0}, {"reader_version": 1, "reader_limit": True}):
            with self.assertRaises(ValueError):
                analysis.analyze_report(self.research(), presentation="news", narration_version=2, **options)

    def snapshot(self, *, up=0, down=18, live=False, dated=True):
        return ("Market Session: " + ("Open — live session." if live else "Closed — weekend.")
                + ("\nQuote session: 2026-10-23" if dated else "")
                + f"\nBreadth: {up} up / {down} down / 18 quoted")

    def test_all_declines_are_observed_before_the_next_test_is_explained(self):
        report = self.outlier()
        report = report.replace("Breadth: 7 up / 11 down / 18 quoted", "Breadth: 0 up / 18 down / 18 quoted")
        text = self.render(report=report)
        intro = text.split("The takeaway:", 1)[1].split("\n\n", 1)[0]
        self.assertLess(intro.index("All three major indexes fell"), intro.index("Alphabet fell 12.0 percent"))
        self.assertIn("All 18 stocks and funds we track finished lower", intro)
        self.assertIn("selling to ease", intro)
        self.assertNotIn("whether selling spreads", intro)
        self.assertNotIn("whether the move spreads", intro)

    def test_watchlist_declines_do_not_become_a_claim_about_every_stock(self):
        report = self.research(replacements={"Market Snapshot": self.snapshot(),
            "Executive Summary": "- Main theme: Uneven.\n- Market moves: S&P +0.5%, Nasdaq +0.4%, Russell +0.2%."})
        text = self.render(report=report)
        intro = text.split("The takeaway:", 1)[1].split("\n\n", 1)[0]
        self.assertIn("All 18 stocks and funds we track finished lower", intro)
        self.assertNotIn("All three major indexes fell", intro)
        self.assertNotIn("every stock", text.lower())
        self.assertIn("Index gains are not shared by most names in this research watchlist", text)

    def test_closed_session_check_looks_forward_to_the_next_session(self):
        text = self.render(report=self.research(replacements={"Market Snapshot": self.snapshot()}))
        watch = section(text, "What We're Watching")
        self.assertIn("All 18 stocks and funds we track finished lower", watch)
        self.assertIn("In the next session", watch)
        self.assertIn("selling is easing", watch)
        self.assertNotIn("0 finished higher", watch)

    def test_live_session_check_can_still_change_before_the_close(self):
        text = self.render(report=self.research(replacements={"Market Snapshot": self.snapshot(live=True)}))
        watch = section(text, "What We're Watching")
        self.assertIn("All 18 stocks and funds we track are lower", watch)
        self.assertIn("before the close", watch)
        self.assertNotIn("In the next session", watch)
        self.assertNotIn("finished", watch)

    def test_all_gains_are_a_staying_power_check_not_a_request_for_more_names(self):
        text = self.render(report=self.research(replacements={"Market Snapshot": self.snapshot(up=18, down=0),
            "Executive Summary": "- Main theme: Strong.\n- Market moves: S&P +0.5%, Nasdaq +0.4%, Russell +0.2%."}))
        watch = section(text, "What We're Watching")
        self.assertIn("All 18 stocks and funds we track finished higher", watch)
        self.assertIn("whether gains continue across this group", watch)
        self.assertNotIn("more companies join", watch)

    def test_missing_session_cannot_supply_the_new_participation_claim(self):
        text = self.render(report=self.research(replacements={"Market Snapshot": self.snapshot(dated=False)}))
        self.assertNotIn("All 18", text)
        self.assertNotIn("All three major indexes fell", text)
        self.assertIn("Market coverage is incomplete", text)

    def test_unknown_index_directions_are_not_filled_from_the_watchlist(self):
        text = self.render(report=self.research(replacements={"Market Snapshot": self.snapshot(),
            "Executive Summary": "- Main theme: Limited.\n- Market moves: Nasdaq -1.5%."}))
        self.assertIn("All 18 stocks and funds we track finished lower", text)
        self.assertNotIn("All three major indexes fell", text)

    def test_tied_participation_does_not_assert_a_recovery_or_a_rally(self):
        text = self.render(report=self.research(replacements={"Market Snapshot": self.snapshot(up=9, down=9)}))
        watch = section(text, "What We're Watching")
        self.assertIn("The next move:", watch)
        self.assertIn("establish a direction within this group", watch)
        self.assertNotIn("Market recovery:", watch)

    def test_dated_intel_outlook_explains_the_test_and_keeps_scene_sources(self):
        from scripts.check_company_earnings import source
        from src.reports import daily_voiceover as voice
        events.review_quotes({"INTC": quote("INTC", -28.6)}, lambda _: quote("INTC", -28.6), NOW)
        raw = source()
        raw["source_excerpt"] = raw["source_excerpt"].replace("$12.5 billion", "$16.5 billion")
        report = self.research(replacements={"Market Snapshot": self.snapshot(),
            "Watchlist Movers": "Largest regular-session movers:\n• INTC: $88.00 (-28.60%)"})
        text = self.render([raw], report)
        record = self.record(text)
        intro = text.split("The takeaway:", 1)[1].split("\n\n", 1)[0]
        self.assertIn("entire next-quarter revenue forecast is below", intro)
        self.assertIn("Compare the next sales report with management's revenue forecast", text)
        self.assertNotIn("whether the move spreads", intro)
        self.assertEqual(record["rules_version"], 24)
        profile = voice.checked(record, NOW)
        self.assertEqual(profile["schema"], 2)
        for heading in ("The Takeaway", "What We're Watching"):
            scene = next(row for row in profile["segments"] if row["heading"] == heading)
            self.assertIn("earnings_INTC", scene["source_ids"])
        self.assertIn("next-quarter revenue forecast is below", profile["script"])
        episode = voice.episode(record, NOW)
        self.assertEqual(episode["voiceover_schema"], 2)
        self.assertTrue(episode["review_required"])
        self.assertEqual(episode["voiceover_sha256"], profile["script_sha256"])
        self.assertLessEqual(len(text), 3800)

    def test_revenue_comparison_requires_a_whole_range_above_or_below_actual(self):
        from scripts.check_company_earnings import source
        events.review_quotes({"INTC": quote("INTC", -28.6)}, lambda _: quote("INTC", -28.6), NOW)
        report = self.research(replacements={"Watchlist Movers": "Largest regular-session movers:\n• INTC: $88.00 (-28.60%)"})
        for actual, direction in (("$16.5 billion", "below"), ("$12.5 billion", "above"), ("$13.5 billion", None)):
            raw = source()
            raw["source_excerpt"] = raw["source_excerpt"].replace("$12.5 billion", actual)
            text = self.render([raw], report)
            intro = text.split("The takeaway:", 1)[1].split("\n\n", 1)[0]
            with self.subTest(actual=actual):
                if direction:
                    self.assertIn(f"entire next-quarter revenue forecast is {direction}", intro)
                else:
                    self.assertNotIn("entire next-quarter revenue forecast is", intro)

    def test_a_rechecked_gain_with_widespread_tracked_gains_asks_if_they_hold(self):
        events.review_quotes({"GOOGL": quote("GOOGL", 12)}, lambda _: quote("GOOGL", 12), NOW)
        report = self.research(replacements={"Market Snapshot": self.snapshot(up=18, down=0),
            "Watchlist Movers": "Largest regular-session movers:\n• GOOGL: $88.00 (+12.00%)",
            "Executive Summary": "- Main theme: Strong.\n- Market moves: S&P +0.5%, Nasdaq +0.4%, Russell +0.2%."})
        text = self.render(report=report)
        intro = text.split("The takeaway:", 1)[1].split("\n\n", 1)[0]
        self.assertIn("Alphabet rose 12.0 percent", intro)
        self.assertIn("whether those gains hold", intro)
        self.assertNotIn("other companies join", intro)

    def test_rules19_saved_brief_and_voiceover_keep_their_original_hashes(self):
        from src.reports import daily_voiceover as voice
        record = json.loads((ROOT / "scripts/fixtures/reader_rules19_edition.json").read_text())
        self.assertEqual(record["rules_version"], 19)
        self.assertEqual(record["analyst_review"]["reader_version"], 1)
        profile = voice.checked(record, NOW)
        self.assertEqual(record["report_sha256"], "c0d02d155fe8359a2fc6e482acf1045688463fb2770f6782221e2be70445af0f")
        self.assertEqual(profile["script_sha256"], "b81f7027f445fe6c7119c00f4294de67d3acf99dd4fd148f63870a2591ce9a8c")


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--windows-socketpair", action="store_true"); args = parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair: stack.enter_context(patch.object(socket, "socketpair", portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    passed = result.wasSuccessful() and not traffic["blocked"]
    print(f"Reader Brief Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())
