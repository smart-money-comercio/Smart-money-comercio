"""Offline contracts for bounded original reading and qualified business facts.

All article text below is synthetic. No paid APIs, live requests or sends run.
"""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
import json
import os
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
from src.intelligence import news_live_sources as feeds, news_original_sources as originals
from src.intelligence import news_editor as editor, news_editor_store as store, company_catalyst_context as companies
from src.intelligence.story_analysis import build_evidence, checked_evidence, investor_read
from src.intelligence.original_disclosures import summarize, gaps
from src.reports.daily_news_brief import build_daily_news_brief, validate_news_brief
from src.reports import daily_voiceover as voice
from src.utils.speech_text import normalize


NVDA = next(s for s in feeds.NEWS_SOURCES if s.get("company_symbol") == "NVDA")
CACI = next(s for s in feeds.NEWS_SOURCES if s.get("company_symbol") == "CACI")
EIA = next(s for s in feeds.NEWS_SOURCES if s["name"] == "EIA")
TITLE = "NVIDIA expands city AI services"
URL = "https://blogs.nvidia.com/blog/synthetic-city-services/"
PUBLICATION = (NOW-timedelta(minutes=20)).isoformat()
DEPLOYMENTS = ("In Portugal, Civic Systems combines NVIDIA Nemotron with its resident-service agents for municipal procedures.\n"
    "In Bergen, Harbor Systems is building shared AI infrastructure using NVIDIA Cosmos and NVIDIA Metropolis for video search and summarization.\n"
    "In Malaysia, Example Vision is scaling NVIDIA RTX PRO 6000 for traffic management to support 21,000+ cameras by 2028.")
AWARD_TITLE = "CACI advances agency accounting services"
AWARD = ("CACI International Inc. announced it has been awarded a three-year, $64 million contract by the U.S. Air Force.\n"
    "By sustaining and modernizing the Example Enterprise Accounting and Management System (EEAMS), CACI supports agency operations.")
REFINERY_TITLE = "Global refinery inputs declined before a partial recovery"
REFINERY = ("Global crude oil refinery inputs fell by 3.2 million barrels per day (b/d) in the second quarter of 2026. "
    "Throughput then increased by 1.1 million b/d in the third quarter.\n"
    "Global crude oil inputs increased by 0.6 million b/d in the second quarter of 2025.")


def payload(url, body, **extra):
    return {"url": url, "final_url": url, "status": "ok", "body": body, "fetched_at_epoch": NOW.timestamp(), **extra}


def page(title=TITLE, text=DEPLOYMENTS, published=PUBLICATION, *, container="article"):
    return (f'<html><head><meta property="og:title" content="{escape(title)}">'
        f'<meta property="article:published_time" content="{published}"></head><body>'
        f'<h1>{escape(title)}</h1><{container}><div class="entry-content"><p>{escape(text)}</p></div></{container}></body></html>')


def rss(rows):
    return '<rss><channel>' + ''.join(f'<item><title>{escape(title)}</title><link>{escape(url)}</link>'
        f'<pubDate>{published}</pubDate></item>' for title, url, published in rows) + '</channel></rss>'


def source(symbol="NVDA", text=None, **changes):
    if symbol == "CACI":
        row = candidate(symbol, title=AWARD_TITLE, source="CACI Investor Relations", source_excerpt=AWARD)
    elif symbol == "EIA":
        row = candidate(symbol, kind="macro", symbols=[], publisher_symbol="", source="EIA", title=REFINERY_TITLE,
            url="https://www.eia.gov/todayinenergy/detail.php?id=12345", source_excerpt=REFINERY)
    else:
        row = candidate(symbol, title=TITLE, source="Nvidia Newsroom", url=URL, source_excerpt=DEPLOYMENTS)
    row.update(excerpt_scope="original release excerpt", evidence_checked_at=(NOW-timedelta(minutes=2)).isoformat())
    if text is not None: row["source_excerpt"] = text
    row.update(changes)
    return row


def evidence(row):
    return build_evidence(row, row.get("source_excerpt", ""), "original release excerpt", schema=8)


class OriginalReadChecks(unittest.TestCase):
    def enrich(self, rows=None, fetch=None, **options):
        rows = rows or [(TITLE, URL, PUBLICATION)]
        fetch = fetch or (lambda url: payload(url, page()))
        return originals.enrich_feed(NVDA, payload(NVDA["url"], rss(rows)), feeds.parse_rss_items, fetch, NOW, **options)

    def test_two_distinct_articles_are_read_and_both_are_bound_to_their_feed_rows(self):
        rows = [(TITLE+str(i), URL+str(i), PUBLICATION) for i in range(4)]
        fetch = Mock(side_effect=lambda url: payload(url, page(title=TITLE+url[-1])))
        value = self.enrich(rows, fetch)
        self.assertEqual(fetch.call_count, 2)
        parsed = feeds.parse_article_items(value, NVDA, full_titles=True, full_text=True)
        self.assertEqual(sum(r["evidence_scope"] == "original release excerpt" for r in parsed), 2)

    def test_calendar_notices_do_not_consume_the_article_budget(self):
        rows = [("NVIDIA sets earnings conference call", URL+"call", PUBLICATION), (TITLE, URL, PUBLICATION)]
        fetch = Mock(side_effect=lambda url: payload(url, page()))
        self.enrich(rows, fetch)
        fetch.assert_called_once_with(URL)

    def test_duplicate_urls_cannot_consume_multiple_reads(self):
        fetch = Mock(side_effect=lambda url: payload(url, page()))
        self.enrich([(TITLE, URL, PUBLICATION)]*3, fetch)
        fetch.assert_called_once_with(URL)

    def test_error_attempts_count_against_the_same_two_page_limit(self):
        rows = [(TITLE+str(i), URL+str(i), PUBLICATION) for i in range(6)]
        fetch = Mock(return_value={"status":"error", "error":"HTTPError 403"})
        value = self.enrich(rows, fetch)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(len(value["release_evidence"]), 0)
        self.assertEqual([r["status"] for r in value["release_read_reviews"]], ["limited"]*2)

    def test_shared_budget_defers_the_second_read_without_fetching(self):
        rows = [(TITLE+str(i), URL+str(i), PUBLICATION) for i in range(3)]
        fetch = Mock(side_effect=lambda url: payload(url, page(title=TITLE+url[-1])))
        value = self.enrich(rows, fetch, budget=originals.DetailReadBudget(reads=1))
        self.assertEqual(fetch.call_count, 1)
        self.assertIn("deferred", value["release_read_reviews"][1]["reason"])

    def test_expired_start_window_does_not_start_a_request(self):
        fetch = Mock(side_effect=AssertionError("No request may start"))
        value = self.enrich(fetch=fetch, budget=originals.DetailReadBudget(seconds=-1))
        fetch.assert_not_called(); self.assertFalse(value["release_evidence"])

    def test_fresh_processed_cache_is_reused_without_refreshing_any_clock(self):
        first = self.enrich(); before = deepcopy(first)
        second = originals.enrich_feed(NVDA, first, feeds.parse_rss_items, Mock(side_effect=AssertionError), NOW)
        self.assertIs(second, first); self.assertEqual(second, before)

    def test_old_feed_marker_is_reprocessed_once(self):
        old = payload(NVDA["url"], rss([(TITLE,URL,PUBLICATION)]), release_excerpt_schema=1)
        result = originals.enrich_feed(NVDA, old, feeds.parse_rss_items, lambda url: payload(url,page()), NOW)
        self.assertEqual(result["release_excerpt_schema"], 3)
        self.assertEqual(result["fetched_at_epoch"], old["fetched_at_epoch"])

    def test_article_clock_conflict_does_not_supply_facts(self):
        value = self.enrich(fetch=lambda url: payload(url,page(published=(NOW-timedelta(hours=1)).isoformat())))
        self.assertFalse(value["release_evidence"])
        self.assertIn("does not match", value["release_read_reviews"][0]["reason"])

    def test_mismatched_title_and_external_redirect_are_rejected(self):
        for result in (payload(URL,page(title="Different article")), payload(URL,page(),final_url="https://example.com/other")):
            self.assertFalse(self.enrich(fetch=lambda url: result)["release_evidence"])

    def test_stale_and_prepublication_article_observations_are_not_reused(self):
        for stamp in ((NOW-timedelta(hours=7)).timestamp(), (NOW-timedelta(hours=1)).timestamp()):
            self.assertFalse(self.enrich(fetch=lambda url: payload(url,page(),fetched_at_epoch=stamp))["release_evidence"])

    def test_nvidia_body_excludes_header_and_share_controls(self):
        body = page(container="div").replace('<div>', '<article><p>Share controls are not article evidence.</p><div class="entry-content">').replace('</div>', '</div></article>')
        text = originals.article_excerpt(body,TITLE,PUBLICATION,publisher=NVDA["name"],url=URL)
        self.assertIn("Civic Systems", text); self.assertNotIn("Share controls", text)

    def test_eia_body_requires_exact_heading_and_same_release_date(self):
        title = REFINERY_TITLE; stamp = PUBLICATION
        body = f'<h1>{title}</h1><div class="tie-article"><span class="date">October 25, 2026</span><p>{REFINERY}</p></div>'
        text = originals.article_excerpt(body,title,stamp,publisher="EIA",url=EIA["url"])
        self.assertIn("3.2 million",text)
        with self.assertRaises(ValueError): originals.article_excerpt(body.replace("October 25", "October 24"),title,stamp,publisher="EIA",url=EIA["url"])

    def test_body_read_failure_remains_visible_alongside_publisher_availability(self):
        value = self.enrich(fetch=lambda url: {"status":"error", "error":"HTTPError 403"})
        health = feeds.describe_source(NVDA,value,NOW)
        self.assertEqual(health["body_limited"], 1)
        self.assertIn("1 limited", feeds.coverage_summary([health]))
        self.assertIn("HTTPError 403", health["body_reason"])


class DisclosureFactChecks(unittest.TestCase):
    def test_deployments_have_named_technology_application_and_stage(self):
        profile = evidence(source()); fields = {r["field"]:r for r in profile["facts"]}
        self.assertEqual(fields["deployment_example"]["status"], "in use")
        self.assertEqual(fields["deployment_example"]["technology"], ["Nemotron"])
        self.assertEqual(fields["deployment_example_2"]["status"], "under development")
        self.assertEqual(fields["rollout_target"]["status"], "target")

    def test_targets_remain_targets_in_summary_and_do_not_become_current_sales(self):
        row = source(); text = summarize(row,evidence(row),"Nvidia")
        self.assertIn("aims to support at least 21,000 cameras by 2028",text)
        self.assertNotIn("NVIDIA expands",text)
        self.assertNotIn("revenue",text)
        self.assertIn("Nvidia revenue timing",gaps(evidence(row)))

    def test_denied_hypothetical_or_previously_reported_deployments_supply_no_new_facts(self):
        for word in ("could", "may", "not", "previously"):
            self.assertEqual(evidence(source(text=f"In Portugal, Civic Systems {word} uses NVIDIA Nemotron in resident-service agents."))["facts"], [])

    def test_award_value_term_customer_and_work_are_separate_fields(self):
        fields = {r["field"]:r["value"] for r in evidence(source("CACI"))["facts"]}
        self.assertEqual(fields["contract_value"],"$64 million")
        self.assertEqual(fields["contract_term"],"three-year")
        self.assertEqual(fields["contract_customer"],"U.S. Air Force")
        self.assertIn("Accounting",fields["contract_scope"])
        self.assertNotIn("obligated_amount", fields)

    def test_ceiling_cannot_become_a_stated_or_funded_award(self):
        profile = evidence(source("CACI",text=AWARD.replace("$64 million", "up to $64 million")))
        fields = {r["field"] for r in profile["facts"]}
        self.assertNotIn("contract_value",fields);self.assertIn("contract_ceiling",fields)
        self.assertNotIn("obligated_amount",fields)

    def test_planned_denied_and_other_issuer_awards_cannot_promote_the_article(self):
        for text in (AWARD.replace("has been awarded", "expects to be awarded"), AWARD.replace("has been awarded", "has not been awarded"), AWARD.replace("CACI", "Another Company")):
            profile = evidence(source("CACI", text=text))
            self.assertNotIn("contract_value",{r["field"] for r in profile["facts"]})
            self.assertNotEqual(profile["event"],"contract")

    def test_money_outside_the_award_clause_and_ambiguous_ranges_are_not_award_values(self):
        row = source("CACI",text="CACI, a business with $9 billion in sales, has been awarded a $64 million contract by the U.S. Air Force.")
        fields = {r["field"]:r["value"] for r in evidence(row)["facts"]}
        self.assertEqual(fields["contract_value"],"$64 million")
        profile = evidence(source("CACI",text=AWARD.replace("$64 million", "$64 million to $88 million")))
        self.assertNotIn("contract_value",{r["field"] for r in profile["facts"]})

    def test_a_supplier_award_is_not_the_issuer_receiving_an_award(self):
        text = "CACI said its supplier, which was awarded a $64 million contract by the U.S. Air Force, supports the program."
        self.assertNotEqual(evidence(source("CACI",text=text))["event"],"contract")

    def test_refinery_observations_keep_units_direction_and_reporting_period(self):
        profile = evidence(source("EIA"))
        self.assertEqual([r["value"] for r in profile["facts"]], [
            "3.2 million barrels per day decrease (second quarter of 2026)",
            "1.1 million barrels per day increase (third quarter of 2026)"])

    def test_refinery_forecasts_and_missing_periods_are_not_observed_changes(self):
        for text in (REFINERY.replace("fell by", "could have fell by").split(" Throughput")[0], "Global refinery inputs fell by 3.2 million b/d."):
            self.assertFalse(evidence(source("EIA",text=text))["facts"])

    def test_refinery_interpretation_does_not_claim_a_current_price_cause(self):
        row = source("EIA");row["event_evidence"] = evidence(row)
        review = investor_read(row)
        self.assertIn("dated throughput",review["why"])
        self.assertIn("current oil-price move",review["why"])

    def test_tampered_value_stage_and_evidence_sentence_fail_reconstruction(self):
        row = source();row["event_evidence"] = evidence(row)
        for key, replacement in (("value","invented purchase"),("status","funded"),("evidence","unrelated text")):
            changed = deepcopy(row);changed["event_evidence"]["facts"][0][key] = replacement
            with self.assertRaises(ValueError):checked_evidence(changed)

    def test_headline_and_feed_excerpts_cannot_claim_the_new_original_body_schema(self):
        for scope in ("headline only","publisher feed excerpt"):
            with self.assertRaises(ValueError):build_evidence(source(),DEPLOYMENTS,scope,schema=8)


class EditionChecks(IsolatedChecks):
    def setUp(self):
        super().setUp()
        ranks = json.loads(self.ranking.read_text());ranks["current"]["CACI"] = {"opportunity_score":82,"structural_score":80}
        self.ranking.write_text(json.dumps(ranks))

    def plan(self, rows):
        return editor.build_editorial_plan(companies.build_company_catalyst_brief(),NOW,rows)

    def render(self, rows):
        with patch.object(editor,"cache_candidates",return_value=(rows,[])):
            report = build_daily_news_brief(self.research())
        return report,store.read_editions(report=report)[0]

    def test_caci_headline_is_promoted_only_after_a_material_original_award_is_read(self):
        row = source("CACI")
        selected = editor.selected_stories(self.plan([row]))
        self.assertEqual(len(selected),1);self.assertEqual(selected[0]["materiality"],"contract")
        for scope in ("headline only","publisher feed excerpt"):
            self.assertFalse(editor.selected_stories(self.plan([{**row,"excerpt_scope":scope}])))

    def test_original_promotion_still_requires_a_verified_publisher(self):
        for changes in ({"official":False},{"url":"https://example.com/caci"}):
            self.assertFalse(editor.selected_stories(self.plan([source("CACI",**changes)])))

    def test_stale_body_and_future_publication_cannot_supply_materiality(self):
        for changes in ({"evidence_checked_at":(NOW-timedelta(hours=7)).isoformat()}, {"published":(NOW+timedelta(hours=1)).isoformat()}):
            self.assertFalse(editor.selected_stories(self.plan([source("CACI",**changes)])))

    def test_eia_can_qualify_from_a_dated_original_read(self):
        row = editor.selected_stories(self.plan([source("EIA")]))[0]
        self.assertEqual(row["materiality"],"energy");self.assertEqual(row["event_evidence"]["event"],"refinery data")

    def test_a_full_edition_keeps_three_stories_their_sources_and_the_brief_budget(self):
        report,record = self.render([source(),source("CACI"),source("EIA")])
        self.assertTrue(validate_news_brief(report)["passes"]);self.assertLessEqual(len(report),3800)
        selected = editor.selected_stories(record)
        self.assertEqual(len(selected),3)
        profile = voice.checked(record,NOW)
        self.assertTrue(profile["quality"]["passes"]);self.assertEqual(record["rules_version"],32)
        self.assertTrue({row["id"] for row in selected} <= set(profile["sources"]))
        self.assertIn("Nvidia",profile["script"]);self.assertNotIn("NVIDIA",profile["script"])
        self.assertIn("sixty four million dollars",profile["script"])
        self.assertIn("second quarter of",profile["script"])
        self.assertIn("draft_review_required",voice.episode(record,NOW)["mode"])

    def test_storylog_shows_business_fields_their_evidence_and_unknown_commitments(self):
        self.render([source(),source("CACI")])
        text = editor.build_editor_status("CACI",history=True)
        self.assertIn("Fact evidence",text);self.assertIn("obligated funding",text);self.assertIn("Accounting",text)

    def test_rules20_narration_and_report_keep_their_original_hashes(self):
        record = json.loads((ROOT/"scripts/fixtures/disclosure_rules20_edition.json").read_text())
        profile = voice.checked(record,NOW)
        self.assertEqual(record["report_sha256"],"0683ba6a535b3094617ee120d1e809bb8646ec97cbb920f7f7b19da9b9e1a253")
        self.assertEqual(profile["script_sha256"],"ef541b54771d341cf87691f55bd6a8738e5d8636785532fda2d531c31dff8083")
        self.assertEqual(normalize("NVIDIA"),"NVIDIA")
        self.assertEqual(normalize("NVIDIA",brand_names=True),"Nvidia")


def main():
    parser = argparse.ArgumentParser();parser.add_argument("--windows-socketpair",action="store_true");args = parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    passed = result.wasSuccessful() and not traffic["blocked"]
    print(f"Disclosure Intelligence Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__ == "__main__":raise SystemExit(main())
