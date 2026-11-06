"""Offline scheduler, delivery ledger, owner controls and outcome regressions."""

import argparse
import asyncio
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,Mock,patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.check_premarket_risk import NOW,quotes,snapshot,PRESSURE,SEVERE
from scripts.check_special_alerts import offline_network_guard,portable_tcp_socketpair
from src.intelligence import premarket_store as store,premarket_review as review,premarket_risk as risk
from src.jobs import premarket_scheduler as scheduler
from src.commands import premarket_commands as commands


class Isolated:
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="premarket ledger with spaces ");self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/"ledger.sqlite3"
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,{"PREMARKET_STATE_FILE":str(self.path),"SPECIAL_ALERT_STATE_FILE":str(Path(temp.name)/"special.sqlite3")}))


def outcome_chart(symbol,low=-3,close=1):
    opened=NOW.replace(hour=14,minute=30);end=NOW.replace(hour=21,minute=0)
    return {"meta":{"symbol":symbol,"instrumentType":"ETF","currency":"USD","dataGranularity":"1d","exchangeTimezoneName":"America/New_York",
           "regularMarketPrice":100+close,"regularMarketTime":int(end.timestamp()),"currentTradingPeriod":{"regular":{"start":int(opened.timestamp()),"end":int(end.timestamp())}}},
           "timestamp":[int((opened-timedelta(days=1)).timestamp()),int(opened.timestamp())],
           "indicators":{"quote":[{"close":[100,100+close],"low":[99,100+low],"volume":[1000,1000]}]}}


def outcome(low=-3,close=1):
    return review.observe(NOW.replace(hour=21,minute=20),lambda symbol,**kwargs:outcome_chart(symbol,low,close))


class LedgerChecks(Isolated,unittest.TestCase):
    def test_reading_empty_history_settings_and_reviews_creates_no_database(self):
        self.assertFalse(store.history());self.assertTrue(store.enabled());self.assertFalse(store.outcomes())
        self.assertIn("awaiting outcome: 0",review.report());self.assertFalse(self.path.exists())

    def test_a_slot_preserves_its_first_frozen_evidence(self):
        first=snapshot(PRESSURE);store.save(first)
        second=snapshot(SEVERE);saved=store.save(second)
        self.assertEqual(saved,first);self.assertEqual(store.history()[0],first)

    def test_a_preview_cannot_enter_the_scheduled_ledger(self):
        with self.assertRaises(ValueError):store.save(snapshot(PRESSURE,slot="preview"))
        self.assertFalse(self.path.exists())

    def test_claims_require_a_saved_current_warning(self):
        value=snapshot(PRESSURE);self.assertFalse(store.claim(value,123,NOW))
        store.save(value);self.assertTrue(store.claim(value,123,NOW))

    def test_successful_delivery_suppresses_the_same_grade_at_the_next_slot(self):
        value=store.save(snapshot(PRESSURE));self.assertTrue(store.claim(value,123,NOW));store.finish(value,123,NOW,True)
        at=NOW+timedelta(minutes=30);later=store.save(snapshot(PRESSURE,at,"09:15"))
        self.assertFalse(store.claim(later,123,at));self.assertTrue(store.claim(later,456,at))

    def test_a_higher_grade_can_alert_again(self):
        value=store.save(snapshot(PRESSURE));store.claim(value,123,NOW);store.finish(value,123,NOW,True)
        at=NOW+timedelta(minutes=30);later=store.save(snapshot(SEVERE,at,"09:15"))
        self.assertTrue(store.claim(later,123,at))

    def test_failed_send_can_retry_at_next_slot_but_not_replay_same_snapshot(self):
        value=store.save(snapshot(PRESSURE));store.claim(value,123,NOW);store.finish(value,123,NOW,False)
        self.assertFalse(store.claim(value,123,NOW))
        at=NOW+timedelta(minutes=30);later=store.save(snapshot(PRESSURE,at,"09:15"))
        self.assertTrue(store.claim(later,123,at))

    def test_uncertain_pending_receipt_is_not_treated_as_delivered_or_retried(self):
        value=store.save(snapshot(PRESSURE));store.claim(value,123,NOW)
        at=NOW+timedelta(minutes=30);later=store.save(snapshot(PRESSURE,at,"09:15"))
        self.assertFalse(store.claim(later,123,at));self.assertEqual(store.receipts(value["day"])[0]["status"],"pending")

    def test_none_limited_stale_and_after_open_decisions_never_claim_a_send(self):
        for value in (snapshot(),risk.snapshot({},[],[],NOW,commands.collect_snapshot.__globals__["settings"](),"08:45")):
            store.save(value);self.assertFalse(store.claim(value,1,NOW))
        other=store.save(snapshot(PRESSURE,NOW+timedelta(minutes=30),"09:15"))
        self.assertFalse(store.claim(other,1,NOW+timedelta(minutes=45)))
        self.assertFalse(store.claim(other,1,NOW+timedelta(minutes=41)))

    def test_receipts_are_separate_from_built_decisions(self):
        value=store.save(snapshot(PRESSURE));self.assertEqual(store.history()[0],value)
        self.assertEqual(store.receipts(value["day"]),[])

    def test_owner_pause_state_persists(self):
        store.set_enabled(False);self.assertFalse(store.enabled());store.set_enabled(True);self.assertTrue(store.enabled())

    def test_intraday_stress_is_measured_even_if_the_close_recovers(self):
        value=outcome(low=-4,close=1);self.assertTrue(value["stress"])
        self.assertEqual(round(value["values"]["QQQ"]["close_change"],2),1)

    def test_outcomes_wait_until_after_the_close_and_reject_the_wrong_day(self):
        with self.assertRaises(ValueError):review.observe(NOW,lambda *args,**kwargs:self.fail("Too early for outcome requests"))
        with self.assertRaises(ValueError):review.observe(NOW.replace(hour=21,minute=20)+timedelta(days=1),lambda s,**kwargs:outcome_chart(s))

    def test_outcome_prices_or_classifications_cannot_be_tampered_with(self):
        value=outcome();value["stress"]=False
        with self.assertRaises(ValueError):store.save_outcome(value["day"],value)

    def test_outcome_storage_is_idempotent(self):
        value=outcome();store.save_outcome(value["day"],value)
        store.save_outcome(value["day"],outcome(low=-.1));self.assertTrue(store.outcomes()[value["day"]]["stress"])

    def test_the_latest_slot_is_scored_once_per_day(self):
        store.save(snapshot(PRESSURE));store.save(snapshot(PRESSURE,NOW+timedelta(minutes=30),"09:15"))
        value=outcome();store.save_outcome(value["day"],value)
        self.assertIn("stress followed warning: 1",review.report())

    def test_an_earlier_warning_is_not_erased_by_a_quiet_later_slot(self):
        store.save(snapshot(PRESSURE));store.save(snapshot({},NOW+timedelta(minutes=30),"09:15"))
        value=outcome();store.save_outcome(value["day"],value)
        text=review.report();self.assertIn("stress followed warning: 1",text);self.assertIn("missed threshold breach: 0",text)

    def test_no_warning_stress_and_missing_records_have_distinct_diagnostics(self):
        value=outcome();store.save_outcome(value["day"],value)
        self.assertIn("no premarket record: 1",review.report())
        store.save(snapshot());self.assertIn("missed threshold breach: 1",review.report())

    def test_a_warning_without_later_stress_is_visible(self):
        store.save(snapshot(PRESSURE));value=outcome(low=-.1);store.save_outcome(value["day"],value)
        self.assertIn("warning without threshold breach: 1",review.report())


class SchedulerChecks(Isolated,unittest.IsolatedAsyncioTestCase):
    def context(self,slot="08:45"):
        return SimpleNamespace(job=SimpleNamespace(data=slot),bot=SimpleNamespace(send_message=AsyncMock()))

    def mock(self,value=None,enabled=True):
        self.stack.enter_context(patch.object(scheduler,"active",return_value=enabled))
        self.stack.enter_context(patch.object(scheduler,"destinations",return_value=[123]))
        self.clock=self.stack.enter_context(patch.object(scheduler,"utc_now",return_value=NOW))
        return self.stack.enter_context(patch.object(scheduler,"collect_snapshot",return_value=value or snapshot(PRESSURE)))

    async def test_scheduled_warning_records_a_delivery_receipt(self):
        self.mock();context=self.context();await scheduler.premarket_job(context)
        context.bot.send_message.assert_awaited_once();self.assertEqual(store.receipts("2026-11-05")[0]["status"],"sent")

    async def test_a_duplicate_job_does_not_refetch_or_resend(self):
        collect=self.mock();context=self.context();await scheduler.premarket_job(context);await scheduler.premarket_job(context)
        self.assertEqual(collect.call_count,1);context.bot.send_message.assert_awaited_once()

    async def test_paused_monitor_has_no_requests_or_messages(self):
        collect=self.mock(enabled=False);context=self.context();await scheduler.premarket_job(context)
        collect.assert_not_called();context.bot.send_message.assert_not_awaited();self.assertFalse(store.history())

    async def test_a_late_job_is_discarded(self):
        collect=self.mock();self.clock.return_value=NOW+timedelta(minutes=12)
        context=self.context();await scheduler.premarket_job(context);collect.assert_not_called();context.bot.send_message.assert_not_awaited()

    async def test_delivery_failure_is_recorded_as_failed(self):
        self.mock();context=self.context();context.bot.send_message.side_effect=RuntimeError("Synthetic delivery failure")
        with self.assertLogs(scheduler.LOG,level="WARNING"):
            await scheduler.premarket_job(context)
        self.assertEqual(store.receipts("2026-11-05")[0]["status"],"failed")

    async def test_none_decisions_are_saved_without_a_channel_message(self):
        self.mock(snapshot());context=self.context();await scheduler.premarket_job(context)
        self.assertEqual(len(store.history()),1);context.bot.send_message.assert_not_awaited()

    async def test_a_pause_during_collection_stops_delivery(self):
        self.mock();self.stack.enter_context(patch.object(scheduler,"active",side_effect=[True,False]))
        context=self.context();await scheduler.premarket_job(context);context.bot.send_message.assert_not_awaited()

    async def test_crossing_the_open_during_collection_prevents_delivery(self):
        self.mock();self.clock.side_effect=[NOW,NOW+timedelta(minutes=45)]
        context=self.context();await scheduler.premarket_job(context);context.bot.send_message.assert_not_awaited()

    async def test_an_absent_destination_keeps_evidence_without_delivery_receipts(self):
        self.mock();self.stack.enter_context(patch.object(scheduler,"destinations",return_value=[]))
        context=self.context();await scheduler.premarket_job(context)
        self.assertEqual(len(store.history()),1);self.assertFalse(store.receipts("2026-11-05"));context.bot.send_message.assert_not_awaited()

    def test_master_pause_controls_the_new_monitor(self):
        with patch.object(scheduler,"settings",return_value={"enabled":True}),patch.object(scheduler.special_store,"get_settings",return_value={"enabled":False}):
            self.assertFalse(scheduler.active())

    def test_collection_uses_the_final_observation_clock(self):
        final=NOW+timedelta(seconds=15)
        with patch.object(scheduler,"utc_now",side_effect=[NOW,final]),patch.object(scheduler.sources,"collect",return_value=(quotes(),[])),patch.object(scheduler.disclosures,"collect",return_value=([],[])):
            value=scheduler.collect_snapshot("08:45")
        self.assertEqual(value["observed_at"],final.isoformat());risk.checked(value)

    async def test_preview_replies_without_recording_or_channel_delivery(self):
        update=SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()),effective_chat=SimpleNamespace(type="private"))
        context=SimpleNamespace(args=["preview"])
        with patch.object(commands,"is_admin",return_value=True),patch.object(commands,"LAST_PREVIEW",0),patch.object(commands,"collect_snapshot",return_value=snapshot(PRESSURE,slot="preview")),patch.object(commands,"reply_long_message",new=AsyncMock()) as reply:
            await commands.premarket_command(update,context)
            reply.assert_awaited_once()
        self.assertFalse(self.path.exists())

    async def test_public_preview_and_nonadmin_toggle_are_denied(self):
        update=SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()),effective_chat=SimpleNamespace(type="group"))
        with patch.object(commands,"is_admin",return_value=True),patch.object(commands,"collect_snapshot") as collect:
            await commands.premarket_command(update,SimpleNamespace(args=["preview"]))
            collect.assert_not_called()
        self.assertIn("Unauthorized",update.message.reply_text.call_args.args[0])

    async def test_preview_has_a_request_cooldown(self):
        update=SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()),effective_chat=SimpleNamespace(type="private"))
        with patch.object(commands,"is_admin",return_value=True),patch.object(commands,"LAST_PREVIEW",commands.monotonic()),patch.object(commands,"collect_snapshot") as collect:
            await commands.premarket_command(update,SimpleNamespace(args=["preview"]))
            collect.assert_not_called()

    def test_daily_jobs_keep_eastern_wall_times_and_weekday_mapping(self):
        app=SimpleNamespace(job_queue=Mock());scheduler.schedule_premarket(app)
        calls=app.job_queue.run_daily.call_args_list;self.assertEqual(len(calls),3)
        self.assertEqual([(c.kwargs["time"].hour,c.kwargs["time"].minute) for c in calls],[(8,45),(9,15),(16,20)])
        for call in calls:
            self.assertEqual(call.kwargs["days"],(1,2,3,4,5));self.assertEqual(str(call.kwargs["time"].tzinfo),"America/New_York")


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--windows-socketpair",action="store_true");args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (LedgerChecks,SchedulerChecks))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    good=result.wasSuccessful() and not traffic["blocked"]
    print(f"Premarket Operations Check: {'PASS' if good else 'FAIL'} ({result.testsRun} tests)")
    return 0 if good else 1


if __name__=="__main__":raise SystemExit(main())
