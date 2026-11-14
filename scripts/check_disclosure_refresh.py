"""Offline tests for scheduled disclosure ingestion and source-specific clocks."""

import argparse
import asyncio
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from scripts.check_transaction_disclosures import form4, ptr
from src.congress import congress_data as congress, congress_scoring
from src.insiders import insider_data as sec
from src.intelligence import transaction_cache as cache, transaction_disclosures as disclosures
from src.intelligence import news_editor as editor, news_editor_store as store
from src.jobs import disclosure_refresh as job
from src.reports import congress_report, daily_news_brief as news, daily_voiceover as voice


MSFT_CIK = "0000789019"
NVDA_CIK = "0001045810"
ACCESSION = "0000789019-26-999999"
SENATE_LINK = "https://efdsearch.senate.gov/search/view/ptr/12345678-1234-1234-1234-123456789abc/"
IDENTIFIERS = {"0": {"ticker": "MSFT", "cik_str": 789019, "title": "Microsoft"},
               "1": {"ticker": "NVDA", "cik_str": 1045810, "title": "Nvidia"}}
FORM4_XML = f"""<ownershipDocument><documentType>4</documentType>
  <issuer><issuerCik>{MSFT_CIK}</issuerCik><issuerTradingSymbol>MSFT</issuerTradingSymbol></issuer>
  <reportingOwner><reportingOwnerId><rptOwnerName>Example Director</rptOwnerName></reportingOwnerId>
  <reportingOwnerRelationship><isDirector>1</isDirector></reportingOwnerRelationship></reportingOwner>
  <nonDerivativeTransaction><transactionDate><value>2026-10-20</value></transactionDate>
  <transactionCoding><transactionCode>P</transactionCode></transactionCoding><transactionAmounts>
  <transactionShares><value>1000</value></transactionShares><transactionPricePerShare><value>240</value></transactionPricePerShare>
  <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
  <postTransactionAmounts><sharesOwnedFollowingTransaction><value>5000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
  <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
  </nonDerivativeTransaction></ownershipDocument>"""


class FrozenCongressClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)


def submissions(cik, has_form):
    recent = {"form": ["4"], "accessionNumber": [ACCESSION], "filingDate": ["2026-10-22"],
              "reportDate": ["2026-10-20"], "primaryDocument": ["xslF345X05/form4.xml"]}
    return {"cik": str(int(cik)), "filings": {"recent": recent if has_form else {key: [] for key in recent}}}


def fmp_row(chamber):
    return {"symbol": "NVDA", "office": "Example Filer", "disclosureDate": "2026-10-23", "transactionDate": "2026-09-24",
            "owner": "Spouse", "assetType": "Stock", "assetDescription": "Nvidia common stock", "type": "Purchase",
            "amount": "$15,001 - $50,000", "link": ptr()["source_url"] if chamber == "House" else SENATE_LINK}


class RefreshChecks(IsolatedChecks):
    def setUp(self):
        super().setUp()
        self.sec = self.root / "sec.json"
        self.congress = self.root / "congress.json"
        self.stack.enter_context(patch.dict(os.environ, {"OPENAI_API_KEY": "offline-import-check",
                                                        "SEC_USER_AGENT": "Smart Money test ops@research-lab.org",
                                                        "FMP_API_KEY": "synthetic-private-key", "CONGRESS_DATA_PROVIDER": "auto",
                                                        "CONGRESS_HOUSE_CLERK_ENABLED": "false", "SEC_OWNERSHIP_ALERTS_ENABLED": "false"}))
        self.stack.enter_context(patch.object(sec, "CACHE_FILE", self.sec))
        self.stack.enter_context(patch.object(sec, "CIK_CACHE_FILE", self.root / "ciks.json"))
        self.stack.enter_context(patch.object(sec, "utc_now_ts", return_value=NOW.timestamp()))
        self.stack.enter_context(patch.object(sec, "get_watchlist_symbols", return_value=["MSFT", "NVDA", "QQQ"]))
        self.stack.enter_context(patch.object(congress, "CACHE_FILE", self.congress))
        self.stack.enter_context(patch.object(congress, "datetime", FrozenCongressClock))
        self.requests = []
        self.unexpected = []
        self.addCleanup(lambda: self.assertEqual(self.unexpected, []))
        self.fail = {}
        self.stack.enter_context(patch.object(job, "urlopen", side_effect=self.network))

    def network(self, request, timeout):
        self.assertLessEqual(timeout, 4)
        url = request.full_url
        self.requests.append(url)
        for part, error in self.fail.items():
            if part in url:
                raise error
        if url == sec.COMPANY_TICKERS_URL:
            data = IDENTIFIERS
        elif "/submissions/" in url:
            cik = url.split("CIK")[-1].split(".")[0]
            data = submissions(cik, has_form=cik == MSFT_CIK)
        elif "/Archives/edgar/data/" in url:
            self.assertTrue(url.endswith("/form4.xml"))
            self.assertNotIn("xslF345X05", url)
            return BytesIO(FORM4_XML.encode())
        elif "/stable/house-latest?" in url:
            data = [fmp_row("House")]
        elif "/stable/senate-latest?" in url:
            data = [fmp_row("Senate")]
        else:
            self.unexpected.append(request.host + request.selector.split("?")[0])
            raise AssertionError("Unexpected disclosure request")
        return BytesIO(json.dumps(data).encode())

    def render(self, now=NOW):
        with patch.object(editor, "cache_candidates", return_value=([], [])):
            report = news.build_daily_news_brief(self.research(now=now))
        record = store.read_editions(report=report)[0]
        return report, record

    def test_automatic_records_reach_the_brief_and_voiceover(self):
        result = job.refresh_due(NOW)
        self.assertEqual(result["status"], "pass")
        self.assertIn("2/2 issuers", result["detail"])
        self.assertIn("2/2 chambers with current dated coverage", result["detail"])
        report, record = self.render()
        self.assertIn("Microsoft (MSFT) — A Form 4", report)
        self.assertIn("Nvidia (NVDA) purchase of $15,001 to $50,000", report)
        self.assertTrue(voice.checked(record, NOW)["quality"]["passes"])
        self.assertEqual(record["transaction_disclosures"]["schema"], 3)

    def test_fresh_caches_reuse_original_filings_and_respect_each_feed_interval(self):
        job.refresh_due(NOW)
        self.requests.clear()
        job.refresh_due(NOW + timedelta(minutes=1))
        job.refresh_due(NOW + timedelta(hours=1))
        self.assertEqual(self.requests, [])
        job.refresh_due(NOW + timedelta(seconds=sec.CACHE_TTL_SECONDS, minutes=1))
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all("/submissions/" in url for url in self.requests))

    def test_missing_sec_contact_does_not_block_congress(self):
        with patch.dict(os.environ, {"SEC_USER_AGENT": "", "SEC_API_USER_AGENT": ""}):
            result = job.refresh_due(NOW)
        self.assertEqual(result["status"], "limited")
        self.assertIn("Configure SEC_USER_AGENT", result["detail"])
        self.assertFalse(self.sec.exists())
        self.assertEqual(len(cache.rows(cache.read(self.congress)[0])), 2)

    def test_house_refresh_preserves_senate_evidence_and_its_older_clock(self):
        old = (NOW - timedelta(hours=40)).timestamp()
        senate = ptr(chamber="Senate", source_url=SENATE_LINK, amount_range="$50,001 - $100,000")
        cache.publish(self.congress, {"source": job.FMP_SOURCE, "fetched_at": old, "trades": [senate]})
        self.fail["senate-latest"] = HTTPError("https://host.test/?apikey=synthetic-private-key", 429, "request refused", {"Retry-After": "9000"}, None)
        result = job.refresh_due(NOW)
        payload, _ = cache.read(self.congress)
        self.assertIn("Senate HTTP 429", result["detail"])
        self.assertNotIn("synthetic-private-key", result["detail"])
        self.assertEqual(payload["observations"]["Senate"]["at"], old)
        self.assertEqual(payload["observations"]["House"]["at"], NOW.timestamp())
        self.assertIn(senate, payload["trades"])
        report, record = self.render()
        self.assertIn("House disclosure", report)
        self.assertEqual(record["transaction_disclosures"]["congress"]["reviewed"], 1)
        self.requests.clear()
        job.refresh_due(NOW + timedelta(hours=2))
        self.assertFalse(any("senate-latest" in url for url in self.requests))
        job.refresh_due(NOW + timedelta(hours=2, minutes=31))
        self.assertTrue(any("senate-latest" in url for url in self.requests))
        self.assertFalse(any("house-latest" in url for url in self.requests))

    def test_outage_keeps_last_good_sec_cache_and_persists_retry(self):
        old = (NOW - timedelta(hours=40)).timestamp()
        cache.publish(self.sec, {"source": job.SEC_SOURCE, "cached_at": old, "trades": [form4()]})
        before = self.sec.read_bytes()
        self.fail["/submissions/"] = HTTPError("https://data.sec.gov/", 403, "denied", {}, None)
        result = job.refresh_due(NOW)
        self.assertEqual(self.sec.read_bytes(), before)
        self.assertIn("HTTP 403", result["detail"])
        self.assertEqual(sum("/submissions/" in url for url in self.requests), 1)
        self.requests.clear()
        job.refresh_due(NOW + timedelta(hours=1))
        self.assertEqual(self.requests, [])

    def test_verified_zero_form4s_are_current_with_no_eligible_rows(self):
        with patch.object(sec, "get_watchlist_symbols", return_value=["NVDA"]):
            job.refresh_due(NOW)
        report, record = self.render()
        self.assertIn("SEC Form 4 — No watchlist trade", report)
        self.assertEqual(record["transaction_disclosures"]["sec"]["reviewed"], 0)

    def test_refresh_rotates_through_tracked_issuers(self):
        with patch.object(job, "SEC_BATCH", 1):
            first = job.refresh_due(NOW)
            self.assertIn("1/2 issuers", first["detail"])
            second = job.refresh_due(NOW + timedelta(minutes=15))
            self.assertIn("2/2 issuers", second["detail"])
        self.assertEqual(list(cache.read(self.sec)[0]["observations"]), [MSFT_CIK, NVDA_CIK])

    def test_partial_sec_refresh_does_not_freshen_an_unchecked_issuer(self):
        stale = (NOW - timedelta(hours=40)).timestamp()
        original = form4(ticker="NVDA", cik=NVDA_CIK, filing_date="2026-10-23", shares=15000)
        cache.publish(self.sec, {"source": job.SEC_SOURCE, "cached_at": stale, "trades": [original]})
        with patch.object(job, "SEC_BATCH", 1):
            job.refresh_due(NOW)
        report, record = self.render()
        self.assertIn("Microsoft (MSFT) — A Form 4", report)
        self.assertEqual(record["transaction_disclosures"]["sec"]["lead"]["ticker"], "MSFT")
        self.assertEqual(cache.read(self.sec)[0]["observations"][NVDA_CIK]["at"], stale)

    def test_historical_provider_feed_cannot_become_current(self):
        provider = [congress.normalize_fmp_trade({**fmp_row("House"), "disclosureDate": "2022-10-23", "transactionDate": "2022-09-24"}, "House")]
        with patch.dict(os.environ, {"CONGRESS_DATA_PROVIDER": "stockwatcher"}), patch.object(job, "stockwatcher_rows", return_value=provider):
            result = job.refresh_due(NOW)
        self.assertIn("Stock Watcher has no current dated disclosures", result["detail"])
        self.assertFalse(self.congress.exists())

    def test_http_retry_date_is_respected(self):
        retry = (NOW + timedelta(hours=3)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        error = HTTPError("https://host.test/", 429, "rate limit", {"Retry-After": retry}, None)
        self.assertEqual(job.retry_delay(error, NOW), 10800)

    def test_publisher_does_not_overwrite_concurrent_manual_update(self):
        manual = {"source": job.SEC_SOURCE, "cached_at": NOW.timestamp(), "trades": [form4()]}
        def concurrently_refreshed(payload, when, cursor):
            cache.publish(self.sec, manual)
            return {"source": job.SEC_SOURCE, "trades": []}, cursor, 900, "pass", "Updated"
        status, detail = job.refresh_source(self.sec, concurrently_refreshed, NOW)
        self.assertEqual(status, "limited")
        self.assertIn("Newer cache saved", detail)
        self.assertEqual(cache.read(self.sec)[0], manual)

    def test_recent_reservation_blocks_duplicate_worker(self):
        start = NOW.timestamp()
        self.assertEqual(cache.reserve(self.sec, start)[0], 0)
        second = Mock()
        self.assertEqual(job.refresh_source(self.sec, second, NOW + timedelta(seconds=1)), ("limited", "Refresh in progress"))
        second.assert_not_called()
        self.assertEqual(cache.reserve(self.sec, start + 901)[0], 0)

    def test_congress_scoring_reads_the_refreshed_cache(self):
        self.assertEqual(congress_scoring.get_congress_trades_safe(), [])
        job.refresh_due(NOW)
        rows = congress_scoring.get_congress_trades_safe()
        self.assertEqual({row["chamber"] for row in rows}, {"House", "Senate"})

    def test_refetched_2020_archive_cannot_influence_any_current_output(self):
        legacy = ptr(chamber="Senate", source_url=SENATE_LINK, amount_range="$1,000,001 - $5,000,000",
                     transaction_date="11/20/2020", disclosure_date="Unknown")
        snapshot = {"fetched_at": NOW.timestamp(), "source": job.STOCKWATCHER_SOURCE, "trades": [legacy]}
        for row in (legacy, {**legacy, "disclosure_date": "12/02/2020"}):
            cache.publish(self.congress, {**snapshot, "trades": [row]})
            rows, coverage = congress.cached_coverage(NOW)
            self.assertEqual(rows, [])
            self.assertIn("Senate — Unavailable", coverage)
            self.assertIn("2020-", coverage)
            self.assertEqual(congress_scoring.get_congress_score("NVDA"), 50)
            text = congress_report.build_congress_report(rows, {"NVDA": 50}, "NVDA", coverage)
            self.assertIn("50/100", text)
            self.assertNotIn("Strong positive", text)
            self.assertNotIn("Example Filer", text)
            brief, record = self.render()
            self.assertIn("Congressional disclosures — Current source data are unavailable", brief)
            self.assertEqual(record["transaction_disclosures"]["congress"]["reviewed"], 0)

    def test_same_cache_filters_old_future_undated_and_stale_other_chamber_rows(self):
        recent = ptr()
        invalid = [ptr(transaction_date="2020-11-20", disclosure_date="2020-12-02"),
                   ptr(disclosure_date="Unknown"), ptr(disclosure_date="2026-10-26"),
                   ptr(transaction_date="2026-10-24"), ptr(transaction_date="2026-07-01"),
                   ptr(ticker="N.A"), ptr(chamber="Senate", source_url=SENATE_LINK)]
        stamps = {"House": {"at": NOW.timestamp(), "provider": "FMP"},
                  "Senate": {"at": (NOW - timedelta(hours=40)).timestamp(), "provider": "FMP"}}
        cache.publish(self.congress, {"source": job.FMP_SOURCE, "observations": stamps, "trades": [recent, *invalid]})
        self.assertEqual(congress.get_congress_trades(), [recent])
        self.assertEqual(congress_scoring.get_congress_score("NVDA"), congress_scoring.get_congress_score("NVDA", trades=[recent]))
        self.assertGreater(congress_scoring.get_congress_score("NVDA"), 50)

    def test_unconfigured_fmp_status_and_plain_congress_read_stay_offline(self):
        with patch.dict(os.environ, {"CONGRESS_DATA_PROVIDER": "fmp", "FMP_API_KEY": ""}):
            status, detail = job.refresh_congress_now()
            self.assertEqual(status, "limited")
            self.assertIn("FMP_API_KEY required", detail)
            self.assertEqual(congress.get_congress_trades(), [])
        self.assertEqual(self.requests, [])

    def test_manual_congress_refresh_respects_active_provider_retry(self):
        self.fail["senate-latest"] = HTTPError("https://host.test/", 429, "rate limit", {"Retry-After": "9000"}, None)
        job.refresh_due(NOW)
        self.requests.clear()
        with patch.object(job, "datetime", FrozenCongressClock):
            status, detail = job.refresh_congress_now()
        self.assertEqual(status, "limited")
        self.assertIn("Senate HTTP 429", detail)
        self.assertFalse(any("senate-latest" in url for url in self.requests))
        self.assertTrue(any("house-latest" in url for url in self.requests))

    def test_house_402_leaves_senate_usable_and_surfaces_the_access_problem(self):
        self.fail["house-latest"] = HTTPError("https://host.test/", 402, "restricted", {}, None)
        result = job.refresh_due(NOW)
        self.assertEqual(result["status"], "limited")
        self.assertIn("1/2 chambers with current dated coverage", result["detail"])
        self.assertIn("House HTTP 402 from FMP", result["detail"])
        rows, coverage = congress.cached_coverage(NOW)
        self.assertEqual({row["chamber"] for row in rows}, {"Senate"})
        self.assertIn("House — Unavailable | HTTP 402 from FMP", coverage)
        self.assertIn("Senate — Current | FMP", coverage)
        brief, _ = self.render()
        self.assertIn("Senate disclosure", brief)

    def test_first_congress_page_survives_an_access_error_on_the_second(self):
        self.fail["page=1"] = HTTPError("https://host.test/", 402, "restricted", {}, None)
        with patch.object(congress, "PAGE_LIMIT", 1):
            result = job.refresh_due(NOW)
        self.assertEqual(result["status"], "limited")
        self.assertIn("2/2 chambers with current dated coverage", result["detail"])
        self.assertIn("additional FMP page HTTP 402", result["detail"])
        self.assertEqual({row["chamber"] for row in congress.cached_coverage(NOW)[0]}, {"House", "Senate"})

    def test_legacy_house_retry_does_not_block_senate(self):
        stamp = NOW.timestamp()
        cache.reserve(self.congress, stamp)
        cache.finish(self.congress, stamp, stamp + 21600, 0, "limited", "Congress — 1/2 chambers checked recently; House HTTP 402")
        result = job.refresh_due(NOW + timedelta(minutes=1))
        self.assertIn("1/2 chambers with current dated coverage", result["detail"])
        self.assertFalse(any("house-latest" in url for url in self.requests))
        self.assertTrue(any("senate-latest" in url for url in self.requests))
        self.assertIn("House — Unavailable | HTTP 402", congress.cached_coverage(NOW + timedelta(minutes=1))[1])

    def test_congress_command_reports_limited_instead_of_celebrating_archive(self):
        from src.commands import intelligence_commands as commands

        self.stack.enter_context(patch.object(commands, "is_admin_update", return_value=True))
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        update.message.reply_text.return_value = SimpleNamespace(edit_text=AsyncMock())
        context = SimpleNamespace(args=["refresh"])
        historical = {**fmp_row("Senate"), "transactionDate": "2020-11-20", "disclosureDate": "2020-12-02"}
        with patch.dict(os.environ, {"FMP_API_KEY": ""}), patch.object(job, "datetime", FrozenCongressClock), patch.object(
                job, "stockwatcher_rows", return_value=[congress.normalize_fmp_trade(historical, "Senate")]):
            asyncio.run(commands.congress(update, context))
        notice = update.message.reply_text.return_value.edit_text.await_args.args[0]
        self.assertIn("Congress Coverage Limited", notice)
        self.assertIn("Current Records: 0", notice)
        self.assertIn("configure FMP_API_KEY", notice)
        self.assertNotIn("Cache Refreshed", notice)

    def test_schedule_is_registered_and_runs_off_event_loop(self):
        queue = Mock()
        job.schedule_disclosure_refresh(SimpleNamespace(job_queue=queue))
        args, options = queue.run_repeating.call_args
        self.assertEqual(args, (job.disclosure_refresh_job,))
        self.assertEqual(options["first"], 30)
        self.assertEqual(options["interval"], 900)
        self.assertEqual(options["job_kwargs"]["max_instances"], 1)
        worker = AsyncMock(return_value={"status": "pass", "detail": "Checked"})
        with patch.object(job.asyncio, "to_thread", worker):
            asyncio.run(job.disclosure_refresh_job(None))
        worker.assert_awaited_once_with(job.refresh_due)

    def test_bot_starts_disclosure_job_without_a_chat_command(self):
        from src import bot

        app = Mock()
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(StringIO()))
            stack.enter_context(patch.object(bot, "BOT_TOKEN", "offline-fixture"))
            builder = stack.enter_context(patch.object(bot, "ApplicationBuilder"))
            builder.return_value.token.return_value.build.return_value = app
            for name in ("register_commands", "schedule_daily_report", "schedule_startup_notification", "schedule_watchlist_alerts",
                         "schedule_special_alerts", "schedule_premarket", "schedule_hourly_research"):
                stack.enter_context(patch.object(bot, name))
            bot.main()
        app.job_queue.run_repeating.assert_called_once()
        self.assertIs(app.job_queue.run_repeating.call_args.args[0], job.disclosure_refresh_job)
        app.run_polling.assert_called_once()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows-socketpair", action="store_true")
    args = parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:
            stack.enter_context(patch.object(socket, "socketpair", portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        tests = unittest.defaultTestLoader.loadTestsFromTestCase(RefreshChecks)
        result = unittest.TextTestRunner(verbosity=1).run(tests)
    passed = result.wasSuccessful() and not traffic["blocked"]
    print(f"Disclosure Refresh Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
