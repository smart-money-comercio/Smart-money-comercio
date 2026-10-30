"""Offline behavior checks for source-bound narration and the renderer handoff."""

import argparse
import asyncio
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import timedelta
from io import StringIO
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_event_news import quote
from scripts.check_news_editor import candidate
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.intelligence import news_editor as editor, news_editor_store as store, market_event_desk as events
from src.reports import daily_news_brief as news, daily_voiceover as voice
from src.utils.speech_text import normalize, words
from scripts import export_daily_voiceover as export
from src.commands import voiceover_commands as commands


class SpeechChecks(unittest.TestCase):
    def test_money_percent_dates_and_acronyms_have_unambiguous_spoken_forms(self):
        text = normalize("CACI: up to $185 million; AI IPO. S&P 500 -0.30%; EPS $2.12. November 05 at 08:30 AM EST.")
        for phrase in ("C A C I", "one hundred eighty five million dollars", "A I initial public offering",
                       "S and P five hundred minus zero point three percent", "two dollars and twelve cents",
                       "November fifth at eight thirty in the morning, Eastern Standard Time"):
            self.assertIn(phrase, text)
        self.assertNotRegex(text, r"\d|\$|%")

    def test_decimal_precision_and_zero_are_preserved(self):
        self.assertEqual(normalize("0.08% +1.38% -0.21%"), "zero point zero eight percent one point three eight percent minus zero point two one percent")
        self.assertIn("zero dollars and eight cents", normalize("$0.08"))
        self.assertIn("four point five nine billion dollars", normalize("$4.59 billion"))
        self.assertEqual(normalize("$694M"),"six hundred ninety four million dollars")
        self.assertEqual(normalize("$63B"),"sixty three billion dollars")
        self.assertEqual(normalize("$4.5bn"),"four point five billion dollars")

    def test_filing_amendments_are_preserved_while_bot_commands_and_urls_are_removed(self):
        text = normalize("Form S-1/A; /fullreport https://example.com/evidence")
        self.assertIn("/A", text)
        self.assertNotIn("fullreport", text)
        self.assertNotIn("https", text)

    def test_clock_edges_and_policy_range_do_not_turn_into_different_numbers(self):
        self.assertEqual(normalize("12:00 PM EDT"), "noon, Eastern Daylight Time")
        self.assertEqual(normalize("12:00 AM EST"), "midnight, Eastern Standard Time")
        self.assertIn("three point seven five to four percent", normalize("3.75–4%"))
        self.assertIn("five oh five in the afternoon", normalize("05:05 PM EST"))
        self.assertIn("twelve thirty in the afternoon", normalize("12:30 PM EDT"))


class VoiceChecks(IsolatedChecks):
    def render(self, values=None, research=None):
        research = research or self.research()
        with patch.object(editor, "cache_candidates", return_value=(values or [], [])):
            text = news.build_daily_news_brief(research)
        return text, store.read_editions(report=text)[0]

    def test_every_new_edition_records_a_frozen_voice_companion(self):
        text, record = self.render()
        profile = voice.checked(record, NOW)
        self.assertEqual(record["report_text"], text)
        self.assertEqual(profile["script"], "\n\n".join(scene["narration"] for scene in profile["segments"]))
        self.assertTrue(profile["quality"]["passes"])
        self.assertEqual(profile["script_sha256"], voice.digest(profile["script"]))

    def test_script_has_flow_without_metadata_commands_or_repeated_breadth(self):
        _, record = self.render(); text = record["voiceover"]["script"]
        self.assertTrue(text.startswith("Good afternoon. This is Smart Money"))
        self.assertIn("The key takeaway.", text)
        self.assertIn("Here are the next checks.", text)
        self.assertEqual(text.count("seven finished higher"), 1)
        for label in ("Generated:", "Research Notes", "/fullreport", "https://", "Investor take:", "Portfolio lens:"):
            self.assertNotIn(label, text)

    def test_no_story_script_retains_useful_company_checks_without_inventing_news(self):
        _, record = self.render(); text = record["voiceover"]["script"]
        self.assertIn("no fresh development cleared", text)
        self.assertIn("higher fuel or shipping bills", text)
        self.assertNotIn("announced a new", text)

    def test_actual_pronunciation_words_determine_the_duration_and_market_budget(self):
        _, record = self.render(); profile = record["voiceover"]; quality = profile["quality"]
        self.assertEqual(quality["words"], words(profile["script"]))
        self.assertGreaterEqual(quality["editorial_words"], 180)
        self.assertTrue(15 <= quality["market_estimated_seconds"] <= 30)
        self.assertNotIn("guaranteed duration", str(quality))

    def test_session_date_and_closed_tense_are_preserved(self):
        _, record = self.render(); market = record["voiceover"]["segments"][1]["narration"]
        self.assertIn("At the close on Friday, October twenty third", market)
        self.assertNotIn("Sunday", market)

    def test_live_session_does_not_become_a_completed_close(self):
        research = self.research(replacements={"Market Snapshot": "Market Session: Open.\nQuote session: 2026-10-25\nBreadth: 7 up / 11 down / 18 quoted"})
        _, record = self.render(research=research)
        self.assertIn("During the Sunday", record["voiceover"]["script"])
        self.assertIn("are higher", record["voiceover"]["script"])

    def test_pending_outlier_cannot_become_a_spoken_numeric_fact(self):
        research = self.research(replacements={"Watchlist Movers": "Largest regular-session movers:\n• GOOGL: $88.00 (-12.00%)"})
        _, record = self.render(research=research); text = record["voiceover"]["script"]
        self.assertNotIn("twelve percent", text)
        self.assertIn("stock split", text)

    def test_missing_index_data_never_becomes_an_unchanged_russell_quote(self):
        evidence = {"session":"2026-10-23","moves":{"Oil":4.32},"is_open":False}
        text = voice.market_copy(evidence)
        self.assertIn("incomplete",text)
        self.assertNotIn("Russell",text)

    def test_ipo_registration_stays_a_milestone_without_assuming_trading(self):
        from scripts.check_ipo_alerts import IPOChecks
        fixture = IPOChecks("value"); fixture.setUp()
        try:
            story = fixture.value()
            _, record = self.render([story]); text = record["voiceover"]["script"]
            self.assertIn("filed a public registration for a proposed initial public offering",text)
            self.assertIn("does not establish that shares are already trading",text)
            self.assertNotIn("buy",text.lower())
        finally: fixture.doCleanups()

    def test_recent_earnings_keep_the_reporting_period_and_source_qualification(self):
        from scripts.check_earnings_context import EarningsContextChecks
        fixture = EarningsContextChecks("render"); fixture.setUp()
        try:
            text, _ = fixture.render()
            record = store.read_editions(report=text)[0]
            script = voice.checked(record,NOW)["script"]
            self.assertIn("third quarter two thousand twenty six revenue of twelve point five billion dollars",script)
            self.assertIn("operating margin of thirty one point eight percent",script)
            self.assertIn("dated results do not establish the cause",script)
            self.assertIn("earnings_GOOG",record["voiceover"]["sources"])
        finally: fixture.doCleanups()

    def test_rechecked_move_has_no_invented_causal_explanation(self):
        events.review_quotes({"GOOGL": quote()}, lambda _: quote(), NOW)
        research = self.research(replacements={"Watchlist Movers": "Largest regular-session movers:\n• GOOGL: $88.00 (-12.00%)"})
        _, record = self.render(research=research); text = record["voiceover"]["script"]
        self.assertIn("Alphabet fell twelve percent", text)
        self.assertIn("before assigning a business explanation", text)
        self.assertNotIn("because earnings", text)

    def test_original_contract_keeps_the_ceiling_and_work_scope(self):
        story = candidate("CACI", title="CACI Awarded $185 Million U.S. Army Task Order to Advance Expeditionary Power and Mission Readiness",
                          source_excerpt="CACI announced a five-year Army task order valued at up to $185 million for expeditionary power systems.", excerpt_scope="original release excerpt")
        with patch.dict("os.environ", {"SPECIAL_ALERT_SYMBOLS":"CACI,MSFT,NVDA"}):
            _, record = self.render([story])
        text = record["voiceover"]["script"]
        self.assertIn("to advance expeditionary power and mission readiness", text)
        self.assertIn("up to one hundred eighty five million dollars", text)
        self.assertIn("a ceiling, not guaranteed revenue", text)
        self.assertIn("committed funding and a start date", text)
        self.assertEqual(len(record["voiceover"]["sources"]), 1)

    def test_nonofficial_or_held_story_cannot_leak_into_voice_or_source_map(self):
        story = candidate("NVDA", official=False, title="Nvidia announces a secret new chip")
        _, record = self.render([story])
        self.assertNotIn("secret", record["voiceover"]["script"])
        self.assertFalse(record["voiceover"]["sources"])

    def test_selected_company_is_not_repeated_as_a_focus_mover(self):
        story = candidate("MSFT", title="Microsoft introduces the Copilot harness for multi-model AI work")
        _, record = self.render([story]); profile = record["voiceover"]
        self.assertEqual(profile["script"].count("introduced the Copilot harness"), 1)
        self.assertIn("paid adoption", profile["script"])
        self.assertFalse(any(scene["heading"] == "Companies in Focus" and "Microsoft" in scene["narration"] for scene in profile["segments"]))

    def test_proposed_and_cancelled_deals_keep_their_stages(self):
        for title in ("Microsoft plans to acquire Example business", "Microsoft terminates acquisition of Example business", "Microsoft loses an Army contract"):
            _, record = self.render([candidate("MSFT",title=title)])
            text = record["voiceover"]["script"].lower()
            self.assertNotIn("announced a new contract", text)
            self.assertTrue(any(word in text for word in ("plans", "terminates", "loses")))

    def test_source_text_or_narration_tampering_blocks_export(self):
        _, record = self.render()
        for key in ("report_text", "research_text"):
            altered = deepcopy(record); altered[key] += " altered"
            with self.assertRaises(ValueError): voice.checked(altered, NOW)
        altered = deepcopy(record); altered["voiceover"]["segments"][0]["narration"] = "Guaranteed returns."
        with self.assertRaises(ValueError): voice.checked(altered,NOW)

    def test_changed_underlying_market_evidence_blocks_export(self):
        _, record = self.render(); record["analyst_review"]["evidence"]["moves"]["Nasdaq"] = 99
        with self.assertRaises(ValueError): voice.checked(record,NOW)

    def test_export_rejects_future_or_older_than_eight_hour_editions(self):
        _, record = self.render()
        for when in (NOW-timedelta(seconds=1), NOW+timedelta(hours=8,seconds=1)):
            with self.assertRaises(ValueError): voice.episode(record,when)
        self.assertEqual(voice.episode(record,NOW+timedelta(hours=8))["mode"], "draft_review_required")

    def test_legacy_records_still_read_but_need_a_new_run_for_voiceover(self):
        text, record = self.render(); old = {key:value for key,value in record.items() if key not in {"id","voiceover","report_text","research_text"}}
        old_id = store.save_edition(old,text)
        previous = next(row for row in store.read_editions(2) if row["id"] == old_id)
        with self.assertRaisesRegex(ValueError,"run /rundailyagent"): voice.checked(previous,NOW)

    def test_json_matches_existing_renderer_scene_and_source_contract(self):
        _, record = self.render([candidate()]); data = voice.episode(record,NOW)
        self.assertTrue(data["review_required"] and data["contains_synthetic_media"])
        self.assertEqual(data["mode"],"draft_review_required")
        self.assertEqual(data["bot_edition_id"],record["id"])
        self.assertEqual(data["bot_report_sha256"],record["report_sha256"])
        self.assertTrue(2 <= len(data["segments"]) <= 14)
        for scene in data["segments"]:
            self.assertTrue(scene["heading"] and scene["narration"])
            self.assertTrue(set(scene["source_ids"]) <= set(data["sources"]))
        for refs in data["sources"].values():
            self.assertTrue(all(set(("url","publisher","published_at","verified_at")) <= set(ref) for ref in refs))

    def test_episode_date_uses_the_report_timezone_at_utc_midnight(self):
        _, record = self.render()
        # The real build uses a New York edition date; move the fixture's
        # timestamp consistently by building a new original report.
        midnight = NOW.replace(hour=1)
        text, record = self.render(research=self.research(now=midnight))
        self.assertEqual(voice.episode(record,midnight)["date"],"2026-10-24")

    def test_cli_writes_identical_script_and_never_rewrites_existing_exports(self):
        _, record = self.render(); output = self.root / "episode.json"
        clock = SimpleNamespace(now=lambda _:NOW)
        with patch.object(export,"datetime",clock), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(export.main(["--latest","--output",str(output)]),0)
            first = output.read_bytes()
            self.assertEqual(export.main(["--latest","--output",str(output)]),1)
        self.assertEqual(output.read_bytes(),first)
        data = json.loads(first)
        self.assertEqual(output.with_suffix(".txt").read_text(),"\n\n".join(scene["narration"] for scene in data["segments"])+"\n")

    def test_command_sends_only_recorded_plain_text_as_an_attachment(self):
        _, record = self.render(); profile = record["voiceover"]
        message = SimpleNamespace(reply_document=AsyncMock(),reply_text=AsyncMock())
        with patch.object(commands,"latest",return_value=(record,profile)):
            asyncio.run(commands.voiceover_command(SimpleNamespace(message=message),SimpleNamespace(args=[])))
        sent = message.reply_document.await_args.kwargs
        self.assertEqual(sent["document"].getvalue().decode(),profile["script"]+"\n")
        self.assertEqual(sent["filename"],"smart_money_voiceover.txt")

    def test_command_rejects_arguments_and_missing_snapshot_without_paid_work(self):
        for args in (["send"],[]):
            message = SimpleNamespace(reply_document=AsyncMock(),reply_text=AsyncMock())
            with patch.object(commands,"latest",side_effect=ValueError("Build a current edition")):
                asyncio.run(commands.voiceover_command(SimpleNamespace(message=message),SimpleNamespace(args=args)))
            message.reply_document.assert_not_awaited(); message.reply_text.assert_awaited_once()

    def test_reader_and_export_leave_other_state_byte_identical(self):
        _, record = self.render()
        before = {path:path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        voice.checked(record,NOW); voice.episode(record,NOW); editor.build_editor_status()
        after = {path:path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before,after)

    def test_editor_status_exposes_narration_quality_without_claiming_audio_exists(self):
        self.render(); text = editor.build_editor_status()
        self.assertIn("Voiceover: PASS",text)
        self.assertIn("spoken words",text)
        self.assertNotIn("audio rendered",text)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--windows-socketpair",action="store_true"); args = parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair: stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    passed = result.wasSuccessful() and not traffic["blocked"]
    print(f"Daily Voiceover Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())
