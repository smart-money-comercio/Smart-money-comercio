"""Offline regressions for source-bound business interpretation and narration."""

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
sys.path.insert(0, str(ROOT))
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from scripts.check_daily_news_brief import IsolatedChecks, NOW as DAILY_NOW
from scripts.check_disclosure_details import RebuildDetailChecks, maintenance, sanctions
from scripts.check_defense_narration import release
from scripts.check_disclosure_intelligence import source
from scripts.check_weekend_outlook import NOW, calendar, market_fetch, story, notice
from src.intelligence import business_analysis as business, weekend_business
from src.intelligence import news_editor, weekend_store
from src.reports import daily_voiceover, weekend_outlook, weekend_media_contract
from src.reports.daily_news_brief import validate_news_brief
from src.utils.speech_text import normalize


def frozen():
    return json.loads((ROOT / "scripts/fixtures/business_rules30_legacy.json").read_text(encoding="utf-8"))


def weekend():
    stamps = {"source_checked_at": NOW.isoformat(), "evidence_checked_at": NOW.isoformat()}
    raw = [story(), release(published="2026-11-04T19:00:00+00:00", **stamps),
           source("CACI", published="2026-11-03T13:15:00+00:00", **stamps), notice()]
    return weekend_outlook.build(now=NOW, raw=raw, market_fetch=market_fetch,
                                 calendar_snapshot=calendar(), persist=False)


class BusinessChecks(unittest.TestCase):
    def setUp(self):
        self.stories = frozen()["weekend"]["inputs"]["stories"]
        self.by_symbol = {row["publisher_symbol"]: row for row in self.stories}

    def test_award_review_binds_its_value_and_term_fields(self):
        row = self.by_symbol["CACI"]
        value = business.assess(row)
        self.assertEqual(value["event_class"], "award")
        self.assertEqual(value["channel"], "contracted workload")
        self.assertIn("contract_value", value["basis_fields"])
        self.assertIn("contract_term", value["basis_fields"])
        self.assertEqual(value["source_sha256"], row["event_evidence"]["source_sha256"])
        self.assertEqual(business.checked(row, value), value)

    def test_existing_program_value_is_development_context(self):
        value = business.assess(self.by_symbol["LMT"])
        self.assertEqual(value["event_class"], "development")
        self.assertIn("existing_program_contract", value["basis_fields"])
        self.assertIn("existing program", value["why"])
        self.assertIn("Critical Design Review", value["watch"])

    def test_contract_ceiling_does_not_become_an_award_value(self):
        from scripts.check_disclosure_intelligence import AWARD
        from src.intelligence.story_analysis import build_evidence
        row = source("CACI", text=AWARD.replace("$64 million", "up to $64 million"))
        row["event_evidence"] = build_evidence(row, row["source_excerpt"], "original release excerpt", schema=8)
        value = business.assess(row)
        self.assertNotEqual(value["event_class"], "award")
        self.assertEqual(value["stage"], "ceiling")

    def test_maintenance_designation_requires_following_orders(self):
        value = business.assess(self.by_symbol["NOC"])
        self.assertEqual(value["event_class"], "maintenance")
        self.assertIn("maintenance_designation", value["basis_fields"])
        self.assertIn("service-order value", value["decision_test"])
        self.assertNotIn("contract_value", value["basis_fields"])

    def test_tampered_original_fact_cannot_supply_a_business_read(self):
        row = deepcopy(self.by_symbol["CACI"])
        row["event_evidence"]["facts"][0]["value"] = "$900 billion"
        with self.assertRaises(ValueError):
            business.assess(row)

    def test_forged_interpretation_and_source_fields_are_rejected(self):
        row = self.by_symbol["LMT"]
        for key, bad in (("why", "Guaranteed revenue"), ("basis_fields", ["new_order"]), ("source_sha256", "x")):
            value = business.assess(row)
            value[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                business.checked(row, value)

    def test_a_third_party_url_cannot_inherit_original_analysis(self):
        row = deepcopy(self.by_symbol["NOC"])
        row["url"] = "https://example.com/copied-release"
        with self.assertRaises(ValueError):
            business.assess(row)

    def test_headline_only_evidence_cannot_establish_a_business_read(self):
        row = deepcopy(self.by_symbol["CACI"])
        row.pop("event_evidence")
        self.assertIsNone(business.assess(row))

    def test_comparison_is_stage_specific_and_source_bound(self):
        value = business.compare(self.stories)
        self.assertIn("new award", value["text"])
        self.assertIn("existing program context", value["text"])
        self.assertIn("maintenance role", value["text"])
        self.assertEqual({row["story_id"] for row in value["sources"]}, {row["id"] for row in self.stories})
        for row in value["sources"]:
            story = next(story for story in self.stories if story["id"] == row["story_id"])
            self.assertEqual(row["source_sha256"], story["event_evidence"]["source_sha256"])
            self.assertTrue(set(row["basis_fields"]) <= {fact["field"] for fact in story["event_evidence"]["facts"]})

    def test_same_stage_and_same_issuer_do_not_create_a_comparison(self):
        row = self.by_symbol["NOC"]
        self.assertIsNone(business.compare([row, deepcopy(row)]))
        self.assertIsNone(business.compare([row]))


class DailyChecks(RebuildDetailChecks):
    # Keep only the new tests in this class; the inherited regressions run separately.
    def test_new_daily_retains_both_stories_and_all_research_scores(self):
        text, record = self.render([maintenance(), sanctions()])
        self.assertEqual(record["rules_version"], 32)
        self.assertEqual(record["business_version"], 7)
        self.assertEqual(len(news_editor.selected_stories(record)), 2)
        self.assertTrue(validate_news_brief(text)["passes"])
        self.assertLessEqual(len(text), 3800)
        self.assertTrue(daily_voiceover.checked(record, DAILY_NOW)["quality"]["passes"])
        before = frozen()["daily"]["analyst_review"]
        current = record["analyst_review"]
        self.assertFalse(current["score_changes"])
        for key in ("moves", "breadth", "companies"):
            self.assertEqual(before["evidence"][key], current["evidence"][key])
        self.assertEqual(len(current["evidence"]["business_reviews"]), 2)

    def test_daily_copy_is_conversational_and_dates_remain(self):
        text, record = self.render([maintenance(), sanctions()])
        self.assertIn("In its October 25 disclosure", text)
        self.assertNotIn("Investor take:", text)
        self.assertNotIn("Our view on", text)
        self.assertNotIn("The key takeaway.", record["voiceover"]["script"])
        self.assertIn("maintenance orders", text)

    def test_forged_daily_business_basis_fails_voice_revalidation(self):
        _, record = self.render([maintenance(), sanctions()])
        changed = deepcopy(record)
        changed["analyst_review"]["evidence"]["business_reviews"][0]["analysis"]["basis_fields"] = ["invented"]
        with self.assertRaises(ValueError):
            daily_voiceover.checked(changed, DAILY_NOW)


class WeekendChecks(unittest.TestCase):
    def test_new_weekend_is_rules31_with_checked_business_analysis(self):
        value = weekend()
        self.assertEqual(value["rules_version"], 31)
        self.assertEqual(value["inputs"]["business_version"], 1)
        self.assertEqual(value["quality"]["status"], "PASS")
        self.assertEqual(len(value["inputs"]["business_analysis"]["reviews"]), 3)
        self.assertEqual(weekend_outlook.checked(value, NOW, require_publishable=True), value)

    def test_weekend_keeps_the_seven_scene_media_contract(self):
        value = weekend()
        packet = weekend_outlook.episode(value, NOW)
        script = value["voiceover"]["script"]
        self.assertEqual(len(packet["segments"]), 7)
        self.assertEqual(packet["weekend_narration_revision"], 2)
        self.assertEqual("\n\n".join(row["narration"] for row in packet["segments"]), script)
        self.assertEqual(weekend_media_contract.validate_packet(packet, script)["status"], "PASS")

    def test_weekend_keeps_all_admitted_facts(self):
        old = {row["id"]: row["event_evidence"] for row in frozen()["weekend"]["inputs"]["stories"]}
        value = weekend()
        self.assertEqual({row["id"]: row["event_evidence"] for row in value["inputs"]["stories"]}, old)

    def test_weekly_narration_keeps_exact_price_basis_and_smooth_dates(self):
        value = weekend()
        script = value["voiceover"]["script"]
        self.assertIn("October thirtieth", script)
        self.assertIn("November sixth", script)
        self.assertIn("On Friday", script)
        self.assertNotIn("Original disclosures:", script)
        self.assertNotIn("Analyst interpretation:", script)
        self.assertNotIn("The disclosure was published", script)
        self.assertIn("Mark twenty-one A", normalize("Mk21A", business_names=True))

    def test_tampered_weekend_analysis_is_rejected_even_with_resealed_identity(self):
        value = weekend()
        value["inputs"]["business_analysis"]["comparison"]["text"] = "Guaranteed profitable growth."
        value["id"] = weekend_store.identity(value)
        with self.assertRaises(ValueError):
            weekend_outlook.checked(value, NOW)

    def test_invalid_business_versions_cannot_be_resealed(self):
        inputs = frozen()["weekend"]["inputs"]
        for bad in (True, "1", 2):
            changed = deepcopy(inputs)
            changed["business_version"] = bad
            with self.subTest(version=bad), self.assertRaises(ValueError):
                weekend_outlook.assemble(changed)

    def test_no_theme_stays_check(self):
        value = weekend_outlook.build(now=NOW, raw=[], market_fetch=market_fetch,
                                      calendar_snapshot=calendar(), persist=False)
        self.assertEqual(value["quality"]["status"], "CHECK")
        self.assertEqual(value["inputs"]["business_analysis"]["reviews"], [])
        with self.assertRaises(ValueError):
            weekend_outlook.episode(value, NOW)

    def test_current_builder_replaces_a_cached_rules30_presentation(self):
        old = frozen()["weekend"]
        evidence = weekend_outlook.evidence
        with patch.object(weekend_store, "latest", return_value=old), \
                patch.object(evidence, "raw_candidates", return_value=([], [])) as leads, \
                patch.object(evidence, "collect_prices", return_value=old["inputs"]["prices"]), \
                patch.object(evidence, "collect_stories", return_value=(old["inputs"]["stories"], old["inputs"]["ledger"])), \
                patch.object(evidence, "calendar_packet", return_value=old["inputs"]["calendar"]):
            value = weekend_outlook.build(now=NOW, persist=False)
        leads.assert_called_once()
        self.assertEqual(value["rules_version"], 31)


class LegacyChecks(unittest.TestCase):
    def test_archived_daily_hashes_remain_exact(self):
        value = frozen()["daily"]
        self.assertEqual(value["report_sha256"], "2b5cc4b540fc5b5216f5163e7e0ef97e65acbcb15d067a709cbe1398e0a2da47")
        self.assertEqual(daily_voiceover.checked(value, DAILY_NOW)["script_sha256"],
                         "450057ccdd4ddee42262d7febd1956273346596c06a07b58ec4819f3769c6190")

    def test_archived_weekend_hashes_and_export_remain_exact(self):
        old = frozen()
        value = old["weekend"]
        self.assertEqual(value["report_sha256"], "899cb11c9b126382afc4be48df5e7a1a780532453779e5145ce93a02e8ecd74c")
        self.assertEqual(value["voiceover"]["script_sha256"], "aa1cd2226f7212ee4ebb36ee8843e0502b5680f715fff6b8b3b7ab6ac07a4f88")
        self.assertEqual(weekend_outlook.checked(value), value)
        self.assertEqual(weekend_outlook.episode(value, NOW), old["weekend_episode"])

    def test_pronunciation_is_opt_in_for_older_narration(self):
        old = normalize("Mk21A and DEAMS")
        new = normalize("Mk21A and DEAMS", business_names=True)
        self.assertEqual(old, "Mk21A and DEAMS")
        self.assertEqual(new, "Mark twenty-one A and D E A M S")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows-socketpair", action="store_true")
    args = parser.parse_args()
    classes = (BusinessChecks, WeekendChecks, LegacyChecks)
    tests = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in classes)
    tests.addTests(DailyChecks(method) for method in (
        "test_new_daily_retains_both_stories_and_all_research_scores",
        "test_daily_copy_is_conversational_and_dates_remain",
        "test_forged_daily_business_basis_fails_voice_revalidation"))
    with ExitStack() as stack:
        if args.windows_socketpair:
            stack.enter_context(patch.object(socket, "socketpair", portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        result = unittest.TextTestRunner(verbosity=1).run(tests)
    good = result.wasSuccessful() and not traffic["blocked"]
    print(f"Business Analysis Check: {'PASS' if good else 'FAIL'} ({result.testsRun} tests)")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
