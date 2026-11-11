"""Offline regressions for market priority and dated refinery product yields.

The saved rules-24 edition and release text are synthetic. No requests or sends.
"""

import argparse
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks,NOW
from scripts.check_special_alerts import offline_network_guard,portable_tcp_socketpair
from src.intelligence import market_priority as priority,market_brief,refinery_mix as refinery
from src.intelligence import news_editor as editor,news_editor_store as store,market_event_desk as events,company_focus as focus
from src.intelligence import company_catalyst_context as companies,daily_brief_analysis as analysis
from src.intelligence.story_analysis import build_evidence,checked_evidence
from src.reports.daily_news_brief import build_daily_news_brief,validate_news_brief
from src.reports import daily_voiceover as voice


def previous():
    return json.loads((ROOT/"scripts/fixtures/market_rules24_edition.json").read_text())


def release(body=None,**changes):
    value=next(row for row in previous()["candidates"] if row["source"]=="EIA")
    value["source_excerpt"]=value.pop("event_evidence")["source_text"] if body is None else body
    value.pop("event_evidence",None)
    value["excerpt_scope"]="original release excerpt"
    value.update(changes)
    return value


BODY=release()["source_excerpt"]


def fields(body=BODY,**changes):
    row=release(body,**changes)
    return {f["field"]:f for f in refinery.product_facts(row,body)}


class RefineryChecks(unittest.TestCase):
    def test_product_shares_keep_comparisons_units_and_measurement_months(self):
        values=fields();self.assertEqual(len(values),5)
        gas=values["gasoline_yield_average"]
        self.assertEqual(gas["comparison"],"less than 47%")
        self.assertEqual(gas["period"],"January through June 2026")
        self.assertEqual(gas["unit"],"refinery product yield, percent")
        self.assertEqual(values["measurement_coverage"]["period_end"],"2026-06")

    def test_jet_first_exceedance_and_subsequent_floor_are_separate_dated_claims(self):
        values=fields()
        self.assertEqual(values["jet_fuel_first_exceeded"]["value"],"above 11% (April 2026)")
        self.assertEqual(values["jet_fuel_yield_floor"]["value"],"at or above 11% through June 2026")
        for fact in values.values():self.assertIn(fact["evidence"],BODY)

    def test_us_scope_cannot_be_inferred_from_a_foreign_fleet(self):
        self.assertFalse(fields(BODY.replace("U.S.","European")))

    def test_regional_gasoline_figures_do_not_become_a_national_average(self):
        self.assertFalse(fields(BODY.replace("refinery yields of gasoline","California refinery yields of gasoline")))

    def test_a_negated_us_anchor_does_not_supply_national_scope(self):
        self.assertFalse(fields(BODY.replace("The U.S.","No U.S.")))

    def test_typical_range_is_not_the_observed_average(self):
        text=BODY+" Gasoline refinery yields typically range from 45% to 50%."
        self.assertEqual(fields(text)["gasoline_yield_average"]["comparison"],"less than 47%")
        self.assertFalse(fields(text.replace("have averaged less than 47%","typically range from 45% to 50%")))

    def test_a_numeric_range_is_not_truncated_to_its_first_value(self):
        for value in ("47%-49%","47% to 49%","47% or 49%"):
            self.assertFalse(fields(BODY.replace("less than 47%",value)))

    def test_a_dated_average_can_be_followed_by_nonnumeric_publisher_context(self):
        text=BODY.replace("less than 47%.","less than 47% and reflect changes in production choices.")
        self.assertEqual(fields(text)["gasoline_yield_average"]["comparison"],"less than 47%")

    def test_future_or_incomplete_measurement_months_are_withheld(self):
        for month in ("October","November"):
            self.assertFalse(fields(BODY.replace("June 2026",month+" 2026")))

    def test_measurement_coverage_cannot_precede_the_reported_average(self):
        self.assertFalse(fields(BODY.replace("data through June 2026","data through May 2026")))

    def test_missing_measurement_coverage_or_average_is_not_material(self):
        for fragment in ("Petroleum Supply Monthly","have averaged"):
            self.assertFalse(fields(BODY.replace(fragment,"omitted detail")))

    def test_conflicting_gasoline_averages_are_withheld(self):
        extra=" From January through June 2026, refinery yields of gasoline have averaged less than 43%."
        self.assertFalse(fields(BODY+extra))

    def test_conflicting_coverage_months_are_withheld(self):
        self.assertFalse(fields(BODY+" Petroleum Supply Monthly includes data through May 2026."))

    def test_negated_and_speculative_yields_are_not_observations(self):
        for words in ("could have averaged","have not averaged","are forecast to have averaged"):
            self.assertFalse(fields(BODY.replace("have averaged",words)))

    def test_may_is_accepted_as_an_explicit_measurement_month(self):
        self.assertEqual(fields(BODY.replace("June 2026","May 2026"))["measurement_coverage"]["value"],"May 2026")

    def test_invalid_percentages_or_reversed_months_do_not_become_facts(self):
        for body in (BODY.replace("47%","147%"),BODY.replace("January through June","July through June")):
            self.assertFalse(fields(body))

    def test_jet_floor_requires_a_matching_unambiguous_first_exceedance(self):
        for body in (BODY.replace("exceeded an average","omitted an average"),
                     BODY.replace("at or above 11%","at or above 12%"),
                     BODY+" The U.S. refinery fleet exceeded an average jet fuel yield of 11% for the first time in March 2026."):
            self.assertNotIn("jet_fuel_yield_floor",fields(body))

    def test_jet_dates_cannot_extend_past_the_latest_data_month(self):
        self.assertNotIn("jet_fuel_first_exceeded",fields(BODY.replace("April 2026","July 2026")))
        self.assertNotIn("jet_fuel_yield_floor",fields(BODY.replace("data for June 2026","data for July 2026")))

    def test_spoofed_or_unrelated_sources_cannot_use_this_profile(self):
        for change in ({"url":"https://www.eia.gov.example.com/todayinenergy/detail.php?id=123"},
                       {"url":"https://www.eia.gov/todayinenergy/detail.php?id=1&id=2"},
                       {"source":"Example"},{"title":"Global refinery inputs fell in the second quarter"}):
            row=release(**change);self.assertFalse(refinery.applicable(row))
            with self.assertRaises(ValueError):build_evidence(row,BODY,"original release excerpt",schema=11)

    def test_only_an_original_body_with_a_zoned_clock_can_supply_product_facts(self):
        with self.assertRaises(ValueError):build_evidence(release(),BODY,"publisher feed excerpt",schema=11)
        with self.assertRaises(ValueError):fields(published="2026-10-25")

    def test_changed_fact_period_or_source_text_breaks_validation(self):
        for key in ("value","period"):
            row=release();row["event_evidence"]=build_evidence(row,BODY,"original release excerpt",schema=11)
            row["event_evidence"]["facts"][1][key]="invented"
            with self.assertRaises(ValueError):checked_evidence(row)


class MarketChecks(unittest.TestCase):
    def evidence(self,**changes):
        value=deepcopy(previous()["analyst_review"]["evidence"])
        value.update(reader_version=4,is_open=True)
        value.update(changes);return value

    def test_sharp_observed_declines_and_scoped_participation_lead(self):
        text=priority.opening(self.evidence())
        self.assertIn("Nasdaq is down 4.30 percent",text)
        self.assertIn("S&P 500 is down 2.79 percent",text)
        self.assertIn("18 stocks and funds we track, 1 is higher",text)
        self.assertNotIn("Critical Design Review",text)

    def test_missing_index_values_do_not_erase_observed_pressure(self):
        value=self.evidence(moves={"S&P":-2.79,"Nasdaq":-4.3})
        text=market_brief.market_segment(value)
        self.assertIn("cautious based on available indexes; coverage is incomplete",text)
        self.assertNotIn("Russell",text);self.assertNotIn("VIX",text)
        self.assertNotIn("All three",priority.opening(value))

    def test_a_single_index_can_establish_pressure_without_inventing_others(self):
        value=self.evidence(moves={"S&P":-2},breadth=None)
        self.assertTrue(priority.selloff(value))
        self.assertIn("S&P 500 is down 2.00",priority.opening(value))
        self.assertNotIn("Nasdaq",priority.opening(value))

    def test_price_pressure_precedes_an_energy_topic_in_the_portfolio_lens(self):
        text=market_brief.market_segment(self.evidence())
        self.assertIn("concentrated growth exposure",text)
        self.assertNotIn("Higher energy costs could squeeze margins",text)
        self.assertIn("VIX rose 49.43 percent",text)

    def test_incomplete_market_narration_keeps_a_qualified_cautious_read(self):
        text=voice.market_copy(self.evidence(moves={"S&P":-2.79,"Nasdaq":-4.3}))
        self.assertIn("cautious; index coverage is incomplete",text)
        self.assertNotIn("Russell",text)
        self.assertLessEqual(voice.words(voice.normalize(text))+4,voice.MAX_MARKET_WORDS)

    def test_no_dated_session_or_positive_volatility_alone_triggers_selloff(self):
        for value in (self.evidence(session=None),self.evidence(moves={"S&P":1,"Nasdaq":1.2,"VIX":50}),self.evidence(moves={})):
            self.assertFalse(priority.selloff(value))

    def test_nonfinite_and_boolean_values_are_not_pressure_evidence(self):
        for moves in ({"Nasdaq":float("nan")},{"S&P":float("-inf")},{"S&P":False}):
            self.assertFalse(priority.sharp_loss(moves))

    def test_mixed_directions_are_stated_as_observed(self):
        text=priority.opening(self.evidence(moves={"Nasdaq":-4.3,"S&P":.5,"Russell":1}))
        self.assertIn("S&P 500 is up 0.50",text);self.assertNotIn("All three",text)

    def test_completed_sessions_keep_past_tense(self):
        text=priority.opening(self.evidence(is_open=False))
        self.assertIn("Nasdaq fell 4.30",text);self.assertIn("1 finished higher",text)
        self.assertNotIn("is down",text)

    def test_singular_up_down_and_one_total_use_singular_verbs(self):
        for breadth,expected in (({"up":1,"down":17,"total":18},"1 is higher"),
                                 ({"up":17,"down":1,"total":18},"1 is lower"),
                                 ({"up":0,"down":1,"total":1},"one stock or fund we track is lower")):
            value=self.evidence(breadth=breadth)
            self.assertIn(expected,priority.opening(value))
            self.assertIn(expected,priority.watching(value)[0]["text"])

    def test_non_selloff_opening_stays_source_led(self):
        text=priority.opening(self.evidence(moves={"S&P":.5,"Nasdaq":.8,"Russell":.2}))
        self.assertIn("XR-42",text);self.assertIn("Critical Design Review",text)

    def test_selling_and_largest_rechecked_company_are_the_first_two_checks(self):
        rows=priority.watching(self.evidence())
        self.assertEqual([row["id"] for row in rows[:2]],["watch_participation","watch_event"])
        self.assertIn("Advanced Micro Devices",rows[1]["text"])
        self.assertIn("Critical Design Review",rows[2]["text"])


class EditionChecks(IsolatedChecks):
    def render(self,values=None,research=None):
        old=previous();research=research or old["research_text"]
        if values is None:
            values=[]
            for saved in old["candidates"]:
                row=deepcopy(saved);row["source_excerpt"]=row.pop("event_evidence")["source_text"]
                row["excerpt_scope"]="original release excerpt";values.append(row)
        context=deepcopy(old["market_event_context"]);context["report_sha256"]=voice.digest(research)
        with patch.object(editor,"cache_candidates",return_value=(values,[])),patch.object(events,"context_for_report",return_value=context),patch.object(focus,"history_context",return_value=old["analyst_review"]["focus_context"]):
            report=build_daily_news_brief(research)
        return report,store.read_editions(report=report)[0]

    def test_rechecked_amd_tesla_palantir_beat_pending_nvidia_despite_recent_amd_exposure(self):
        _,record=self.render();rows=record["analyst_review"]["evidence"]["company_focus"]["selected"]
        self.assertEqual([row["symbol"] for row in rows],["AMD","TSLA","PLTR"])
        self.assertGreater(rows[0]["recent_days"],0)

    def test_rechecked_movers_are_not_limited_to_the_three_ranked_companies(self):
        _,record=self.render();evidence=record["analyst_review"]["evidence"]
        self.assertNotIn("AMD",[row["symbol"] for row in evidence["companies"]])
        self.assertIn("AMD",evidence["company_focus"]["featured_symbols"])

    def test_market_and_companies_sections_precede_secondary_source_sections(self):
        report,_=self.render()
        self.assertLess(report.index("\nMarket Update\n"),report.index("\nCompanies in Focus\n"))
        self.assertLess(report.index("\nCompanies in Focus\n"),report.index("\nPolicy & Economy\n"))

    def test_original_eia_body_is_selected_with_five_dated_facts(self):
        report,record=self.render();story=next(row for row in editor.selected_stories(record) if row["source"]=="EIA")
        self.assertEqual(story["event_evidence"]["schema"],11);self.assertEqual(len(story["event_evidence"]["facts"]),5)
        self.assertIn("January through June 2026",report);self.assertIn("at or above 11 percent through June 2026",report)
        self.assertIn("In its October 25 report",report);self.assertNotIn("Review the original report for scope",report)

    def test_eia_headline_without_original_body_is_held(self):
        row=release();row.pop("source_excerpt");row.pop("excerpt_scope")
        plan=editor.build_editorial_plan(companies.build_company_catalyst_brief(),NOW,[row])
        self.assertEqual(plan["candidates"][0]["source_check"],"hold")

    def test_eia_body_without_dated_yields_does_not_pass_by_its_headline(self):
        row=release("The original EIA article describes refinery product choices without reporting a dated average for any fuel. "*2)
        plan=editor.build_editorial_plan(companies.build_company_catalyst_brief(),NOW,[row])
        self.assertEqual(plan["candidates"][0]["decision"],"skip")

    def test_market_only_hook_and_lens_do_not_cite_unrelated_eia_or_defense_sources(self):
        _,record=self.render();segments=voice.checked(record,NOW)["segments"]
        self.assertEqual(segments[0]["source_ids"],[]);self.assertEqual(segments[1]["source_ids"],[])
        self.assertNotIn("XR-forty two",segments[0]["narration"])
        self.assertEqual(segments[2]["heading"],"Companies in Focus")
        self.assertIn("Advanced Micro Devices",segments[2]["narration"])

    def test_eia_voiceover_retains_dated_fuel_yields_and_its_own_source(self):
        _,record=self.render();episode=voice.episode(record,NOW)
        scene=next(row for row in episode["segments"] if row["heading"]=="Energy Watch")
        self.assertIn("January through June two thousand twenty six",scene["narration"])
        self.assertEqual(len(scene["source_ids"]),1)
        self.assertEqual(episode["sources"][scene["source_ids"][0]][0]["publisher"],"EIA")
        self.assertNotIn("interest rate",scene["narration"].lower())

    def test_numeric_rankings_and_research_snapshot_are_unchanged(self):
        research=previous()["research_text"];before=self.ranking.read_bytes()
        _,record=self.render(research=research)
        self.assertEqual(record["research_text"],research);self.assertEqual(self.ranking.read_bytes(),before)
        self.assertIs(record["analyst_review"]["score_changes"],False)

    def test_new_report_and_private_schema2_export_pass_all_budgets(self):
        report,record=self.render();episode=voice.episode(record,NOW)
        self.assertEqual(record["rules_version"],32);self.assertEqual(record["analyst_review"]["reader_version"],4)
        self.assertTrue(validate_news_brief(report)["passes"]);self.assertTrue(record["voiceover"]["quality"]["passes"])
        self.assertEqual(episode["voiceover_schema"],2);self.assertEqual(episode["mode"],"draft_review_required")

    def test_changed_market_takeaway_breaks_frozen_review(self):
        report,record=self.render();review=deepcopy(record["analyst_review"])
        next(row for row in review["insights"] if row["id"]=="opening_takeaway")["text"]="All stocks will recover."
        with self.assertRaises(ValueError):analysis.validate_review(review,record["research_text"],report,editor.selected_stories(record))

    def test_saved_rules24_report_voiceover_and_focus_are_unchanged(self):
        record=previous()
        self.assertEqual(record["report_sha256"],"64e36fe323ecec24907decaea7f333a7e374eee1920df28c3ff9b5a997b19818")
        self.assertEqual(voice.checked(record,NOW)["script_sha256"],"4b6245c7af12651b9bbf0f2b4138b90b20c67efd3147113ac7e30788313f6d63")
        self.assertEqual(record["analyst_review"]["evidence"]["company_focus"]["featured_symbols"],["NVDA","PLTR","TSLA"])


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--windows-socketpair",action="store_true");args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in (RefineryChecks,MarketChecks,EditionChecks))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    passed=result.wasSuccessful() and not traffic["blocked"]
    print(f"Market Priority Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__=="__main__":raise SystemExit(main())
