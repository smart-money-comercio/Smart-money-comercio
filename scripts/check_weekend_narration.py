"""Offline narration revisions, native pairing, renderer routing and no-paid-call checks."""

import argparse
from contextlib import ExitStack,redirect_stdout
from copy import deepcopy
from hashlib import sha256
import json
from io import StringIO
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import ModuleType,SimpleNamespace
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_weekend_outlook import edition,calendar,NOW,story
from scripts.check_special_alerts import offline_network_guard,portable_tcp_socketpair
from scripts import check_weekend_media as cli,prepare_weekend_renderer as adapter
from src.reports import weekend_outlook as report,weekend_narration as narration,weekend_media_contract as contract
from src.intelligence import weekend_store as store,weekend_inputs as inputs


class PrivateState(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ,{"WEEKEND_STATE_FILE":str(self.root/'weekend.sqlite3')}))

    def native(self):
        value=edition();store.save(value)
        return value,report.episode(value,NOW)

    def legacy(self):
        return json.loads((ROOT/'scripts/fixtures/weekend_narration_v1_edition.json').read_text())


class NarrationChecks(PrivateState):
    def test_legacy_record_and_exact_export_keep_their_original_hashes(self):
        frozen=self.legacy();value=frozen["record"]
        self.assertEqual(value["report_sha256"],"21e1d05c31d7bb428b50fe8bdc6ea5aa76ef1312501647bdcb6b612faa5e4c3e")
        self.assertEqual(value["voiceover"]["script_sha256"],"056885486bc20162f1b8a2ea6fe50524c58455d7760882789e4b3ff6b770cee6")
        self.assertEqual(report.checked(value),value);self.assertEqual(report.episode(value,NOW),frozen["episode"])

    def test_new_build_records_revision_two_in_inputs_voice_and_export(self):
        value,packet=self.native()
        self.assertEqual(value["inputs"]["narration_revision"],2);self.assertEqual(value["voiceover"]["narration_revision"],2)
        self.assertEqual(packet["weekend_narration_revision"],2)

    def test_every_spoken_word_is_inside_the_scene_list(self):
        value,packet=self.native()
        self.assertEqual("\n\n".join(s["narration"] for s in packet["segments"]),value["voiceover"]["script"])
        self.assertTrue(packet["segments"][0]["narration"].startswith("Smart Money Weekend Outlook."))

    def test_grammar_cleanup_applies_to_report_and_new_narration(self):
        value,_=self.native()
        self.assertNotIn("This week disclosure",value["report_text"]);self.assertNotIn("This week disclosure",value["voiceover"]["script"])
        self.assertIn("The disclosure was published",value["report_text"])

    def test_pronunciation_is_explicit_for_program_and_accounting_terms(self):
        text=narration.spoken("Mk21A supports the Defense Enterprise Accounting and Management System (DEAMS). DEAMS reporting.")
        self.assertIn("Mark twenty-one A",text);self.assertNotIn("(DEAMS)",text);self.assertIn("D E A M S reporting",text)

    def test_department_of_labor_is_expanded_without_duplicate_article(self):
        self.assertEqual(narration.spoken("According to DOL."),"According to the U S Department of Labor.")
        self.assertEqual(narration.spoken("The DOL confirmed the time."),"The U S Department of Labor confirmed the time.")

    def test_written_calendar_keeps_five_days_while_speech_summarizes_gaps_once(self):
        value,packet=self.native();spoken=next(s["narration"] for s in packet["segments"] if s["heading"].startswith("Coming week"))
        self.assertEqual(value["report_text"].count("No publisher-verified entry"),4)
        self.assertNotIn("No publisher-verified entry",spoken);self.assertEqual(spoken.count("calendar is incomplete"),1)
        self.assertIn("Thursday, November twelfth",spoken);self.assertIn("eight thirty in the morning",spoken)

    def test_empty_calendar_still_describes_missing_evidence(self):
        packet={"macro":[],"company":[]}
        text=narration.calendar(packet,inputs.window(NOW))
        self.assertIn("no publisher-verified",text);self.assertIn("Coverage is incomplete",text)

    def test_later_issuer_event_stays_outside_the_spoken_coming_week(self):
        _,packet=self.native();coming=next(s["narration"] for s in packet["segments"] if s["heading"].startswith("Coming week"))
        later=next(s["narration"] for s in packet["segments"] if s["heading"]=="Beyond the coming week")
        self.assertNotIn("seventeenth",coming);self.assertIn("seventeenth",later)

    def test_old_cache_does_not_prevent_a_new_revision_build(self):
        old=self.legacy()["record"];store.save(old)
        with patch.object(inputs,"raw_candidates",return_value=([story()],[])) as leads,patch.object(inputs.feeds,"fetch_url") as fetch,patch.object(inputs.calendar_context,"read_snapshot",return_value=calendar()):
            from scripts.check_weekend_outlook import market_fetch
            fetch.side_effect=market_fetch
            new=report.build(NOW,persist=False)
        self.assertEqual(leads.call_count,1);self.assertEqual(new["inputs"]["narration_revision"],2)

    def test_unknown_or_boolean_revision_cannot_be_resealed(self):
        value=edition()
        for revision in (True,3,"2"):
            changed=deepcopy(value["inputs"]);changed["narration_revision"]=revision
            with self.assertRaises(ValueError):report.assemble(changed)


class ContractChecks(PrivateState):
    def test_new_packet_and_txt_pair_validate(self):
        value,packet=self.native();summary=contract.validate_packet(packet,value["voiceover"]["script"]+"\n")
        self.assertTrue(summary["all_spoken_text_in_scenes"]);self.assertEqual(summary["narration_revision"],2)

    def test_legacy_pair_remains_inspectable_but_reports_external_title_prefix(self):
        frozen=self.legacy();summary=contract.validate_packet(frozen["episode"],frozen["record"]["voiceover"]["script"])
        self.assertFalse(summary["all_spoken_text_in_scenes"])

    def test_changed_txt_or_scene_narration_is_rejected(self):
        value,packet=self.native()
        with self.assertRaises(ValueError):contract.validate_packet(packet,value["voiceover"]["script"]+" Extra words.")
        packet["segments"][0]["narration"]+=" Extra words."
        with self.assertRaises(ValueError):contract.validate_packet(packet)

    def test_title_cannot_disappear_without_changing_the_approved_checksum(self):
        _,packet=self.native();packet["segments"][0]["narration"]=packet["segments"][0]["narration"].removeprefix("Smart Money Weekend Outlook.\n\n")
        with self.assertRaises(ValueError):contract.validate_packet(packet)

    def test_unknown_source_reference_is_rejected(self):
        _,packet=self.native();packet["segments"][0]["source_ids"].append("unknown")
        with self.assertRaises(ValueError):contract.validate_packet(packet)

    def test_article_bodies_are_not_media_fields(self):
        _,packet=self.native();packet["sources"]["extra"]=[{"source_text":"Original body"}]
        with self.assertRaises(ValueError):contract.validate_packet(packet)

    def test_review_or_synthetic_media_flags_cannot_be_removed(self):
        _,packet=self.native()
        for field,value in (("review_required",False),("contains_synthetic_media",False),("mode","approved_for_render")):
            changed={**packet,field:value}
            with self.assertRaises(ValueError):contract.validate_packet(changed)

    def test_weekly_and_later_horizons_are_checked(self):
        _,packet=self.native();packet["next_week_end"]="2026-11-17"
        with self.assertRaises(ValueError):contract.validate_packet(packet)

    def test_market_metadata_must_use_the_same_two_fridays(self):
        _,packet=self.native();next(v for k,v in packet["sources"].items() if k.startswith("market_"))[0]["baseline_date"]="2026-11-02"
        with self.assertRaises(ValueError):contract.validate_packet(packet)

    def test_metrics_are_recomputed_from_the_actual_script(self):
        _,packet=self.native();packet["voiceover_quality"]["words"]+=1
        with self.assertRaises(ValueError):contract.validate_packet(packet)

    def test_source_observations_are_checked_at_generation(self):
        _,packet=self.native();next(iter(packet["sources"].values()))[0]["verified_at"]="2026-11-07T00:00:00+00:00"
        with self.assertRaises(ValueError):contract.validate_packet(packet)

    def test_native_preflight_matches_the_exact_record_without_network(self):
        value,packet=self.native();summary=cli.preflight(packet,value["voiceover"]["script"],NOW)
        self.assertEqual(summary["native_record"],"PASS");self.assertFalse(summary["paid_production_ready"])

    def test_forged_but_self_consistent_packet_still_fails_native_record_binding(self):
        value,packet=self.native();packet["description"]="Different approved description"
        contract.validate_packet(packet,value["voiceover"]["script"])
        with self.assertRaises(ValueError):cli.preflight(packet,value["voiceover"]["script"],NOW)

    def test_stale_native_record_cannot_be_approved_for_current_media(self):
        value,packet=self.native()
        from datetime import timedelta
        with self.assertRaises(ValueError):cli.preflight(packet,value["voiceover"]["script"],NOW+timedelta(hours=7))

    def test_legacy_native_record_requests_reexport_for_new_media(self):
        old=self.legacy();store.save(old["record"])
        with self.assertRaisesRegex(ValueError,"revision 2"):cli.preflight(old["episode"],old["record"]["voiceover"]["script"],NOW)

    def test_missing_record_does_not_create_a_database(self):
        value=edition();packet=report.episode(value,NOW)
        with self.assertRaises(ValueError):cli.preflight(packet,value["voiceover"]["script"],NOW)
        self.assertFalse(store.state_path().exists())

    def test_specific_edition_read_does_not_substitute_the_latest(self):
        first,packet=self.native()
        from datetime import timedelta
        second=edition(now=NOW+timedelta(minutes=1));store.save(second)
        self.assertEqual(store.latest()["id"],second["id"])
        self.assertEqual(store.read_record(first["id"]),first);self.assertIsNone(store.read_record("f"*20))
        self.assertIsNone(store.read_record("not-an-edition"))

    def test_cli_creates_a_new_preflight_only_and_preserves_existing_output(self):
        value,packet=self.native();ep=self.root/'episode.json';txt=self.root/'script.txt';out=self.root/'preflight.json'
        ep.write_text(json.dumps(packet));txt.write_text(value["voiceover"]["script"]+"\n")
        with patch.object(cli,"datetime") as now:
            now.now.return_value=NOW
            self.assertEqual(cli.main(["--episode",str(ep),"--script",str(txt),"--output",str(out)]),0)
            before=out.read_bytes();self.assertEqual(cli.main(["--episode",str(ep),"--script",str(txt),"--output",str(out)]),1)
        self.assertEqual(out.read_bytes(),before);self.assertFalse(json.loads(out.read_text())["paid_production_ready"])


class RendererChecks(PrivateState):
    def reference(self):
        return (ROOT/'scripts/fixtures/weekend_v2_renderer_reference.txt').read_text(encoding="utf-8")

    def test_reviewed_source_and_generated_variant_fingerprints_match(self):
        text=self.reference();self.assertEqual(sha256(text.encode()).hexdigest(),contract.REFERENCE_RENDERER_SHA256)
        changed=contract.adapted_renderer(text);self.assertEqual(sha256(changed.encode()).hexdigest(),contract.WEEKEND_RENDERER_SHA256)

    def test_customized_renderer_is_not_silently_patched(self):
        with self.assertRaises(ValueError):contract.adapted_renderer(self.reference()+"\n# Local customization\n")

    def test_renderer_inspection_is_static_and_keeps_production_on_hold(self):
        path = self.root / "render.py"
        source = self.reference()
        cases = (
            (source, "WEEKEND_BANNER_ADAPTER_REQUIRED"),
            (contract.adapted_renderer(source), "PREVIEW_COMPATIBLE"),
            (source + "\n# Local customization\n", "CUSTOM_RENDERER_REVIEW_REQUIRED"),
        )
        formats = (("utf-8", "\n"), ("utf-8", "\r\n"), ("utf-8-sig", "\r\n"))
        for text, expected in cases:
            for encoding, newline in formats:
                with self.subTest(expected=expected, encoding=encoding, newline=newline):
                    path.write_text(text, encoding=encoding, newline=newline)
                    result = contract.inspect_renderer(path)
                    self.assertEqual(result["status"], expected)
                    self.assertEqual(result["renderer_sha256"], sha256(path.read_bytes()).hexdigest())
                    self.assertFalse(result["paid_production_ready"])

    def test_preparer_creates_a_sibling_preserves_original_and_is_idempotent(self):
        path = self.root / "render_episode.py"
        path.write_text(self.reference(), encoding="utf-8", newline="\r\n")
        before = path.read_bytes()
        self.assertEqual(adapter.main(["--renderer",str(path)]),0);self.assertEqual(path.read_bytes(),before)
        self.assertEqual(adapter.main(["--renderer",str(path)]),0)
        path.with_name('weekend_render_episode.py').write_text("# Local work\n")
        self.assertEqual(adapter.main(["--renderer",str(path)]),1)

    def load_renderer(self):
        requests=ModuleType("requests");requests.post=Mock(side_effect=AssertionError("No paid speech or HTTP permitted"))
        dotenv=ModuleType("dotenv");dotenv.load_dotenv=lambda:None
        pil=ModuleType("PIL")
        class Still:
            def resize(self,*args,**kwargs):return self
            def save(self,path,**kwargs):Path(path).write_bytes(b"synthetic still")
        pil.Image=SimpleNamespace(open=lambda _:Still())
        for name in ("ImageDraw","ImageFont","ImageFilter","ImageOps"):setattr(pil,name,SimpleNamespace())
        namespace={"__name__":"offline_weekend_renderer","__file__":str(self.root/'weekend_render_episode.py')}
        with patch.dict(sys.modules,{"requests":requests,"dotenv":dotenv,"PIL":pil}):
            exec(compile(contract.adapted_renderer(self.reference()),namespace["__file__"],"exec"),namespace)
        namespace.update(compose_slide=Mock(),brand_frame=Mock(),speech=Mock(),silence=Mock(),make_clip=Mock(),duration=Mock(return_value=1.0))
        namespace["shutil"]=SimpleNamespace(which=lambda _:"offline",copy2=lambda a,b:Path(b).write_bytes(Path(a).read_bytes()))
        namespace["subprocess"]=SimpleNamespace(run=Mock(side_effect=AssertionError("FFmpeg is disabled")))
        namespace["run"]=lambda argv:Path(argv[-1]).write_bytes(b"synthetic video stub")
        return namespace,requests

    def test_actual_renderer_orchestration_receives_every_spoken_word_without_paid_calls(self):
        value,packet=self.native();path=self.root/'episode.json';path.write_text(json.dumps(packet));out=self.root/'preview'
        namespace,requests=self.load_renderer()
        with patch.dict(os.environ,{"BACKGROUND_MUSIC_PATH":""}),redirect_stdout(StringIO()):namespace["main"](SimpleNamespace(episode=path,out=out,demo=False))
        spoken="\n\n".join(call.args[0] for call in namespace["speech"].call_args_list)
        self.assertEqual(spoken,value["voiceover"]["script"]);self.assertEqual(namespace["compose_slide"].call_count,len(packet["segments"]))
        self.assertTrue(all(call.kwargs["edition_label"]=="WEEKEND OUTLOOK" for call in namespace["compose_slide"].call_args_list))
        metadata=json.loads((out/'metadata.json').read_text());self.assertIn("weekend outlook",metadata["tags"])
        self.assertEqual(metadata["bot_edition_id"],packet["bot_edition_id"]);self.assertEqual(metadata["voiceover_sha256"],packet["voiceover_sha256"])
        self.assertTrue((out/'Smart_Money_Project_Weekend_Outlook.mp4').exists());requests.post.assert_not_called();namespace["subprocess"].run.assert_not_called()

    def test_variant_retains_daily_defaults_when_explicitly_given_daily_data(self):
        _,packet=self.native();packet.pop("edition_type");path=self.root/'daily.json';path.write_text(json.dumps(packet));out=self.root/'daily'
        namespace,requests=self.load_renderer()
        with patch.dict(os.environ,{"BACKGROUND_MUSIC_PATH":""}),redirect_stdout(StringIO()):namespace["main"](SimpleNamespace(episode=path,out=out,demo=False))
        self.assertTrue(all(call.kwargs["edition_label"]=="DAILY MARKET BRIEF" for call in namespace["compose_slide"].call_args_list))
        self.assertTrue((out/'Smart_Money_Project_Daily_Brief.mp4').exists());requests.post.assert_not_called()


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--windows-socketpair",action="store_true");args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case) for case in (NarrationChecks,ContractChecks,RendererChecks))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    good=result.wasSuccessful() and not traffic["blocked"]
    print(f"Weekend Narration Check: {'PASS' if good else 'FAIL'} ({result.testsRun} tests)")
    return 0 if good else 1


if __name__=="__main__":raise SystemExit(main())
