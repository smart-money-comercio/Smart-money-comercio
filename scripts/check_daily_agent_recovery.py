"""Offline research-versus-Telegram failures, receipts and duplicate-send checks."""

import argparse
import asyncio
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.commands import daily_agent_commands as commands
from src.utils import daily_agent_delivery as delivery
from src.reports import daily_agent_status_report as status_report

LAST_RUN="2026-11-08T15:45:00Z"
REPORT="Smart Money Daily News Brief\n\n"+"A"*2100+"\n\n"+"B"*2100


def result(success=True):
    return {"success":success,"last_run":LAST_RUN,"report":REPORT,"report_characters":len(REPORT),"steps":[
        {"name":"Daily Report Build","status":"pass","detail":"Report built."},
        {"name":"Quality Review","status":"pass" if success else "fail","detail":"Synthetic quality result."}]}


class PrivateState:
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ,{"DAILY_AGENT_DELIVERY_STATE_FILE":str(self.root/'delivery.json')}))


class CommandChecks(PrivateState,unittest.IsolatedAsyncioTestCase):
    def update(self):
        loading=SimpleNamespace(edit_text=AsyncMock())
        chat=SimpleNamespace(send_message=AsyncMock())
        update=SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock(return_value=loading)),effective_chat=chat)
        return update,loading,chat

    async def run_command(self,update,value=None,error=None):
        with patch.object(commands,"run_daily_agent",return_value=value or result(),side_effect=error) as run,patch.object(commands.asyncio,"sleep",new_callable=AsyncMock):
            await commands.rundailyagent_command(update,SimpleNamespace())
        self.assertEqual(run.call_count,1)

    async def test_success_retains_research_pass_and_all_api_confirmations(self):
        update,loading,chat=self.update();await self.run_command(update)
        saved=delivery.read_receipt()
        self.assertEqual(saved["state"],"confirmed");self.assertEqual(saved["workflow_status"],"PASS")
        self.assertEqual(saved["report_confirmed"],2);self.assertEqual(chat.send_message.await_count,2)
        self.assertIn("Status: PASS",loading.edit_text.await_args.args[0])

    async def test_report_read_error_does_not_turn_research_pass_into_fail(self):
        update,loading,chat=self.update();chat.send_message.side_effect=NetworkError("httpx.ReadError:")
        value=result();before=deepcopy(value);await self.run_command(update,value)
        self.assertEqual(value,before)
        self.assertIn("Status: PASS",loading.edit_text.await_args.args[0]);self.assertIn("UNCONFIRMED",loading.edit_text.await_args.args[0])
        saved=delivery.read_receipt();self.assertEqual(saved["stage"],"brief_part");self.assertEqual(saved["part"],1)

    async def test_uncertain_report_post_is_not_retried(self):
        update,_,chat=self.update();chat.send_message.side_effect=NetworkError("httpx.ReadError:")
        await self.run_command(update);self.assertEqual(chat.send_message.await_count,1)
        self.assertEqual(delivery.read_receipt()["report_confirmed"],0)

    async def test_partial_report_keeps_confirmed_parts_and_stops_at_uncertain_part(self):
        update,loading,chat=self.update();chat.send_message.side_effect=[SimpleNamespace(message_id=1),TimedOut()]
        await self.run_command(update);saved=delivery.read_receipt()
        self.assertEqual((saved["report_confirmed"],saved["report_total"],saved["part"]),(1,2,2))
        self.assertIn("Affected part: 2/2",loading.edit_text.await_args.args[0]);self.assertEqual(chat.send_message.await_count,2)

    async def test_transient_status_edit_repeats_identical_text_then_continues(self):
        update,loading,chat=self.update();loading.edit_text.side_effect=[NetworkError("ReadError"),True]
        await self.run_command(update)
        self.assertEqual(loading.edit_text.await_args_list[0],loading.edit_text.await_args_list[1])
        self.assertEqual(chat.send_message.await_count,2);self.assertEqual(delivery.read_receipt()["state"],"confirmed")

    async def test_already_applied_status_edit_counts_as_confirmed_on_retry(self):
        update,loading,_=self.update();loading.edit_text.side_effect=[NetworkError("ReadError"),BadRequest("Message is not modified: specified new message content is exactly the same")]
        await self.run_command(update);self.assertEqual(delivery.read_receipt()["state"],"confirmed")

    async def test_persistent_status_edit_failure_does_not_send_a_duplicate_status_or_brief(self):
        update,loading,chat=self.update();loading.edit_text.side_effect=[NetworkError("ReadError"),NetworkError("ReadError"),True]
        await self.run_command(update);chat.send_message.assert_not_awaited()
        self.assertEqual(delivery.read_receipt()["stage"],"status_edit");self.assertIn("Status: PASS",loading.edit_text.await_args.args[0])

    async def test_failure_notice_can_fail_without_erasing_the_original_receipt(self):
        update,loading,_=self.update();loading.edit_text.side_effect=NetworkError("ReadError")
        await self.run_command(update);saved=delivery.read_receipt()
        self.assertEqual(loading.edit_text.await_count,4);self.assertEqual(saved["stage"],"status_edit")
        self.assertEqual(saved["state"],"unconfirmed");self.assertIn("NetworkError",saved["notice_error"])

    async def test_long_status_failure_has_its_own_stage_and_no_report_send(self):
        update,loading,chat=self.update();value=result()
        value["steps"]=[{"name":"Source "+str(i),"status":"fail","detail":"Long source diagnostic "*20} for i in range(25)]+value["steps"]
        chat.send_message.side_effect=NetworkError("ReadError")
        await self.run_command(update,value);saved=delivery.read_receipt()
        self.assertEqual(saved["stage"],"status_part");self.assertEqual(saved["part"],2)
        self.assertEqual(saved["status_confirmed"],1);self.assertEqual(saved["report_confirmed"],0)

    async def test_missing_loading_acknowledgement_does_not_prevent_requested_research(self):
        update,_,chat=self.update();update.message.reply_text.side_effect=NetworkError("ReadError")
        await self.run_command(update);saved=delivery.read_receipt()
        self.assertEqual(saved["loading_notice"],"unconfirmed");self.assertEqual(saved["state"],"confirmed")
        self.assertEqual(chat.send_message.await_count,3)

    async def test_rejected_report_post_is_not_retried_or_labeled_research_failure(self):
        update,loading,chat=self.update();chat.send_message.side_effect=Forbidden("Synthetic rejected destination")
        await self.run_command(update);self.assertEqual(chat.send_message.await_count,1)
        self.assertEqual(delivery.read_receipt()["state"],"failed");self.assertIn("Status: PASS",loading.edit_text.await_args.args[0])

    async def test_rate_limited_report_is_not_blindly_reposted(self):
        update,_,chat=self.update();chat.send_message.side_effect=RetryAfter(30)
        await self.run_command(update);self.assertEqual(chat.send_message.await_count,1)
        self.assertEqual(delivery.read_receipt()["error"],"RetryAfter")

    async def test_bad_request_is_not_treated_as_a_retryable_network_error(self):
        loading=SimpleNamespace(edit_text=AsyncMock(side_effect=BadRequest("Synthetic invalid edit")))
        with self.assertRaises(BadRequest):await commands.edit_status(loading,"Same text")
        self.assertEqual(loading.edit_text.await_count,1)

    async def test_not_modified_is_not_accepted_without_a_prior_uncertain_edit(self):
        loading=SimpleNamespace(edit_text=AsyncMock(side_effect=BadRequest("Message is not modified")))
        with self.assertRaises(BadRequest):await commands.edit_status(loading,"Same text")

    async def test_critical_research_failure_stays_fail_and_sends_no_report(self):
        update,loading,chat=self.update();await self.run_command(update,result(False))
        self.assertIn("Status: FAIL",loading.edit_text.await_args.args[0]);chat.send_message.assert_not_awaited()
        self.assertEqual(delivery.read_receipt()["workflow_status"],"FAIL")

    async def test_uncaught_workflow_exception_is_distinct_from_delivery_error(self):
        update,loading,chat=self.update();await self.run_command(update,error=RuntimeError("Synthetic build failure"))
        saved=delivery.read_receipt();self.assertEqual(saved["state"],"workflow_error");self.assertEqual(saved["workflow_last_run"],"")
        self.assertIn("research workflow did not return",loading.edit_text.await_args.args[0]);chat.send_message.assert_not_awaited()

    async def test_diagnostic_write_failure_does_not_fail_the_workflow_or_reply(self):
        update,loading,chat=self.update()
        with patch.object(delivery,"save_receipt",return_value=False):await self.run_command(update)
        self.assertIn("Status: PASS",loading.edit_text.await_args.args[0]);self.assertEqual(chat.send_message.await_count,2)

    async def test_reply_diagnostics_do_not_echo_tokens_or_provider_urls(self):
        update,loading,chat=self.update();chat.send_message.side_effect=NetworkError("httpx.ReadError: https://api.telegram.org/bot12345:secret/sendMessage")
        await self.run_command(update)
        text=delivery.state_path().read_text()+loading.edit_text.await_args.args[0]
        self.assertNotIn("secret",text);self.assertNotIn("https://",text);self.assertIn("ReadError",text)

    async def test_status_query_reads_matching_receipt_without_running_the_agent(self):
        update,_,chat=self.update();chat.send_message.side_effect=NetworkError("ReadError");await self.run_command(update)
        with patch.object(status_report,"load_daily_agent_status",return_value=result()),patch.object(commands,"run_daily_agent",side_effect=AssertionError("Read only")):
            text=status_report.build_daily_agent_status_report()
        self.assertIn("Status: PASS",text);self.assertIn("Manual Telegram reply: UNCONFIRMED",text)


class ReceiptChecks(PrivateState,unittest.TestCase):
    def test_missing_receipt_read_does_not_create_any_file(self):
        self.assertIsNone(delivery.read_receipt());self.assertFalse(delivery.state_path().exists())

    def test_read_does_not_change_the_recorded_receipt(self):
        receipt=delivery.Receipt();receipt.result(result(),1,2);before=delivery.state_path().read_bytes()
        self.assertEqual(delivery.read_receipt(),receipt.value);self.assertEqual(delivery.state_path().read_bytes(),before)

    def test_old_run_receipt_is_not_assigned_to_a_new_saved_run(self):
        receipt=delivery.Receipt();receipt.result(result(),1,2)
        self.assertEqual(delivery.status_suffix({"last_run":"other-run"}),"")

    def test_older_command_cannot_overwrite_a_newer_request_receipt(self):
        first=delivery.Receipt();second=delivery.Receipt();first.update(stage="old-attempt")
        self.assertEqual(delivery.read_receipt()["run_id"],second.value["run_id"])

    def test_corrupt_or_oversized_receipts_are_ignored(self):
        for text in ("{invalid", "x"*(delivery.MAX_BYTES+1), "[]"):
            delivery.state_path().write_text(text);self.assertIsNone(delivery.read_receipt())

    def test_boolean_schema_and_impossible_confirmed_counts_are_rejected(self):
        receipt=delivery.Receipt()
        for changes in ({"schema":True},{"status_total":1,"status_confirmed":2},{"report_confirmed":-1}):
            delivery.state_path().write_text(json.dumps({**receipt.value,**changes}));self.assertIsNone(delivery.read_receipt())

    def test_failed_atomic_replace_keeps_the_previous_receipt_and_removes_temporary_file(self):
        receipt=delivery.Receipt();before=delivery.state_path().read_bytes()
        with patch.object(delivery.os,"replace",side_effect=OSError("Synthetic write failure")):
            receipt.update(stage="status_edit")
        self.assertEqual(delivery.state_path().read_bytes(),before)
        self.assertEqual([p.name for p in self.root.iterdir()],["delivery.json"])

    def test_unreturned_request_cannot_be_mistaken_for_the_previous_saved_pass(self):
        receipt=delivery.Receipt();receipt.update(state="workflow_error",stage="research_workflow",error="RuntimeError")
        suffix=delivery.status_suffix(result());self.assertIn("saved run above may be earlier",suffix)

    def test_exception_chain_is_retained_without_exception_messages(self):
        error=NetworkError("secret URL");error.__cause__=ConnectionError("secret credential")
        self.assertEqual(delivery.error_note(error),"NetworkError / ConnectionError")

    def test_malformed_receipt_strings_cannot_break_the_status_report(self):
        receipt=delivery.Receipt()
        for changes in ({"error":{}},{"stage":None},{"started_at":"no clock"},{"workflow_status":"invalid"}):
            delivery.state_path().write_text(json.dumps({**receipt.value,**changes}));self.assertEqual(delivery.status_suffix(result()),"")

    def test_no_saved_workflow_still_displays_the_unreturned_manual_request(self):
        receipt=delivery.Receipt();receipt.update(state="workflow_error",stage="research_workflow",error="RuntimeError")
        with patch.object(status_report,"load_daily_agent_status",return_value={}):
            text=status_report.build_daily_agent_status_report()
        self.assertIn("NOT RUN YET",text);self.assertIn("manual request did not return",text)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--windows-socketpair",action="store_true");args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case) for case in (CommandChecks,ReceiptChecks))
        test_result=unittest.TextTestRunner(verbosity=1).run(suite)
    good=test_result.wasSuccessful() and not traffic["blocked"]
    print(f"Daily Agent Recovery Check: {'PASS' if good else 'FAIL'} ({test_result.testsRun} tests)")
    return 0 if good else 1


if __name__=="__main__":raise SystemExit(main())
