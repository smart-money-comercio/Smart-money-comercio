"""Offline checks for original ownership evidence and the House Clerk pilot."""

import argparse
import asyncio
from contextlib import ExitStack
from datetime import timedelta
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_alphabet_sources import pdf
from scripts.check_disclosure_refresh import ACCESSION, MSFT_CIK, NOW, NVDA_CIK, RefreshChecks, submissions
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from scripts.check_transaction_disclosures import form4
from src.congress import congress_data as congress, house_clerk
from src.insiders import insider_data as sec
from src.intelligence import ownership_signals as ownership, special_alert_context, special_alert_store as alert_store
from src.intelligence import transaction_cache as cache
from src.jobs import daily_agent_job, disclosure_refresh, special_alert_scheduler
from src.reports import congress_report


OLDER = "0001234567-26-000001"
NEWER = "0001234567-26-000002"
PTR_ID = "20035999"
PTR_URL = house_clerk.document_url(2026, PTR_ID)


def purchase(**changes):
    return form4(**{"security_title": "Common Stock", **changes})


def form4_payload(*rows):
    return {"source": "SEC Form 4", "trades": list(rows),
            "observations": {MSFT_CIK: {"provider": "SEC Form 4", "at": NOW.timestamp()}}}


def schedule13d(*, amended=False, percent="6.2", owner="0001234567", cusip="594918104", issuer=MSFT_CIK):
    submission = "SCHEDULE 13D/A" if amended else "SCHEDULE 13D"
    return f"""<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13D">
    <headerData><submissionType>{submission}</submissionType></headerData>
    <formData><coverPageHeader><securitiesClassTitle>Common Stock</securitiesClassTitle><dateOfEvent>10/19/2026</dateOfEvent>
      <issuerInfo><issuerCIK>{issuer}</issuerCIK><issuerName>Microsoft Corp</issuerName>
        <issuerCusips><issuerCusipNumber>{cusip}</issuerCusipNumber></issuerCusips></issuerInfo></coverPageHeader>
      <reportingPersons><reportingPersonInfo><reportingPersonCIK>{owner}</reportingPersonCIK>
        <reportingPersonName>Example Capital</reportingPersonName><aggregateAmountOwned>6000000</aggregateAmountOwned>
        <percentOfClass>{percent}</percentOfClass></reportingPersonInfo></reportingPersons>
      <items1To7><item4><transactionPurpose>The securities are held for investment.</transactionPurpose></item4></items1To7>
    </formData></edgarSubmission>""".encode()


def schedule_index(cik=MSFT_CIK):
    value = submissions(cik, has_form=False)
    value["filings"]["recent"] = {"form": ["SCHEDULE 13D/A", "SCHEDULE 13D"], "accessionNumber": [NEWER, OLDER],
                                   "filingDate": ["2026-10-23", "2026-10-20"], "reportDate": ["", ""],
                                   "primaryDocument": ["xslSCHEDULE_13D_X01/primary_doc.xml", "primary_doc.xml"]}
    return value


def mixed_index():
    original = submissions(MSFT_CIK, has_form=True)
    for field, values in schedule_index()["filings"]["recent"].items():
        original["filings"]["recent"][field].extend(values)
    return original


def house_archive(*entries, year=2026):
    columns = "Prefix\tLast\tFirst\tSuffix\tFilingType\tStateDst\tYear\tFilingDate\tDocID\n"
    rows = [f"\tFiler\tExample\t\t{kind}\tCA01\t{year}\t{filed}\t{document}\n" for kind, filed, document in entries]
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(f"{year}FD.txt", columns + "".join(rows))
    return output.getvalue()


def house_pdf(*body, document=PTR_ID, name="Hon. Example Filer"):
    return pdf(["PERIODIC TRANSACTION REPORT", f"Name: {name}", "Status: Member", "State/District: CA01",
                "Owner   Asset   Type   Date   Notification Date   Amount", *body, f"Filing ID #{document}"])


PURCHASE = "SP   Nvidia Corp Common Stock (NVDA) [ST]   P   10/22/2026   10/23/2026   $100,001 - $250,000"


class SignalChecks(unittest.TestCase):
    def test_two_distinct_filers_get_a_stable_cluster_with_original_sources(self):
        first = purchase(reporting_owner_cik="0000000100")
        second = purchase(accession="0000789019-26-999998", insider_name="Example Officer", reporting_owner_cik="0000000200",
                          transaction_date="2026-09-28", filing_date="2026-09-29")
        result, = ownership.purchase_clusters(form4_payload(first, second), NOW)
        reordered, = ownership.purchase_clusters(form4_payload(second, first, second), NOW)
        self.assertEqual(result, reordered)
        text = ownership.alert_text(result)
        self.assertIn("Example Director and Example Officer", text)
        self.assertIn("2026-09-28, filed 2026-09-29", text)
        self.assertIn(first["url"], text)
        self.assertIn(second["url"], text)

    def test_cluster_filters_repeated_owner_amendments_and_nonpurchase_rows(self):
        first = purchase(reporting_owner_cik="0000000100")
        second = dict(accession="0000789019-26-999998", insider_name="Example Officer")
        for changes in ({"reporting_owner_cik": first["reporting_owner_cik"]}, {"insider_name": first["insider_name"]},
                        {"accession": ACCESSION}, {"rule_10b5_1": True}, {"security_type": "Derivative"},
                        {"security_title": "Preferred Stock"}, {"joint_reporting": True}, {"transaction_code": "M"},
                        {"shares": 10}, {"transaction_date": "2026-09-20"}, {"filing_date": "2026-10-26"},
                        {"form": "4/A"}):
            with self.subTest(changes=changes):
                self.assertEqual(ownership.purchase_clusters(form4_payload(first, purchase(**(second | changes))), NOW), [])
        amended = purchase(accession="0000789019-26-999997", form="4/A", shares=1)
        self.assertEqual(ownership.purchase_clusters(form4_payload(first, purchase(**second), amended), NOW), [])

    def stake_payload(self, *, percent="7.4", owner="0001234567", cusip="594918104"):
        current, prior = ownership.source_filings(schedule_index(), NOW.date())
        rows = [ownership.parse_ownership(raw, MSFT_CIK, "MSFT", filing, ownership.filing_base(MSFT_CIK, filing[1]) + "primary_doc.xml")
                for filing, raw in ((current, schedule13d(amended=True, percent=percent, owner=owner, cusip=cusip)),
                                    (prior, schedule13d()))]
        rows[0]["prior_accession"] = OLDER
        return {"ownership_filings": rows, "ownership_checks": {MSFT_CIK: NOW.timestamp()}}

    def test_matches_13d_owner_and_class_before_comparing_a_change(self):
        for percent, phrase in (("7.4", "up from 6.2%"), ("4.5", "down from 6.2%")):
            with self.subTest(percent=percent):
                alert, = ownership.stake_changes(self.stake_payload(percent=percent), NOW)
                text = ownership.alert_text(alert)
                self.assertIn(phrase, text)
                self.assertIn("Shares reported: 6,000,000", text)
                self.assertIn("The securities are held for investment.", text)
                self.assertIn(OLDER.replace("-", ""), text)
        for changes in ({"percent": "6.9"}, {"owner": "0007654321"}, {"cusip": "000000001"}):
            with self.subTest(changes=changes):
                self.assertFalse(ownership.stake_changes(self.stake_payload(**changes), NOW))

    def test_initial_stake_and_incomplete_or_wrong_source_documents(self):
        payload = self.stake_payload()
        current, prior = payload["ownership_filings"]
        payload["ownership_filings"] = [prior]
        alert, = ownership.stake_changes(payload, NOW)
        self.assertIn("6.2% beneficial ownership", ownership.alert_text(alert))
        payload["ownership_filings"] = [current]
        self.assertEqual(ownership.stake_changes(payload, NOW), [])
        filing = ownership.source_filings(schedule_index(), NOW.date())[0]
        with self.assertRaisesRegex(ValueError, "issuer"):
            ownership.parse_ownership(schedule13d(amended=True, issuer="0000000002"), MSFT_CIK, "MSFT", filing, current["url"])
        with self.assertRaisesRegex(ValueError, "Invalid"):
            ownership.parse_ownership(b"<!DOCTYPE x>" + schedule13d(amended=True), MSFT_CIK, "MSFT", filing, current["url"])


class HouseChecks(unittest.TestCase):
    def test_house_reads_a_pdf_and_preserves_the_original_value_range_and_owner(self):
        entry, = house_clerk.index_rows(house_archive(("P", "10/24/2026", PTR_ID), ("O", "10/24/2026", "10035999")), 2026, NOW.date())
        row, = house_clerk.document_rows(house_pdf(PURCHASE, "      Filing Status: New"), entry)
        self.assertEqual((row["ticker"], row["owner"], row["amount_range"]), ("NVDA", "spouse", "$100,001 - $250,000"))
        self.assertEqual((row["transaction_date"], row["disclosure_date"], row["source_url"]), ("2026-10-22", "2026-10-24", PTR_URL))
        text = congress_report.build_congress_report([row], {"NVDA": 50}, "NVDA")
        self.assertIn("Trade: 2026-10-22 | Filed: 2026-10-24", text)
        self.assertIn(PTR_URL, text)
        self.assertGreater(congress_report.amount_rank("$100,001 - $250,000"), congress_report.amount_rank("$50,001 - $500,000"))

    def test_corporate_actions_options_and_wrong_documents_are_excluded(self):
        entry, = house_clerk.index_rows(house_archive(("P", "10/24/2026", PTR_ID)), 2026, NOW.date())
        for note in ("Description: Cash proceeds from the merger.", "Description: Purchase of put options.",
                     "Description: Automatic dividend reinvestment."):
            with self.subTest(note=note):
                self.assertFalse(house_clerk.document_rows(house_pdf(PURCHASE, "    Filing Status: New", "     " + note), entry))
        self.assertFalse(house_clerk.document_rows(house_pdf(PURCHASE, "    Filing Status: Amended"), entry))
        with self.assertRaisesRegex(ValueError, "match the index"):
            house_clerk.document_rows(house_pdf(PURCHASE, document="20035000"), entry)

    def test_wrapped_stock_name_and_amount_stay_on_the_same_trade(self):
        entry, = house_clerk.index_rows(house_archive(("P", "10/24/2026", PTR_ID)), 2026, NOW.date())
        row, = house_clerk.document_rows(house_pdf(
            "      Nvidia Corporation - Common    S (partial)   10/22/2026   10/23/2026   $100,001 -",
            "      Stock (NVDA) [ST]                                                    $250,000",
            "      Filing Status: New"), entry)
        self.assertEqual((row["ticker"], row["owner"], row["transaction"], row["amount_range"]),
                         ("NVDA", "self", "Sale", "$100,001 - $250,000"))


class WorkflowChecks(RefreshChecks):
    def test_schedule13d_reuses_the_existing_issuer_submissions_response(self):
        def respond(request, timeout):
            url = request.full_url
            if url.endswith(MSFT_CIK + ".json"):
                self.requests.append(url)
                return BytesIO(json.dumps(mixed_index()).encode())
            if url.endswith("/primary_doc.xml"):
                self.requests.append(url)
                return public_response(url, schedule13d(amended=NEWER.replace("-", "") in url,
                                                         percent="7.4" if NEWER.replace("-", "") in url else "6.2"))
            return self.network(request, timeout)

        with patch.dict(os.environ, {"SEC_OWNERSHIP_ALERTS_ENABLED": "true"}), \
                patch.object(disclosure_refresh, "urlopen", side_effect=respond), \
                patch.object(disclosure_refresh, "build_opener", return_value=SimpleNamespace(open=respond)):
            result = disclosure_refresh.refresh_due(NOW)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(sum(url.endswith(MSFT_CIK + ".json") for url in self.requests), 1)
            self.assertEqual(sum(url.endswith("/primary_doc.xml") for url in self.requests), 2)
            with patch.object(special_alert_scheduler, "collect_inputs", return_value=({}, [], [])), \
                    patch.object(special_alert_scheduler, "datetime", FrozenAlertClock):
                snapshot = special_alert_scheduler.collect_snapshot()
            alert, = snapshot["alerts"]
            self.assertEqual(alert["kind"], "ownership_stake")
            self.assertIn("Schedule 13D: 2", snapshot["source_status"]["SEC Ownership"])
            alert_store.record_snapshot([alert], {}, NOW.timestamp())
            self.assertIn("7.4% beneficial ownership", special_alert_context.event_fact(alert))
            self.assertTrue(alert_store.claim(1, alert, NOW.timestamp()))
            alert_store.finish(1, alert, NOW.timestamp(), True)
            self.assertFalse(alert_store.claim(1, alert, NOW.timestamp() + 60))

    def test_schedule13d_coverage_is_saved_when_form4_is_unreadable(self):
        with patch.dict(os.environ, {"SEC_OWNERSHIP_ALERTS_ENABLED": "true"}), \
                patch.object(sec, "get_watchlist_symbols", return_value=["MSFT"]), \
                patch.object(disclosure_refresh, "form4_rows", side_effect=disclosure_refresh.SECEvidenceError("SEC filing XML could not be matched")):
            result = disclosure_refresh.refresh_due(NOW)
            payload, _ = cache.read(self.sec)
            self.assertEqual(result["status"], "limited")
            self.assertEqual(payload["observations"], {})
            self.assertEqual(payload["ownership_checks"], {MSFT_CIK: NOW.timestamp()})
            self.assertIn("MSFT Form 4 document: SEC filing XML could not be matched", result["detail"])
            alerts, status = ownership.collect(NOW)
            self.assertFalse(alerts)
            self.assertIn("Schedule 13D: 1", status)
            self.assertIn("Latest refresh", status)

    def test_form4_coverage_survives_a_bad_current_13d_document(self):
        def respond(request, timeout):
            url = request.full_url
            if url.endswith(MSFT_CIK + ".json"):
                return BytesIO(json.dumps(mixed_index()).encode())
            if url.endswith("/primary_doc.xml"):
                return public_response(url, b"Invalid XML")
            return self.network(request, timeout)

        with patch.dict(os.environ, {"SEC_OWNERSHIP_ALERTS_ENABLED": "true"}), \
                patch.object(disclosure_refresh, "urlopen", side_effect=respond), \
                patch.object(disclosure_refresh, "build_opener", return_value=SimpleNamespace(open=respond)):
            result = disclosure_refresh.refresh_due(NOW)
            payload, _ = cache.read(self.sec)
            self.assertEqual(result["status"], "limited")
            self.assertEqual(payload["observations"][MSFT_CIK]["at"], NOW.timestamp())
            self.assertEqual(payload["ownership_checks"], {NVDA_CIK: NOW.timestamp()})
            self.assertIn("MSFT Schedule 13D document: SEC filing XML could not be verified", result["detail"])
            self.assertFalse(ownership.collect(NOW)[0])

    def test_schedule13d_can_catch_up_without_rereading_fresh_form4(self):
        old = NOW - timedelta(minutes=20)
        snapshot = form4_payload()
        snapshot["observations"][MSFT_CIK]["at"] = old.timestamp()
        cache.publish(self.sec, snapshot)
        with patch.dict(os.environ, {"SEC_OWNERSHIP_ALERTS_ENABLED": "true"}), \
                patch.object(sec, "get_watchlist_symbols", return_value=["MSFT"]), \
                patch.object(disclosure_refresh, "form4_rows") as form4_reader:
            result = disclosure_refresh.refresh_due(NOW)
            form4_reader.assert_not_called()
            payload, _ = cache.read(self.sec)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(payload["observations"], snapshot["observations"])
            self.assertEqual(payload["ownership_checks"], {MSFT_CIK: NOW.timestamp()})
            self.assertIn("Schedule 13D 1/1", result["detail"])

    def test_missing_older_13d_baseline_keeps_the_new_filing_without_a_change_alert(self):
        index = schedule_index()
        index["filings"]["recent"]["filingDate"][1] = "2026-10-18"
        reader = SimpleNamespace(bytes=lambda url, **_: schedule13d(amended=True) if NEWER.replace("-", "") in url else b"Invalid XML")
        saved = []
        ownership.read_issuer(index, MSFT_CIK, "MSFT", saved, reader, NOW)
        self.assertEqual([row["accession"] for row in saved], [NEWER])
        self.assertFalse(ownership.stake_changes({"ownership_filings": saved, "ownership_checks": {MSFT_CIK: NOW.timestamp()}}, NOW))

    def deny_fmp(self):
        for endpoint in ("house-latest", "senate-latest"):
            self.source_failures[endpoint] = HTTPError("https://host.test/?apikey=synthetic-private-key", 402, "denied", {}, None)

    def test_fmp_denial_falls_back_to_the_house_clerk_without_changing_scores(self):
        def respond(request, timeout):
            url = request.full_url
            if url == house_clerk.index_url(2026):
                return public_response(url, house_archive(("P", "10/24/2026", PTR_ID)))
            if url == PTR_URL:
                return public_response(url, house_pdf(PURCHASE, "      Filing Status: New"))
            return self.network(request, timeout)

        self.deny_fmp()
        with patch.dict(os.environ, {"CONGRESS_HOUSE_CLERK_ENABLED": "true"}), \
                patch.object(disclosure_refresh, "urlopen", side_effect=respond), \
                patch.object(disclosure_refresh, "build_opener", return_value=SimpleNamespace(open=respond)):
            result = disclosure_refresh.refresh_due(NOW)
            self.assertEqual(result["status"], "limited")
            self.assertIn("0/2 chambers with current dated coverage", result["detail"])
            self.assertIn("House Clerk pilot — 1 report read", result["detail"])
            self.assertIn("Senate HTTP 402", result["detail"])
            rows, coverage = congress.cached_coverage(NOW)
            self.assertEqual(len(rows), 1)
            self.assertIn("bounded sample", coverage)
            self.assertEqual(congress.get_congress_trades(), [])
            self.assertFalse(congress.cached_coverage(NOW + timedelta(hours=37))[0])
            from src.commands import intelligence_commands as commands
            update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
            with patch.object(commands, "send_split_message", new_callable=AsyncMock) as send:
                asyncio.run(commands.congress(update, SimpleNamespace(args=["NVDA"])))
            output = send.await_args.args[1]
            self.assertIn("$100,001 - $250,000", output)
            self.assertIn("Congress Score: 50/100", output)
            self.assertIn(PTR_URL, output)
            path = congress.house_clerk_path()
            snapshot, _ = cache.read(path)
            disclosure_refresh.refresh_congress(NOW + timedelta(hours=7))
            self.assertEqual(cache.read(path)[0]["fetched_at"], snapshot["fetched_at"])

    def test_house_index_denial_is_visible_without_a_cache(self):
        def respond(request, timeout):
            self.requests.append(request.full_url)
            raise HTTPError(request.full_url, 403, "denied", {}, None)

        self.deny_fmp()
        with patch.dict(os.environ, {"CONGRESS_HOUSE_CLERK_ENABLED": "true", "SEC_OWNERSHIP_ALERTS_ENABLED": "true"}), \
                patch.object(disclosure_refresh, "build_opener", return_value=SimpleNamespace(open=respond)):
            self.assertIn("Awaiting the first recorded check", congress.cached_coverage(NOW)[1])
            result = disclosure_refresh.refresh_due(NOW)
            rendered = daily_agent_job.format_daily_agent_result({"success": True, "steps": [
                {"name": "Disclosure Source Refresh", **result}]})
            self.assertIn("Schedule 13D 2/2", rendered)
            self.assertIn("Senate HTTP 402", rendered)
            self.assertIn("House Clerk pilot — Annual index: HTTP 403", rendered)
            self.assertNotIn("synthetic-private-key", rendered)
            self.assertFalse(congress.house_clerk_path().exists())
            rows, coverage = congress.cached_coverage(NOW)
            self.assertFalse(rows)
            self.assertIn("House Clerk pilot — Annual index: HTTP 403; next check after", coverage)
            self.requests.clear()
            disclosure_refresh.refresh_due(NOW + timedelta(hours=1))
            self.assertFalse(self.requests)

    def test_house_keeps_verified_reports_before_a_rate_limit(self):
        denied_id = "20035998"
        denied_url = house_clerk.document_url(2026, denied_id)

        def respond(request, timeout):
            url = request.full_url
            if url == house_clerk.index_url(2026):
                return public_response(url, house_archive(("P", "10/24/2026", PTR_ID), ("P", "10/24/2026", denied_id)))
            if url == PTR_URL:
                return public_response(url, house_pdf(PURCHASE, "      Filing Status: New"))
            if url == denied_url:
                raise HTTPError(url, 429, "rate limited", {"Retry-After": "9000"}, None)
            raise AssertionError("Unexpected House Clerk request")

        self.deny_fmp()
        with patch.dict(os.environ, {"CONGRESS_HOUSE_CLERK_ENABLED": "true"}), \
                patch.object(disclosure_refresh, "build_opener", return_value=SimpleNamespace(open=respond)) as opener:
            disclosure_refresh.refresh_due(NOW)
            rows, coverage = congress.cached_coverage(NOW)
            self.assertEqual([row["source_url"] for row in rows], [PTR_URL])
            self.assertIn("1 pending or unread", coverage)
            self.assertIn("report access HTTP 429", coverage)
            self.assertFalse(congress.get_congress_trades())
            opener.reset_mock()
            disclosure_refresh.refresh_due(NOW + timedelta(hours=2))
            opener.assert_not_called()

    def test_house_zero_pending_reports_is_distinct_from_unreadable_reports(self):
        for raw, description in ((house_archive(), "0 pending or unread"),
                                 (house_archive(("P", "10/24/2026", PTR_ID)), "1 report could not be verified")):
            with self.subTest(description=description):
                def respond(request, timeout):
                    url = request.full_url
                    return public_response(url, raw if url == house_clerk.index_url(2026) else b"Scanned image only")
                with patch.dict(os.environ, {"CONGRESS_HOUSE_CLERK_ENABLED": "true"}), \
                        patch.object(congress, "CACHE_FILE", self.root / ("empty" if "0 pending" in description else "unreadable") / "congress.json"), \
                        patch.object(disclosure_refresh, "build_opener", return_value=SimpleNamespace(open=respond)):
                    self.deny_fmp()
                    disclosure_refresh.refresh_congress(NOW)
                    rows, coverage = congress.cached_coverage(NOW)
                    self.assertFalse(rows)
                    self.assertIn(description, coverage)

    def test_refresh_does_not_overwrite_a_usable_13d_snapshot(self):
        saved = {"ownership_filings": [], "ownership_checks": {MSFT_CIK: NOW.timestamp()}}
        cache.publish(self.sec, {**form4_payload(), **saved})
        sec.write_trade_cache([purchase()])
        current, _ = cache.read(self.sec)
        self.assertEqual(current["ownership_filings"], saved["ownership_filings"])
        self.assertEqual(current["ownership_checks"], saved["ownership_checks"])


class FrozenAlertClock:
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def public_response(url, raw):
    response = BytesIO(raw)
    response.geturl = lambda: url
    return response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows-socketpair", action="store_true")
    args = parser.parse_args()
    tests = unittest.TestSuite()
    for test_type in (SignalChecks, HouseChecks):
        tests.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(test_type))
    tests.addTests(WorkflowChecks(name) for name in (
        "test_schedule13d_reuses_the_existing_issuer_submissions_response",
        "test_schedule13d_coverage_is_saved_when_form4_is_unreadable",
        "test_form4_coverage_survives_a_bad_current_13d_document",
        "test_schedule13d_can_catch_up_without_rereading_fresh_form4",
        "test_missing_older_13d_baseline_keeps_the_new_filing_without_a_change_alert",
        "test_fmp_denial_falls_back_to_the_house_clerk_without_changing_scores",
        "test_house_index_denial_is_visible_without_a_cache",
        "test_house_keeps_verified_reports_before_a_rate_limit",
        "test_house_zero_pending_reports_is_distinct_from_unreadable_reports",
        "test_refresh_does_not_overwrite_a_usable_13d_snapshot",
    ))
    with ExitStack() as stack:
        if args.windows_socketpair:
            stack.enter_context(patch.object(socket, "socketpair", portable_tcp_socketpair))
        network = stack.enter_context(offline_network_guard())
        result = unittest.TextTestRunner().run(tests)
    passed = result.wasSuccessful() and not network["blocked"]
    print(f"Ownership Signals Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
