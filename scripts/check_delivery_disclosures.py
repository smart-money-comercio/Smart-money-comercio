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
ORDER = ("ARLINGTON, Va. — (OCTOBER 25, 2026) — AeroVironment, Inc. (“AV”) (NASDAQ: AVAV), "
         "today announced a landmark $84.5 million international direct commercial sales order for its maintenance equipment.")
RECON = ("Kratos Defense & Security Solutions, Inc. (Nasdaq: KTOS) announced the release of KnownSpace® Recon+™. "
         "Recon+ is a commercially available product. Units have already been purchased by multiple U.S. government agencies.")
INFERENCE = ("Intel announced a collaboration with RadixArk to optimize SGLang, an open-source AI inference stack, for Intel platforms. "
             "The companies describe software improvements for developers deploying AI models.")
INFERENCE_TITLE = "Intel, RadixArk Collaborate to Advance Open AI Inference on Intel Platforms"


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


def order_release(**changes):
    row = candidate("AVAV", title="AV Awarded Landmark $84.5 Million International Order",
                    url="https://www.avinc.com/2026/10/25/synthetic-international-order/",
                    source="AeroVironment Newsroom", source_excerpt=ORDER, excerpt_scope="original release excerpt")
    row.update(evidence_checked_at=row["source_checked_at"])
    row.update(changes)
    return row


class FactChecks(unittest.TestCase):
    def test_intel_software_scope_requires_the_original_release(self):
        row = candidate("INTC", title=INFERENCE_TITLE)
        profile = build_evidence(row, INFERENCE, "original release excerpt", schema=16)
        self.assertEqual((profile["event"], profile["stage"]), ("technology collaboration", "announced"))
        self.assertEqual([fact["field"] for fact in profile["facts"]], ["collaboration_partner", "optimization_target"])
        with self.assertRaises(ValueError):
            build_evidence(row, INFERENCE_TITLE, "original release excerpt", schema=16)
        with self.assertRaises(ValueError):
            build_evidence(row, INFERENCE, "publisher feed excerpt", schema=16)

    def test_defense_product_sales_require_both_availability_and_actual_purchases(self):
        row = candidate("KTOS", title="Kratos Introduces KnownSpace® Recon+™")
        profile = build_evidence(row, RECON, "original release excerpt", schema=14)
        self.assertEqual(profile["stage"], "initial purchases")
        self.assertEqual([item["field"] for item in profile["facts"]], ["commercial_availability", "customer_purchases"])
        for text in (RECON.replace("have already been", "may be"), RECON.replace("is a commercially", "will be a commercially"),
                     RECON.replace("Recon+ is", "Another product is"), row["title"]):
            with self.subTest(text=text), self.assertRaises(ValueError):
                build_evidence(row, text, "original release excerpt", schema=14)

    def test_order_fields_derive_from_the_attributed_original_clause(self):
        row = order_release()
        profile = build_evidence(row, ORDER, "original release excerpt", schema=15)
        self.assertEqual((profile["event"], profile["stage"]), ("contract", "order award"))
        self.assertEqual([(fact["field"], fact["value"]) for fact in profile["facts"]],
                         [("order_value", "$84.5 million"), ("order_type", "international order")])
        self.assertTrue(all(fact["evidence"] in ORDER for fact in profile["facts"]))
        self.assertNotIn("equipment", profile["facts"][0]["evidence"])
        self.assertEqual(checked_evidence({**row, "event_evidence": profile}), profile)

    def test_order_ceiling_retains_its_up_to_qualification(self):
        from src.intelligence.order_awards import summary
        row = order_release(title="AV announces an international order")
        text = "AeroVironment received an international purchase order worth up to $84.5 million from a customer."
        profile = build_evidence(row, text, "original release excerpt", schema=15)
        self.assertEqual(profile["facts"][0]["basis"], "ceiling")
        self.assertIn("worth up to $84.5 million", summary(profile, "AeroVironment"))

    def test_order_reader_supports_an_ordinary_commercial_issuer(self):
        row = candidate("MSFT", title="Microsoft receives $18 million purchase order")
        text = "Microsoft received a purchase order valued at $18 million from a commercial customer."
        profile = build_evidence(row, text, "original release excerpt", schema=15)
        self.assertEqual([fact["value"] for fact in profile["facts"]], ["$18 million", "purchase order"])

    def test_order_rejects_headlines_unrelated_money_and_unconfirmed_awards(self):
        row = order_release()
        for body in (row["title"], ORDER.replace("$84.5 million", "$89 million"),
                     ORDER.replace("AeroVironment, Inc.", "Another Company"),
                     ORDER.replace("today announced", "today announced plans for"),
                     ORDER.replace("for its maintenance equipment", "subject to regulatory approval"),
                     ORDER.replace("today announced", "today awarded"),
                     ORDER.replace("for its maintenance equipment", "for its equipment under a $500 million agreement")):
            with self.subTest(body=body), self.assertRaises(ValueError):
                build_evidence(row, body, "original release excerpt", schema=15)
        with self.assertRaises(ValueError):
            build_evidence(row, ORDER, "publisher feed excerpt", schema=15)

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
    def test_intel_inference_and_fed_schedule_in_the_same_edition(self):
        intel = candidate("INTC", title=INFERENCE_TITLE, source="Intel Newsroom",
                          url="https://www.intel.com/content/www/us/en/newsroom/news/artificial-intelligence/radixark-open-ai-inference.html",
                          source_excerpt=INFERENCE, excerpt_scope="original release excerpt")
        fed = candidate("", title="Federal Reserve announces revised tentative schedule of Federal Open Market Committee meetings in 2027",
                        kind="macro", symbols=[], source="Federal Reserve", url="https://www.federalreserve.gov/newsevents/pressreleases/example.htm",
                        source_excerpt="The Federal Reserve announced a revised tentative schedule. This is a calendar notice for next year.",
                        excerpt_scope="original release excerpt")
        text, record = self.render([intel, fed])
        story = next(row for row in editor.selected_stories(record) if row["publisher_symbol"] == "INTC")
        self.assertEqual(story["event_evidence"]["schema"], 16)
        self.assertIn("optimize SGLang", text)
        self.assertIn("customers to report using them in production", text)
        self.assertNotIn("task orders", text)
        self.assertNotIn("committed funding", text)
        self.assertNotIn(fed["title"], text)
        calendar = next(row for row in record["candidates"] if row["url"] == fed["url"])
        self.assertEqual(calendar["decision"], "skip")
        self.assertIn("Tentative policy calendar", calendar["reason"])
        voice = daily_voiceover.checked(record, NOW)
        scene = next(scene for scene in voice["segments"] if story["id"] in scene["source_ids"])
        self.assertIn("optimize SGLang", scene["narration"])
        self.assertNotIn("award", scene["narration"])

    def test_defense_segment_explains_the_disclosed_purchases_in_text_and_speech(self):
        row = candidate("KTOS", title="Kratos Introduces KnownSpace® Recon+™", source="Kratos Newsroom",
                        url="https://www.kratosdefense.com/newsroom/fixture-initial-purchases",
                        source_excerpt=RECON, excerpt_scope="original release excerpt")
        row["evidence_checked_at"] = row["source_checked_at"]
        text, record = self.render([row])
        story = editor.selected_stories(record)[0]
        self.assertEqual(story["materiality"], "defense product sales")
        block = daily_voiceover.sections(text)["Global and Defense Watch"]
        self.assertIn("government agencies have bought units", block)
        self.assertIn("Sales volume and delivery costs", block)
        voice = daily_voiceover.checked(record, NOW)
        scene = next(scene for scene in voice["segments"] if scene["source_ids"] == [story["id"]])
        self.assertIn("Sales volume and delivery costs", scene["narration"])
        self.assertTrue(validate_news_brief(text)["passes"])

    def test_market_comparison_is_shared_by_the_brief_and_voiceover(self):
        research = self.research(replacements={
            "Executive Summary": "- Main theme: Market advance.\n- Market moves: S&P +1.31%, Nasdaq +1.60%, Russell +0.88%, VIX -10.12%, Oil +0.01%, TLT +0.05%.",
            "Market Snapshot": "Market Session: Closed.\nQuote session: 2026-10-23\nBreadth: 13 up / 5 down / 18 quoted",
        })
        with patch.object(self, "research", return_value=research):
            text, record = self.render([order_release()])
        from src.utils.speech_text import normalize
        market = daily_voiceover.sections(text)["Market Update"]
        self.assertIn("the Nasdaq Composite rose 1.60 percent, leading the three indexes we track", market)
        self.assertIn("the small-cap Russell 2000 gained 0.88 percent", market)
        self.assertIn("The VIX fell 10.12 percent", market)
        self.assertIn("Watch whether small caps can narrow the gap in the next session.", market)
        voice = daily_voiceover.checked(record, NOW)
        self.assertEqual(voice["segments"][1]["narration"], normalize(market))
        self.assertEqual(voice["segments"][1]["source_ids"], [])
        self.assertTrue(validate_news_brief(text)["passes"])

    def test_reviewed_order_leads_with_the_dated_fact_and_uses_the_value_once(self):
        order = order_release()
        reviewed = independently_reviewed(order)
        text, record = self.render([order, reviewed])
        selected = editor.selected_stories(record)
        self.assertEqual(len(selected), 1)
        story = selected[0]
        self.assertEqual((story["materiality"], story["event_evidence"]["schema"]), ("contract", 15))
        self.assertIn("verified order terms", story["reason"])
        self.assertTrue(validate_news_brief(text)["passes"])
        fact = "AeroVironment reported an international order worth $84.5 million in its October 25 announcement."
        self.assertIn("The takeaway: " + fact, text)
        self.assertEqual(record["story_narrations"][story["id"]], fact)
        self.assertEqual(text.count("$84.5 million"), 1)
        self.assertIn("Global and Defense Watch\nFor AeroVironment, execution costs and the pace of deliveries", text)
        self.assertIn("AeroVironment (AVAV) — Look for a delivery timetable", text)
        self.assertNotIn(order["title"], text)
        voice = daily_voiceover.checked(record, NOW)
        self.assertTrue(voice["quality"]["passes"])
        self.assertEqual(voice["script"].count("eighty four point five million dollars"), 1)
        lead = voice["segments"][0]
        self.assertIn("AeroVironment reported an international order", lead["narration"])
        self.assertEqual(lead["narration"].count("October twenty fifth"), 1)
        self.assertEqual(lead["source_ids"], [story["id"]])
        self.assertEqual(sum("$84.5 million" in bullet for scene in voice["segments"] for bullet in scene["bullets"]), 1)
        self.assertIn("execution costs and the pace of deliveries", voice["script"])
        self.assertIn("2 sourced fact fields", editor.build_editor_status())

    def test_non_defense_order_keeps_its_business_implications(self):
        body = "Microsoft received a purchase order valued at $18 million from a commercial customer."
        order = candidate("MSFT", title="Microsoft receives $18 million purchase order",
                          url="https://news.microsoft.com/source/2026/10/25/synthetic-order/",
                          source="Microsoft News", source_excerpt=body, excerpt_scope="original release excerpt")
        order["evidence_checked_at"] = order["source_checked_at"]
        text, record = self.render([order])
        self.assertIn("The takeaway: Microsoft reported a purchase order worth $18 million", text)
        self.assertEqual(text.count("$18 million"), 1)
        self.assertIn("Companies in Focus\nFor Microsoft, execution costs and the pace of deliveries", text)
        self.assertTrue(daily_voiceover.checked(record, NOW)["quality"]["passes"])

    def test_market_first_selloff_keeps_the_order_fact_in_its_story(self):
        research = self.research(replacements={
            "Executive Summary": "- Main theme: Growth pressure.\n- Market moves: S&P -2.79%, Nasdaq -4.30%, Russell -2.27%, VIX +49.43%.",
        })
        with patch.object(self, "research", return_value=research):
            text, record = self.render([order_release()])
        self.assertIn("The takeaway: The Nasdaq fell 4.30 percent", text)
        self.assertNotIn("$84.5 million", text.split("\nMarket Update\n", 1)[0])
        self.assertEqual(text.count("$84.5 million"), 1)
        self.assertTrue(daily_voiceover.checked(record, NOW)["quality"]["passes"])

    def test_real_daily_build_uses_source_facts_once_in_brief_and_voiceover(self):
        production = release("LMT")
        text, record = self.render([release("AMD"), independently_reviewed(production), production])
        selected = editor.selected_stories(record)
        self.assertEqual(record["rules_version"], 32)
        self.assertEqual({story["publisher_symbol"] for story in selected}, {"AMD", "LMT"})
        self.assertEqual(len(selected), 2)
        self.assertTrue(all(checked_evidence(story)["schema"] == 14 for story in selected))
        self.assertEqual(record["business_version"], 8)
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
        self.assertEqual(text.count("7 finished higher and 11 lower"), 1)
        self.assertEqual(text.count("Reported server sales and margins"), 1)
        self.assertIn("What We're Watching\nAdvanced Micro Devices (AMD) — Reported server sales and margins", text)
        self.assertIn("Watchlist breadth — Of the 18 quoted stocks and funds", text)
        self.assertNotIn("Watch cloud availability", text)
        self.assertNotIn("No fresh Starbucks announcement", text)
        self.assertTrue(validate_news_brief(text)["passes"])
        voice = daily_voiceover.checked(record, NOW)
        self.assertTrue(voice["quality"]["passes"])
        self.assertIn("Server vendors are shipping systems.", voice["script"])
        self.assertIn("G M L R S delivery number", voice["script"])
        watch = next(row for row in voice["segments"] if row["heading"] == "What We're Watching")
        self.assertTrue(watch["narration"].startswith("For Advanced Micro Devices, reported server sales and margins"))
        self.assertTrue(watch["bullets"][0].startswith("Advanced Micro Devices (AMD) —"))
        self.assertEqual(watch["source_ids"], [next(story["id"] for story in selected if story["publisher_symbol"] == "AMD")])
        from src.intelligence.market_priority import watching
        only = watching({**record["analyst_review"]["evidence"], "reader_limit": 1})
        self.assertEqual([row["symbol"] for row in only], ["AMD"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows-socketpair", action="store_true")
    args = parser.parse_args()
    tests = unittest.defaultTestLoader.loadTestsFromTestCase(FactChecks)
    tests.addTest(DailyChecks("test_intel_inference_and_fed_schedule_in_the_same_edition"))
    tests.addTest(DailyChecks("test_defense_segment_explains_the_disclosed_purchases_in_text_and_speech"))
    tests.addTest(DailyChecks("test_real_daily_build_uses_source_facts_once_in_brief_and_voiceover"))
    tests.addTest(DailyChecks("test_reviewed_order_leads_with_the_dated_fact_and_uses_the_value_once"))
    tests.addTest(DailyChecks("test_non_defense_order_keeps_its_business_implications"))
    tests.addTest(DailyChecks("test_market_first_selloff_keeps_the_order_fact_in_its_story"))
    tests.addTest(DailyChecks("test_market_comparison_is_shared_by_the_brief_and_voiceover"))
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
