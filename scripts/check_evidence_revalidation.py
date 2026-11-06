"""Offline regressions for rebuilding and revalidating admitted source text."""

import argparse
import asyncio
from contextlib import ExitStack
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import AsyncMock,patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks,NOW
from scripts.check_news_editor import candidate
from scripts.check_disclosure_intelligence import source,AWARD
from scripts.check_special_alerts import offline_network_guard,portable_tcp_socketpair
from src.intelligence import story_analysis as analysis,news_editor as editor,news_editor_store as store,company_catalyst_context as companies
from src.reports import daily_report,daily_voiceover as voice
from src.reports.daily_news_brief import build_daily_news_brief,validate_news_brief
from src.commands import reportcheck_commands

TITLE="Kratos Reports Third Quarter 2026 Financial Results"
BODY=("Kratos reported quarterly results. The source's encoded R&amp;amp;amp;D label describes its research activities. "
      "The company discussed operating results and its business outlook in the original release.")


def kratos():
    return candidate("KTOS",title=TITLE,source="Kratos Newsroom",url="https://www.kratosdefense.com/newsroom/synthetic-results",
        source_excerpt=BODY,excerpt_scope="original release excerpt",evidence_checked_at=NOW.isoformat())


def proof(text=None):
    row=source("CACI",text=AWARD+" The source's R&amp;amp;D label is retained literally." if text is None else text)
    row["materiality"]="contract"
    row["event_evidence"]=analysis.build_evidence(row,row["source_excerpt"],"original release excerpt",schema=8)
    return row


class EvidenceChecks(unittest.TestCase):
    def test_nested_entities_no_longer_change_between_build_and_check(self):
        row=proof();before=deepcopy(row["event_evidence"])
        self.assertIn("R&amp;D",before["source_text"])
        self.assertEqual(analysis.checked_evidence(row),before)

    def test_escaped_literal_tags_are_source_text_during_validation(self):
        row=proof(AWARD+" The literal text &lt;span&gt;research&lt;/span&gt; is quoted in the source.")
        self.assertIn("<span>research</span>",row["event_evidence"]["source_text"])
        self.assertEqual(analysis.checked_evidence(row),row["event_evidence"])

    def test_raw_markup_is_still_normalized_on_initial_admission(self):
        row=proof("<p>"+AWARD+"</p><p>Research &amp; development.</p>")
        self.assertNotIn("<p>",row["event_evidence"]["source_text"])
        self.assertIn("Research & development.",row["event_evidence"]["source_text"])
        analysis.checked_evidence(row)

    def test_validation_does_not_mutate_an_existing_profile(self):
        row=proof();before=deepcopy(row)
        for _ in range(4):analysis.checked_evidence(row)
        self.assertEqual(row,before)

    def test_source_hash_is_the_hash_of_the_exact_admitted_plain_text(self):
        value=proof()["event_evidence"]
        self.assertEqual(value["source_sha256"],sha256(value["source_text"].encode()).hexdigest())

    def test_changed_fact_value_or_quoted_evidence_is_still_rejected(self):
        for field in ("value","evidence"):
            row=proof();row["event_evidence"]["facts"][0][field]="Changed without source support"
            with self.assertRaisesRegex(ValueError,"fields: facts"):analysis.checked_evidence(row)

    def test_wrong_event_and_wrong_stage_are_still_rejected(self):
        for field in ("event","stage"):
            row=proof();row["event_evidence"][field]="invented"
            with self.assertRaises(ValueError):analysis.checked_evidence(row)

    def test_source_url_publication_observation_and_hash_remain_bound(self):
        for field in ("source_url","published","observed_at","source_sha256"):
            row=proof();row["event_evidence"][field]="changed"
            with self.assertRaises(ValueError):analysis.checked_evidence(row)

    def test_changed_source_text_is_not_accepted_under_its_old_hash(self):
        row=proof();row["event_evidence"]["source_text"]+=" Extra words."
        with self.assertRaisesRegex(ValueError,"source_sha256"):analysis.checked_evidence(row)

    def test_bad_profile_shapes_and_unsupported_schemas_are_rejected(self):
        for value in ([],{"schema":True},{"schema":999},{"source_text":None}):
            row=proof();row["event_evidence"]=value
            with self.assertRaises(ValueError):analysis.checked_evidence(row)

    def test_oversized_admitted_text_is_not_silently_truncated_to_match(self):
        row=proof();row["event_evidence"]["source_text"]="x"*(analysis.MAX_EXCERPT+1)
        with self.assertRaises(ValueError):analysis.checked_evidence(row)

    def test_headline_only_profiles_keep_their_earlier_behavior(self):
        row=candidate();row["materiality"]="product";row["event_evidence"]=analysis.build_evidence(row)
        self.assertEqual(analysis.checked_evidence(row),row["event_evidence"])

    def test_original_entity_and_plain_unicode_are_not_conflated(self):
        first=proof(AWARD+" R&amp;amp;D and naïve café wording.")
        second=proof(AWARD+" R&D and naïve café wording.")
        analysis.checked_evidence(first);analysis.checked_evidence(second)
        self.assertNotEqual(first["event_evidence"]["source_sha256"],second["event_evidence"]["source_sha256"])


class RebuildChecks(IsolatedChecks):
    def render(self,rows=None):
        rows=[kratos()] if rows is None else rows
        with patch.object(editor,"cache_candidates",return_value=(rows,[])):
            report=build_daily_news_brief(self.research())
        return report,store.read_editions(report=report)[0]

    def test_encoded_original_body_survives_the_complete_news_build(self):
        report,record=self.render()
        self.assertTrue(validate_news_brief(report)["passes"])
        row=next(r for r in editor.selected_stories(record) if r["publisher_symbol"]=="KTOS")
        self.assertIn("amp;",row["event_evidence"]["source_text"])
        analysis.checked_evidence(row)

    def test_quality_card_can_build_the_real_edition_instead_of_reusing_mocked_text(self):
        research=self.research()
        with patch.object(editor,"cache_candidates",return_value=([kratos()],[])),patch.object(daily_report,"build_research_report",return_value=research):
            for _ in range(2):
                card=reportcheck_commands.build_daily_report_quality_card()
                self.assertIn("Status: PASS",card)
                self.assertNotIn("Error:",card)

    def test_the_actual_quality_command_reports_pass_after_a_rebuild(self):
        from types import SimpleNamespace
        loading=SimpleNamespace(edit_text=AsyncMock())
        update=SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock(return_value=loading)))
        with patch.object(editor,"cache_candidates",return_value=([kratos()],[])),patch.object(daily_report,"build_research_report",return_value=self.research()):
            asyncio.run(reportcheck_commands.reportcheck_command(update,SimpleNamespace()))
        self.assertIn("Status: PASS",loading.edit_text.call_args.args[0])

    def test_voiceover_rechecks_the_same_immutable_evidence(self):
        report,record=self.render();before=deepcopy(record)
        self.assertEqual(voice.checked(record,NOW)["script_sha256"],record["voiceover"]["script_sha256"])
        self.assertEqual(record,before)

    def test_later_cache_changes_do_not_rewrite_a_saved_edition(self):
        rows=[kratos()];_,record=self.render(rows)
        rows[0]["source_excerpt"]="A later unrelated cache observation."
        self.assertEqual(voice.checked(record,NOW)["script_sha256"],record["voiceover"]["script_sha256"])

    def test_priority_proof_mutations_still_stop_editorial_review(self):
        report,record=self.render()
        changed=deepcopy(record)
        row=next(row for row in changed["candidates"] if row.get("priority_evidence"))
        row["priority_evidence"]["source_sha256"]="changed"
        with self.assertRaisesRegex(ValueError,"Editorial priority evidence changed"):
            editor.review_and_record(changed,report,{},record["research_text"],analyst_review=record["analyst_review"])

    def test_priority_proof_cannot_change_to_an_older_valid_schema(self):
        report,record=self.render();changed=deepcopy(record)
        row=next(row for row in changed["candidates"] if row.get("priority_evidence"))
        value=row["priority_evidence"]
        row["priority_evidence"]=analysis.build_evidence(row,value["source_text"],value["scope"],schema=1)
        with self.assertRaisesRegex(ValueError,"Unexpected priority evidence schema"):
            editor.review_and_record(changed,report,{},record["research_text"],analyst_review=record["analyst_review"])

    def test_one_invalid_original_profile_is_held_without_blocking_other_stories(self):
        original=editor.build_evidence
        def corrupt(story,*args,**kwargs):
            value=original(story,*args,**kwargs)
            if story["publisher_symbol"]=="KTOS":value["stage"]="invented"
            return value
        with patch.object(editor,"build_evidence",side_effect=corrupt):
            report,record=self.render([kratos(),candidate("MSFT",title="Microsoft introduces an AI platform")])
        bad=next(row for row in record["candidates"] if row["publisher_symbol"]=="KTOS")
        self.assertEqual(bad["source_check"],"hold");self.assertNotIn("event_evidence",bad)
        self.assertIn("stage",bad["reason"]);self.assertTrue(validate_news_brief(report)["passes"])
        self.assertTrue(any(row["publisher_symbol"]=="MSFT" for row in editor.selected_stories(record)))

    def test_rejected_profile_is_not_silently_replaced_by_a_headline_selection(self):
        original=editor.build_evidence
        def corrupt(story,*args,**kwargs):
            value=original(story,*args,**kwargs);value["source_sha256"]="bad";return value
        with patch.object(editor,"build_evidence",side_effect=corrupt):
            plan=editor.build_editorial_plan(companies.build_company_catalyst_brief(),NOW,[kratos()])
        self.assertFalse(editor.selected_stories(plan));self.assertEqual(plan["candidates"][0]["source_check"],"hold")

    def test_saved_rules24_and25_hashes_remain_valid(self):
        expected={"market_rules24_edition.json":"4b6245c7af12651b9bbf0f2b4138b90b20c67efd3147113ac7e30788313f6d63",
                  "premarket_rules25_edition.json":"e3cec385ba544b36c69e0fed581203f471768995ebd7abbd04231077b8bcb2b1"}
        for filename,script in expected.items():
            path=ROOT/"scripts/fixtures"/filename
            row=json.loads(path.read_text());self.assertEqual(voice.checked(row,NOW)["script_sha256"],script)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--windows-socketpair",action="store_true");args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (EvidenceChecks,RebuildChecks))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    good=result.wasSuccessful() and not traffic["blocked"]
    print(f"Evidence Revalidation Check: {'PASS' if good else 'FAIL'} ({result.testsRun} tests)")
    return 0 if good else 1


if __name__=="__main__":raise SystemExit(main())
