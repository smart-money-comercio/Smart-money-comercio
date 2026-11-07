"""Synthetic original-source cases; no live requests, legal determinations or sends."""

import argparse
import asyncio
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_news_editor import candidate
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.intelligence import disclosure_details as details, story_analysis as analysis, news_editor as editor
from src.intelligence import news_editor_store as store, hourly_research as desk, northrop_newsroom as northrop
from src.intelligence import news_original_sources as originals, news_live_sources as feeds
from src.intelligence import daily_brief_analysis as analyst, evidence_opening, market_brief
from src.intelligence.special_alert_company_sources import publication_time
from src.reports import daily_voiceover as voice, daily_report
from src.reports.daily_news_brief import build_daily_news_brief, validate_news_brief
from src.commands import reportcheck_commands
from src.utils.speech_text import normalize

TITLE = "Northrop Grumman Facility Selected as Certified US Maintenance Depot for C-130 Hercules Fleet"
URL = "https://news.northropgrumman.com/aircraft-sustainment/synthetic-c130-depot-designation"
STAMP = (NOW-timedelta(minutes=15)).isoformat()
MAINTENANCE = ("Northrop Grumman is expanding C-130 Hercules depot-level maintenance at its Example Bay, Louisiana, facility. "
    "Northrop Grumman has been selected as a Certified Continental U.S. depot for the C-130 Hercules fleet. "
    "As a certified depot, Northrop Grumman will provide aircraft maintenance, including repair, overhaul and inspection.")
SANCTIONS = ("The Department of the Treasury's Office of Foreign Assets Control (OFAC) designated three money services businesses based in Canada that handled transfers for a synthetic restricted network. "
    "These companies exchange currencies for digital assets to support international transactions. "
    "This text is synthetic fixture evidence for software validation.")


def page(text=MAINTENANCE, *, clock=STAMP, dateline="", nav=""):
    return (f'<meta property="og:title" content="{TITLE}"><meta property="og:url" content="{URL}">'
        f'<meta property="og:publishDate" content="{clock}"><h1>{TITLE}</h1>'
        f'<nav>{nav}</nav><div class="NewsroomArticleBody_BodyCopy__synthetic"><p>{escape(dateline+text)}</p></div>')


def maintenance(text=MAINTENANCE, **changes):
    values=dict(title=TITLE, url=URL, source="Northrop Grumman Newsroom",
        source_excerpt=text, excerpt_scope="original release excerpt", evidence_checked_at=STAMP)
    return candidate("NOC", **{**values, **changes})


def sanctions(text=SANCTIONS, **changes):
    values=dict(kind="macro", symbols=[], publisher_symbol="", source="U.S. Treasury",
        title="Treasury Sanctions Three Canadian Money Services Businesses", url="https://home.treasury.gov/news/press-releases/sb9999",
        source_excerpt=text, excerpt_scope="original release excerpt", evidence_checked_at=STAMP)
    return candidate("", **{**values, **changes})


def proof(row, schema):
    return analysis.build_evidence(row, row["source_excerpt"], "original release excerpt", schema=schema)


class FactChecks(unittest.TestCase):
    def test_maintenance_requires_designation_platform_and_location(self):
        facts=details.maintenance_facts(maintenance(),MAINTENANCE)
        self.assertEqual(len(facts),4);self.assertTrue(details.material(facts,"maintenance"))
        self.assertEqual({f["field"]:f["value"] for f in facts}["maintenance_location"],"Example Bay, Louisiana")

    def test_headline_and_unscoped_feed_text_cannot_establish_certification(self):
        row=maintenance();self.assertEqual(details.maintenance_facts(row,TITLE),[])
        with self.assertRaises(ValueError):analysis.build_evidence(row,MAINTENANCE,"publisher feed excerpt",schema=12)

    def test_planned_negated_and_historical_designations_are_not_completed(self):
        for replacement in ("could be selected", "will be selected", "has not been selected", "was previously selected"):
            with self.subTest(replacement=replacement):
                self.assertFalse(details.maintenance_facts(maintenance(),MAINTENANCE.replace("has been selected",replacement)))

    def test_another_issuers_designation_is_not_attributed_to_northrop(self):
        self.assertFalse(details.maintenance_facts(maintenance(),MAINTENANCE.replace("Northrop Grumman has been selected","Its supplier Example Aviation has been selected")))

    def test_provisional_designation_is_not_presented_as_an_unqualified_designation(self):
        body=MAINTENANCE.replace("Hercules fleet.","Hercules fleet, subject to final approval.")
        self.assertFalse(details.maintenance_facts(maintenance(),body))

    def test_two_locations_are_held_as_ambiguous(self):
        other=" Northrop Grumman is expanding C-130 depot maintenance at its Other Bay, Texas, facility."
        self.assertFalse(details.maintenance_facts(maintenance(),MAINTENANCE+other))

    def test_generic_iso_certificate_is_outside_this_reader(self):
        row=maintenance(title="Northrop Grumman receives an ISO quality certification")
        self.assertEqual(details.family(row),"")

    def test_background_contract_values_and_aircraft_are_not_added_to_designation_facts(self):
        body=MAINTENANCE+" An unrelated E-6B maintenance contract was valued at $900 million."
        facts=details.maintenance_facts(maintenance(),body)
        self.assertEqual(len(facts),4)
        self.assertFalse(any("900" in f["value"] or "E-6B" in f["value"] for f in facts))

    def test_planned_services_are_qualified_and_not_counted_as_completed_work(self):
        profile=proof(maintenance(),12)
        self.assertIn("Planned services",details.summary(profile))
        self.assertIn("service orders",details.review(profile)["why"])
        self.assertNotIn("awarded",details.summary(profile))

    def test_sanctions_reader_extracts_action_targets_country_and_channel(self):
        facts=details.sanctions_facts(sanctions(),SANCTIONS)
        self.assertEqual(len(facts),4)
        values={f["field"]:f["value"] for f in facts}
        self.assertEqual(values["sanctions_targets"],"three money services businesses")
        self.assertEqual(values["sanctions_jurisdiction"],"Canada")

    def test_sanctions_title_does_not_substitute_for_original_action_text(self):
        self.assertFalse(details.sanctions_facts(sanctions(),sanctions()["title"]))

    def test_planned_negated_historical_and_quoted_sanctions_are_not_current_designations(self):
        for replacement in ("will designate", "did not designate", "previously designated", 'said "designated'):
            with self.subTest(replacement=replacement):
                body=SANCTIONS.replace("designated",replacement,1)
                self.assertFalse(details.sanctions_facts(sanctions(),body))

    def test_conflicting_target_counts_are_held_as_ambiguous(self):
        self.assertFalse(details.sanctions_facts(sanctions(),SANCTIONS+" OFAC designated five money services businesses based in Canada that moved funds."))

    def test_financial_sanctions_do_not_infer_tariffs_or_watchlist_exposure(self):
        profile=proof(sanctions(),13);review=details.review(profile)
        self.assertIn("payment and counterparty exposure",review["why"])
        self.assertIn("require their own disclosures",review["why"])
        self.assertFalse(any("tariff" in f["field"] or "earnings" in f["field"] for f in profile["facts"]))

    def test_financial_topic_removes_only_its_generic_sanctions_trade_label(self):
        row=sanctions();row["event_evidence"]=proof(row,13)
        self.assertIn("financial sanctions",market_brief.story_topics(row));self.assertNotIn("trade",market_brief.story_topics(row))
        legacy={**row,"event_evidence":analysis.build_evidence(row,SANCTIONS,"original release excerpt",schema=8)}
        self.assertIn("trade",market_brief.story_topics(legacy))
        self.assertIn("trade",market_brief.story_topics(candidate(title="U.S. expands chip export restrictions")))

    def test_hash_fact_stage_clock_and_url_tampering_still_fail(self):
        row=maintenance();row["event_evidence"]=proof(row,12)
        for field in ("source_sha256","stage","observed_at","source_url"):
            changed=deepcopy(row);changed["event_evidence"][field]="tampered"
            with self.assertRaises(ValueError):analysis.checked_evidence(changed)
        row["event_evidence"]["facts"][0]["value"]="unsupported approval"
        with self.assertRaises(ValueError):analysis.checked_evidence(row)

    def test_observed_energy_stress_takes_priority_over_indirect_financial_context(self):
        lens=market_brief.portfolio_lens({"Oil":3},{"financial sanctions"},"mixed")
        self.assertIn("Higher energy costs",lens)

    def test_genuine_export_controls_keep_the_trade_lens_with_financial_context(self):
        lens=market_brief.portfolio_lens({}, {"financial sanctions","trade","chips"}, "mixed")
        self.assertIn("chip-market access",lens)


class PublicationChecks(unittest.TestCase):
    def test_matching_dateline_keeps_the_exact_original_clock(self):
        dateline=f"EXAMPLE BAY, La. – {NOW:%B} {NOW.day}, {NOW.year} – "
        self.assertEqual(publication_time(page(dateline=dateline).encode(),TITLE,url=URL).isoformat(),STAMP)

    def test_new_cms_date_cannot_replace_an_older_original_dateline(self):
        with self.assertRaisesRegex(ValueError,"dateline date conflicts"):
            publication_time(page(dateline="EXAMPLE BAY, La. – October 1, 2026 – ").encode(),TITLE,url=URL)

    def test_abbreviated_dateline_month_is_checked(self):
        northrop.check_dateline("ORLANDO, Fla. – Oct. 25, 2026 – "+MAINTENANCE,STAMP)
        with self.assertRaises(ValueError):northrop.check_dateline("ORLANDO, Fla. – Oct. 1, 2026 – "+MAINTENANCE,STAMP)
        northrop.check_dateline("ORLANDO, Fla. – Sept. 25, 2026 – "+MAINTENANCE,"2026-09-25T16:45:00+00:00")
        with self.assertRaises(ValueError):northrop.check_dateline("ORLANDO, Fla. – Sept. 1, 2026 – "+MAINTENANCE,STAMP)

    def test_body_without_dateline_does_not_gain_an_invented_clock(self):
        self.assertEqual(publication_time(page().encode(),TITLE,url=URL).isoformat(),STAMP)
        with self.assertRaises(ValueError):publication_time(page(clock="").encode(),TITLE,url=URL)

    def test_modified_time_alone_is_not_original_publication(self):
        body=page().replace('property="og:publishDate"','property="article:modified_time"')
        with self.assertRaises(ValueError):publication_time(body.encode(),TITLE,url=URL)

    def test_hourly_reader_extracts_the_identified_article_body_only(self):
        value=desk.verified({"url":URL},NOW,fetch=lambda url:page(nav="Unrelated site navigation and another aircraft award.").encode())
        self.assertEqual(value["source_excerpt"],MAINTENANCE)
        self.assertEqual(value["discovery_evidence"]["scope"],"original release excerpt")
        self.assertNotIn("Unrelated",value["source_excerpt"])
        desk.check_proof(value,NOW)

    def test_hourly_reader_holds_an_unrecognizable_body(self):
        body=page().replace("NewsroomArticleBody_BodyCopy__synthetic","unidentified-layout")
        with self.assertRaisesRegex(ValueError,"body unavailable"):
            desk.verified({"url":URL},NOW,fetch=lambda url:body.encode())

    def test_conflicted_northrop_index_row_loses_its_fresh_date(self):
        source=next(s for s in feeds.NEWS_SOURCES if s["name"]=="Northrop Grumman Newsroom")
        index='<div>Dynamic newsroom index</div>'
        home=f'<a href="{URL}" aria-label="Read More about {TITLE}">{TITLE}</a>'
        def fetch(url):
            body=index if url==source["url"] else home if url==northrop.HOME else page(dateline="EXAMPLE BAY, La. – October 1, 2026 – ")
            return {"url":url,"final_url":url,"status":"ok","body":body,"fetched_at_epoch":NOW.timestamp()}
        result=originals.retrieve(source,fetch,NOW)
        self.assertEqual(result["original_profile"],4)
        self.assertEqual(result["articles"][0]["published"],"")
        self.assertIn("dateline",result["publication_problems"][0])


class RebuildDetailChecks(IsolatedChecks):
    def render(self, rows):
        with patch.object(editor,"cache_candidates",return_value=(rows,[])):
            report=build_daily_news_brief(self.research())
        return report,store.read_editions(report=report)[0]

    def test_two_original_stories_produce_eight_fact_fields_and_specific_analysis(self):
        report,record=self.render([maintenance(),sanctions()])
        selected=editor.selected_stories(record)
        self.assertEqual(record["rules_version"],28);self.assertEqual(len(selected),2)
        self.assertEqual(sum(len(s["event_evidence"]["facts"]) for s in selected),8)
        self.assertIn("payment and counterparty exposure",report)
        self.assertNotIn("cross-border costs and supply chains",report)
        self.assertIn("maintenance opportunity",report)
        self.assertTrue(validate_news_brief(report)["passes"])

    def test_spoken_maintenance_is_summarized_without_headline_copy(self):
        _,record=self.render([maintenance(),sanctions()]);script=record["voiceover"]["script"]
        self.assertIn("C one thirty Hercules",script)
        self.assertNotIn("one hundred thirty",script)
        self.assertNotIn("Facility Selected as Certified",script)
        self.assertIn("Planned services",script)

    def test_missing_body_or_required_facts_are_held_without_poisoning_the_edition(self):
        for row in (maintenance(excerpt_scope="headline only",source_excerpt=""),maintenance(text="An unrelated original body with no designation or site facts. "*3)):
            report,record=self.render([row,sanctions()])
            held=next(r for r in record["candidates"] if r["publisher_symbol"]=="NOC")
            self.assertEqual(held["source_check"],"hold");self.assertNotIn("event_evidence",held)
            self.assertTrue(validate_news_brief(report)["passes"])

    def test_cached_body_dateline_conflict_is_held_before_selection(self):
        row=maintenance(text="EXAMPLE BAY, La. – October 1, 2026 – "+MAINTENANCE)
        _,record=self.render([row,sanctions()])
        held=next(r for r in record["candidates"] if r["publisher_symbol"]=="NOC")
        self.assertEqual(held["source_check"],"hold");self.assertIn("dateline",held["reason"])

    def test_unscoped_old_discovery_proof_needs_a_new_body_review(self):
        row=desk.verified({"url":URL},NOW,fetch=lambda url:page().encode())
        row["discovery_evidence"].pop("scope")
        _,record=self.render([row,sanctions()])
        held=next(r for r in record["candidates"] if r["publisher_symbol"]=="NOC")
        self.assertIn("scoped article-body review",held["reason"])

    def test_storylog_shows_each_fact_quote_and_the_unestablished_business_terms(self):
        _,record=self.render([maintenance(),sanctions()])
        log=editor.build_editor_status("NOC",history=True)
        self.assertIn("Fact evidence — maintenance_location",log)
        self.assertIn("Not established by these extracted facts",log)

    def test_actual_quality_card_and_command_pass_with_the_new_evidence_schemas(self):
        from types import SimpleNamespace
        loading=SimpleNamespace(edit_text=AsyncMock())
        update=SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock(return_value=loading)))
        with patch.object(editor,"cache_candidates",return_value=([maintenance(),sanctions()],[])),patch.object(daily_report,"build_research_report",return_value=self.research()):
            self.assertIn("Status: PASS",reportcheck_commands.build_daily_report_quality_card())
            asyncio.run(reportcheck_commands.reportcheck_command(update,SimpleNamespace()))
        self.assertIn("Status: PASS",loading.edit_text.call_args.args[0])

    def test_saved_rules26_report_script_and_export_hashes_are_preserved(self):
        record=json.loads((ROOT/'scripts/fixtures/disclosure_rules26_edition.json').read_text())
        self.assertEqual(voice.checked(record,NOW)["script_sha256"],"8223210da0a131c04dfb203be91500bbe9a9e2b6154b63a36b691c6b85a289b1")
        self.assertEqual(record["report_sha256"],"9b4212a95154b2e87fa21af40cfff8b4a10114f081e4f331a4e9ad2141e094bf")
        self.assertEqual(voice.episode(record,NOW)["voiceover_sha256"],record["voiceover"]["script_sha256"])

    def test_targeted_financial_context_does_not_become_the_lead_without_company_exposure(self):
        report,record=self.render([sanctions()])
        opening=next(row["text"] for row in record["analyst_review"]["insights"] if row["id"]=="opening_takeaway")
        self.assertNotIn("Treasury",opening)
        self.assertIn("Treasury said OFAC",report)


class SpeechChecks(unittest.TestCase):
    def test_new_designators_are_conversational_without_changing_legacy_scripts(self):
        self.assertEqual(normalize("C-130 Hercules",disclosure_names=True),"C one thirty Hercules")
        self.assertEqual(normalize("C-130J-30",disclosure_names=True),"C one thirty J thirty")
        self.assertEqual(normalize("C-130 Hercules"),"C-one hundred thirty Hercules")

    def test_amd_possessive_uses_the_short_name_only_in_new_reader_copy(self):
        evidence={"disclosure_version":1,"reader_limit":3,"stories":[],"earnings_context":[],"market_event_context":{"events":[]}}
        old=[{"id":"watch_business","section":"watch","text":"Advanced Micro Devices's business outlook: Watch original guidance.","sources":[]}]
        with patch('src.intelligence.reader_brief.watching',return_value=deepcopy(old)):
            rows=evidence_opening.watching(evidence)
        self.assertTrue(rows[0]["text"].startswith("AMD's"))
        self.assertEqual(normalize(rows[0]["text"],disclosure_names=True),"A M D's business outlook: Watch original guidance.")


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--windows-socketpair",action="store_true");args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (FactChecks,PublicationChecks,RebuildDetailChecks,SpeechChecks))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    good=result.wasSuccessful() and not traffic["blocked"]
    print(f"Disclosure Details Check: {'PASS' if good else 'FAIL'} ({result.testsRun} tests)")
    return 0 if good else 1


if __name__=='__main__':raise SystemExit(main())
