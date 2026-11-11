"""Offline regressions for publisher identity and original Treasury financing facts.

All release text is synthetic. No paid APIs, requests or messages are used.
"""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import Mock, patch
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_news_editor import candidate
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.intelligence import news_editor as editor, news_editor_store as store, company_catalyst_context as companies
from src.intelligence import news_live_sources as feeds, news_original_sources as originals
from src.intelligence.story_analysis import build_evidence, checked_evidence
from src.intelligence.treasury_financing import summary
from src.reports.daily_news_brief import build_daily_news_brief, validate_news_brief
from src.reports import daily_voiceover as voice


POLICY = "Quarterly Refunding Statement of Assistant Secretary for Financial Markets Example Official"
REPORT = "Report to the Secretary of the Treasury from the Treasury Borrowing Advisory Committee"
MINUTES = "Minutes of the Meeting of the Treasury Borrowing Advisory Committee October 24, 2026"
FINANCING = ("WASHINGTON — The U.S. Department of the Treasury is offering $90 billion of Treasury securities to refund approximately $70 billion of privately-held Treasury notes and bonds maturing on November 15, 2026. "
             "This issuance will raise new cash from private investors of approximately $20 billion. The securities are:\n"
             "A 3-year note in the amount of $40 billion, maturing November 15, 2029;\n"
             "A 10-year note in the amount of $30 billion, maturing November 15, 2036;\n"
             "A 30-year bond in the amount of $20 billion, maturing November 15, 2056.\n"
             "The 3-year note will be auctioned at 1:00 p.m. ET on Monday, October 26, 2026. "
             "The 10-year note will be auctioned at 1:00 p.m. ET on Tuesday, October 27, 2026. "
             "The 30-year bond will be auctioned at 1:00 p.m. ET on Thursday, October 29, 2026.")
COMMITTEE = "The Committee discussed financing conditions and unanimously recommended maintaining auction sizes. Its advice is provided to Treasury for consideration."
AMD = next(s for s in feeds.NEWS_SOURCES if s.get("company_symbol") == "AMD")
AMAZON = next(s for s in feeds.NEWS_SOURCES if s.get("company_symbol") == "AMZN")


def treasury(title=POLICY, text=FINANCING, **changes):
    suffix = {POLICY:"sb0001",REPORT:"sb0002",MINUTES:"sb0003"}.get(title,"sb0004")
    return candidate(kind="macro", symbols=[], publisher_symbol="", source="U.S. Treasury", title=title,
        url="https://home.treasury.gov/news/press-releases/"+suffix, source_excerpt=text,
        excerpt_scope="original release excerpt", evidence_checked_at=NOW.isoformat(), **changes)


def proof(row):
    return build_evidence(row,row["source_excerpt"],"original release excerpt",schema=9)


def payload(url, body="", **changes):
    return {"url":url,"final_url":url,"status":"ok","body":body,"fetched_at_epoch":NOW.timestamp(),**changes}


def rss(title, url, when=None):
    return f'<rss><channel><item><title>{escape(title)}</title><link>{escape(url)}</link><pubDate>{when or (NOW-timedelta(minutes=15)).isoformat()}</pubDate></item></channel></rss>'


class PublisherIdentityChecks(IsolatedChecks):
    def amd_candidates(self):
        url="https://ir.amd.com/news-events/press-releases/detail/999/synthetic-results"
        cache={AMD["url"]:payload(AMD["url"],rss("AMD Reports Third Quarter Financial Results",url))}
        brief=companies.build_company_catalyst_brief()
        return brief,editor.cache_candidates(NOW,[r["symbol"] for r in brief["rows"]],cache=cache)[0]

    def test_fresh_official_publisher_keeps_issuer_identity_outside_top_ten(self):
        brief,values=self.amd_candidates()
        self.assertNotIn("AMD",[r["symbol"] for r in brief["rows"]])
        self.assertEqual(values[0]["symbols"],["AMD"])
        self.assertEqual(values[0]["publisher_symbol"],"AMD");self.assertTrue(values[0]["official"])

    def test_configured_issuer_is_reviewed_and_can_be_selected_without_rescoring(self):
        before=self.ranking.read_bytes();brief,values=self.amd_candidates()
        plan=editor.build_editorial_plan(brief,NOW,values)
        self.assertEqual([(r["symbols"],r["decision"]) for r in plan["candidates"]],[(["AMD"],"selected")])
        self.assertEqual(self.ranking.read_bytes(),before)

    def test_storylog_returns_the_actual_amd_decision(self):
        _,values=self.amd_candidates()
        with patch.object(editor,"cache_candidates",return_value=(values,[])):
            report=build_daily_news_brief(self.research())
        log=editor.build_editor_status("AMD",history=True)
        self.assertIn("SELECTED — AMD Reports Third Quarter Financial Results",log)
        self.assertNotIn("No matching story decisions for AMD",log)
        self.assertTrue(store.read_editions(report=report))

    def test_fresh_publisher_precedes_stale_originals_at_scan_limit(self):
        brief,values=self.amd_candidates()
        old=[candidate(title=f"MSFT introduces example product {i}",url=f"https://microsoft.com/news/{i}",
                       published=(NOW-timedelta(days=2)).isoformat()) for i in range(205)]
        plan=editor.build_editorial_plan(brief,NOW,old+values)
        self.assertEqual(len(plan["candidates"]),editor.MAX_CANDIDATES)
        self.assertEqual(plan["candidates"][0]["symbols"],["AMD"])
        self.assertEqual(plan["candidates"][0]["decision"],"selected")
        self.assertGreater(plan["publisher_scan_omissions"]["MSFT"],0)

    def test_editorial_scope_does_not_change_special_alert_universe(self):
        before=companies.build_company_catalyst_brief()
        self.amd_candidates()
        after=companies.build_company_catalyst_brief()
        self.assertEqual(before,after);self.assertNotIn("AMD",[r["symbol"] for r in after["rows"]])

    def test_a_candidate_outside_the_scan_limit_has_an_explicit_storylog_explanation(self):
        _,values=self.amd_candidates()
        newer=[candidate(title=f"MSFT introduces example product {i}",url=f"https://microsoft.com/news/{i}",
                         published=(NOW-timedelta(minutes=1)).isoformat()) for i in range(editor.MAX_CANDIDATES)]
        with patch.object(editor,"cache_candidates",return_value=(newer+values,[])):
            report=build_daily_news_brief(self.research())
        self.assertTrue(store.read_editions(report=report))
        self.assertIn("Scan limit: 1 publisher candidate was outside",editor.build_editor_status("AMD",history=True))

    def test_unknown_issuer_is_not_admitted_by_expanded_publisher_scope(self):
        plan=editor.build_editorial_plan(companies.build_company_catalyst_brief(),NOW,[candidate("ZZZZ")])
        self.assertEqual(plan["candidates"][0]["decision"],"wait")


class FinancingFactChecks(unittest.TestCase):
    def test_offering_maturities_and_new_cash_remain_separate(self):
        values={r["field"]:r for r in proof(treasury())["facts"]}
        self.assertEqual(values["refunding_offering"]["value"],"$90 billion")
        self.assertEqual(values["refunding_maturities"]["value"],"approximately $70 billion")
        self.assertEqual(values["refunding_new_cash"]["value"],"approximately $20 billion")
        self.assertIn("execution not established",values["refunding_offering"]["status"])

    def test_tranche_amounts_and_future_auction_dates_have_their_own_evidence(self):
        values={r["field"]:r for r in proof(treasury())["facts"]}
        self.assertEqual(len(values),9)
        self.assertEqual(values["refunding_tranche_10"]["value"],"$30 billion")
        self.assertEqual(values["refunding_auction_30"]["value"],"October 29, 2026 at 01:00 PM ET")
        for row in values.values():self.assertIn(row["evidence"],FINANCING)

    def test_inconsistent_new_cash_arithmetic_is_withheld(self):
        self.assertEqual(proof(treasury(text=FINANCING.replace("approximately $20 billion","approximately $25 billion")))["facts"],[])

    def test_conflicting_offering_amounts_are_not_resolved_by_first_match(self):
        other=FINANCING.split("This issuance")[0].replace("$90 billion","$95 billion")
        self.assertEqual(proof(treasury(text=FINANCING+"\n"+other))["facts"],[])

    def test_cash_from_another_paragraph_is_not_attached_to_the_offering(self):
        text=FINANCING.replace("This issuance will", "Another financing plan was discussed. This issuance will")
        self.assertNotIn("refunding_new_cash",[r["field"] for r in proof(treasury(text=text))["facts"]])

    def test_committee_advice_is_never_promoted_to_a_treasury_decision(self):
        for title in (REPORT,MINUTES):
            self.assertEqual(proof(treasury(title,FINANCING))["facts"],[])
            self.assertEqual(proof(treasury(title,COMMITTEE))["facts"],[])

    def test_speculation_negation_history_and_unscoped_quotes_are_not_financing_facts(self):
        for prefix in ("An analyst said ","Previously, ","For example, "):
            self.assertEqual(proof(treasury(text=prefix+FINANCING))["facts"],[])
        for words in ("is not offering","may offer","is considering offering"):
            self.assertEqual(proof(treasury(text=FINANCING.replace("is offering",words)))["facts"],[])

    def test_money_range_is_not_converted_to_a_point_estimate(self):
        self.assertEqual(proof(treasury(text=FINANCING.replace("$90 billion","$90 billion to $95 billion")))["facts"],[])

    def test_wrong_weekday_or_past_date_withholds_only_the_invalid_auction_clock(self):
        for bad in ("Tuesday, October 26, 2026","Monday, October 19, 2026"):
            value=proof(treasury(text=FINANCING.replace("Monday, October 26, 2026",bad)))
            self.assertNotIn("refunding_auction_3",[r["field"] for r in value["facts"]])
            self.assertIn("refunding_offering",[r["field"] for r in value["facts"]])

    def test_impostor_publisher_cannot_use_treasury_fact_profile(self):
        row=treasury();row["url"]="https://home.treasury.gov.example.com/news/press-releases/sb0001"
        with self.assertRaises(ValueError):proof(row)

    def test_fact_tampering_breaks_evidence_validation(self):
        row=treasury();row["event_evidence"]=proof(row)
        row["event_evidence"]["facts"][0]["value"]="$999 billion"
        with self.assertRaises(ValueError):checked_evidence(row)

    def test_body_is_required_and_source_text_hash_remains_bound(self):
        row=treasury()
        with self.assertRaises(ValueError):build_evidence(row,FINANCING,"publisher feed excerpt",schema=9)
        value=proof(row)
        self.assertEqual(value["source_sha256"],hashlib.sha256(value["source_text"].encode()).hexdigest())


class FinancingEditionChecks(IsolatedChecks):
    def render(self,values=None):
        values=values if values is not None else [treasury(REPORT,COMMITTEE),treasury(MINUTES,COMMITTEE),treasury()]
        with patch.object(editor,"cache_candidates",return_value=(values,[])):
            report=build_daily_news_brief(self.research())
        return report,store.read_editions(report=report)[0]

    def test_related_documents_form_one_substantive_refunding_story(self):
        _,record=self.render();selected=editor.selected_stories(record)
        self.assertEqual([r["title"] for r in selected],[POLICY])
        self.assertEqual(len(selected[0]["related_reports"]),2)
        for row in record["candidates"]:
            if row["title"]!=POLICY:
                self.assertEqual(row["decision"],"skip");self.assertEqual(row["related_to"],selected[0]["id"])

    def test_committee_titles_alone_do_not_fill_empty_news_slots(self):
        _,record=self.render([treasury(REPORT,COMMITTEE),treasury(MINUTES,COMMITTEE)])
        self.assertEqual(editor.selected_stories(record),[])

    def test_no_concrete_financing_facts_means_no_selected_refunding_statement(self):
        _,record=self.render([treasury(text=COMMITTEE)])
        self.assertEqual(editor.selected_stories(record),[])

    def test_different_publication_days_are_not_clustered(self):
        old=treasury(REPORT,COMMITTEE,published=(NOW-timedelta(hours=23)).isoformat())
        _,record=self.render([old,treasury()])
        self.assertNotIn("related_to",record["candidates"][1] if record["candidates"][1]["title"]==REPORT else record["candidates"][0])

    def test_reader_brief_contains_financing_facts_and_an_economic_interpretation(self):
        report,record=self.render()
        self.assertIn("$90 billion",report);self.assertIn("approximately $20 billion in new cash",report)
        self.assertIn("supply of government debt",report);self.assertNotIn("Review the original report for scope",report)
        self.assertTrue(validate_news_brief(report)["passes"])
        self.assertEqual(record["rules_version"],31)

    def test_voiceover_uses_a_factual_summary_and_preserves_schema2_review(self):
        _,record=self.render();profile=voice.checked(record,NOW);episode=voice.episode(record,NOW)
        self.assertIn("ninety billion dollars",profile["script"])
        self.assertNotIn("Quarterly Refunding Statement",profile["script"])
        self.assertEqual(episode["voiceover_schema"],2);self.assertEqual(episode["mode"],"draft_review_required")
        self.assertTrue(profile["quality"]["passes"])
        self.assertEqual(len(episode["sources"]),1)

    def test_storylog_keeps_the_financing_and_related_document_evidence(self):
        self.render();log=editor.build_editor_status(history=True)
        self.assertIn("Fact evidence — refunding_offering",log)
        self.assertIn("Related original: "+REPORT,log)
        self.assertIn("official policy statement supplies the financing facts",log)

    def test_rules22_saved_edition_hashes_and_narration_remain_valid(self):
        cases=[("publisher_rules22_edition.json","1910597b7b430b29dc5556c6400405a9f8a8ff2547bca05c458c5e9845a8993b","e2f214bd1f6f4ba71f74d591e6d6e36919449ddb44e1e302aa7993f91c5014cc"),
               ("treasury_rules22_edition.json","8f553cd8d0f626984b3db04b76a59e035fae000ec77bb5a12434894d5b012278","d6b6a0a5b9651fc84e48a6b247e74d6c602b51fc699182b9a712c070fadec371")]
        for name,report_hash,speech_hash in cases:
            record=json.loads((ROOT/"scripts/fixtures"/name).read_text())
            self.assertEqual(record["report_sha256"],report_hash)
            self.assertEqual(voice.checked(record,NOW)["script_sha256"],speech_hash)


class AmazonReaderChecks(unittest.TestCase):
    title="Amazon.com Announces Third Quarter Results"
    url="https://ir.aboutamazon.com/news-release/news-release-details/2026/synthetic-results/default.aspx"

    def page(self,title=None,date="October 25, 2026"):
        return (f'<h1>{title or self.title}</h1><div class="module_date-time">{date}</div>'
                '<nav>Unrelated navigation promise $999 billion.</nav><div class="module_body"><p>'
                'Amazon.com, Inc. today announced financial results for its third quarter ended September 30, 2026. '
                'Net sales increased to $100 billion. These are synthetic test results.</p></div><footer>Other content</footer>')

    def enrich(self,page=None,**changes):
        fetch=Mock(return_value=payload(self.url,self.page() if page is None else page,**changes))
        feed=payload(AMAZON["url"],rss(self.title,self.url))
        return originals.enrich_feed(AMAZON,feed,feeds.parse_rss_items,fetch,NOW),fetch

    def test_configured_source_is_the_official_ir_feed_and_requires_an_original_body(self):
        self.assertEqual(AMAZON["url"],"https://ir.aboutamazon.com/rss/pressrelease.aspx?LanguageId=1")
        self.assertTrue(AMAZON["requires_original_body"])

    def test_release_body_is_bound_to_the_matching_rss_headline_and_date(self):
        value,fetch=self.enrich();items=feeds.parse_article_items(value,AMAZON,full_titles=True,full_text=True)
        self.assertEqual(fetch.call_count,1);self.assertEqual(items[0]["evidence_scope"],"original release excerpt")
        self.assertIn("financial results",items[0]["description"])
        self.assertNotIn("navigation",items[0]["description"]);self.assertNotIn("Other content",items[0]["description"])

    def test_mismatched_title_or_date_cannot_supply_an_original_release_body(self):
        for page in (self.page(title="A different release"),self.page(date="October 24, 2026")):
            value,_=self.enrich(page)
            self.assertEqual(value["release_evidence"],[])

    def test_external_redirect_is_held(self):
        value,_=self.enrich(final_url="https://example.com/release")
        self.assertEqual(value["release_evidence"],[])

    def test_old_official_results_stay_available_without_becoming_fresh_news(self):
        body=rss(self.title,self.url,(NOW-timedelta(days=6)).isoformat());fetch=Mock(side_effect=AssertionError("Old news needs no detail fetch"))
        value=originals.enrich_feed(AMAZON,payload(AMAZON["url"],body),feeds.parse_rss_items,fetch,NOW)
        self.assertEqual(fetch.call_count,0)
        health=feeds.describe_source(AMAZON,value,NOW)
        self.assertEqual(health["status"],"available");self.assertEqual(health["fresh"],0)

    def test_publisher_http_cooldown_is_retained_even_on_forced_refresh(self):
        failed=payload(AMAZON["url"],status="error",error="HTTPError 403",retry_after_epoch=NOW.timestamp()+3600)
        with patch.object(feeds,"get_cached_source",return_value=failed),patch.object(feeds,"urlopen",side_effect=AssertionError("Cooldown must prevent fetch")):
            self.assertEqual(feeds.fetch_source(AMAZON,True)["retry_after_epoch"],failed["retry_after_epoch"])


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--windows-socketpair",action="store_true");args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in
            (PublisherIdentityChecks,FinancingFactChecks,FinancingEditionChecks,AmazonReaderChecks))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    passed=result.wasSuccessful() and not traffic["blocked"]
    print(f"Financing Editorial Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__=="__main__":raise SystemExit(main())
