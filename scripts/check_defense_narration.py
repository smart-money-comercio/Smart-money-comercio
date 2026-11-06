"""Offline regressions for program context, disclosure-led openings and speech.

Release text and program names below are synthetic. No requests or sends run.
"""

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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks,NOW
from scripts.check_news_editor import candidate
from scripts.check_financing_editorial import treasury,FINANCING
from scripts.check_event_news import quote
from scripts.check_special_alerts import offline_network_guard,portable_tcp_socketpair
from src.intelligence import defense_program as programs,evidence_opening as opening,news_editor as editor,news_editor_store as store
from src.intelligence import company_catalyst_context as companies,market_event_desk as events,company_focus as focus
from src.intelligence import daily_brief_analysis as analysis,treasury_financing
from src.intelligence.story_analysis import build_evidence,checked_evidence
from src.reports.daily_news_brief import build_daily_news_brief,validate_news_brief
from src.reports import daily_voiceover as voice


TITLE="Lockheed Martin Completes Flight Test of Military Development Vehicle"
BODY=("Lockheed Martin and the U.S. Air Force completed a test flight of its unarmed, developmental XR-42 uncrewed system.\n"
      "Executed under a prime military contract valued at over $2.4B, the flight supplied development data.\n"
      "The program is working toward system-level Critical Design Review (CDR).")


def release(text=BODY,**changes):
    value=candidate("LMT",title=TITLE,source="Lockheed Martin Newsroom",url="https://news.lockheedmartin.com/synthetic-development-test",
        source_excerpt=text,excerpt_scope="original release excerpt",evidence_checked_at=NOW.isoformat())
    value.update(changes)
    return value


def proof(row=None):
    row=release() if row is None else row
    return build_evidence(row,row["source_excerpt"],"original release excerpt",schema=10)


class ProgramFactChecks(unittest.TestCase):
    def test_names_the_program_development_stage_and_reported_completion(self):
        value=proof();fields={f["field"]:f for f in value["facts"]}
        self.assertEqual(fields["program_name"]["value"],"XR-42 uncrewed system")
        self.assertEqual(fields["program_stage"]["value"],"developmental")
        self.assertEqual(fields["development_test"]["value"],"company-reported completed flight test")
        self.assertIn("production readiness not established",fields["program_stage"]["status"])

    def test_customer_contract_context_and_future_gate_have_separate_quotes(self):
        fields={f["field"]:f for f in proof()["facts"]}
        self.assertEqual(len(fields),6);self.assertEqual(fields["program_customer"]["value"],"U.S. Air Force")
        self.assertEqual(fields["existing_program_contract"]["value"],"over $2.4 billion")
        self.assertEqual(fields["next_program_gate"]["value"],"Critical Design Review")
        self.assertIn("new award, obligation and revenue not established",fields["existing_program_contract"]["status"])
        self.assertIn("completion and date not established",fields["next_program_gate"]["status"])
        for row in fields.values():self.assertIn(row["evidence"],BODY)

    def test_preserves_contract_ceiling_qualifier_instead_of_claiming_funding(self):
        fields={f["field"]:f for f in proof(release(BODY.replace("over $2.4B","up to $2.4B")))["facts"]}
        self.assertEqual(fields["existing_program_contract"]["value"],"up to $2.4 billion")
        self.assertNotIn("obligated_amount",fields);self.assertNotIn("contract_value",fields)

    def test_a_new_award_sentence_does_not_become_an_existing_program_value(self):
        body=BODY.replace("Executed under a prime military contract valued at over $2.4B, the flight supplied development data.",
                          "Lockheed Martin won a new $2.4 billion contract.")
        fields={f["field"] for f in proof(release(body))["facts"]}
        self.assertNotIn("existing_program_contract",fields)

    def test_future_negated_failed_historical_and_speculative_tests_are_withheld(self):
        for words in ("will complete","did not complete","failed to complete","previously completed","could complete"):
            body=BODY.replace("completed",words,1)
            self.assertEqual(programs.program_facts(release(body),body),[])

    def test_an_older_explicit_event_year_is_not_treated_as_the_current_test(self):
        body=BODY.replace("Lockheed Martin","In 2024, Lockheed Martin",1)
        self.assertEqual(programs.program_facts(release(body),body),[])

    def test_a_prior_day_dateline_across_new_year_accepts_iso_and_zoned_rss_clocks(self):
        body="December 31, 2026 — " + BODY
        for clock in ("2027-01-01T01:00:00+00:00","Thu, 31 Dec 2026 20:00:00 -0500"):
            self.assertEqual(len(proof(release(body,published=clock))["facts"]),6)

    def test_a_supplier_test_is_not_credited_to_the_issuer(self):
        body=BODY.replace("Lockheed Martin and the U.S. Air Force","A supplier of Lockheed Martin")
        self.assertEqual(programs.program_facts(release(body),body),[])

    def test_an_operational_platform_is_not_silently_labeled_developmental(self):
        body=BODY.replace("developmental","operational")
        self.assertEqual(programs.program_facts(release(body),body),[])

    def test_two_distinct_completed_program_tests_are_ambiguous(self):
        body=BODY+"\n"+BODY.splitlines()[0].replace("XR-42","XR-99")
        self.assertEqual(programs.program_facts(release(body),body),[])

    def test_second_program_blocks_unscoped_contract_and_gate_attachment(self):
        body=BODY.splitlines()[0]+"\nA separate XR-99 aircraft is being developed.\n"+"\n".join(BODY.splitlines()[1:])
        fields={r["field"] for r in proof(release(body))["facts"]}
        self.assertNotIn("existing_program_contract",fields);self.assertNotIn("next_program_gate",fields)

    def test_conflicting_contract_values_are_not_resolved_by_first_match(self):
        body=BODY+"\n"+BODY.splitlines()[1].replace("$2.4B","$3.4B")
        self.assertNotIn("existing_program_contract",{r["field"] for r in proof(release(body))["facts"]})

    def test_a_completed_review_is_not_recast_as_a_future_gate(self):
        body=BODY.replace("working toward system-level Critical Design Review (CDR)","past Critical Design Review (CDR)")
        self.assertNotIn("next_program_gate",{r["field"] for r in proof(release(body))["facts"]})

    def test_pending_headline_does_not_use_completed_test_evidence(self):
        row=release(title="Lockheed Martin Plans Military Flight Test")
        self.assertFalse(programs.applicable(row))
        with self.assertRaises(ValueError):proof(row)

    def test_impostor_or_unrelated_issuer_cannot_use_program_profile(self):
        for change in ({"url":"https://news.lockheedmartin.com.example.com/release"},{"publisher_symbol":"MSFT"}):
            with self.assertRaises(ValueError):proof(release(**change))

    def test_feed_excerpt_cannot_use_original_program_fact_profile(self):
        with self.assertRaises(ValueError):build_evidence(release(),BODY,"publisher feed excerpt",schema=10)

    def test_tampered_fact_or_stage_breaks_evidence_validation(self):
        for key in ("stage","facts"):
            row=release();row["event_evidence"]=proof(row)
            if key=="stage":row["event_evidence"][key]="production"
            else:row["event_evidence"][key][0]["value"]="XR-99 aircraft"
            with self.assertRaises(ValueError):checked_evidence(row)


class EditionChecks(IsolatedChecks):
    def render(self,values=None,moves=None,pending=None):
        values=[release(),treasury()] if values is None else values
        moves={"AAPL":5.3,"AMZN":6.1,"MSFT":6.7} if moves is None else moves
        quotes={s:quote(s,v) for s,v in moves.items()}
        def repeated(symbol):return quote(symbol,moves[symbol]-8) if symbol==pending else quotes[symbol]
        events.review_quotes(quotes,repeated,NOW)
        research=self.research(replacements={"Watchlist Movers":"Largest regular-session movers:\n"+"\n".join(f"• {s}: $100.00 ({v:+.2f}%)" for s,v in moves.items())})
        with patch.object(editor,"cache_candidates",return_value=(values,[])):
            report=build_daily_news_brief(research)
        return report,store.read_editions(report=report)[0]

    def test_original_program_reader_extracts_six_fields_in_a_selected_story(self):
        _,record=self.render();story=next(s for s in editor.selected_stories(record) if s["publisher_symbol"]=="LMT")
        self.assertEqual(story["event_evidence"]["schema"],10);self.assertEqual(len(story["event_evidence"]["facts"]),6)
        self.assertEqual(story["materiality"],"defense innovation")

    def test_existing_capability_reader_remains_the_fallback_for_other_tests(self):
        row=release(text="Lockheed Martin demonstrated in-flight retargeting during an Army rocket test. The company described the completed event as a development test.",
                    title="Lockheed Martin validates in-flight retargeting during an Army rocket test")
        plan=editor.build_editorial_plan(companies.build_company_catalyst_brief(),NOW,[row])
        self.assertEqual(plan["candidates"][0]["event_evidence"]["schema"],8)
        self.assertIn("tested_capability",{r["field"] for r in plan["candidates"][0]["event_evidence"]["facts"]})

    def test_stale_body_clock_cannot_supply_a_program_profile(self):
        row=release(evidence_checked_at=(NOW-timedelta(hours=7)).isoformat())
        plan=editor.build_editorial_plan(companies.build_company_catalyst_brief(),NOW,[row])
        self.assertEqual(plan["candidates"][0]["source_check"],"hold")

    def test_both_substantive_stories_fit_without_dropping_the_defense_item(self):
        report,record=self.render();self.assertEqual(len(editor.selected_stories(record)),2)
        self.assertEqual(record["rules_version"],26);self.assertEqual(record["analyst_review"]["reader_version"],4)
        self.assertTrue(validate_news_brief(report)["passes"]);self.assertLessEqual(len(report),3800)

    def test_program_summary_uses_past_tense_and_keeps_existing_contract_context(self):
        report,record=self.render();script=record["voiceover"]["script"]
        self.assertIn("reported a completed flight test",report)
        self.assertIn("XR-42",report);self.assertIn("existing prime contract valued at over $2.4 billion",report)
        self.assertIn("Critical Design Review",script);self.assertNotIn(TITLE,script)
        self.assertNotIn("new contract award",script)

    def test_grouped_price_moves_have_one_shared_company_disclosure_check(self):
        _,record=self.render();scenes=[s for s in record["voiceover"]["segments"] if s["heading"]=="Companies in Focus"]
        self.assertEqual(len(scenes),1);text=scenes[0]["narration"]
        for name in ("Apple","Amazon","Microsoft"):self.assertIn(name,text)
        self.assertEqual(record["voiceover"]["script"].count("Check original company results and guidance"),1)
        self.assertNotIn("Across semiconductor",text)

    def test_pending_quote_remains_separate_from_rechecked_group(self):
        report,record=self.render(pending="AMZN");evidence=record["analyst_review"]["evidence"]
        group=focus.grouped_price_watch(evidence)
        self.assertIsNotNone(group);self.assertNotIn("AMZN",group["symbols"])
        self.assertNotIn("Amazon rose six point one",record["voiceover"]["script"])
        self.assertIn("under review",report)

    def test_price_group_excludes_named_company_results_context(self):
        _,record=self.render();evidence=deepcopy(record["analyst_review"]["evidence"])
        evidence["earnings_context"]=[{"symbol":"MSFT"}]
        self.assertNotIn("MSFT",focus.grouped_price_watch(evidence)["symbols"])

    def test_takeaway_uses_admitted_financing_fact_with_a_matching_source_reference(self):
        _,record=self.render();profile=voice.checked(record,NOW);first=profile["segments"][0]
        story=next(s for s in editor.selected_stories(record) if s["source"]=="U.S. Treasury")
        self.assertIn("twenty billion dollars in new cash",first["narration"])
        self.assertIn(story["id"],first["source_ids"]);self.assertIn(story["id"],profile["sources"])
        self.assertNotIn("sharp advance",first["narration"])

    def test_without_treasury_the_named_program_can_supply_the_takeaway(self):
        _,record=self.render([release()]);first=record["voiceover"]["segments"][0]
        self.assertIn("XR-forty two",first["narration"])
        self.assertIn("Critical Design Review",first["narration"])
        self.assertEqual(first["source_ids"],[editor.selected_stories(record)[0]["id"]])

    def test_contract_opening_preserves_the_natural_award_worth_amount_word_order(self):
        from scripts.check_disclosure_intelligence import source
        _,record=self.render([source("CACI")]);script=record["voiceover"]["script"]
        self.assertIn("worth sixty four million dollars",script)
        self.assertNotIn("million dollars contract award",script)

    def test_financial_opening_uses_reported_revenue_and_a_clean_reporting_period(self):
        from scripts.check_company_earnings import source
        row=source();row["published"]=(NOW-timedelta(minutes=30)).isoformat()
        _,record=self.render([row]);intro=next(r["text"] for r in record["analyst_review"]["insights"] if r["id"]=="opening_takeaway")
        self.assertIn("$12.5 billion for third quarter 2026",intro)
        self.assertNotIn(", reported.",intro);self.assertNotIn("$13.0 billion",intro)

    def test_removed_or_unconfirmed_release_cannot_supply_the_opening(self):
        _,record=self.render([release(official=False)])
        self.assertNotIn("XR-42",record["voiceover"]["segments"][0]["narration"])

    def test_next_check_names_the_disclosed_review_instead_of_generic_price_cause(self):
        _,record=self.render();watch=next(r["text"] for r in record["analyst_review"]["insights"] if r["id"]=="watch_business")
        self.assertIn("Critical Design Review outcome",watch)
        self.assertNotIn("business outlook",watch)

    def test_changed_opening_fails_frozen_evidence_review(self):
        report,record=self.render();review=deepcopy(record["analyst_review"])
        row=next(r for r in review["insights"] if r["id"]=="opening_takeaway")
        row["text"]=row["text"].replace("$20 billion","$999 billion")
        with self.assertRaises(ValueError):analysis.validate_review(review,record["research_text"],report,editor.selected_stories(record))

    def test_schema2_export_and_private_review_requirement_are_preserved(self):
        _,record=self.render();episode=voice.episode(record,NOW)
        self.assertEqual(episode["voiceover_schema"],2);self.assertEqual(episode["mode"],"draft_review_required")
        self.assertTrue(episode["review_required"])
        used={key for scene in episode["segments"] for key in scene["source_ids"]}
        self.assertEqual(used,set(episode["sources"]))

    def test_rules23_saved_report_and_voiceover_hashes_remain_valid(self):
        record=json.loads((ROOT/"scripts/fixtures/defense_rules23_edition.json").read_text())
        self.assertEqual(record["report_sha256"],"250a013f8d5eb3638a8eb6937ac904d9ee2fe2603627a3b6bc54b3fa5d56174f")
        self.assertEqual(voice.checked(record,NOW)["script_sha256"],"4d9706c19b9b0bffaf881f435844ff62292eedd66e64cdd4bf650dc25a542b03")


class OpeningAndSpeechChecks(unittest.TestCase):
    def evidence(self,**changes):
        value={"reader_version":3,"is_open":False,"moves":{"S&P":1.5,"Nasdaq":1.4,"Russell":1.6},
               "breadth":{"up":10,"down":8,"total":18},"stories":[],"market_event_context":{"events":[]},"earnings_context":[]}
        value.update(changes);return value

    def test_missing_russell_does_not_turn_two_index_gains_into_three(self):
        text=opening.opening(self.evidence(moves={"S&P":1.5,"Nasdaq":1.4}))
        self.assertNotIn("All three",text);self.assertIn("S&P 500 and Nasdaq",text)

    def test_completed_and_open_sessions_use_the_correct_tense(self):
        self.assertIn("rose in the completed session",opening.opening(self.evidence()))
        self.assertIn("are higher in the quoted session",opening.opening(self.evidence(is_open=True)))

    def test_watchlist_weakness_is_not_hidden_by_index_gains(self):
        text=opening.opening(self.evidence(breadth={"up":3,"down":15,"total":18}))
        self.assertIn("Most names in our tracked group still finished lower",text)

    def test_unselected_and_held_stories_cannot_supply_source_facts(self):
        row=treasury();row["event_evidence"]=build_evidence(row,FINANCING,"original release excerpt",schema=9)
        for change in ({"decision":"skip","source_check":"pass"},{"decision":"selected","source_check":"hold"}):
            self.assertIsNone(opening.opening_source(self.evidence(stories=[{**row,**change}])))

    def test_spoken_auction_dates_keep_each_tenor_and_drop_hanging_hyphens(self):
        row=treasury();profile=build_evidence(row,FINANCING,"original release excerpt",schema=9)
        text=treasury_financing.summary(profile,speech=True)
        self.assertIn("three-year note auction is scheduled for October 26",text);self.assertIn("ten-year note auction for October 27",text)
        self.assertIn("thirty-year bond auction for October 29, 2026",text)
        self.assertNotIn("respectively",text);self.assertNotIn("three-,",text)

    def test_default_treasury_summary_retains_historical_wording(self):
        row=treasury();profile=build_evidence(row,FINANCING,"original release excerpt",schema=9)
        self.assertIn("three-, ten- and thirty-year",treasury_financing.summary(profile))
        self.assertIn("respectively",treasury_financing.summary(profile))

    def test_partial_schedule_is_not_completed_by_guessing_missing_auction_dates(self):
        row=treasury(text=FINANCING.replace("Monday, October 26, 2026","Tuesday, October 26, 2026"))
        profile=build_evidence(row,row["source_excerpt"],"original release excerpt",schema=9)
        self.assertNotIn("October 26",treasury_financing.summary(profile,speech=True))
        self.assertIn("$90 billion",treasury_financing.summary(profile,speech=True))


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--windows-socketpair",action="store_true");args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in
            (ProgramFactChecks,EditionChecks,OpeningAndSpeechChecks))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    passed=result.wasSuccessful() and not traffic["blocked"]
    print(f"Defense Narration Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__=="__main__":raise SystemExit(main())
