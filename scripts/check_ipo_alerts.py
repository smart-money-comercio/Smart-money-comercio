"""Offline IPO milestone, source, delivery and news-edition checks."""

import argparse
import asyncio
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.config.special_alerts import settings
from src.intelligence import ipo_monitor as ipo, special_alert_engine as engine, special_alert_store as store, news_editor
from src.jobs import special_alert_scheduler as job
from src.reports.daily_news_brief import build_daily_news_brief, validate_news_brief


class IPOChecks(IsolatedChecks):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"AI_IPO_ISSUERS_JSON": "{}", "AI_IPO_ALERTS_ENABLED": "true"}))
        self.cfg = {**settings(), "symbols": [], "ipo_enabled": True, "ipo_hours": 24}
        self.row = ipo.DEFAULT_ISSUERS["anthropic"]

    def value(self, form="S-1", excerpt="This is an initial public offering. We intend to list under the symbol ‘EXAI’."):
        accession = "0001628280-26-000001"
        return ipo.item("anthropic", self.row, f"Anthropic: Form {form} filed for a proposed initial public offering",
            "https://www.sec.gov/Archives/edgar/data/2130357/" + accession.replace("-", "") + "/fixture.htm",
            (NOW-timedelta(minutes=15)).isoformat(), excerpt, NOW.isoformat(), form=form, accession=accession)

    def feed_request(self, calls, *, form="S-1", excerpt="This is an initial public offering."):
        def request(url, prefix=False):
            calls.append((url, prefix))
            if "data.sec.gov/submissions/" in url:
                return json.dumps({"cik": 2130357, "filings": {"recent": {"form": [form], "acceptanceDateTime": [(NOW-timedelta(minutes=15)).isoformat()],
                    "accessionNumber": ["0001628280-26-000001"], "primaryDocument": ["fixture.htm"]}}}).encode()
            if "www.sec.gov/Archives/" in url:
                return ("<html><p>"+excerpt+"</p></html>").encode()
            return b"<rss><channel></channel></rss>"
        return request

    def test_public_ipo_filing_does_not_require_a_watchlist_symbol(self):
        event = engine.evaluate({}, [self.value()], NOW, self.cfg)[0]
        self.assertEqual(event["kind"], "ipo"); self.assertEqual(event["symbols"], [])
        self.assertIn("Public IPO registration filed", event["text"])
        self.assertNotIn("buy ANT", event["text"])

    def test_registration_form_alone_does_not_establish_an_ipo(self):
        for excerpt in ("This registration covers resale shares.", "Our initial public offering occurred ten years ago.", "The AI company is raising private capital."):
            self.assertIsNone(self.value(excerpt=excerpt))

    def test_supported_sec_forms_keep_their_distinct_stages(self):
        for form, stage in ipo.FORMS.items():
            self.assertEqual(self.value(form)["ipo"]["stage"], stage)

    def test_final_prospectus_without_a_price_is_not_priced(self):
        self.assertEqual(self.value("424B4")["ipo"]["stage"], "prospectus")
        self.assertEqual(self.value("424B4", "This is an initial public offering. The initial public offering price is $24.00 per share.")["ipo"]["stage"], "priced")

    def test_company_stages_do_not_collapse_plans_into_trading(self):
        for title, stage in (("OpenAI announces plans for an IPO", "plan"), ("OpenAI confidentially submits draft S-1 for an IPO", "confidential"),
                             ("OpenAI files S-1 for initial public offering", "filing"), ("OpenAI announces IPO pricing", "priced"),
                             ("OpenAI announces IPO price range", "terms"),
                             ("OpenAI IPO shares will begin trading tomorrow", "trading planned"), ("OpenAI IPO shares begin trading", "trading"),
                             ("OpenAI withdraws its IPO", "withdrawn")):
            self.assertEqual(ipo.company_stage(title), stage, title)

    def test_rumors_price_predictions_and_unconfirmed_plans_do_not_alert(self):
        for title in ("OpenAI reportedly files for IPO", "OpenAI could IPO", "Will OpenAI IPO?", "OpenAI denies IPO plans", "OpenAI expected to launch IPO"):
            self.assertIsNone(ipo.company_stage(title), title)

    def test_private_funding_is_not_an_ipo(self):
        self.assertIsNone(ipo.company_stage("OpenAI announces a new private funding round"))
        self.assertIsNone(ipo.company_stage("OpenAI announces a funding round ahead of its IPO"))
        self.assertIsNone(ipo.company_stage("OpenAI announces pre-IPO funding"))

    def test_issuer_post_about_somebody_elses_ipo_is_not_reassigned(self):
        row = ipo.DEFAULT_ISSUERS["openai"]
        for title in ("Anthropic announces IPO", "OpenAI invests in an AI company's IPO", "OpenAI announces support for Anthropic IPO"):
            self.assertIsNone(ipo.item("openai", row, title, "https://openai.com/news/fixture", NOW.isoformat(), title, NOW.isoformat()))

    def test_freshness_and_original_clocks_are_enforced(self):
        for field, value in (("published", "2026-10-25"), ("published", (NOW+timedelta(minutes=1)).isoformat()),
                             ("published", (NOW-timedelta(hours=25)).isoformat()), ("source_checked_at", (NOW-timedelta(hours=7)).isoformat())):
            record = self.value(); record[field] = value
            self.assertIsNone(ipo.alert(record, NOW, self.cfg))

    def test_symbol_is_qualified_and_no_price_or_valuation_is_invented(self):
        record = self.value(excerpt='This is an initial public offering under the symbol "EXAI".')
        text = ipo.alert(record, NOW, self.cfg)["text"]
        self.assertIn("EXAI; trading status requires separate confirmation", text)
        self.assertIn("verify the latest original offering terms", text)
        self.assertNotIn("$", text)

    def test_sec_issuer_cik_and_accession_paths_are_bound_to_evidence(self):
        for url in ("https://www.sec.gov/Archives/edgar/data/1/000162828026000001/fixture.htm", "https://www.sec.gov.attacker.test/Archives/fixture.htm", "http://www.sec.gov/Archives/fixture.htm"):
            record = self.value(); record["url"] = url
            self.assertIsNone(ipo.alert(record, NOW, self.cfg))

    def test_changed_excerpt_stage_date_and_symbol_are_rejected(self):
        for key, value in (("excerpt", "This is a resale offering."), ("stage", "trading"), ("proposed_symbol", "BUYME")):
            record = self.value(); record["ipo"][key] = value
            self.assertIsNone(ipo.alert(record, NOW, self.cfg))

    def test_collection_checks_the_original_sec_issuer_identity(self):
        request = self.feed_request([])
        raw = json.loads(request("https://data.sec.gov/submissions/test")); raw["cik"] = 1
        with self.assertRaisesRegex(ValueError, "identity"):
            ipo.sec_items("anthropic", self.row, json.dumps(raw).encode(), request, NOW, 24)

    def test_sec_detail_reads_are_bounded_and_explicitly_prefix_reads(self):
        calls = []; request = self.feed_request(calls)
        values = ipo.sec_items("anthropic", self.row, request("https://data.sec.gov/submissions/test"), request, NOW, 24)
        self.assertEqual(len(values), 1)
        self.assertEqual(sum(prefix for _, prefix in calls), 1)
        self.assertEqual(values[0]["published"], (NOW-timedelta(minutes=15)).isoformat())

    def test_cache_prevents_repeated_fetches_without_refreshing_the_publication(self):
        calls = []; request = self.feed_request(calls)
        first, status, issues = ipo.collect(NOW, self.cfg, request)
        count = len(calls)
        second, _, _ = ipo.collect(NOW+timedelta(minutes=1), self.cfg, request)
        self.assertEqual(len(calls), count); self.assertEqual(first, second)
        self.assertEqual(first[0]["published"], (NOW-timedelta(minutes=15)).isoformat())

    def test_a_failed_publisher_does_not_delay_a_healthy_sec_reader(self):
        calls = []; good = self.feed_request(calls)
        def request(url, prefix=False):
            if "openai.com" in url: raise HTTPError(url, 403, "fixture", {}, None)
            return good(url, prefix=prefix)
        ipo.collect(NOW, self.cfg, request)
        count = sum("data.sec.gov" in url for url, _ in calls)
        ipo.collect(NOW+timedelta(minutes=5), self.cfg, request)
        self.assertEqual(sum("data.sec.gov" in url for url, _ in calls), count+1)

    def test_a_later_milestone_replaces_earlier_source_cache_candidates(self):
        ipo.collect(NOW, self.cfg, self.feed_request([]))
        state = ipo.read_cache(); state["items"].append(self.value("S-1/A"))
        ipo.cache_path().write_text(json.dumps(state))
        values = ipo.cached_items(NOW)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["ipo"]["stage"], "amendment")

    def test_failed_sources_are_limited_and_retry_does_not_invent_a_milestone(self):
        def denied(url, **kwargs): raise HTTPError(url, 403, "fixture", {}, None)
        items, status, issues = ipo.collect(NOW, self.cfg, denied)
        self.assertEqual(items, []); self.assertIn("HTTP 403", status); self.assertTrue(issues)
        self.assertGreater(ipo.read_cache()["retry_at"], NOW.timestamp())

    def test_stale_cached_observations_cannot_become_current_after_a_failure(self):
        ipo.collect(NOW, self.cfg, self.feed_request([]))
        def denied(url, **kwargs): raise OSError("fixture")
        items, _, _ = ipo.collect(NOW+timedelta(hours=7), self.cfg, denied)
        self.assertEqual(items, [])

    def test_malformed_cache_records_are_withheld_without_writing(self):
        for payload in ({"items": {}}, {"items": [None, {}, "bad"]}):
            ipo.cache_path().write_text(json.dumps(payload)); before = ipo.cache_path().read_bytes()
            self.assertEqual(ipo.cached_items(NOW), [])
            self.assertEqual(before, ipo.cache_path().read_bytes())

    def test_configured_issuers_are_independent_of_stock_rankings(self):
        self.assertIn("anthropic", ipo.issuers()); self.assertIn("openai", ipo.issuers())
        with patch.dict(os.environ, {"AI_IPO_ISSUERS_JSON": '{"exampleai":{"name":"Example AI","domain":"example.ai","cik":"12345"}}'}):
            self.assertIn("exampleai", ipo.issuers())
        with patch.dict(os.environ, {"AI_IPO_ISSUERS_JSON": '{"bad":{"name":"Bad","domain":"bad.test","feed":"http://attacker.test/feed"}}'}):
            with self.assertRaises(ValueError): ipo.issuers()

    def test_new_stage_can_alert_once_without_repeating_the_same_stage(self):
        first = ipo.alert(self.value(), NOW, self.cfg)
        self.assertTrue(store.claim(1, first, NOW.timestamp())); store.finish(1, first, NOW.timestamp(), True)
        self.assertFalse(store.claim(1, first, NOW.timestamp()+60))
        amended = ipo.alert(self.value("S-1/A"), NOW, self.cfg)
        self.assertTrue(store.claim(1, amended, NOW.timestamp()+60))

    def test_agent_context_does_not_assign_a_stock_score_to_the_ipo(self):
        from src.agents.analyst_agent import review_special_event
        from src.intelligence.special_alert_context import event_fact
        event = ipo.alert(self.value(), NOW, self.cfg)
        review = review_special_event(event, [])
        self.assertFalse(review["score_changes"]); self.assertIn("No IPO score inferred", review["model_context"][0])
        self.assertIn("Public IPO registration filed", event_fact(event))

    def test_ipo_flows_into_the_news_brief_and_original_source_log(self):
        ipo.collect(NOW, self.cfg, self.feed_request([]))
        with patch.object(news_editor, "cache_candidates", return_value=([], [])):
            text = build_daily_news_brief(self.research())
        self.assertIn("Anthropic", text); self.assertIn("Public IPO registration filed", text)
        self.assertLess(text.index("Anthropic"), text.index("Market Update"))
        self.assertTrue(validate_news_brief(text)["passes"])
        self.assertIn("SEC EDGAR", news_editor.build_editor_status("ANTHROPIC", history=True))

    def test_disabled_ipo_monitor_does_not_fetch_or_emit(self):
        from unittest.mock import Mock
        request = Mock()
        self.assertEqual(ipo.collect(NOW, {**self.cfg, "ipo_enabled": False}, request), ([], "disabled", []))
        request.assert_not_called()
        self.assertEqual(engine.evaluate({}, [self.value()], NOW, {**self.cfg, "ipo_enabled": False}), [])

    def test_scheduler_keeps_delivery_receipts_and_the_shared_message_cap(self):
        event = ipo.alert(self.value(), NOW, self.cfg)
        alerts = [event] + [{**event, "key": "company:"+str(i), "kind": "company"} for i in range(4)]
        snapshot = {"asof": NOW.isoformat(), "alerts": alerts, "observations": {}, "issues": []}
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(job, "settings", return_value=self.cfg), patch.object(job, "destinations", return_value=[1]), patch.object(job, "collect_snapshot", return_value=snapshot), patch.object(job, "datetime") as clock:
            clock.now.return_value = NOW
            asyncio.run(job.special_alert_job(context))
        self.assertEqual(context.bot.send_message.await_count, 3)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows-socketpair", action="store_true")
    args = parser.parse_args(argv)
    with ExitStack() as stack:
        if args.windows_socketpair:
            stack.enter_context(patch.object(socket, "socketpair", portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(IPOChecks))
    ok = result.wasSuccessful() and not traffic["blocked"]
    print(f"AI IPO Alert Check: {'PASS' if ok else 'FAIL'} ({result.testsRun} tests)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
