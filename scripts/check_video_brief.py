"""Offline editorial and native scene contracts for the branded video workflow."""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks,NOW
from scripts.check_news_editor import candidate
from scripts.check_semiconductor_news import PresentationChecks
from scripts.check_special_alerts import offline_network_guard,portable_tcp_socketpair
from src.intelligence import news_editor as editor,energy_analysis as energy
from src.intelligence.story_analysis import build_evidence,checked_evidence,investor_read
from src.reports import daily_voiceover as voice

SOLAR_TITLE="The share of solar generation with co-located battery storage is increasing"
SOLAR_TEXT=("As of September 2026, over 16% of new utility-scale solar capacity added this year is co-located with operable battery storage, "
            "compared with 2% in 2017, according to data reported to EIA by operators.")


def agency(source="EIA",title=SOLAR_TITLE,**changes):
    domain="eia.gov" if source=="EIA" else "home.treasury.gov"
    row=candidate(kind="macro",symbols=[],source=source,publisher_symbol="",url="https://"+domain+"/fixture-release",title=title,
                  source_excerpt=SOLAR_TEXT,excerpt_scope="publisher feed excerpt")
    row.update(changes);return row


class VideoBriefChecks(IsolatedChecks):
    research_moves=PresentationChecks.research_moves
    render=PresentationChecks.render

    def plan(self,values):
        from src.intelligence.company_catalyst_context import build_company_catalyst_brief
        return editor.build_editorial_plan(build_company_catalyst_brief(now=NOW),NOW,values)

    def test_new_profiles_use_schema_two(self):
        _,record=self.render()
        self.assertEqual(record["voiceover"]["schema"],2)
        self.assertTrue(voice.checked(record,NOW)["quality"]["passes"])

    def test_opening_card_contains_the_actual_editorial_takeaway(self):
        _,record=self.render();scene=record["voiceover"]["segments"][0]
        self.assertIn("Intel",scene["bullets"][0])
        self.assertNotIn("Source-backed market research",scene["bullets"])
        self.assertFalse(any(line.startswith("Edition:") for line in scene["bullets"]))

    def test_company_card_shows_every_checked_peer_and_signed_return(self):
        _,record=self.render();scene=next(row for row in record["voiceover"]["segments"] if row["heading"]=="Companies in Focus")
        self.assertEqual(len(scene["bullets"]),3)
        for symbol,value in (("INTC","-28.6%"),("ASML","-5.7%"),("AMD","-9.8%")):
            self.assertTrue(any(symbol in line and value in line for line in scene["bullets"]))
        self.assertIn("shared cause",scene["narration"])
        self.assertNotIn("same provider",scene["narration"])

    def test_pending_quotes_never_become_numeric_visual_bullets(self):
        _,record=self.render(research=self.research_moves(pending=True))
        bullets=" ".join(line for row in record["voiceover"]["segments"] for line in row["bullets"])
        self.assertNotIn("-28.6%",bullets)

    def test_watch_card_contains_a_concrete_observation(self):
        _,record=self.render();scene=next(row for row in record["voiceover"]["segments"] if row["heading"]=="What We're Watching")
        self.assertTrue(any("track" in line or "guidance" in line or "higher" in line for line in scene["bullets"]))
        self.assertNotEqual(scene["bullets"],["Market recovery","Intel's business outlook"])

    def test_agenda_copy_retains_event_date_time_and_timezone(self):
        text="Nvidia has scheduled its earnings conference call for Tuesday, November 17 at 05:00 PM EST, according to its company announcement."
        self.assertEqual(voice.agenda_bullet(text),"Nvidia: earnings call — Tue, Nov 17 at 5:00 PM EST")
        cached=voice.agenda_bullet("A previously checked, cached schedule lists weekly jobless claims for Thursday, November 05 at 08:30 AM EST.")
        self.assertTrue(cached.startswith("Cached schedule:"));self.assertIn("Nov 5 at 8:30 AM EST",cached)

    def test_legacy_voice_profile_replays_its_original_visuals_and_script(self):
        report,record=self.render();legacy=deepcopy(record)
        legacy["voiceover"]=voice.build(legacy,report,legacy["research_text"],schema=1)
        checked=voice.checked(legacy,NOW)
        self.assertEqual(checked,legacy["voiceover"])
        self.assertIn("Source-backed market research",checked["segments"][0]["bullets"])
        self.assertIn("Repeat quotes from the same provider",checked["script"])

    def test_new_editions_do_not_rewrite_an_older_stored_review_or_voice_profile(self):
        from src.intelligence import news_editor_store as store
        report,record=self.render();legacy=deepcopy(record);legacy.pop("id")
        legacy["rules_version"]=14
        legacy["voiceover"]=voice.build(legacy,report,legacy["research_text"],schema=1)
        old_id=store.save_edition(legacy,report)
        original=next(row for row in store.read_editions(200) if row["id"]==old_id)
        self.render([agency()])
        retained=next(row for row in store.read_editions(200) if row["id"]==old_id)
        self.assertEqual(retained,original)
        self.assertEqual(voice.checked(retained,NOW),original["voiceover"])

    def test_invalid_profile_schema_and_modified_visuals_are_rejected(self):
        _,record=self.render()
        for value in (0,3,True):
            changed=deepcopy(record);changed["voiceover"]["schema"]=value
            with self.assertRaises(ValueError):voice.checked(changed,NOW)
        changed=deepcopy(record);changed["voiceover"]["segments"][0]["bullets"]=["Guaranteed returns"]
        with self.assertRaises(ValueError):voice.checked(changed,NOW)

    def test_treasury_identity_without_a_market_development_is_skipped(self):
        story=agency("U.S. Treasury","Remarks by Secretary of the Treasury Scott Bessent on New Fraud Prevention Measures in Minnesota")
        plan=self.plan([story]);row=plan["candidates"][0]
        self.assertEqual(row["decision"],"skip");self.assertIn("Agency identity alone",row["reason"])

    def test_specific_treasury_market_actions_remain_eligible(self):
        for title in ("Treasury announces bond auction terms","Treasury sanctions facilitators of DPRK IT worker fraud","Treasury announces debt buybacks","Treasury announces export restrictions on AI chips"):
            with self.subTest(title=title):
                plan=self.plan([agency("U.S. Treasury",title)])
                self.assertEqual(plan["candidates"][0]["decision"],"selected")

    def test_solar_story_has_traceable_capacity_facts_and_an_investor_question(self):
        plan=self.plan([agency()]);row=editor.selected_stories(plan)[0]
        evidence=checked_evidence(row)
        self.assertEqual(evidence["schema"],6)
        self.assertEqual(evidence["event"],"solar storage")
        self.assertEqual(len(evidence["facts"]),3)
        review=investor_read(row)
        for phrase in ("September 2026","over 16%","new utility-scale solar capacity","2% in 2017"):
            self.assertIn(phrase,review["facts"])
        self.assertIn("question",review["why"])
        self.assertNotIn("will improve",review["why"])

    def test_title_only_solar_story_is_held(self):
        for changes in ({"source_excerpt":"","excerpt_scope":"headline only"},{"source_excerpt":"Solar capacity and battery storage are discussed without a reported share."}):
            with self.subTest(changes=changes):
                row=self.plan([agency(**changes)])["candidates"][0]
                self.assertEqual(row["decision"],"wait");self.assertIn("capacity facts",row["reason"])

    def test_forecasts_and_impossible_shares_are_not_reported_capacity(self):
        for text in (SOLAR_TEXT.replace("over 16%","over 160%"),SOLAR_TEXT.replace("is co-located","could be co-located"),"Hypothetical. "+SOLAR_TEXT.replace("As of","As forecast, as of"),SOLAR_TEXT.replace("September 2026","September 2016")):
            self.assertFalse(energy.storage_facts(text),text)

    def test_other_capacity_denominators_do_not_turn_into_new_solar_share(self):
        for text in (SOLAR_TEXT.replace("new utility-scale solar capacity","all U.S. generating capacity"),SOLAR_TEXT.replace("added this year","planned for 2028")):
            self.assertFalse(energy.storage_facts(text))

    def test_solar_fact_tampering_and_publisher_swap_are_rejected(self):
        row=editor.selected_stories(self.plan([agency()]))[0]
        changed=deepcopy(row);changed["event_evidence"]["facts"][0]["value"]="September 2030"
        with self.assertRaises(ValueError):checked_evidence(changed)
        changed=deepcopy(row);changed["source"]="U.S. Treasury"
        with self.assertRaises(ValueError):checked_evidence(changed)

    def test_original_clocks_and_freshness_still_apply_to_solar_reports(self):
        for changes in ({"published":(NOW-timedelta(hours=25)).isoformat()}, {"source_checked_at":(NOW-timedelta(hours=7)).isoformat()}):
            self.assertEqual(self.plan([agency(**changes)])["candidates"][0]["decision"],"wait")

    def test_energy_scene_explains_the_fact_instead_of_reading_a_headline(self):
        report,record=self.render([agency()]);profile=voice.checked(record,NOW)
        scene=next(row for row in profile["segments"] if row["heading"]=="Energy and Infrastructure")
        self.assertIn("over sixteen percent",scene["narration"])
        self.assertIn("project economics",scene["narration"])
        self.assertNotIn("Review the original release",scene["narration"])
        self.assertNotIn("On policy",scene["narration"])
        self.assertIn("over 16%",report)

    def test_unexplained_macro_headlines_do_not_leak_into_new_voice_scenes(self):
        _,record=self.render([agency("U.S. Treasury","Treasury announces bond auction terms")])
        self.assertNotIn("Treasury announces bond auction terms",record["voiceover"]["script"])
        self.assertFalse(record["voiceover"]["sources"])
        report=record["report_text"];old=voice.build(record,report,record["research_text"],schema=1)
        self.assertIn("Treasury announces bond auction terms",old["script"])

    def test_a_macro_source_used_by_the_market_lens_keeps_its_reference(self):
        _,record=self.render([agency("U.S. Treasury","Treasury announces export restrictions on AI chips")])
        profile=record["voiceover"]
        market=next(row for row in profile["segments"] if row["heading"]=="Market Update")
        self.assertIn("chip-market access",market["narration"])
        self.assertTrue(market["source_ids"])
        self.assertTrue(set(market["source_ids"])<=set(profile["sources"]))

    def test_render_and_export_do_not_change_scores_or_delivery_receipts(self):
        ranking=self.ranking.read_bytes();_,record=self.render([agency()])
        before={path:path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        data=voice.episode(record,NOW)
        self.assertEqual(data["mode"],"draft_review_required");self.assertTrue(data["review_required"])
        self.assertEqual(self.ranking.read_bytes(),ranking)
        self.assertEqual(before,{path:path.read_bytes() for path in self.root.rglob('*') if path.is_file()})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--windows-socketpair',action='store_true');args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,'socketpair',portable_tcp_socketpair))
        network=stack.enter_context(offline_network_guard())
        result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(VideoBriefChecks))
    passed=result.wasSuccessful() and not network['blocked']
    print(f"Video Brief Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
