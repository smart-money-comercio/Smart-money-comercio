"""Offline behavior checks for the opening takeaway and useful watch signals."""

from contextlib import ExitStack
from copy import deepcopy
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import socket
import sys
from pathlib import Path
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_event_news import quote
from scripts.check_news_editor import candidate
from scripts.check_report_consistency import BuilderConsistencyChecks, enriched_ranked_stocks
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.intelligence import daily_brief_analysis as analysis, market_event_desk as events, news_editor as editor, news_editor_store as store, watchlist_breadth
from src.reports import daily_news_brief as news, daily_report, daily_voiceover


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

    def close_report(self, at, session, previous, moves, *, timing="completed_session"):
        quotes = {
            symbol: {"ok": True, "price": 100 + move, "change_percent": move, "session_date": session,
                     "previous_session_date": previous, "quote_timing": timing, "asof": session + "T20:00:00+00:00"}
            for symbol, move in moves.items()
        }
        report = BuilderConsistencyChecks.build_daily_fixture(
            SimpleNamespace(daily=daily_report), at, ranked=enriched_ranked_stocks(), quotes=quotes,
        )
        return report.replace(
            "• Focus: NVDA; confirm before acting.",
            "- Main theme: Oil / inflation risk.\n"
            "- Market moves: S&P -0.52%, Nasdaq -0.21%, Russell -0.29%, VIX +2.21%, Oil +4.32%, TLT -0.49%.",
        )

    def test_watchlist_follow_through_uses_only_names_quoted_at_both_closes(self):
        friday = datetime(2026, 10, 23, 21, tzinfo=timezone.utc)
        monday = datetime(2026, 10, 26, 21, tzinfo=timezone.utc)
        before = self.close_report(friday, "2026-10-23", "2026-10-22",
                                   {"NVDA": -1, "MSFT": -1, "GOOGL": -1, "CIBR": 2, "META": -1})
        first_edition = self.record(self.render(report=before))
        self.assertNotIn("Watchlist follow-through", first_edition["report_text"])
        after = self.close_report(monday, "2026-10-26", "2026-10-23",
                                  {"NVDA": 1, "MSFT": 1, "GOOGL": -1, "CIBR": 0, "AMD": -1})
        self.assertIn("Watchlist closes vs 2026-10-23 — AMD down, CIBR flat", after)
        text = self.render(report=after)
        watch = section(text, "What We're Watching")
        result = "Of 4 watchlist names quoted at both closes, 3 finished lower on October 23 and 1 on October 26."
        self.assertIn("Watchlist follow-through — " + result, watch)
        self.assertIn("at least 3 advances at the next close", watch)
        self.assertNotIn("Watchlist breadth —", watch)
        record = self.record(text)
        follow_through = record["analyst_review"]["evidence"]["watchlist_follow_through"]
        self.assertEqual(follow_through["symbols"], ["CIBR", "GOOGL", "MSFT", "NVDA"])
        self.assertEqual(follow_through["edition_id"], first_edition["id"])
        self.assertIn("2026-10-23 to 2026-10-26 | 4 matched names | prior edition " + first_edition["id"],
                      editor.build_editor_status())
        self.assertIn("Of four watchlist names quoted at both closes, three finished lower on October twenty third "
                      "and one on October twenty sixth.", daily_voiceover.checked(record)["script"])
        altered = deepcopy(record["analyst_review"])
        altered["evidence"]["watchlist_follow_through"]["previous_down"] = 1
        with self.assertRaisesRegex(ValueError, "evidence does not match"):
            analysis.validate_review(altered, after, text, editor.selected_stories(record))

        rerun = self.render(report=after.replace("17:00:00 America/New_York", "17:10:00 America/New_York"))
        self.assertIn(result, rerun)
        self.assertEqual(self.record(rerun)["analyst_review"]["watchlist_baseline"]["edition_id"], first_edition["id"])

    def test_watchlist_waits_for_a_comparable_completed_close(self):
        friday = datetime(2026, 10, 23, 21, tzinfo=timezone.utc)
        monday = datetime(2026, 10, 26, 21, tzinfo=timezone.utc)
        self.render(report=self.close_report(friday, "2026-10-23", "2026-10-22", {"NVDA": -1, "MSFT": 1}))
        intraday = self.close_report(monday.replace(hour=18), "2026-10-26", "2026-10-23",
                                     {"NVDA": 1, "MSFT": -1}, timing="regular_session")
        later = self.close_report(monday.replace(day=27), "2026-10-27", "2026-10-26", {"NVDA": 1, "MSFT": -1})
        disjoint = self.close_report(monday, "2026-10-26", "2026-10-23", {"NVDA": 1, "AMD": -1})
        for report in (intraday, later, disjoint):
            with self.subTest(report=watchlist_breadth.market_snapshot(report)):
                self.assertNotIn("Watchlist follow-through", self.render(report=report))
        bad_counts = later.replace("Breadth: 1 up / 1 down / 2 quoted", "Breadth: 2 up / 0 down / 2 quoted")
        self.assertIsNone(watchlist_breadth.closing_snapshot(watchlist_breadth.market_snapshot(bad_counts)))

    def checkpoint_fixture(self):
        friday = datetime(2026, 10, 23, 21, tzinfo=timezone.utc)
        monday = datetime(2026, 10, 26, 21, tzinfo=timezone.utc)
        symbols = {"NVDA": -1, "MSFT": -1, "GOOGL": -1, "CIBR": -1}
        self.render(report=self.close_report(friday, "2026-10-23", "2026-10-22", symbols))
        report = self.close_report(monday, "2026-10-26", "2026-10-23", symbols)
        return monday, symbols, self.render_current(report)

    def render_current(self, report):
        with patch.object(editor, "cache_candidates", return_value=([], [])), \
                patch.object(daily_report, "build_research_report", return_value=report), \
                patch.object(daily_report, "DAILY_REPORT_LIVE_QUOTES", False):
            return daily_report.build_daily_report()

    def deliver(self, brief, when, *, error=None):
        from src.jobs import daily_report_scheduler as scheduler

        bot = SimpleNamespace(send_message=AsyncMock(side_effect=[None, error] if error else None))
        with patch.object(scheduler, "build_daily_report_safe", AsyncMock(return_value=brief)), \
                patch.object(store.time, "time", return_value=when.timestamp()):
            return asyncio.run(scheduler.send_daily_report_to_chat(bot, 1))

    def test_delivered_checkpoint_ignores_previews_and_uses_exact_same_names(self):
        monday, _, brief = self.checkpoint_fixture()
        tuesday = monday + timedelta(days=1)
        self.assertIn("2 or fewer", brief)
        research = self.close_report(tuesday, "2026-10-27", "2026-10-26",
                                     {"NVDA": -2, "MSFT": 2, "GOOGL": -1, "CIBR": 0, "AMD": -2})
        text = self.render_current(research)
        self.assertNotIn("What Changed Since Our Last Brief", text)
        self.assertTrue(self.deliver(brief, monday + timedelta(seconds=1)))
        self.assertTrue(self.deliver(brief, monday + timedelta(seconds=2)))
        self.assertEqual(store.confirmed_watchlist_ids(tuesday), [self.record(brief)["id"]])
        text = self.render_current(research)
        body = section(text, "What Changed Since Our Last Brief")
        self.assertEqual(body, "At the October 27 close, 2 of the same 4 watchlist names fell, down from 4. "
                               "That met our target of 2 or fewer decliners.")
        record = self.record(text)
        verdict = record["analyst_review"]["evidence"]["watchlist_verdict"]
        self.assertEqual(verdict["symbols"], ["CIBR", "GOOGL", "MSFT", "NVDA"])
        self.assertIn("Watchlist checkpoint: MET | close 2026-10-27 | 4/4 quoted | delivered edition " + self.record(brief)["id"],
                      editor.build_editor_status())
        self.assertIn("two of the same four watchlist names fell", daily_voiceover.checked(record)["script"])
        with self.assertRaisesRegex(ValueError, "lost its verified copy"):
            analysis.validate_review(record["analyst_review"], research, text.replace("That met our target", "That missed our target"), [])

    def test_incomplete_coverage_stays_pending_and_can_resolve_later_for_same_close(self):
        monday, symbols, brief = self.checkpoint_fixture()
        tuesday = monday + timedelta(days=1)
        self.assertTrue(self.deliver(brief, monday + timedelta(seconds=1)))
        partial = self.close_report(tuesday, "2026-10-27", "2026-10-26",
                                    {**{key: -1 for key in symbols if key != "CIBR"}, "AMD": 1})
        text = self.render_current(partial)
        self.assertIn("Comparable quotes covered 3 of the 4 names", section(text, "What Changed Since Our Last Brief"))
        self.assertIn("Watchlist checkpoint: LIMITED", editor.build_editor_status())
        full = self.close_report(tuesday + timedelta(minutes=5), "2026-10-27", "2026-10-26", {**symbols, "MSFT": 1})
        self.assertIn("That missed our target of 2 or fewer decliners", self.render_current(full))
        intraday = self.close_report(tuesday.replace(hour=18), "2026-10-27", "2026-10-26", symbols, timing="regular_session")
        skipped = self.close_report(tuesday + timedelta(days=1), "2026-10-28", "2026-10-27", symbols)
        for report in (intraday, skipped):
            self.assertNotIn("What Changed Since Our Last Brief", self.render_current(report))

    def test_failed_telegram_send_does_not_register_a_checkpoint(self):
        from telegram.error import TelegramError

        monday, _, brief = self.checkpoint_fixture()
        self.assertFalse(self.deliver(brief, monday + timedelta(seconds=1), error=TelegramError("offline simulated failure")))
        self.assertEqual(store.confirmed_watchlist_ids(monday + timedelta(minutes=1)), [])

    def test_takeaway_follows_greeting_and_precedes_every_news_section(self):
        text = self.render()
        at = text.index("The takeaway:")
        self.assertLess(text.index("Good afternoon."), at)
        self.assertTrue(all(at < text.index(header + "\n") for header in news.HEADERS))
        self.assertIn("All three major indexes fell", text[:text.index("Market Update")])
        self.assertEqual(text.count("The takeaway:"), 1)

    def test_watch_explains_the_next_observation_and_why_it_matters(self):
        text = self.render(); watch = section(text, "What We're Watching")
        self.assertIn("18 quoted stocks and funds on our watchlist", watch)
        self.assertIn("7 finished higher and 11 lower", watch)
        self.assertIn("Watch whether the share of decliners falls in the next session", watch)
        self.assertIn("reduce margins", watch)
        self.assertNotIn("disclosures, price and volume support these research ideas", watch)
        review = self.record(text)["analyst_review"]
        target = review["evidence"]["company_focus"]["selected"][0]
        self.assertTrue(watch.startswith(f"{target['name']} ({target['symbol']}) — "))
        self.assertIn("Watchlist breadth —", watch)
        self.assertTrue(2 <= len(review["insights"]) <= 20)

    def test_watch_uses_plain_language_instead_of_model_or_entry_jargon(self):
        watch = section(self.render(), "What We're Watching").lower()
        for phrase in ("setup risk", "score risk", "conviction", "alignment", "scorecard", "signal stack", "buy now"):
            self.assertNotIn(phrase, watch)

    def test_verified_large_move_leads_without_inventing_a_cause(self):
        text = self.render(report=self.outlier())
        opening = text.split("The takeaway:", 1)[1].split("\n\n", 1)[0]
        watch = section(text, "What We're Watching")
        self.assertIn("Alphabet fell 12.0 percent", opening)
        self.assertNotIn("Compare the move with original results and guidance", opening)
        self.assertIn("Watch original results and guidance", watch)
        self.assertNotIn("whether selling spreads", opening)
        self.assertTrue(watch.startswith("Alphabet (GOOGL) — Watch original results and guidance"))
        self.assertIn("price move alone cannot explain it", watch)
        self.assertNotIn("caused", text.lower())

    def test_pending_large_move_cannot_become_a_confirmed_opening_fact(self):
        text = self.render(report=self.outlier(False))
        opening = text.split("The takeaway:", 1)[1].split("\n\n", 1)[0]
        self.assertNotIn("Alphabet's sharp decline", opening)
        self.assertNotIn("12.0 percent", text)
        self.assertTrue(section(text, "What We're Watching").startswith("Alphabet (GOOGL) — The unusually large reported move"))
        self.assertIn("stock split could change the reading", text)

    def test_watch_keeps_the_quoted_share_class(self):
        events.review_quotes({"GOOG": quote("GOOG", -12)}, lambda _: quote("GOOG", -12), NOW)
        text = self.render(report=self.research(replacements={
            "Watchlist Movers": "Largest regular-session movers:\n• GOOG: $88.00 (-12.00%)"}))
        watch = section(text, "What We're Watching")
        self.assertTrue(watch.startswith("Alphabet (GOOG) — Watch original results and guidance"))
        self.assertNotIn("Alphabet (GOOGL)", watch)

    def test_opposing_index_directions_are_explained_without_a_market_wide_claim(self):
        report = self.research(replacements={"Executive Summary": "- Main theme: Mixed.\n- Market moves: S&P -0.17%, Nasdaq -1.04%, Russell +1.22%, VIX -2.9%, Oil -1.56%, TLT +0.53%."})
        text = self.render(report=report)
        self.assertIn("Nasdaq fell while the Russell index rose", text)
        self.assertIn("Watch whether the share of decliners falls in the next session", section(text, "What We're Watching"))
        self.assertNotIn("all stocks are falling", text.lower())

    def test_higher_indexes_and_weak_watchlist_have_a_scoped_takeaway(self):
        report = self.research(replacements={"Executive Summary": "- Main theme: Growth.\n- Market moves: S&P +0.5%, Nasdaq +0.4%, Russell +0.1%."})
        text = self.render(report=report)
        self.assertIn("All three major indexes rose in the completed session", text)
        self.assertIn("Most names in our tracked group still finished lower", text)
        self.assertIn("a majority of the quoted list rising in the next session", text)

    def test_closed_session_watch_preserves_completed_session_tense(self):
        watch = section(self.render(), "What We're Watching")
        self.assertIn("finished higher", watch)
        self.assertNotIn("are higher", watch)

    def test_missing_session_does_not_supply_a_current_price_or_breadth_claim(self):
        report = self.research(replacements={"Market Snapshot": "Market Session: Closed.\nBreadth: 7 up / 11 down / 18 quoted"})
        text = self.render([candidate()], report)
        self.assertIn("Market coverage is incomplete", text)
        self.assertIn("Major indexes — We still need a dated view", section(text, "What We're Watching"))
        self.assertNotIn("7 finished higher", text)
        self.assertNotIn("Rising oil prices", text)

    def test_funded_work_and_start_dates_are_the_contract_follow_up(self):
        story = candidate("CACI", title="CACI awarded an Army contract valued at up to $185 million",
            source_excerpt="CACI announced a five-year Army task order valued at up to $185 million for expeditionary power systems.", excerpt_scope="original release excerpt")
        with patch.dict("os.environ", {"SPECIAL_ALERT_SYMBOLS": "MSFT,NVDA,TSM,CACI"}):
            text = self.render([story])
        watch = section(text, "What We're Watching")
        self.assertTrue(watch.startswith("CACI International (CACI) —"))
        self.assertIn("committed funding and a start date", watch)
        self.assertIn("potential award can become sales", watch)
        self.assertNotIn("booked $185 million", text)

    def test_product_watch_explains_the_commercial_test(self):
        text = self.render([candidate("MSFT", title="Microsoft introduces a multi-model AI platform")])
        watch = section(text, "What We're Watching")
        self.assertTrue(watch.startswith("Microsoft (MSFT) —"))
        self.assertIn("paying customers and the cost of serving them", watch)
        self.assertIn("profits and cash generation", watch)

    def test_removed_or_unconfirmed_story_does_not_supply_a_business_watch(self):
        value = candidate("NVDA", official=False, title="Nvidia announces record quarterly earnings")
        text = self.render([value])
        self.assertNotIn("Compare sales, profits and cash generation with management's outlook", section(text, "What We're Watching"))
        self.assertNotIn(value["title"], text)

    def test_opening_and_every_watch_signal_are_bound_to_the_research_edition(self):
        report = self.research(); text = self.render(report=report)
        record = self.record(text); reviewed = record["analyst_review"]
        self.assertEqual(reviewed["reader_version"], 4)
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
        for options in ({"reader_version": 5}, {"reader_version": True}, {"reader_version": 1, "reader_limit": 0}, {"reader_version": 1, "reader_limit": True}):
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
        self.assertIn("All 18 quoted stocks and funds on our watchlist finished lower", intro)
        self.assertIn("selling is easing", section(text, "What We're Watching"))
        self.assertNotIn("whether selling spreads", intro)
        self.assertNotIn("whether the move spreads", intro)

    def test_watchlist_declines_do_not_become_a_claim_about_every_stock(self):
        report = self.research(replacements={"Market Snapshot": self.snapshot(),
            "Executive Summary": "- Main theme: Uneven.\n- Market moves: S&P +0.5%, Nasdaq +0.4%, Russell +0.2%."})
        text = self.render(report=report)
        intro = text.split("The takeaway:", 1)[1].split("\n\n", 1)[0]
        self.assertIn("All 18 quoted stocks and funds on our watchlist finished lower", intro)
        self.assertNotIn("All three major indexes fell", intro)
        self.assertNotIn("every stock", text.lower())
        self.assertIn("a majority of the quoted list rising in the next session", text)

    def test_closed_session_check_looks_forward_to_the_next_session(self):
        text = self.render(report=self.research(replacements={"Market Snapshot": self.snapshot()}))
        watch = section(text, "What We're Watching")
        self.assertEqual(text.count("All 18 quoted stocks and funds on our watchlist finished lower"), 1)
        self.assertNotIn("All 18 quoted stocks and funds on our watchlist finished lower", watch)
        self.assertIn("in the next session", watch)
        self.assertIn("selling is easing", watch)
        self.assertNotIn("0 finished higher", watch)

    def test_live_session_check_can_still_change_before_the_close(self):
        text = self.render(report=self.research(replacements={"Market Snapshot": self.snapshot(live=True)}))
        watch = section(text, "What We're Watching")
        self.assertEqual(text.count("All 18 quoted stocks and funds on our watchlist are lower"), 1)
        self.assertNotIn("All 18 quoted stocks and funds on our watchlist are lower", watch)
        self.assertIn("by the close", watch)
        self.assertNotIn("in the next session", watch)
        self.assertNotIn("finished", watch)

    def test_all_gains_are_a_staying_power_check_not_a_request_for_more_names(self):
        text = self.render(report=self.research(replacements={"Market Snapshot": self.snapshot(up=18, down=0),
            "Executive Summary": "- Main theme: Strong.\n- Market moves: S&P +0.5%, Nasdaq +0.4%, Russell +0.2%."}))
        watch = section(text, "What We're Watching")
        self.assertEqual(text.count("All 18 quoted stocks and funds on our watchlist finished higher"), 1)
        self.assertNotIn("All 18 quoted stocks and funds on our watchlist finished higher", watch)
        self.assertIn("whether the share of advancers holds", watch)
        self.assertNotIn("more companies join", watch)

    def test_missing_session_cannot_supply_the_new_participation_claim(self):
        text = self.render(report=self.research(replacements={"Market Snapshot": self.snapshot(dated=False)}))
        self.assertNotIn("All 18", text)
        self.assertNotIn("All three major indexes fell", text)
        self.assertIn("Market coverage is incomplete", text)

    def test_unknown_index_directions_are_not_filled_from_the_watchlist(self):
        text = self.render(report=self.research(replacements={"Market Snapshot": self.snapshot(),
            "Executive Summary": "- Main theme: Limited.\n- Market moves: Nasdaq -1.5%."}))
        self.assertIn("All 18 quoted stocks and funds on our watchlist finished lower", text)
        self.assertNotIn("All three major indexes fell", text)

    def test_tied_participation_does_not_assert_a_recovery_or_a_rally(self):
        text = self.render(report=self.research(replacements={"Market Snapshot": self.snapshot(up=9, down=9)}))
        watch = section(text, "What We're Watching")
        self.assertIn("Watchlist breadth —", watch)
        self.assertIn("would show selling spreading within the watchlist", watch)
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
        self.assertEqual(record["rules_version"], 32)
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
        self.assertIn("whether the share of advancers holds", section(text, "What We're Watching"))
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
