"""Offline checks for the daily brief's public transaction disclosure review."""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.congress import congress_data
from src.insiders import insider_data
from src.intelligence import news_editor as editor, news_editor_store as store, transaction_disclosures as disclosures
from src.reports import daily_news_brief as news, daily_voiceover as voice


def form4(**changes):
    row = {"ticker": "MSFT", "cik": "0000789019", "form": "4", "accession": "0000789019-26-999999",
           "source": "SEC Form 4", "security_type": "Non-Derivative", "ownership": "D",
           "transaction_code": "P", "acquired_disposed": "A", "insider_name": "Example Director",
           "role": "Director", "shares": 1000, "price": 240.0, "shares_owned_after": 5000,
           "transaction_date": "2026-10-20", "filing_date": "2026-10-22"}
    row.update(changes)
    row["url"] = insider_data.build_filing_url({**row, "primary_document": "xslF345X05/form4.xml"})
    return row


def ptr(**changes):
    return {"ticker": "NVDA", "chamber": "House", "politician": "Example Filer", "transaction": "Purchase",
            "asset_type": "Stock", "sector": "Nvidia common stock", "owner": "SP", "amount_range": "$15,001 – $50,000",
            "transaction_date": "2026-09-24", "disclosure_date": "2026-10-23",
            "source_url": "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/99999999.pdf", **changes}


class DisclosureChecks(IsolatedChecks):
    def setUp(self):
        super().setUp()
        self.sec = self.root / "sec.json"
        self.congress = self.root / "congress.json"
        self.stack.enter_context(patch.object(insider_data, "CACHE_FILE", self.sec))
        self.stack.enter_context(patch.object(congress_data, "CACHE_FILE", self.congress))

    def seed(self, lane, rows, age=1, source=None):
        path = self.sec if lane == "sec" else self.congress
        clock = "cached_at" if lane == "sec" else "fetched_at"
        default = "SEC Form 4" if lane == "sec" else "FMP House/Senate congressional disclosure endpoints"
        path.write_text(json.dumps({clock: (NOW - timedelta(hours=age)).timestamp(), "source": source or default, "trades": rows}), encoding="utf-8")

    def capture(self):
        return disclosures.checked(disclosures.capture(NOW), NOW)

    def render(self):
        with patch.object(editor, "cache_candidates", return_value=([], [])):
            report = news.build_daily_news_brief(self.research())
        self.assertTrue(news.validate_news_brief(report)["passes"])
        return report, store.read_editions(report=report)[0]

    def test_each_source_reaches_brief_editor_log_and_voiceover(self):
        self.seed("sec", [form4()]); self.seed("congress", [ptr()])
        report, record = self.render()
        self.assertIn(disclosures.HEADER + "\nMicrosoft (MSFT)", report)
        self.assertIn("October 20 purchase worth about $240,000", report)
        self.assertIn("raised the reported direct holding by about 25%", report)
        self.assertIn("Nvidia (NVDA) purchase of $15,001 to $50,000 (spouse's holding), disclosed 29 days later on October 23", report)
        status = editor.build_editor_status()
        self.assertIn("Transaction disclosure review: 1", status)
        self.assertIn(form4()["url"], status)
        self.assertIn(ptr()["source_url"], status)
        profile = voice.checked(record, NOW)
        scene = next(row for row in profile["segments"] if row["heading"] == disclosures.HEADER)
        self.assertEqual(scene["source_ids"], ["transactions_sec", "transactions_congress"])
        self.assertEqual(profile["sources"]["transactions_congress"][0]["publisher"], "FMP index of House disclosures")
        self.assertEqual(profile["sources"]["transactions_sec"][0]["published_at"], "2026-10-22")
        self.assertIn("twenty nine days later", scene["narration"])
        self.assertEqual(profile["segments"][1]["heading"], "Market Update")
        self.assertNotIn("https://", scene["narration"])
        self.sec.unlink(); self.congress.unlink()
        self.assertEqual(voice.checked(record, NOW), profile)

    def test_missing_stale_and_empty_sources_are_explicit(self):
        self.seed("congress", [ptr()], age=37)
        report, record = self.render()
        self.assertIn("SEC Form 4 — Current source data are unavailable", report)
        self.assertIn("Congressional disclosures — The last source check is stale", report)
        self.assertNotIn("Example Filer", report)
        self.assertNotIn(disclosures.HEADER, [row["heading"] for row in voice.checked(record, NOW)["segments"]])
        self.seed("congress", [])
        self.assertEqual(self.capture()["congress"]["status"], "unavailable")

    def test_current_feed_with_no_eligible_rows_is_distinct_from_outage(self):
        self.seed("sec", [form4(transaction_code="A")]); self.seed("congress", [ptr(amount_range="$1,001 - $15,000")])
        report, _ = self.render()
        self.assertEqual(report.count("No watchlist trade in the current feed met"), 2)

    def test_sec_filters_equity_grants_exercises_withholding_and_indirect_rows(self):
        invalid = [form4(transaction_code=code) for code in ("A", "F", "M", "G")]
        invalid += [form4(security_type="Derivative"), form4(ownership="I"), form4(acquired_disposed="D"), form4(price=0)]
        self.seed("sec", invalid + [form4()])
        state = self.capture()["sec"]
        self.assertEqual(state["eligible"], 1)
        self.assertEqual(state["lead"]["transaction_code"], "P")

    def test_sales_are_read_against_the_prior_direct_holding(self):
        self.seed("sec", [form4(transaction_code="S", acquired_disposed="D", shares_owned_after=3000)])
        row = self.capture()["sec"]["lead"]
        self.assertIn("sale reduced the reported direct holding by about 25%", disclosures.sec_copy(row))
        self.seed("sec", [form4(transaction_code="S", acquired_disposed="D", shares_owned_after=3000, rule_10b5_1=True)])
        self.assertIsNone(self.capture()["sec"]["lead"])
        self.seed("sec", [form4(transaction_code="S", acquired_disposed="D", shares=5000, rule_10b5_1=True)])
        self.assertIn("filing indicates use of a trading plan", disclosures.sec_copy(self.capture()["sec"]["lead"]))

    def test_amendments_preserve_identical_facts_and_hold_conflicts(self):
        amendment = form4(form="4/A", filing_date="2026-10-23", accession="0000789019-26-999998")
        self.seed("sec", [form4(), amendment])
        result = self.capture()["sec"]
        self.assertEqual(result["eligible"], 1)
        self.assertEqual(result["lead"]["form"], "4/A")
        self.seed("sec", [form4(), {**amendment, "shares": 100}])
        self.assertIsNone(self.capture()["sec"]["lead"])

    def test_congress_ranks_by_lower_bound_for_the_same_disclosure_day(self):
        self.seed("congress", [ptr(amount_range="$15,001 - $100,000"), ptr(amount_range="$50,001 - $60,000")])
        self.assertEqual(self.capture()["congress"]["lead"]["amount_range"], "$50,001 - $60,000")

    def test_stock_watcher_dates_are_normalized_and_duplicate_rows_count_once(self):
        legacy = ptr(asset_type="", transaction_date="09/24/2026", disclosure_date="10/23/2026")
        self.seed("congress", [legacy, ptr()], source="House/Senate Stock Watcher public JSON datasets")
        result = self.capture()["congress"]
        self.assertEqual(result["eligible"], 2)
        self.seed("congress", [legacy, legacy], source="House/Senate Stock Watcher public JSON datasets")
        result = self.capture()["congress"]
        self.assertEqual(result["provider"], "Stock Watcher")
        self.assertEqual(result["eligible"], 1)
        self.assertEqual(result["lead"]["transaction_date"], "2026-09-24")

    def test_congress_holds_options_funds_and_nonfiling_links(self):
        bad = [ptr(asset_type="Corporate Bond"), ptr(asset_type="Stock Option"), ptr(ticker="SPY"), ptr(ticker="FAKE"),
               ptr(source_url="https://financialmodelingprep.com/stable/house-latest"), ptr(chamber="Senate"),
               ptr(source_url="https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/99999999.pdf?other=1"),
               ptr(amount_range="$15,00,1 - $50,000"), ptr(transaction="Exchange")]
        self.seed("congress", bad + [ptr()])
        self.assertEqual(self.capture()["congress"]["eligible"], 1)

    def test_senate_disclosure_has_unambiguous_owner_qualification(self):
        self.seed("congress", [ptr(chamber="Senate", owner="", source_url="https://efdsearch.senate.gov/search/view/ptr/12345678-1234-1234-1234-123456789abc/")])
        row = self.capture()["congress"]["lead"]
        self.assertIn("owner unspecified in the feed", disclosures.congress_copy(row, "FMP"))

    def test_chronology_rejects_future_old_and_inverted_dates(self):
        self.seed("sec", [form4(filing_date="2026-10-26"), form4(transaction_date="2026-10-24"), form4(filing_date="2026-10-17")])
        self.seed("congress", [ptr(transaction_date="2026-08-12"), ptr(disclosure_date="2026-10-26")])
        self.assertIsNone(self.capture()["sec"]["lead"])
        self.assertIsNone(self.capture()["congress"]["lead"])
        self.seed("congress", [ptr(disclosure_date="2026-10-25")], age=28)
        self.assertIsNone(self.capture()["congress"]["lead"])

    def test_malformed_cache_and_future_clock_stay_unavailable(self):
        self.sec.write_text("{", encoding="utf-8")
        self.seed("congress", [ptr()], age=-1)
        result = self.capture()
        self.assertEqual([result[lane]["status"] for lane in disclosures.LANES], ["unavailable", "unavailable"])

    def test_filing_identity_and_report_wording_are_rechecked(self):
        self.seed("sec", [form4()]); self.seed("congress", [ptr()])
        report, record = self.render()
        for value in ("https://www.sec.gov.evil.test/filing.xml", form4(accession="0000789019-26-999991")["url"]):
            broken = deepcopy(record)
            broken["transaction_disclosures"]["sec"]["lead"]["url"] = value
            with self.assertRaises(ValueError):
                voice.checked(broken, NOW)
        changed = report.replace("$240,000", "$340,000")
        with self.assertRaisesRegex(ValueError, "wording"):
            voice.build(record, changed, record["research_text"])
        without = deepcopy(record)
        del without["transaction_disclosures"]
        with self.assertRaisesRegex(ValueError, "retained evidence"):
            voice.checked(without, NOW)

    def test_original_form4_plan_flag_and_provider_asset_type_survive_ingestion(self):
        filing = {**form4(), "primary_document": "form4.xml"}
        xml = """<ownershipDocument><aff10b5One>1</aff10b5One><reportingOwner><rptOwnerName>Example Director</rptOwnerName></reportingOwner>
          <nonDerivativeTransaction><transactionDate><value>2026-10-20</value></transactionDate>
          <transactionCoding><transactionCode>S</transactionCode></transactionCoding><transactionAmounts>
          <transactionShares><value>100</value></transactionShares><transactionPricePerShare><value>40</value></transactionPricePerShare>
          <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts></nonDerivativeTransaction></ownershipDocument>"""
        self.assertTrue(insider_data.parse_form4_xml(xml, filing)[0]["rule_10b5_1"])
        row = congress_data.normalize_fmp_trade({"symbol": "NVDA", "firstName": "Example", "lastName": "Filer", "assetType": "Stock"}, "House")
        self.assertEqual(row["politician"], "Example Filer")
        self.assertEqual(row["asset_type"], "Stock")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows-socketpair", action="store_true")
    args = parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:
            stack.enter_context(patch.object(socket, "socketpair", portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(DisclosureChecks)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    passed = result.wasSuccessful() and not traffic["blocked"]
    print(f"Transaction Disclosure Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
