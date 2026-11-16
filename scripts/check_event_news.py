"""Offline contracts for quote attention, event priority and issuer calendars."""

from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import Mock, patch
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_news_editor import candidate
from scripts.check_hourly_research import ResearchFixture, Client
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.intelligence import market_event_desk as events, company_schedule as schedules, news_editor as editor, news_editor_store as store
from src.intelligence import company_catalyst_context as catalysts, daily_brief_analysis as analysis, weekend_store
from src.reports.daily_news_brief import build_daily_news_brief, validate_news_brief
from src.utils.yahoo_quote import parse_regular_quote


def quote(symbol="GOOGL", move=-12, now=NOW):
    day = now.astimezone(ZoneInfo("America/New_York")).date()
    while day.weekday() >= 5: day -= timedelta(days=1)
    start = datetime(day.year, day.month, day.day, 13, 30, tzinfo=timezone.utc)
    end = start.replace(hour=20, minute=0)
    previous = day-timedelta(days=3 if day.weekday() == 0 else 1)
    before = start.replace(year=previous.year, month=previous.month, day=previous.day)
    price = 100*(1+move/100)
    evidence = {"meta": {"symbol": symbol, "instrumentType": "EQUITY", "currency": "USD", "exchangeTimezoneName": "America/New_York",
        "regularMarketPrice": price, "regularMarketTime": min(now, end).timestamp(),
        "currentTradingPeriod": {"regular": {"start": start.timestamp(), "end": end.timestamp()}}},
        "timestamp": [before.timestamp(), start.timestamp()], "indicators": {"quote": [{"close": [100, price], "volume": [1000, 1200]}]}}
    value = parse_regular_quote(symbol, evidence, now)
    return {**value, "quote_evidence": evidence}


class EventQuoteChecks(IsolatedChecks):
    def report(self, symbol="GOOGL", move=-12):
        return self.research(replacements={"Watchlist Movers": f"Relevant research universe: 18 symbols\nLargest regular-session movers:\n• {symbol}: $88.00 ({move:+.2f}%)"})

    def test_large_move_rechecks_the_same_provider_without_changing_original_quotes(self):
        values = {"GOOGL": quote()}; before = deepcopy(values); fetch = Mock(return_value=quote(move=-12.1))
        result = events.review_quotes(values, fetch, NOW)
        fetch.assert_called_once_with("GOOGL")
        self.assertEqual(result[0]["status"], "rechecked")
        self.assertEqual(values, before)

    def test_only_three_issuer_checks_are_read_and_alphabet_share_classes_are_deduplicated(self):
        values = {symbol: quote(symbol, move) for symbol, move in (("MSFT", -15), ("GOOGL", -14), ("GOOG", -13), ("AAPL", 12), ("NVDA", 11))}
        fetch = Mock(side_effect=lambda symbol: deepcopy(values[symbol]))
        rows = events.review_quotes(values, fetch, NOW)
        self.assertEqual(len(rows), 3); self.assertEqual(fetch.call_count, 3)
        self.assertEqual({row["issuer"] for row in rows}, {"MSFT", "GOOGL", "AAPL"})

    def test_small_moves_unknown_instruments_and_missing_chart_evidence_do_not_trigger_reads(self):
        values = {"MSFT": quote("MSFT", 4.9), "SPCX": quote("SPCX", 12), "NVDA": {"ok": True, "change_percent": -12}}
        fetch = Mock(side_effect=AssertionError("No qualifying evidence"))
        self.assertEqual(events.review_quotes(values, fetch, NOW), [])
        fetch.assert_not_called()

    def test_displayed_returns_cannot_override_the_native_price_or_dated_close(self):
        value = quote(); value["change_percent"] = -18
        fetch = Mock(side_effect=AssertionError("Invalid initial evidence"))
        self.assertEqual(events.review_quotes({"GOOGL": value}, fetch, NOW), [])

    def test_failed_recheck_and_conflicting_prior_close_stay_pending(self):
        values = {"GOOGL": quote()}
        row = events.review_quotes(values, Mock(side_effect=RuntimeError("Unavailable")), NOW)[0]
        self.assertEqual(row["status"], "quote check pending")
        changed = quote(); changed["previous_close"] = 99
        rows = events.review_quotes(values, lambda _: changed, NOW+timedelta(minutes=16))
        self.assertEqual(rows[0]["status"], "quote check pending")

    def test_changed_direction_is_not_rechecked_confirmation(self):
        rows = events.review_quotes({"GOOGL": quote()}, lambda _: quote(move=12), NOW)
        self.assertEqual(rows[0]["status"], "quote changed; check pending")

    def test_split_evidence_requires_a_corporate_action_check(self):
        value = quote(); value["quote_evidence"]["events"] = {"splits": {"fixture": {"splitRatio": "2:1"}}}
        row = events.review_quotes({"GOOGL": value}, lambda _: quote(), NOW)[0]
        self.assertEqual(row["status"], "corporate action check")

    def test_recent_recheck_is_reused_but_its_clock_is_not_refreshed(self):
        values = {"GOOGL": quote()}; fetch = Mock(return_value=quote())
        first = events.review_quotes(values, fetch, NOW)[0]
        second = events.review_quotes(values, fetch, NOW+timedelta(minutes=10))[0]
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(first["recheck_at"], second["recheck_at"])
        events.review_quotes(values, fetch, NOW+timedelta(minutes=16))
        self.assertEqual(fetch.call_count, 2)

    def test_frozen_attention_cannot_swap_share_class_move_or_confirmation(self):
        events.review_quotes({"GOOGL": quote()}, lambda _: quote(), NOW)
        report = self.report(); context = events.context_for_report(report, NOW)
        events.checked_context(context, report, NOW)
        for field, value in (("status", "quote check pending"), ("source_symbol", "GOOG"), ("reported_move", -13)):
            changed = deepcopy(context); changed["events"][0][field] = value
            with self.assertRaises(ValueError): events.checked_context(changed, report, NOW)
        changed = deepcopy(context); changed["events"] = []
        with self.assertRaises(ValueError): events.checked_context(changed, report, NOW)

    def test_malformed_event_cache_is_a_pending_check_instead_of_a_report_failure(self):
        events.state_path().write_text('[]')
        context = events.context_for_report(self.report(), NOW)
        self.assertEqual(context["events"][0]["status"], "quote check pending")

    def test_pending_large_move_is_not_narrated_as_a_confirmed_numeric_move(self):
        report = self.report()
        text = build_daily_news_brief(report)
        self.assertIn("unusually large reported move is under review", text)
        self.assertNotIn("fell 12.0 percent", text)
        self.assertTrue(validate_news_brief(text)["passes"])

    def test_frozen_quote_attention_remains_readable_after_the_live_cache_changes(self):
        events.review_quotes({"GOOGL": quote()}, lambda _: quote(), NOW)
        report = self.report(); context = events.context_for_report(report, NOW)
        events.save_snapshot([])
        events.checked_context(context, report, NOW)
        self.assertEqual(context["events"][0]["status"], "rechecked")

    def test_intraday_search_cue_survives_until_next_hour_without_becoming_a_fresh_quote(self):
        when = datetime(2026, 10, 26, 14, tzinfo=timezone.utc)
        value = quote(now=when)
        events.review_quotes({"GOOGL": value}, lambda _: deepcopy(value), when)
        later = when+timedelta(minutes=35)
        self.assertEqual(events.search_hints(later)[0]["symbol"], "GOOGL")
        report = self.research(now=later, replacements={"Market Snapshot": "Market Session: Open — live session.\nQuote session: 2026-10-26\nBreadth: 4 up / 14 down / 18 quoted",
            "Watchlist Movers": "Largest regular-session movers:\n• GOOGL: $88.00 (-12.00%)"})
        self.assertEqual(events.context_for_report(report, later)["events"][0]["status"], "quote check pending")

    def test_future_and_swapped_session_fields_do_not_revalidate_quote_evidence(self):
        for key, value in (("session_date", "2026-10-26"), ("symbol", "GOOG"), ("asof", (NOW+timedelta(days=1)).isoformat())):
            changed = quote(); changed[key] = value
            self.assertEqual(events.review_quotes({"GOOGL": changed}, Mock(side_effect=AssertionError("Bad quote")), NOW), [])

    def test_rechecked_move_is_narrated_with_the_same_provider_qualification(self):
        events.review_quotes({"GOOGL": quote()}, lambda _: quote(), NOW)
        path = events.state_path(); before = path.read_bytes()
        with patch.object(events, "review_quotes", side_effect=AssertionError("Narration cannot fetch")):
            text = build_daily_news_brief(self.report())
        self.assertIn("fell 12.0 percent", text)
        self.assertIn("same provider", text)
        self.assertIn("price alone does not establish the cause", text.lower())
        self.assertEqual(path.read_bytes(), before)


class EventPriorityChecks(IsolatedChecks):
    report = EventQuoteChecks.report
    def financial(self, **changes):
        return candidate("GOOGL", title="Alphabet reports third-quarter financial results",
            source_excerpt="The company reported quarterly revenue and operating margins in its original financial tables. Management also described demand, expenses and its business outlook.",
            excerpt_scope="original release excerpt", **changes)

    def test_fresh_financial_disclosure_leads_a_rechecked_move_and_older_policy_story(self):
        events.review_quotes({"GOOGL": quote()}, lambda _: quote(), NOW)
        report = self.report(); context = events.context_for_report(report, NOW)
        policy = candidate(kind="macro", symbols=[], publisher_symbol="", title="Federal Reserve issues FOMC statement", source="Federal Reserve",
            url="https://www.federalreserve.gov/newsevents/pressreleases/fixture.htm", published=(NOW-timedelta(hours=18)).isoformat(),
            source_excerpt="The Committee decided to maintain the target range for the federal funds rate at 3.75 to 4 percent.", excerpt_scope="original release excerpt")
        values = [policy, self.financial(), candidate("MSFT"), candidate("LMT", title="Lockheed Martin awarded a defense contract")]
        with patch.object(editor, "cache_candidates", return_value=(values, [])):
            text = build_daily_news_brief(report)
        record = store.read_editions(report=text)[0]
        lead = next(row for row in record["candidates"] if row["id"] == record["lead_story_id"])
        self.assertEqual(lead["publisher_symbol"], "GOOGL")
        self.assertEqual(lead["event_priority"], 7)
        self.assertLess(text.index("Companies in Focus"), text.index("Policy & Economy"))
        self.assertIn("fell 12.0 percent", text)
        self.assertIn("a market cause is not established", text)
        self.assertEqual(record["market_event_context"], context)

    def test_a_headline_without_disclosure_text_does_not_receive_financial_promotion(self):
        report = self.report(); value = candidate("GOOGL", title="Alphabet reports quarterly financial results")
        plan = editor.build_editorial_plan(catalysts.build_company_catalyst_brief(), NOW, [value],
            event_context=events.context_for_report(report, NOW), research_report=report)
        story = editor.selected_stories(plan)[0]
        self.assertLess(story["event_priority"], 6)

    def test_priority_does_not_admit_an_unconfirmed_financial_headline(self):
        report = self.report(); value = self.financial(official=False)
        plan = editor.build_editorial_plan(catalysts.build_company_catalyst_brief(), NOW, [value],
            event_context=events.context_for_report(report, NOW), research_report=report)
        self.assertEqual(editor.selected_stories(plan), [])

    def test_original_ranking_memory_and_unprioritized_selection_are_retained(self):
        before = self.ranking.read_bytes(); report = self.report()
        with patch.object(editor, "cache_candidates", return_value=([self.financial()], [])):
            text = build_daily_news_brief(report)
        record = store.read_editions(report=text)[0]
        self.assertFalse(record["analyst_review"]["score_changes"])
        self.assertEqual(self.ranking.read_bytes(), before)
        unprioritized = editor.build_editorial_plan(catalysts.build_company_catalyst_brief(), NOW, [self.financial()])
        self.assertEqual(unprioritized["rules_version"], 16)
        self.assertNotIn("event_priority", unprioritized["candidates"][0])

    def test_changed_analyst_event_proof_is_rejected_against_the_research_edition(self):
        report = self.report(); text = build_daily_news_brief(report)
        record = store.read_editions(report=text)[0]; reviewed = deepcopy(record["analyst_review"])
        reviewed["event_context"]["events"][0]["reported_move"] = -20
        with self.assertRaises(ValueError): analysis.validate_review(reviewed, report, text, editor.selected_stories(record))


class EarningsWatchChecks(IsolatedChecks):
    preview_at = datetime(2026, 11, 14, 23, 18, tzinfo=timezone.utc)
    results_at = datetime(2026, 11, 17, 22, 30, tzinfo=timezone.utc)
    title = "Nvidia Announces CEO Transition"
    release = (
        "Nvidia's board announced today that Jordan Reed has resigned as President, Chief Executive Officer, and a member of the board.",
        "Taylor Ortiz, current chief financial officer of Nvidia, has agreed to serve as Interim Chief Executive Officer.",
        "Nvidia will report its third-quarter fiscal 2027 financial results on Tuesday, November 17, at approximately 1:20 p.m. PT, "
        "as previously scheduled, followed by its earnings call at 2 p.m. PT.",
    )

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"WEEKEND_STATE_FILE": str(self.root / "weekend.sqlite3")}))

    def scheduled_release(self, observed):
        return candidate("NVDA", title=self.title, source="Nvidia Newsroom",
                         url="https://nvidianews.nvidia.com/news/test-ceo-transition",
                         published="2026-11-12T13:48:00+00:00", source_checked_at=observed.isoformat(),
                         source_excerpt="\n".join(self.release), excerpt_scope="original release excerpt")

    def save_weekend(self, observed):
        source = self.scheduled_release(observed)
        notice = schedules.parse_notice(source, observed)
        data = {"generated_at": observed.isoformat(), "inputs": {"calendar": {"company": [notice]}}}
        weekend_store.save({**data, "id": weekend_store.identity(data)})
        return source

    def result_release(self, published="2026-11-17T21:20:00+00:00"):
        return candidate("NVDA", title="Nvidia Announces Financial Results for Third Quarter Fiscal 2027",
                         source="Nvidia Newsroom", url="https://nvidianews.nvidia.com/news/test-quarterly-results",
                         published=published, source_checked_at=self.results_at.isoformat(),
                         source_excerpt="NVIDIA (NASDAQ: NVDA) today reported revenue for the third quarter ended October 25, 2026, "
                         "of $42.0 billion. For the quarter, GAAP and non-GAAP gross margins were 72.1% and 72.3%, respectively.",
                         excerpt_scope="original release excerpt")

    def preview_report(self, candidates=()):
        with patch.object(editor, "cache_candidates", return_value=(list(candidates), [])):
            return build_daily_news_brief(self.research(now=self.preview_at))

    def guidance_response(self, quarter="third", published="August 26, 2026"):
        from src.intelligence.nvidia_guidance import preceding_release

        title, url = preceding_release(("third", 2027))
        body = (
            f'<h1>{title}</h1><div class="article-date">{published}</div>'
            '<div class="article-body"><p>' + ("Illustrative table cell. " * 310) + "</p>"
            f"<h2>Outlook</h2><p>NVIDIA’s outlook for the {quarter} quarter of fiscal 2027 is as follows:</p>"
            "<ul><li>Revenue is expected to be $40.0 billion, plus or minus 2%. Figures are company-wide.</li>"
            "<li>GAAP and non-GAAP gross margins are expected to be 73.5% and 76.0%, respectively, "
            "plus or minus 50 basis points.</li></ul></div>"
        )
        return {"status": "ok", "url": url, "final_url": url + "/", "body": body,
                "fetched_at_epoch": self.results_at.timestamp()}

    def test_lost_weekend_notice_supplies_daily_lead_source_and_specific_next_check(self):
        observed = self.preview_at - timedelta(hours=2)
        source = self.save_weekend(observed)
        with patch.object(editor.feeds, "fetch_url", side_effect=AssertionError("Fresh proof needs no fetch")) as fetch:
            text = self.preview_report()
        fetch.assert_not_called()
        record = store.read_editions(report=text)[0]
        watch = record["analyst_review"]["earnings_watch"]
        self.assertEqual(watch["phase"], "preview")
        self.assertEqual(watch["notice"]["source"]["source_checked_at"], observed.isoformat())
        self.assertIn("The takeaway: Nvidia's next earnings report follows a CEO change.", text)
        self.assertIn("On November 12, the company said Jordan Reed resigned and Taylor Ortiz would serve as interim CEO.", text)
        self.assertIn("Tuesday, November 17 at 05:00 PM EST", text)
        self.assertIn("Compare reported revenue and gross margin", text)
        self.assertIn("Original earnings source — " + source["url"], text)
        self.assertIn("calendar_NVDA", record["voiceover"]["segments"][0]["source_ids"])
        self.assertEqual(record["candidates"], [])

    def test_stale_calendar_observation_uses_original_article_with_new_observation(self):
        source = self.save_weekend(self.preview_at - timedelta(days=1))
        body = (f'<h1>{self.title}</h1><div class="article-date">November 12, 2026</div>'
                '<div class="article-body">' + "".join(f"<p>{p}</p>" for p in self.release) + "</div>")
        response = {"status": "ok", "url": source["url"], "body": body, "fetched_at_epoch": self.preview_at.timestamp()}
        with patch.object(editor.feeds, "fetch_url", return_value=response) as fetch:
            text = self.preview_report()
        fetch.assert_called_once_with(source["url"], cache_result=False)
        notice = store.read_editions(report=text)[0]["narrated_company_schedules"][0]
        self.assertEqual(notice["source"]["published"], source["published"])
        self.assertEqual(notice["source"]["source_checked_at"], self.preview_at.isoformat())

    def test_result_follows_the_previous_question_with_reported_figures_and_original_link(self):
        self.preview_report([self.scheduled_release(self.preview_at)])
        release = self.result_release()
        with patch.object(editor, "cache_candidates", return_value=([release], [])), \
                patch.object(editor.feeds, "fetch_url", return_value={"status": "error"}):
            research = self.research(now=self.results_at)
            text = build_daily_news_brief(research)
        record = store.read_editions(report=text)[0]
        watch = record["analyst_review"]["earnings_watch"]
        self.assertEqual(watch["phase"], "results")
        self.assertEqual(watch["preview"]["notice"]["event_date"], "2026-11-17")
        self.assertIn("We were watching Nvidia's revenue and margins.", text)
        self.assertIn("revenue of $42.0 billion for the third quarter and a GAAP gross margin of 72.1 percent.", text)
        self.assertIn("Original earnings source — " + release["url"], text)
        self.assertIn(watch["story_id"], record["voiceover"]["segments"][0]["source_ids"])
        self.assertTrue(record["voiceover"]["quality"]["passes"])
        altered = deepcopy(record["analyst_review"])
        altered["earnings_watch"]["revenue"] = "$49.0 billion"
        with self.assertRaisesRegex(ValueError, "Earnings watch does not match"):
            analysis.validate_review(altered, research, text, editor.selected_stories(record))

    def test_prior_guidance_answers_the_preview_and_carries_both_sources_into_narration(self):
        from src.intelligence import earnings_watch

        before = self.preview_report([self.scheduled_release(self.preview_at)])
        self.assertIn("Compare reported revenue and gross margin", before)
        original = self.guidance_response()
        release = self.result_release()
        release["source_excerpt"] += (
            "\nOutlook\nNVIDIA’s outlook for the fourth quarter of fiscal 2027 is as follows:\n"
            "GAAP and non-GAAP gross margins are expected to be 75.0%, plus or minus 50 basis points."
        )
        with patch.object(editor, "cache_candidates", return_value=([release], [])), \
                patch.object(editor.feeds, "fetch_url", return_value=original) as fetch:
            research = self.research(now=self.results_at)
            text = build_daily_news_brief(research)
        fetch.assert_called_once_with(original["url"])
        record = store.read_editions(report=text)[0]
        watch = record["analyst_review"]["earnings_watch"]
        self.assertEqual(watch["fiscal_year"], 2027)
        self.assertEqual(watch["guidance_comparison"]["revenue"]["position"], "above")
        self.assertEqual(watch["guidance_comparison"]["gaap_margin"]["position"], "below")
        self.assertLess(text.index(earnings_watch.COMPARISON_HEADER), text.index("Market Update"))
        self.assertIn("above its original $39.2 billion to $40.8 billion range", text)
        self.assertIn("GAAP gross margin was 72.1 percent, below the original 73 to 74 percent range.", text)
        self.assertIn("Management's next-quarter GAAP gross margin guidance is 74.5 to 75.5 percent.", text)
        self.assertIn("Original guidance source — " + original["url"], text)
        self.assertIn("Original earnings source — " + release["url"], text)
        scene = next(row for row in record["voiceover"]["segments"] if row["heading"] == "Earnings Follow-up")
        self.assertEqual(scene["source_ids"], [watch["story_id"], earnings_watch.GUIDANCE_SOURCE_ID])
        self.assertTrue(record["voiceover"]["quality"]["passes"])
        altered = deepcopy(record["analyst_review"])
        altered["earnings_watch"]["guidance_comparison"]["gaap_margin"]["position"] = "above"
        with self.assertRaisesRegex(ValueError, "Earnings watch does not match"):
            analysis.validate_review(altered, research, text, editor.selected_stories(record))

    def test_guidance_capture_withholds_wrong_quarters_late_releases_and_redirects(self):
        from src.intelligence import nvidia_guidance

        release = self.result_release()
        for response in (self.guidance_response(quarter="second"),
                         self.guidance_response(published="November 15, 2026"),
                         {**self.guidance_response(), "final_url": "https://example.com/copied-release"}):
            with self.subTest(response=response["final_url"]), self.assertRaises(ValueError):
                nvidia_guidance.capture(release, self.preview_at, self.results_at, lambda url: response)
        _, first_quarter_source = nvidia_guidance.preceding_release(("first", 2027))
        self.assertTrue(first_quarter_source.endswith("fourth-quarter-and-fiscal-2026"))

    def test_guidance_compares_millions_on_the_same_basis_and_includes_the_bounds(self):
        from src.intelligence import nvidia_guidance

        example = self.guidance_response()
        example["body"] = example["body"].replace("73.5% and 76.0%, respectively", "74.0%")
        proof = nvidia_guidance.capture(self.result_release(), self.preview_at, self.results_at, lambda url: example)
        comparisons = nvidia_guidance.comparisons(
            proof, {"revenue": "$40,800 million", "gaap_margin": "73.5"}, ("third", 2027),
        )
        self.assertEqual(comparisons["revenue"]["position"], "within")
        self.assertEqual(comparisons["gaap_margin"]["position"], "within")
        self.assertEqual(nvidia_guidance.next_range(proof["outlook"], ("third", 2027), "gaap_margin"), "")
    def test_other_release_date_cannot_close_the_earlier_earnings_preview(self):
        self.preview_report([self.scheduled_release(self.preview_at)])
        release = self.result_release(published="2026-11-16T23:30:00+00:00")
        with patch.object(editor, "cache_candidates", return_value=([release], [])):
            text = build_daily_news_brief(self.research(now=self.results_at))
        self.assertNotIn("We were watching Nvidia's revenue and margins.", text)

    def test_current_cancellation_suppresses_an_archived_daily_preview(self):
        source = self.save_weekend(self.preview_at - timedelta(hours=1))
        canceled = {**source, "title": "Nvidia Cancels Quarterly Earnings Call",
                    "url": source["url"] + "-canceled", "published": self.preview_at.isoformat(),
                    "source_checked_at": self.preview_at.isoformat()}
        text = self.preview_report([canceled])
        self.assertNotIn("Nvidia has scheduled its earnings conference call", text)
        self.assertNotIn("Original earnings source", text)

    def test_broad_selloff_still_leads_and_verified_report_closes_the_watch(self):
        self.preview_report([self.scheduled_release(self.preview_at)])
        release = self.result_release()
        with patch.object(editor, "cache_candidates", return_value=([release], [])), \
                patch.object(editor.feeds, "fetch_url", return_value={"status": "error"}):
            research = self.research(now=self.results_at, replacements={
                "Executive Summary": "- Main theme: Defensive market.\n- Market moves: S&P -2.50%, Nasdaq -3.12%, Russell -2.40%, VIX +21.21%, Oil +1.32%, TLT -0.49%.",
            })
            text = build_daily_news_brief(research)
        self.assertIn("The takeaway: The Nasdaq fell 3.12 percent", text)
        self.assertIn("Earnings follow-up — We were watching Nvidia's revenue and margins.", text)
        record = store.read_editions(report=text)[0]
        scene = next(row for row in record["voiceover"]["segments"] if row["heading"] == "What We're Watching")
        self.assertIn(record["analyst_review"]["earnings_watch"]["story_id"], scene["source_ids"])


class CompanyScheduleChecks(IsolatedChecks):
    def notice(self, text=None, **changes):
        value = candidate("NVDA", title="Nvidia Sets Conference Call for Quarterly Financial Results",
            source_excerpt=text or "Nvidia will host a conference call on Tuesday, November 3, at 2 p.m. PT (5 p.m. ET) to discuss its quarterly financial results, which ended October 25, 2026.",
            excerpt_scope="publisher feed excerpt")
        value.update(changes); return value

    def reaffirmation(self):
        return self.notice(title="Nvidia Announces a Leadership Update", excerpt_scope="original release excerpt",
                           text="Nvidia will report its quarterly financial results on Tuesday, November 3, at 1:20 p.m. PT, as previously scheduled, followed by its earnings call at 2 p.m. PT.")

    def test_reaffirmed_issuer_call_keeps_the_call_time_separate_from_results(self):
        value = self.reaffirmation()
        row = schedules.parse_notice(value, NOW)
        self.assertEqual((row["schema"], row["event_at"]), (2, "2026-11-03T17:00:00-05:00"))
        schedules.checked_notice(row, NOW)
        with patch.object(editor, "cache_candidates", return_value=([value], [])):
            report = build_daily_news_brief(self.research())
        record = store.read_editions(report=report)[0]
        self.assertIn("Tuesday, November 03 at 05:00 PM EST", report)
        self.assertIn("data center sales and margin guidance", report)
        self.assertIn("data center sales and margin guidance", record["voiceover"]["script"])
        self.assertTrue(record["voiceover"]["quality"]["passes"])

    def test_reaffirmation_needs_an_original_issuer_body_and_ordered_clocks(self):
        value = self.reaffirmation()
        text = value["source_excerpt"]
        for candidate in ({**value, "excerpt_scope": "publisher feed excerpt"},
                          {**value, "source_excerpt": text.replace("Nvidia will report", "Other Company will report")},
                          {**value, "source_excerpt": text.replace("2 p.m. PT", "1 p.m. PT")},
                          {**value, "source_excerpt": text.replace("2 p.m. PT", "2 p.m.")},
                          {**value, "source_excerpt": text.replace("2 p.m. PT", "2 p.m. PT (4 p.m. ET)")},
                          {**value, "evidence_checked_at": (NOW-timedelta(hours=7)).isoformat()}):
            with self.subTest(candidate=candidate):
                self.assertIsNone(schedules.parse_notice(candidate, NOW))

    def test_original_call_notice_resolves_the_unique_year_and_both_explicit_timezones(self):
        row = schedules.parse_notice(self.notice(), NOW)
        self.assertEqual(row["event_at"], "2026-11-03T17:00:00-05:00")
        self.assertEqual(row["event"], "earnings conference call")
        self.assertIn("original publication", row["year_basis"])
        schedules.checked_notice(row, NOW)

    def test_date_only_notice_keeps_its_time_unverified(self):
        row = schedules.parse_notice(self.notice(text="Nvidia will host a conference call on November 3, 2026 to discuss its financial results and answer questions from financial analysts and institutional investors."), NOW)
        self.assertEqual((row["precision"], row["event_at"]), ("date", ""))
        self.assertIn("does not supply a verified time", schedules.narration(row, schedules.NY, {"NVDA": "Nvidia"}))

    def test_wrong_weekday_conflicting_clocks_and_wrong_dst_do_not_become_calendar_facts(self):
        for old, new in (("Tuesday", "Wednesday"), ("5 p.m. ET", "6 p.m. ET"), ("2 p.m. PT", "2 p.m. PDT")):
            value = self.notice(); value["source_excerpt"] = value["source_excerpt"].replace(old, new)
            self.assertIsNone(schedules.parse_notice(value, NOW))

    def test_unconfirmed_stale_source_or_future_publication_does_not_confirm_a_schedule(self):
        for changes in ({"official": False}, {"source_checked_at": (NOW-timedelta(hours=7)).isoformat()},
                        {"published": (NOW+timedelta(hours=1)).isoformat()}, {"url": "https://example.com/copied"}):
            self.assertIsNone(schedules.parse_notice(self.notice(**changes), NOW))

    def test_an_old_original_announcement_can_confirm_a_future_calendar_event_without_becoming_news(self):
        value = self.notice(published=(NOW-timedelta(days=3)).isoformat())
        self.assertIsNotNone(schedules.parse_notice(value, NOW))
        plan = editor.build_editorial_plan(catalysts.build_company_catalyst_brief(), NOW, [value])
        self.assertEqual(plan["candidates"][0]["decision"], "wait")
        self.assertIn("older than 24 hours", plan["candidates"][0]["reason"])

    def test_conflicting_announcements_and_later_cancellation_withhold_the_schedule(self):
        value = self.notice()
        other = deepcopy(value); other["url"] += "-other"; other["source_excerpt"] = other["source_excerpt"].replace("Tuesday, November 3", "Wednesday, November 4")
        self.assertEqual(schedules.notices([value, other], NOW), [])
        canceled = deepcopy(value); canceled.update(title="Nvidia Cancels Quarterly Earnings Call", published=(NOW-timedelta(minutes=5)).isoformat())
        self.assertEqual(schedules.notices([value, canceled], NOW), [])

    def test_a_calendar_notice_is_skipped_as_news_and_included_in_whats_ahead(self):
        value = self.notice()
        with patch.object(editor, "cache_candidates", return_value=([value], [])):
            text = build_daily_news_brief(self.research())
        record = store.read_editions(report=text)[0]
        self.assertEqual(record["candidates"][0]["decision"], "skip")
        self.assertIn("Tuesday, November 03 at 05:00 PM EST", text)
        self.assertEqual(len(record["narrated_company_schedules"]), 1)
        self.assertEqual(record["narrated_company_schedules"][0]["source"]["url"], value["url"])

    def test_calendar_evidence_cannot_change_its_date_or_supporting_passage(self):
        row = schedules.parse_notice(self.notice(), NOW)
        for field, value in (("event_at", "2026-11-04T17:00:00-05:00"), ("source_quote", "An invented source passage")):
            altered = deepcopy(row); altered[field] = value
            with self.assertRaises(ValueError): schedules.checked_notice(altered, NOW)

    def test_a_confirmed_call_is_not_labeled_as_a_nasdaq_earnings_estimate(self):
        row = schedules.parse_notice(self.notice(), NOW)
        with patch.object(schedules, "cached_notices", return_value=[row]):
            brief = catalysts.build_company_catalyst_brief(now=NOW)
        company = next(value for value in brief["rows"] if value["symbol"] == "NVDA")
        self.assertEqual(company["calendar"]["status"], "confirmed")
        self.assertIn("earnings conference call", company["calendar"]["text"])
        self.assertNotIn("Nasdaq estimate", company["review"]["interpretation"])

    def test_a_stale_original_call_date_is_not_announced_as_upcoming(self):
        value = self.notice(text="Nvidia will host a conference call on October 24, 2026 at 2 p.m. PT to discuss its quarterly financial results and answer questions from financial analysts.",
                            published=(NOW-timedelta(days=4)).isoformat())
        self.assertIsNone(schedules.parse_notice(value, NOW))


class EventHandoffChecks(ResearchFixture):
    def test_outlier_attention_targets_the_existing_hourly_search_without_extra_requests(self):
        events.review_quotes({"GOOGL": quote()}, lambda _: quote(), NOW)
        client = Client(); result = self.run_desk(client)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0]["max_tool_calls"], 2)
        payload = json.loads(client.calls[0]["input"])
        self.assertEqual(payload["market_event_attention"][0]["symbol"], "GOOGL")
        self.assertIn("GOOG", payload["research_symbols"])
        self.assertIn("GOOGL", payload["research_symbols"])
        self.assertEqual(result["details"]["market_event_attention"][0]["quote_status"], "rechecked")
        second = self.run_desk(client)
        self.assertEqual(second["status"], "already attempted this hour")
        self.assertEqual(len(client.calls), 2)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--windows-socketpair", action="store_true"); args = parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair: stack.enter_context(patch.object(socket, "socketpair", portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    passed = result.wasSuccessful() and not traffic["blocked"]
    print(f"Event News Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())
