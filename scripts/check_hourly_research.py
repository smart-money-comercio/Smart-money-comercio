"""Offline contract, source-gate, scheduling and prospectus checks."""

import argparse
from contextlib import closing, ExitStack
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.agents import research_agents as agents
from src.config.special_alerts import settings
from src.intelligence import hourly_research as desk, ipo_filing_analysis as financials, ipo_monitor as ipo
from src.intelligence import special_alert_engine as engine, special_alert_context as alert_context, news_editor
from src.jobs import hourly_research_scheduler as scheduler
from src.reports.daily_news_brief import build_daily_news_brief, validate_news_brief, IPO_HEADER


URL = "https://nvidianews.nvidia.com/news/fixture"
TITLE = "Nvidia unveils Blackwell platform for AI infrastructure"
QUOTE = "The company announced a new Blackwell platform for enterprise AI infrastructure."


def html(title=TITLE, clock=None, text=QUOTE):
    return (f'<html><head><meta property="og:title" content="{title}">'
            f'<meta property="article:published_time" content="{clock or (NOW-timedelta(minutes=10)).isoformat()}">'
            f'</head><body><article><p>{text}</p></article></body></html>').encode()


def response(payload, *, searched=False, urls=None, status="completed"):
    outputs = [{"type": "reasoning", "content": None}]
    if searched:
        outputs.append({"type": "web_search_call", "action": {"sources": [{"url": url} for url in urls or [URL]]}})
    outputs.append({"type": "message", "content": [{"type": "output_text", "text": json.dumps(payload)}]})
    return {"id": "resp_discovery" if searched else "resp_review", "status": status, "model": "gpt-5", "output": outputs,
            "usage": {"input_tokens": 100, "output_tokens": 50}}


class Client:
    def __init__(self, leads=None, decision="accept", quote=QUOTE, fail_review=False):
        self.calls = []; self.leads = leads if leads is not None else [{"title": TITLE, "url": URL, "topic": "AI"}]
        self.decision, self.quote, self.fail_review = decision, quote, fail_review
        self.responses = SimpleNamespace(create=self.create)

    def create(self, **options):
        self.calls.append(options)
        if options["tools"]:
            return response({"candidates": self.leads}, searched=True, urls=[lead["url"] for lead in self.leads])
        if self.fail_review: raise RuntimeError("provider error")
        rows = json.loads(options["input"])["candidates"]
        return response({"decisions": [{"id": row["id"], "decision": self.decision, "score": 85,
            "reason": "Discrete AI infrastructure development; review deployment and revenue timing.", "evidence_quote": self.quote} for row in rows]})


class ResearchChecks(IsolatedChecks):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"HOURLY_RESEARCH_STATE_FILE": str(self.root / "research.sqlite3"),
            "HOURLY_RESEARCH_ENABLED": "true", "RESEARCH_DISCOVERY_MODEL": "gpt-5", "RESEARCH_REVIEW_MODEL": "gpt-5",
            "AI_IPO_ISSUERS_JSON": "{}", "SPECIAL_ALERT_CONFIRMED_ONLY": "true"}))

    def run_desk(self, client=None, now=NOW, fetch=None):
        return desk.run(now, client=client or Client(), fetch=fetch or (lambda _: html()))

    def test_two_separate_model_roles_and_search_budget(self):
        client = Client(); value = self.run_desk(client)
        self.assertEqual(value["status"], "complete"); self.assertEqual(value["details"]["approved"], 1)
        self.assertEqual(len(client.calls), 2)
        discovery, review = client.calls
        self.assertEqual(discovery["max_tool_calls"], 2); self.assertEqual(discovery["tool_choice"], "required")
        self.assertEqual(discovery["tools"][0]["type"], "web_search"); self.assertEqual(review["tools"], [])
        self.assertIn("web_search_call.action.sources", discovery["include"])
        for call in client.calls:
            self.assertFalse(call["store"]); self.assertEqual(call["max_output_tokens"], 4000)
            self.assertTrue(call["text"]["format"]["strict"])
        self.assertEqual([row["role"] for row in value["details"]["agents"]], ["Discovery Agent", "Relevance Reviewer"])

    def test_source_text_and_date_are_handed_to_reviewer(self):
        client = Client(); self.run_desk(client)
        row = json.loads(client.calls[1]["input"])["candidates"][0]
        self.assertIn(QUOTE, row["source_text"]); self.assertEqual(row["url"], URL)
        self.assertIn("2026-", row["published"])

    def test_once_per_utc_hour_including_restart(self):
        client = Client(); self.run_desk(client)
        self.assertEqual(self.run_desk(client, NOW+timedelta(minutes=1))["status"], "already attempted this hour")
        self.assertEqual(len(client.calls), 2)
        self.run_desk(client, NOW+timedelta(hours=1)); self.assertEqual(len(client.calls), 4)

    def test_atomic_hour_claim(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: desk.claim(NOW), range(4)))
        self.assertEqual(sum(results), 1)

    def test_missing_api_key_is_limited_without_publishing(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            value = desk.run(NOW)
        self.assertEqual(value["status"], "limited"); self.assertEqual(desk.approved(NOW), [])
        self.assertEqual(value["details"]["error"], "ValueError")

    def test_failure_is_not_automatically_retried_this_hour(self):
        client = Client(fail_review=True); value = self.run_desk(client)
        self.assertEqual(value["status"], "limited"); self.assertEqual(desk.approved(NOW), [])
        self.run_desk(client); self.assertEqual(len(client.calls), 2)
        self.assertEqual(desk.read_history()[0]["review"]["final"], "hold")

    def test_pause_survives_restart_and_withholds_cache(self):
        self.run_desk(); desk.set_enabled(False)
        self.assertFalse(desk.settings()["enabled"]); self.assertEqual(desk.approved(NOW), [])
        client = Client(); self.assertEqual(desk.run(NOW, client=client)["status"], "disabled")
        self.assertEqual(client.calls, [])
        desk.set_enabled(True); self.assertEqual(len(desk.approved(NOW)), 1)

    def test_environment_master_switch_cannot_be_overridden(self):
        desk.set_enabled(True)
        with patch.dict(os.environ, {"HOURLY_RESEARCH_ENABLED": "false"}):
            self.assertEqual(desk.run(NOW, client=Client())["status"], "disabled")

    def test_bad_state_fails_closed_before_paid_work(self):
        desk.state_path().write_bytes(b"corrupt database")
        client = Client(); self.assertEqual(desk.run(NOW, client=client)["status"], "disabled")
        self.assertEqual(client.calls, [])

    def test_original_source_failure_stays_held(self):
        def blocked(_): raise HTTPError(URL, 403, "Denied", {}, None)
        self.run_desk(fetch=blocked)
        self.assertEqual(desk.approved(NOW), [])
        self.assertIn("HTTPError", desk.read_history()[0]["verification"])

    def test_unconfigured_secondary_lead_is_held_without_fetch(self):
        client = Client(leads=[{"title": TITLE, "url": "https://reuters.com/fixture", "topic": "AI"}])
        with patch.object(desk, "fetch_original", side_effect=AssertionError("no fetch")):
            self.run_desk(client, fetch=lambda _: self.fail("secondary page fetched"))
        self.assertEqual(desk.approved(NOW), [])

    def test_read_budget_and_candidate_budget(self):
        client = Client(leads=[{"title": TITLE, "url": URL+str(i), "topic": "AI"} for i in range(8)])
        calls = []; self.run_desk(client, fetch=lambda url: calls.append(url) or html())
        self.assertEqual(len(calls), 6); self.assertEqual(len(desk.approved(NOW)), 6)
        self.assertEqual(sum(row["review"]["final"] == "hold" for row in desk.read_history()), 2)

    def test_invented_or_too_short_quotes_are_held(self):
        for quote in ("An invented supporting quotation that does not occur in the original.", "company"):
            with self.subTest(quote=quote):
                self.run_desk(Client(quote=quote)); self.assertEqual(desk.approved(NOW), [])
                desk.state_path().unlink()

    def test_newer_hold_overrides_older_accept_for_the_same_url(self):
        self.run_desk(); self.run_desk(Client(decision="hold"), NOW+timedelta(hours=1))
        self.assertEqual(desk.approved(NOW+timedelta(hours=1)), [])

    def test_approved_findings_are_deduplicated(self):
        self.run_desk(); self.run_desk(now=NOW+timedelta(hours=1))
        self.assertEqual(len(desk.approved(NOW+timedelta(hours=1))), 1)

    def test_stale_observations_are_excluded(self):
        self.run_desk(); self.assertEqual(desk.approved(NOW+timedelta(hours=7)), [])

    def test_proof_binds_title_url_date_and_text(self):
        value = desk.verified({"url": URL}, NOW, lambda _: html())
        for field, changed in (("title", "invented"), ("url", URL+"/other"), ("source_excerpt", "invented"),
                               ("source_checked_at", (NOW+timedelta(hours=1)).isoformat()), ("publisher_symbol", "MSFT")):
            row = deepcopy(value); row[field] = changed
            with self.subTest(field=field), self.assertRaises((ValueError, KeyError)):
                desk.check_proof(row, NOW)

    def test_unzoned_date_only_future_and_stale_sources_are_rejected(self):
        for clock in ("2026-10-25", "2026-10-25T01:00:00", (NOW+timedelta(hours=1)).isoformat(), (NOW-timedelta(hours=25)).isoformat()):
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                desk.verified({"url": URL}, NOW, lambda _: html(clock=clock))

    def test_redirect_leaving_original_publisher_is_blocked(self):
        def opener(handler):
            with self.assertRaises(ValueError):
                handler.redirect_request(None, None, 302, "redirect", {}, "https://attacker.test/report")
            raise ValueError("stopped before network")
        with patch.object(desk, "build_opener", side_effect=opener), self.assertRaises(ValueError):
            desk.fetch_original(URL)

    def test_untrusted_hosts_and_credentials_never_pass_identity(self):
        for url in ("https://nvidia.com.attacker.test/story", "http://nvidia.com/story", "https://user:pass@nvidia.com/story", "https://127.0.0.1/story", "https://nvidia.com:8000/story"):
            with self.subTest(url=url):
                try: self.assertIsNone(desk.identity(url))
                except ValueError: pass

    def test_read_only_views_do_not_create_state(self):
        self.assertEqual(desk.read_history(), []); self.assertEqual(desk.approved(NOW), [])
        self.assertEqual(desk.status()["status"], "not run"); self.assertFalse(desk.state_path().exists())

    def test_reader_does_not_initialize_missing_schema(self):
        with closing(sqlite3.connect(desk.state_path())) as db: db.execute("CREATE TABLE unrelated (id INTEGER)")
        self.assertEqual(desk.status()["status"], "unavailable")
        self.assertEqual(desk.approved(NOW), [])
        with closing(sqlite3.connect(desk.state_path())) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("unrelated",)])

    def test_bad_audit_digest_does_not_promote_story(self):
        self.run_desk()
        with closing(sqlite3.connect(desk.state_path())) as db, db: db.execute("UPDATE findings SET digest='invalid'")
        self.assertEqual(desk.approved(NOW), [])

    def test_models_cannot_send_or_change_scores_or_receipts(self):
        before = {path: path.read_bytes() for path in (self.ranking, self.db)}
        self.run_desk()
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_approved_original_enters_cache_only_editor(self):
        self.run_desk()
        with patch.object(desk, "run", side_effect=AssertionError("no AI from rendering")):
            item = desk.approved(NOW)[0]
            self.assertEqual(news_editor.primary_source(item), "NVDA")
            plan = news_editor.build_editorial_plan({"rows": [{"symbol": "NVDA", "events": []}], "issues": []}, NOW, extra_candidates=[item])
            self.assertEqual(len(news_editor.selected_stories(plan)), 1)

    def test_approved_finding_reaches_brief_and_editor_audit_without_model_calls(self):
        client = Client(); self.run_desk(client)
        text = build_daily_news_brief(self.research())
        self.assertIn(TITLE, text); self.assertTrue(validate_news_brief(text)["passes"])
        from src.intelligence.news_editor_store import read_editions
        editions = read_editions(report=text)
        self.assertEqual(len(editions), 1)
        selected = news_editor.selected_stories(editions[0])
        self.assertTrue(any(story.get("discovery_evidence") for story in selected)); self.assertEqual(len(client.calls), 2)

    def test_intelligence_context_uses_only_reviewed_cache(self):
        self.run_desk()
        with patch.object(desk, "datetime") as clock:
            clock.now.return_value = NOW
            context = desk.context_provider()
        self.assertIn(TITLE, context.signal); self.assertIn("NVDA", context.symbols)
        self.assertFalse(context.metadata["score_changes"])

    def test_admin_run_calls_worker_in_private_chat(self):
        import asyncio
        from src.commands import hourly_research_commands as command
        from unittest.mock import Mock
        async def check():
            update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock(return_value=SimpleNamespace(edit_text=AsyncMock()))),
                                     effective_chat=SimpleNamespace(type="private"))
            worker = Mock(return_value={"status": "complete"})
            with patch.object(command, "is_admin", return_value=True), patch.object(desk, "run", worker), patch.object(command, "reply_long_message", new_callable=AsyncMock):
                await command.researchdesk_command(update, SimpleNamespace(args=["run"]))
            worker.assert_called_once_with()
        asyncio.run(check())

    def test_defaults_require_original_company_confirmation(self):
        item = {"title": "Broadcom partners with a bank for AI hardware", "symbol": "AVGO", "published": NOW.isoformat(),
                "url": "https://stocktwits.com/news/fixture", "source": "Secondary headline", "official": False}
        cfg = {**settings(), "symbols": ["AVGO"]}
        self.assertTrue(cfg["confirmed_only"]); self.assertIsNone(engine.company_alert(item, NOW, cfg))
        self.assertIsNotNone(engine.company_alert(item, NOW, {**cfg, "confirmed_only": False}))
        item.update(official=True, publisher_symbol="AVGO")
        self.assertIsNone(engine.company_alert(item, NOW, cfg))

    def test_original_company_alert_passes_default_policy(self):
        item = desk.verified({"url": URL}, NOW, lambda _: html()); cfg = {**settings(), "symbols": ["NVDA"]}
        self.assertIsNotNone(engine.company_alert(item, NOW, cfg))

    def test_unconfirmed_old_events_are_retained_only_in_history(self):
        events = [{"kind": "company", "evidence": {"official": False}}, {"kind": "market", "evidence": {}}]
        self.assertEqual(alert_context.current_evidence(events), events[1:]); self.assertEqual(len(events), 2)

    def test_scheduler_registers_hourly_nonoverlapping_job(self):
        from unittest.mock import Mock
        queue = Mock(); scheduler.schedule_hourly_research(SimpleNamespace(job_queue=queue))
        options = queue.run_repeating.call_args.kwargs
        self.assertEqual(options["interval"], 3600); self.assertEqual(options["first"], 90)
        self.assertEqual(options["job_kwargs"]["max_instances"], 1)

    def test_scheduler_and_admin_run_do_not_block_event_loop(self):
        import asyncio
        async def check():
            with patch.object(scheduler.asyncio, "to_thread", new_callable=AsyncMock) as thread:
                await scheduler.hourly_research_job(None); thread.assert_awaited_once_with(scheduler.run)
        asyncio.run(check())

    def test_nonadmin_cannot_start_paid_work_or_pause(self):
        import asyncio
        from src.commands import hourly_research_commands as command
        async def check():
            for action in ("run", "on", "off"):
                update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()), effective_chat=SimpleNamespace(type="private"))
                with patch.object(command, "is_admin", return_value=False), patch.object(desk, "run") as run:
                    await command.researchdesk_command(update, SimpleNamespace(args=[action])); run.assert_not_called()
                    self.assertIn("Unauthorized", update.message.reply_text.call_args.args[0])
        asyncio.run(check())


class ContractChecks(unittest.TestCase):
    def test_discovery_rejects_url_without_actual_search_provenance(self):
        client = Client(); client.responses.create = lambda **_: response({"candidates": client.leads}, searched=True, urls=[URL+"/other"])
        with self.assertRaisesRegex(ValueError, "absent"):
            agents.discover(client, "gpt-5", NOW.isoformat(), ["NVDA"], ["nvidia.com"])

    def test_incomplete_model_output_is_rejected(self):
        with self.assertRaises(ValueError): agents.result(response({}, status="incomplete"))

    def test_refusal_is_rejected(self):
        value = response({}); value["output"][-1]["content"] = [{"type": "refusal", "refusal": "no"}]
        with self.assertRaises(ValueError): agents.result(value)

    def test_missing_duplicate_and_invented_review_ids_are_rejected(self):
        row = {"id": "one", "decision": "accept", "score": 90, "reason": "Material", "evidence_quote": QUOTE}
        for decisions in ([], [row, row], [{**row, "id": "invented"}], [{**row, "score": True}]):
            client = SimpleNamespace(responses=SimpleNamespace(create=lambda **_: response({"decisions": decisions})))
            with self.subTest(decisions=decisions), self.assertRaises(ValueError):
                agents.review(client, "gpt-5", [{"id": "one"}], ["NVDA"])

    def test_discovery_cannot_handoff_more_than_eight(self):
        leads = [{"title": TITLE, "url": URL+str(i), "topic": "AI"} for i in range(9)]
        with self.assertRaises(ValueError): agents.discover(Client(leads), "gpt-5", NOW.isoformat(), [], ["nvidia.com"])


def table(*, unit="millions", period="Year Ended December 31,", values=None):
    values = values or [("Revenue", "$100", "$250"), ("Operating loss", "(50)", "(80)"), ("Net loss", "(70)", "(1,965)"),
        ("Change in fair value of convertible notes", "(10)", "(1,700)")]
    return ('<table><tr><td></td><td colspan="2">'+period+'</td></tr><tr><td>(in '+unit+')</td><td>2024</td><td>2025</td></tr>'
            + ''.join('<tr>'+''.join('<td>'+cell+'</td>' for cell in row)+'</tr>' for row in values)+'</table>').encode()


class FinancialChecks(IsolatedChecks):
    def analysis(self, raw=None): return financials.analyze(financials.evidence(raw or table()))

    def test_period_units_signs_and_values_are_bound_to_cells(self):
        rows = self.analysis()["facts"]; latest = [row for row in rows if row["year"] == 2025]
        self.assertEqual({row["field"]: row["value"] for row in latest}, {"revenue": "250", "operating_loss": "-80", "net_loss": "-1965", "financing_fair_value_change": "-1700"})
        self.assertTrue(all(row["period"] == "Year ended December 31, 2025" and row["unit"] == "millions" for row in latest))

    def test_annual_growth_is_not_mixed_with_interim(self):
        value = self.analysis(table()+table(period="Six Months Ended June 30,", values=[("Revenue", "$300", "$500")]))
        text = financials.narration(value)
        self.assertIn("2025 revenue of $250 million, versus $100 million in 2024", text)
        self.assertNotIn("$500", text)

    def test_loss_is_not_called_cash_burn(self):
        text = financials.narration(self.analysis())
        self.assertIn("not an operating-cash-flow measure", text); self.assertIn("not established", text)
        self.assertIn("$1.7 billion financing-related fair-value loss", text)

    def test_known_operating_cash_flow_has_its_own_period(self):
        text = financials.narration(self.analysis(table(values=[("Revenue", "$100", "$250"), ("Net cash used in operating activities", "(30)", "(60)")])))
        self.assertIn("Operating activities used $60 million in 2025", text)

    def test_half_up_rounding(self):
        self.assertEqual(financials.dollars({"value": "41965", "unit": "millions"}), "$41.97 billion")

    def test_growth_uses_comparable_annual_values(self):
        self.assertIn("150.0 percent increase", financials.narration(self.analysis()))

    def test_pro_forma_ambiguous_currency_units_or_periods_are_omitted(self):
        for raw in (table(period="Pro Forma Year Ended December 31,"), table(unit="millions and in thousands"),
                    table(period="Six Months Ended"), table(unit="millions of Canadian dollars")):
            with self.subTest(raw=raw): self.assertEqual(self.analysis(raw)["facts"], [])

    def test_rowspan_and_nested_tables_are_omitted(self):
        for raw in (table().replace(b'<td>Revenue', b'<td rowspan="2">Revenue'), table().replace(b'<td>Revenue</td>', b'<td><table><tr><td>Revenue</td></tr></table></td>')):
            self.assertEqual(self.analysis(raw)["facts"], [])

    def test_conflicting_same_period_values_are_suppressed(self):
        facts = self.analysis(table()+table(values=[("Revenue", "$100", "$999")]))["facts"]
        self.assertFalse(any(row["field"] == "revenue" and row["year"] == 2025 for row in facts))

    def test_malformed_disclosure_passage_is_rejected(self):
        source = financials.evidence(table()); source["passages"] = [{"field": "governance", "text": 123}]
        with self.assertRaises(ValueError): financials.analyze(source)

    def test_governance_and_dated_customer_concentration_are_retained(self):
        raw = table()+b'<p>The Long-Term Benefit Trust can appoint directors to the board under the conditions described in this prospectus.</p><p>Our largest customer accounted for 30% of revenue in 2025.</p>'
        analysis = self.analysis(raw)
        self.assertEqual({row["field"] for row in analysis["passages"]}, {"governance", "customer_concentration"})
        text = financials.narration(analysis); self.assertIn("board appointment rights", text); self.assertIn("customer concentration", text)

    def filing(self, schema=2, source=None):
        return ipo.item("anthropic", ipo.DEFAULT_ISSUERS["anthropic"], "Anthropic: Form S-1 filed for a proposed initial public offering",
            "https://www.sec.gov/Archives/edgar/data/2130357/000162828026000001/fixture.htm", NOW.isoformat(),
            "This is an initial public offering.", NOW.isoformat(), form="S-1", accession="0001628280-26-000001", schema=schema, filing_source=source)

    def test_old_ipo_schema_remains_readable(self):
        self.assertEqual(ipo.checked(self.filing(schema=1), NOW)["name"], "Anthropic")

    def test_changed_financial_analysis_is_rejected(self):
        value = self.filing(source=financials.evidence(table())); value["ipo"]["filing_analysis"]["facts"][0]["value"] = "999999"
        with self.assertRaises(ValueError): ipo.checked(value, NOW)

    def test_ipo_financials_render_in_separate_section(self):
        value = self.filing(source=financials.evidence(table()))
        with patch.object(ipo, "cached_items", return_value=[value]):
            text = build_daily_news_brief(self.research())
        self.assertIn(IPO_HEADER, text.splitlines()); self.assertIn("2025 revenue of $250 million", text)
        defense = text.split("\nGlobal and Defense Watch\n", 1)[1].split("\nWhat's Ahead\n", 1)[0]
        self.assertNotIn("Anthropic", defense); self.assertTrue(validate_news_brief(text)["passes"])
        result = validate_news_brief(text)
        self.assertGreaterEqual(result["spoken_words"], 180); self.assertTrue(45 <= result["market_spoken_words"] <= 90)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--windows-socketpair", action="store_true"); args = parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:
            stack.enter_context(patch.object(socket, "socketpair", portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in (ResearchChecks, ContractChecks, FinancialChecks))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    ok = result.wasSuccessful() and not traffic["blocked"]
    print(f"Hourly Research Check: {'PASS' if ok else 'FAIL'} ({result.testsRun} tests)")
    raise SystemExit(0 if ok else 1)
