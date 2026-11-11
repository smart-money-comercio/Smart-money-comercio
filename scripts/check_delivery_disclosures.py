"""Regressions for a shipping server launch and a reported production milestone."""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_disclosure_details import RebuildDetailChecks, NOW
from scripts.check_news_editor import candidate
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from scripts.check_weekend_outlook import NOW as WEEKEND_NOW
from src.intelligence import delivery_disclosures as delivery, hourly_research as desk, news_editor as editor
from src.intelligence import weekend_inputs
from src.intelligence.story_analysis import build_evidence, checked_evidence
from src.reports import daily_voiceover
from src.reports.daily_news_brief import validate_news_brief

# Synthetic generation, socket and delivery counts model the source grammar.
LAUNCH = ("AMD (NASDAQ: AMD) announced general availability of its 7th Gen AMD EPYC server SP9 processors. "
          "Systems based on the new CPUs are now shipping from server vendors. "
          "Cloud instances from Microsoft Azure and OCI will be generally available soon.")
PRODUCTION = ("Lockheed Martin reported an update on its GMLRS program. "
              "The company has delivered its 25,000th GMLRS rocket and is now producing nearly 2,500 rockets per year "
              "– a production rate achieved ahead of schedule.")


def release(symbol, **changes):
    if symbol == "AMD":
        value = candidate(symbol, title="AMD showcases 7th Gen AMD EPYC processors for AI and enterprise computing",
                          url="https://ir.amd.com/news-events/press-releases/detail/9999/synthetic-server-launch",
                          source="AMD Investor Relations", source_excerpt=LAUNCH)
    else:
        value = candidate(symbol, title="Lockheed Martin reaches GMLRS production milestone",
                          url="https://news.lockheedmartin.com/2026-10-25-synthetic-production-milestone",
                          source="Lockheed Martin Newsroom", source_excerpt=PRODUCTION)
    value.update(excerpt_scope="original release excerpt", evidence_checked_at=value["source_checked_at"])
    value.update(changes)
    return value


def independently_reviewed(row):
    value = deepcopy(row)
    publisher = desk.identity(value["url"])
    text = value["source_excerpt"]
    value.update(source=publisher["name"], origin="Hourly AI research review", discovery_evidence={
        "schema": 1, "publisher": publisher, "url": value["url"], "title": value["title"],
        "published": value["published"], "observed": value["source_checked_at"], "text": text,
        "sha256": sha256(text.encode()).hexdigest(), "scope": value["excerpt_scope"]}, research_review={
        "response_id": "offline-review", "score": 90, "quote": text.split(". ", 1)[-1],
        "reason": "Compare this milestone with a possible 90,000 future deliveries."})
    desk.check_proof(value, NOW)
    return value


class FactChecks(unittest.TestCase):
    def test_launch_distinguishes_available_hardware_shipping_and_future_cloud(self):
        row = release("AMD")
        profile = build_evidence(row, LAUNCH, "original release excerpt", schema=14)
        self.assertEqual((profile["event"], profile["stage"]), ("product", "available"))
        fields = {field["field"]: field for field in profile["facts"]}
        self.assertEqual(fields["product_availability"]["value"], "7th-generation EPYC SP9 server processors")
        self.assertEqual(fields["system_shipments"]["status"], "shipping")
        self.assertEqual(fields["cloud_rollout"]["status"], "expected")
        self.assertIn("expects Microsoft Azure and Oracle Cloud", delivery.summary(profile))
        for field in fields.values():
            self.assertIn(field["evidence"], profile["source_text"])

    def test_future_negated_and_different_generation_shipments_do_not_change_stage(self):
        for body in (LAUNCH.replace("are now shipping", "are expected to ship"),
                     LAUNCH.replace("are now shipping", "are not shipping"),
                     LAUNCH.replace("the new CPUs", "6th Gen AMD EPYC CPUs"),
                     LAUNCH.replace("AMD (NASDAQ: AMD) announced", "It is not true that AMD announced")):
            with self.subTest(body=body):
                self.assertIsNone(delivery.extract(release("AMD"), body))

    def test_production_preserves_actual_counts_units_and_qualifiers(self):
        profile = build_evidence(release("LMT"), PRODUCTION, "original release excerpt", schema=14)
        fields = {row["field"]: row for row in profile["facts"]}
        self.assertEqual(profile["stage"], "production")
        self.assertEqual(fields["delivery_milestone"]["value"], "25,000")
        self.assertEqual(fields["annual_production_rate"]["value"], "nearly 2,500")
        self.assertEqual(fields["annual_production_rate"]["unit"], "units per year")
        self.assertEqual(fields["production_schedule"]["value"], "ahead of schedule")

    def test_forecast_other_product_or_conflicting_production_is_withheld(self):
        for body in (PRODUCTION.replace("is now producing", "plans to produce"),
                     PRODUCTION.replace("GMLRS rocket and", "unrelated product and"),
                     PRODUCTION + "\n" + PRODUCTION.replace("2,500", "9,000")):
            with self.subTest(body=body):
                self.assertIsNone(delivery.extract(release("LMT"), body))

    def test_feed_excerpt_cannot_establish_the_original_body_profile(self):
        with self.assertRaises(ValueError):
            build_evidence(release("AMD"), LAUNCH, "publisher feed excerpt", schema=14)

    def test_fact_and_stage_changes_fail_revalidation(self):
        story = release("LMT")
        story["event_evidence"] = build_evidence(story, PRODUCTION, "original release excerpt", schema=14)
        for field in ("facts", "stage"):
            changed = deepcopy(story)
            changed["event_evidence"][field] = [] if field == "facts" else "reveal"
            with self.subTest(field=field), self.assertRaises(ValueError):
                checked_evidence(changed)

    def test_archived_product_reveal_keeps_its_original_profile(self):
        story = release("AMD", materiality="product")
        profile = build_evidence(story, LAUNCH, "original release excerpt", schema=8)
        self.assertEqual(profile["stage"], "reveal")
        self.assertEqual(profile["facts"], [])
        self.assertEqual(checked_evidence({**story, "event_evidence": profile}), profile)

    def test_weekend_admission_reuses_and_rechecks_original_delivery_facts(self):
        row = release("LMT", published=(WEEKEND_NOW - timedelta(days=2)).isoformat(),
                      source_checked_at=WEEKEND_NOW.isoformat(), evidence_checked_at=WEEKEND_NOW.isoformat())
        periods = weekend_inputs.window(WEEKEND_NOW)
        story = weekend_inputs.admit_story(row, PRODUCTION, WEEKEND_NOW.isoformat(), periods, WEEKEND_NOW)
        self.assertEqual(story["event_evidence"]["schema"], 14)
        self.assertEqual(weekend_inputs.checked_story(story, periods, WEEKEND_NOW), story)


class DailyChecks(RebuildDetailChecks):
    def test_real_daily_build_uses_source_facts_once_in_brief_and_voiceover(self):
        production = release("LMT")
        text, record = self.render([release("AMD"), independently_reviewed(production), production])
        selected = editor.selected_stories(record)
        self.assertEqual(record["rules_version"], 32)
        self.assertEqual({story["publisher_symbol"] for story in selected}, {"AMD", "LMT"})
        self.assertEqual(len(selected), 2)
        self.assertTrue(all(checked_evidence(story)["schema"] == 14 for story in selected))
        self.assertEqual(len(record["analyst_review"]["evidence"]["business_reviews"]), 2)
        copies = [story for story in record["candidates"] if story["url"] == production["url"]]
        self.assertEqual(len(copies), 2)
        self.assertTrue(all(len(checked_evidence(story)["facts"]) == 3 for story in copies))
        self.assertTrue(any("Duplicate article URL" in story["reason"] for story in copies))
        self.assertEqual(text.count("delivery number 25,000"), 1)
        self.assertIn("nearly 2,500 units per year", text)
        self.assertIn("Server vendors are shipping systems.", text)
        self.assertNotIn("90,000", text)
        self.assertNotIn(production["title"], text)
        self.assertTrue(validate_news_brief(text)["passes"])
        voice = daily_voiceover.checked(record, NOW)
        self.assertTrue(voice["quality"]["passes"])
        self.assertIn("Server vendors are shipping systems.", voice["script"])
        self.assertIn("G M L R S delivery number", voice["script"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows-socketpair", action="store_true")
    args = parser.parse_args()
    tests = unittest.defaultTestLoader.loadTestsFromTestCase(FactChecks)
    tests.addTest(DailyChecks("test_real_daily_build_uses_source_facts_once_in_brief_and_voiceover"))
    with ExitStack() as stack:
        if args.windows_socketpair:
            stack.enter_context(patch.object(socket, "socketpair", portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        result = unittest.TextTestRunner(verbosity=1).run(tests)
    good = result.wasSuccessful() and not traffic["blocked"]
    print(f"Delivery Disclosure Check: {'PASS' if good else 'FAIL'} ({result.testsRun} tests)")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
