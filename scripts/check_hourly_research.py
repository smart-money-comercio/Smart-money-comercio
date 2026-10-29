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
from src.intelligence import sec_research as sec
from src.intelligence.research_evidence import SourceRejected
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


class ResearchFixture(IsolatedChecks):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"HOURLY_RESEARCH_STATE_FILE": str(self.root / "research.sqlite3"),
            "HOURLY_RESEARCH_ENABLED": "true", "RESEARCH_DISCOVERY_MODEL": "gpt-5", "RESEARCH_REVIEW_MODEL": "gpt-5",
            "AI_IPO_ISSUERS_JSON": "{}", "SPECIAL_ALERT_CONFIRMED_ONLY": "true"}))

    def run_desk(self, client=None, now=NOW, fetch=None):
        return desk.run(now, client=client or Client(), fetch=fetch or (lambda _: html()))


class ResearchChecks(ResearchFixture):
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
        self.assertIn("HTTP 403", desk.read_history()[0]["verification"])

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

    def test_routine_help_lead_is_skipped_without_reads_or_paid_review(self):
        lead = {"title": "Projects product help updated five hours ago", "url": "https://help.openai.com/en/articles/fixture", "topic": "AI"}
        client = Client(leads=[lead])
        value = self.run_desk(client, fetch=lambda _: self.fail("Routine help page fetched"))
        self.assertEqual(len(client.calls), 1); self.assertEqual(value["details"]["original_reads"], 0)
        self.assertEqual(value["details"]["skipped"], 1); self.assertEqual(desk.approved(NOW), [])

    def test_discovery_receives_two_investor_search_tasks_and_reviewed_urls(self):
        self.run_desk(); client = Client(); self.run_desk(client, NOW+timedelta(hours=1))
        payload = json.loads(client.calls[0]["input"])
        self.assertEqual(len(payload["search_tasks"]), 2); self.assertIn(URL, payload["recently_reviewed_urls"])
        self.assertIn("Defense", payload["search_tasks"][1]); self.assertIn("product-help", client.calls[0]["instructions"])

    def test_routine_paths_are_filtered_but_company_news_is_preserved(self):
        for url in ("https://docs.microsoft.com/cloud", "https://openai.com/pricing", "https://nvidia.com/support/article"):
            self.assertTrue(desk.routine_page(url))
        self.assertFalse(desk.routine_page("https://blogs.microsoft.com/blog/layoffs-announced"))


SEC_CIK = "1234567"
SEC_ACCESSION = "0000000001-26-000001"
SEC_COMPACT = SEC_ACCESSION.replace("-", "")
SEC_ROOT = f"https://www.sec.gov/Archives/edgar/data/{SEC_CIK}/{SEC_COMPACT}/"
SEC_INDEX = SEC_ROOT + SEC_ACCESSION + "-index.htm"
SEC_PRIMARY = SEC_ROOT + "report.htm"
SEC_QUOTE = "The Company entered into a binding commitment letter for a finance lease covering GPU equipment."
SEC_TEXT = ("Item 8.01. Other Events. " + SEC_QUOTE + " The Company expects aggregate principal payments under the lease schedules over their respective terms to total approximately $12 billion. "
            "The transaction is subject to specified closing conditions and expected equipment delivery.")


def sec_metadata(**changes):
    value = {"cik": int(SEC_CIK), "name": "EXAMPLE ORBITAL SYSTEMS CORP", "tickers": ["XORB"], "filings": {"recent": {
        "accessionNumber": [SEC_ACCESSION], "form": ["8-K"], "acceptanceDateTime": [(NOW-timedelta(minutes=20)).isoformat()], "primaryDocument": ["report.htm"]}}}
    for field, changed in changes.items():
        if field in {"cik", "name", "tickers"}: value[field] = changed
        else: value["filings"]["recent"][field] = changed
    return json.dumps(value).encode()


def sec_document(*, cik=SEC_CIK, name="Example Orbital Systems Corp.", form="8-K", text=SEC_TEXT):
    fields = {"EntityCentralIndexKey": cik.zfill(10), "EntityRegistrantName": name, "DocumentType": form, "TradingSymbol": "XORB"}
    return ('<html><body>'+''.join(f'<ix:nonNumeric name="dei:{key}">{value}</ix:nonNumeric>' for key, value in fields.items())
            +'<p>'+text+'</p><p>Forward-Looking Statements</p><p>Other unrelated boilerplate.</p></body></html>').encode()


class SECResearchChecks(ResearchFixture):
    def fetch(self, metadata=None, document=None, calls=None):
        def get(url):
            if calls is not None: calls.append(url)
            if url == f"https://data.sec.gov/submissions/CIK{int(SEC_CIK):010d}.json": return metadata if metadata is not None else sec_metadata()
            if url == SEC_PRIMARY: return document if document is not None else sec_document()
            if url.startswith(URL): return html()
            self.fail("Unexpected original URL: " + url)
        return get

    def test_sec_index_is_resolved_using_issuer_submissions_and_primary_document(self):
        calls = []; value = desk.verified({"url": SEC_INDEX}, NOW, self.fetch(calls=calls))
        self.assertEqual(value["url"], SEC_PRIMARY); self.assertEqual(len(calls), 2)
        self.assertEqual(sec.checked(value, NOW)["issuer"], "EXAMPLE ORBITAL SYSTEMS CORP")
        self.assertEqual(value["symbols"], ["XORB"]); self.assertIn("AI infrastructure financing", value["title"])

    def test_direct_and_inline_viewer_leads_resolve_to_the_same_document(self):
        viewer = "https://www.sec.gov/ix?doc=" + SEC_PRIMARY.removeprefix("https://www.sec.gov")
        for url in (SEC_PRIMARY, viewer):
            self.assertEqual(desk.verified({"url": url}, NOW, self.fetch())["url"], SEC_PRIMARY)

    def test_model_title_does_not_supply_issuer_identity(self):
        value = desk.verified({"url": SEC_INDEX, "title": "An unrelated company announces a completed deal"}, NOW, self.fetch())
        self.assertNotIn("unrelated", value["title"]); self.assertIn("EXAMPLE ORBITAL", value["title"])

    def test_sec_acceptance_is_used_instead_of_event_or_filing_date(self):
        value = desk.verified({"url": SEC_INDEX}, NOW, self.fetch())
        self.assertEqual(value["published"], (NOW-timedelta(minutes=20)).isoformat())

    def test_wrong_cik_name_form_and_document_are_rejected(self):
        fixtures = [(sec_metadata(cik=1), sec_document()), (sec_metadata(), sec_document(cik="1")),
            (sec_metadata(), sec_document(name="Different Issuer")), (sec_metadata(), sec_document(form="10-Q")),
            (sec_metadata(form=["S-1"]), sec_document(form="S-1")), (sec_metadata(primaryDocument=["../other.htm"]), sec_document())]
        for metadata, document in fixtures:
            with self.subTest(metadata=metadata[:80]), self.assertRaises(ValueError):
                desk.verified({"url": SEC_INDEX}, NOW, self.fetch(metadata, document))

    def test_unrelated_exhibit_or_index_accession_does_not_establish_primary_report(self):
        for url in (SEC_ROOT+"exhibit.htm", SEC_ROOT+"0000000001-26-000002-index.htm"):
            with self.assertRaises(ValueError): desk.verified({"url": url}, NOW, self.fetch())

    def test_missing_duplicate_or_stale_submission_records_are_rejected(self):
        cases = [sec_metadata(accessionNumber=[]), sec_metadata(acceptanceDateTime=["2026-10-25"]),
            sec_metadata(acceptanceDateTime=[(NOW-timedelta(hours=25)).isoformat()]), sec_metadata(acceptanceDateTime=[(NOW+timedelta(hours=1)).isoformat()])]
        value = json.loads(sec_metadata())
        for key in value["filings"]["recent"]: value["filings"]["recent"][key] *= 2
        cases.append(json.dumps(value).encode())
        for metadata in cases:
            with self.assertRaises(ValueError): desk.verified({"url": SEC_INDEX}, NOW, self.fetch(metadata))

    def test_sec_authentication_does_not_allow_arbitrary_urls(self):
        for url in ("https://www.sec.gov.attacker.test/Archives/report.htm", "https://www.sec.gov/Archives/edgar/data/1/123/report.htm",
                    "https://www.sec.gov/ix?doc=https://attacker.test/report", SEC_PRIMARY+"?redirect=attacker.test", "https://data.sec.gov/submissions/../../other"):
            self.assertFalse(sec.authority(url))

    def test_tampered_filing_facts_or_identity_are_rejected(self):
        original = desk.verified({"url": SEC_INDEX}, NOW, self.fetch())
        for change in ("amount", "issuer", "title", "clock", "body"):
            value = deepcopy(original)
            if change == "amount": value["sec_filing"]["disclosure"]["facts"][0]["value"] = "$999 billion"
            if change == "issuer": value["sec_filing"]["issuer"] = "Another company"
            if change == "title": value["title"] = "Closed deal"
            if change == "clock": value["published"] = NOW.isoformat()
            if change == "body": value["source_excerpt"] = "Invented facts"
            with self.subTest(change=change), self.assertRaises(ValueError): sec.checked(value, NOW)

    def test_financing_analysis_preserves_expected_total_and_conditions(self):
        text = sec.narration(desk.verified({"url": SEC_INDEX}, NOW, self.fetch()))
        self.assertIn("expected aggregate principal payments of approximately $12 billion over the lease terms", text)
        self.assertIn("conditional", text); self.assertIn("rather than a single year's expense or revenue", text)
        self.assertNotIn("IPO", text); self.assertNotIn("completed deal", text)

    def test_both_sec_reads_count_against_the_existing_six_read_budget(self):
        leads = [{"title": "A current SEC report", "url": SEC_INDEX, "topic": "AI"}] + [{"title": TITLE, "url": URL+str(i), "topic": "AI"} for i in range(7)]
        calls = []; value = self.run_desk(Client(leads=leads), fetch=self.fetch(calls=calls))
        self.assertEqual(len(calls), 6); self.assertEqual(value["details"]["original_reads"], 6)
        self.assertEqual(value["details"]["source_verified"], 5)

    def test_verified_sec_report_passes_separate_reviewer_and_cache_only_brief(self):
        client = Client(leads=[{"title": "Material current report", "url": SEC_INDEX, "topic": "AI"}], quote=SEC_QUOTE)
        value = self.run_desk(client, fetch=self.fetch())
        self.assertEqual(value["details"]["approved"], 1)
        text = build_daily_news_brief(self.research())
        self.assertIn("approximately $12 billion", text); self.assertIn(IPO_HEADER, text.splitlines())
        self.assertIn("conditional", text); self.assertTrue(validate_news_brief(text)["passes"])
        from src.intelligence.news_editor_store import read_editions
        editions = read_editions(report=text); self.assertEqual(len(editions), 1)
        self.assertTrue(any(story.get("sec_filing") for story in news_editor.selected_stories(editions[0])))
        self.assertEqual(len(client.calls), 2)

    def test_index_and_document_urls_share_the_same_deduplication_key(self):
        self.assertEqual(desk.finding_key(SEC_INDEX), desk.finding_key(SEC_PRIMARY))
        self.run_desk(Client(leads=[{"title": "Current report", "url": SEC_INDEX, "topic": "AI"}, {"title": "Same report", "url": SEC_PRIMARY, "topic": "AI"}], quote=SEC_QUOTE), fetch=self.fetch())
        self.assertEqual(len(desk.approved(NOW)), 1)

    def test_newer_hold_on_index_blocks_older_approval_for_its_document(self):
        self.run_desk(Client(leads=[{"title": "Current report", "url": SEC_PRIMARY, "topic": "AI"}], quote=SEC_QUOTE), fetch=self.fetch())
        self.run_desk(Client(leads=[{"title": "Current report", "url": SEC_INDEX, "topic": "AI"}], decision="hold"), NOW+timedelta(hours=1), self.fetch())
        self.assertEqual(desk.approved(NOW+timedelta(hours=1)), [])


class FollowupChecks(ResearchFixture):
    def held(self, url=URL):
        def blocked(_): raise HTTPError(url, 403, "Denied", {}, None)
        self.run_desk(Client(leads=[{"title": TITLE, "url": url, "topic": "AI"}]), fetch=blocked)
        return desk.read_history()[0]

    def test_empty_search_revisits_a_held_lead_with_two_total_model_requests(self):
        parent = self.held(); client = Client(leads=[])
        value = self.run_desk(client, NOW+timedelta(hours=1))
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(value["details"]["search_leads"], 0); self.assertEqual(value["details"]["retried"], 1)
        self.assertEqual(value["details"]["candidates"], 1); self.assertEqual(value["details"]["approved"], 1)
        record = desk.read_history()[0]
        self.assertEqual(record["discovered_at"], parent["discovered_at"])
        self.assertEqual(record["last_attempt_at"], (NOW+timedelta(hours=1)).isoformat())
        self.assertEqual(record["retry_count"], 1); self.assertEqual(record["origin"], "held retry")
        self.assertEqual(record["prior_review_response_id"], parent["review_response_id"])
        self.assertEqual(json.loads(client.calls[1]["input"])["candidates"][0]["lead_origin"], "held retry")

    def test_recovered_held_sec_filing_reaches_the_brief_after_empty_search(self):
        self.held(SEC_INDEX); client = Client(leads=[], quote=SEC_QUOTE)
        calls = []; fetch = SECResearchChecks.fetch(self, calls=calls)
        value = self.run_desk(client, NOW+timedelta(hours=1), fetch)
        self.assertEqual(value["details"]["approved"], 1); self.assertEqual(len(calls), 2)
        text = build_daily_news_brief(self.research(now=NOW+timedelta(hours=1)))
        self.assertIn("approximately $12 billion", text); self.assertTrue(validate_news_brief(text)["passes"])
        self.assertEqual(len(client.calls), 2)

    def test_retry_failure_never_reuses_previously_verified_text_for_approval(self):
        self.run_desk(Client(decision="hold"))
        self.assertIsNotNone(desk.read_history()[0]["verified"])
        def blocked(_): raise HTTPError(URL, 403, "Denied", {}, None)
        value = self.run_desk(Client(leads=[]), NOW+timedelta(hours=1), blocked)
        self.assertEqual(value["details"]["approved"], 0); self.assertEqual(desk.approved(NOW+timedelta(hours=1)), [])
        self.assertIsNone(desk.read_history()[0]["verified"])

    def test_retry_requires_a_new_successful_independent_model_review(self):
        self.held()
        value = self.run_desk(Client(leads=[], fail_review=True), NOW+timedelta(hours=1))
        self.assertEqual(value["status"], "limited"); self.assertEqual(desk.approved(NOW+timedelta(hours=1)), [])
        self.assertEqual(desk.read_history()[0]["review"]["final"], "hold")

    def test_retry_still_rejects_an_invented_evidence_quote(self):
        self.held()
        value = self.run_desk(Client(leads=[], quote="A quotation that never appeared in the original source text."), NOW+timedelta(hours=1))
        self.assertEqual(value["details"]["approved"], 0); self.assertEqual(desk.read_history()[0]["review"]["final"], "hold")

    def test_skipped_and_approved_findings_do_not_enter_the_retry_queue(self):
        self.run_desk()
        self.assertEqual(desk.retry_candidates(NOW+timedelta(hours=1), [], desk.read_history()), [])
        self.run_desk(Client(decision="skip"), NOW+timedelta(hours=1))
        self.assertEqual(desk.retry_candidates(NOW+timedelta(hours=2), [], desk.read_history()), [])

    def test_empty_search_without_pending_findings_uses_one_request(self):
        client = Client(leads=[]); value = self.run_desk(client)
        self.assertEqual(len(client.calls), 1); self.assertEqual(value["details"]["retried"], 0)

    def test_three_retry_limit_preserves_the_original_discovery_clock(self):
        parent = self.held()
        def blocked(_): raise HTTPError(URL, 403, "Denied", {}, None)
        for hour in range(1, 4):
            value = self.run_desk(Client(leads=[]), NOW+timedelta(hours=hour), blocked)
            self.assertEqual(value["details"]["retried"], 1)
            self.assertEqual(desk.read_history()[0]["retry_count"], hour)
            self.assertEqual(desk.read_history()[0]["discovered_at"], parent["discovered_at"])
        client = Client(leads=[]); value = self.run_desk(client, NOW+timedelta(hours=4), blocked)
        self.assertEqual(value["details"]["retried"], 0); self.assertEqual(len(client.calls), 1)

    def test_retry_does_not_bypass_the_once_per_hour_claim(self):
        self.held(); client = Client(leads=[])
        self.assertEqual(self.run_desk(client)["status"], "already attempted this hour")
        self.assertEqual(client.calls, [])

    def test_expired_future_and_malformed_first_seen_clocks_are_excluded(self):
        parent = self.held()
        for discovered in ((NOW-timedelta(hours=25)).isoformat(), (NOW+timedelta(hours=2)).isoformat(), "unknown"):
            value = deepcopy(parent); value["discovered_at"] = discovered
            self.assertEqual(desk.retry_candidates(NOW+timedelta(hours=1), [], [value]), [])

    def test_known_stale_publication_is_not_freshened_by_retry(self):
        self.run_desk(Client(decision="hold")); value = desk.read_history()[0]
        value["verified"]["published"] = (NOW-timedelta(hours=25)).isoformat()
        self.assertEqual(desk.retry_candidates(NOW+timedelta(hours=1), [], [value]), [])

    def test_legacy_hold_without_new_fields_can_be_revisited(self):
        parent = self.held()
        for key in ("retry_count", "last_attempt_at", "origin", "discovery_response_id", "prior_review_response_id"):
            parent.pop(key, None)
        self.assertEqual(len(desk.retry_candidates(NOW+timedelta(hours=1), [], [parent])), 1)
        raw = json.dumps(parent, sort_keys=True)
        with closing(sqlite3.connect(desk.state_path())) as db, db:
            db.execute("UPDATE findings SET payload=?,digest=?", (raw, hashlib.sha256(raw.encode()).hexdigest()))
        value = self.run_desk(Client(leads=[]), NOW+timedelta(hours=1))
        self.assertEqual(value["details"]["approved"], 1)
        self.assertEqual(desk.read_history()[0]["retry_count"], 1)

    def test_latest_skip_suppresses_an_older_hold(self):
        parent = self.held(); skipped = deepcopy(parent); skipped["review"] = {"final": "skip"}
        self.assertEqual(desk.retry_candidates(NOW+timedelta(hours=1), [], [skipped, parent]), [])

    def test_current_discovery_is_not_duplicated_as_a_retry(self):
        self.held()
        value = self.run_desk(Client(), NOW+timedelta(hours=1))
        self.assertEqual(value["details"]["candidates"], 1); self.assertEqual(value["details"]["retried"], 0)
        self.assertEqual(desk.read_history()[0]["discovered_at"], NOW.isoformat())

    def test_sec_index_and_document_aliases_are_not_retried_twice(self):
        self.held(SEC_INDEX)
        lead = {"title": "Current report", "url": SEC_PRIMARY, "topic": "AI"}
        self.assertEqual(desk.retry_candidates(NOW+timedelta(hours=1), [lead], desk.read_history()), [])

    def test_followup_is_bounded_and_uses_the_existing_six_source_reads(self):
        old = [{"title": TITLE, "url": URL+str(i), "topic": "AI"} for i in range(3)]
        self.run_desk(Client(leads=old, decision="hold"))
        fresh = [{"title": TITLE, "url": URL+"new"+str(i), "topic": "AI"} for i in range(6)]
        calls = []; value = self.run_desk(Client(leads=fresh), NOW+timedelta(hours=1), lambda url: calls.append(url) or html())
        self.assertEqual(value["details"]["retried"], 2); self.assertEqual(value["details"]["candidates"], 8)
        self.assertEqual(len(calls), 6); self.assertEqual(value["details"]["original_reads"], 6)

    def test_full_new_batch_keeps_all_search_results_and_defers_retries(self):
        self.held(URL+"held")
        fresh = [{"title": TITLE, "url": URL+str(i), "topic": "AI"} for i in range(8)]
        value = self.run_desk(Client(leads=fresh), NOW+timedelta(hours=1))
        self.assertEqual(value["details"]["candidates"], 8); self.assertEqual(value["details"]["retried"], 0)
        candidates = desk.retry_candidates(NOW+timedelta(hours=2), [], desk.read_history())
        self.assertEqual(candidates[0]["lead"]["url"], URL+"held")

    def test_malformed_history_does_not_hide_a_usable_pending_finding(self):
        parent = self.held()
        for invalid in ({}, {**deepcopy(parent), "retry_count": True}, {**deepcopy(parent), "lead": {"url": "http://127.0.0.1/private"}}):
            rows = desk.retry_candidates(NOW+timedelta(hours=1), [], [invalid])
            self.assertEqual(rows, [])
        self.assertEqual(len(desk.retry_candidates(NOW+timedelta(hours=1), [], [{}, parent])), 1)

    def test_original_decision_and_production_receipts_remain_unchanged(self):
        self.held(); before = {path: path.read_bytes() for path in (self.db, self.ranking)}
        with closing(sqlite3.connect(desk.state_path())) as db:
            original = db.execute("SELECT payload,digest FROM findings").fetchone()
        self.run_desk(Client(leads=[]), NOW+timedelta(hours=1))
        with closing(sqlite3.connect(desk.state_path())) as db:
            self.assertEqual(db.execute("SELECT payload,digest FROM findings ORDER BY slot LIMIT 1").fetchone(), original)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_read_only_history_labels_old_decisions_after_an_empty_scan(self):
        import asyncio
        from src.commands import hourly_research_commands as command
        self.held(); when = NOW+timedelta(hours=1)
        self.assertTrue(desk.claim(when)); desk.finish(when, "complete", [], {"candidates": 0, "approved": 0})
        async def check():
            update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
            with patch.object(command, "reply_long_message", new_callable=AsyncMock) as reply, patch.object(desk, "run") as run:
                await command.researchdesk_command(update, SimpleNamespace(args=["history"]))
            run.assert_not_called()
            text = reply.call_args.args[1]
            self.assertIn("latest scan recorded no story decisions", text)
            self.assertIn("Last checked (UTC): "+NOW.isoformat(), text)
        asyncio.run(check())


class PublisherEvidenceChecks(ResearchFixture):
    def test_three_alternate_issuer_sources_reach_the_reviewer_with_no_extra_model_or_source_reads(self):
        from html import escape
        from src.intelligence import news_live_sources as feeds
        values = {}
        for name, symbol, url in (
            ("Broadcom Financial News", "AVGO", "https://investors.broadcom.com/news-releases/news-release-details/fixture-ai"),
            ("AeroVironment Newsroom", "AVAV", "https://www.avinc.com/2026/10/25/fixture-defense/"),
            ("Kratos Newsroom", "KTOS", "https://www.kratosdefense.com/newsroom/fixture-defense")):
            source = next(row for row in feeds.NEWS_SOURCES if row["name"] == name)
            title = symbol + " announces a funded AI defense contract"
            payload = {"status": "ok", "url": source["url"], "final_url": source["url"], "fetched_at_epoch": NOW.timestamp()}
            if source.get("format"):
                payload.update(body="", original_profile=2, articles=[{"title": title, "link": url,
                    "published": (NOW-timedelta(minutes=20)).isoformat(), "description": QUOTE, "publication_url": url,
                    "evidence_checked_at": NOW.timestamp(), "release_body_verified": True}])
            else:
                payload["body"] = '<rss><channel><item><title>' + title + '</title><link>' + url + '</link><pubDate>' + (NOW-timedelta(minutes=20)).isoformat() + '</pubDate><description>' + escape(QUOTE) + '</description></item></channel></rss>'
            values[source["url"]] = payload
        path = Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"]); path.write_text(json.dumps(values)); before = path.read_bytes()
        client = Client(leads=[])
        with patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "AVGO,AVAV,KTOS"}):
            result = self.run_desk(client, fetch=lambda _: self.fail("Verified alternate sources must stay cache-only"))
        self.assertEqual(len(client.calls), 2)
        self.assertEqual((result["details"]["approved"], result["details"]["original_reads"]), (3, 0))
        approved = desk.approved(NOW)
        self.assertEqual({row["publisher_symbol"] for row in approved}, {"AVGO", "AVAV", "KTOS"})
        for row in approved: desk.check_proof(row, NOW)
        self.assertEqual(path.read_bytes(), before)

    def test_direct_kratos_webpage_uses_its_original_heading_clock_and_identified_release_body(self):
        url, title = "https://www.kratosdefense.com/newsroom/fixture-defense", "Kratos announces a funded defense contract"
        page_title = title + " | Kratos Defense"
        body = ('<meta property="og:title" content="' + page_title + '"><h1>' + title + '</h1>' +
                '<script type="application/ld+json">' + json.dumps({"@type": "WebPage", "@id": url, "url": url,
                "name": page_title, "datePublished": (NOW-timedelta(minutes=20)).isoformat()}) + '</script>' +
                '<article>Unrelated article must not enter the report.</article><section class="wysiwyg-section"><p>' + QUOTE + '</p></section>').encode()
        value = desk.verified({"url": url}, NOW, lambda _: body)
        self.assertEqual(value["title"], title)
        self.assertEqual(value["source_excerpt"], QUOTE)
        self.assertEqual(desk.timestamp(value["published"]), NOW-timedelta(minutes=20))
        self.assertEqual(desk.check_proof(value, NOW)["symbol"], "KTOS")

    def publication_cache(self):
        from src.intelligence import news_live_sources as feeds
        values = {}
        for name, title, url, publication_url in (
            ("U.S. Treasury", "Treasury announces new AI export sanctions", "https://home.treasury.gov/news/press-releases/sb0999/", "https://home.treasury.gov/news/press-releases/sb0999/"),
            ("Palantir Investor Relations", "Palantir announces a new AI defense contract", "https://investors.palantir.com/news-details/2026/fixture/default.aspx", "https://www.businesswire.com/news/home/20261025000001/en/")):
            source = next(row for row in feeds.NEWS_SOURCES if row["name"] == name)
            values[source["url"]] = {"status": "ok", "body": "", "url": source["url"], "final_url": source["url"],
                "original_profile": 2, "fetched_at_epoch": NOW.timestamp(), "articles": [
                {"title": title, "link": url, "published": (NOW-timedelta(minutes=20)).isoformat(),
                 "description": QUOTE, "publication_url": publication_url, "evidence_checked_at": NOW.timestamp()}]}
        path = Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"]); path.write_text(json.dumps(values))
        return path

    def test_treasury_and_linked_palantir_publications_reach_the_independent_reviewer(self):
        path = self.publication_cache(); before = path.read_bytes(); client = Client(leads=[])
        with patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "PLTR"}):
            result = self.run_desk(client, fetch=lambda _: self.fail("Verified publisher cache must not fetch"))
        self.assertEqual(len(client.calls), 2)
        self.assertEqual((result["details"]["approved"], result["details"]["original_reads"]), (2, 0))
        approved = desk.approved(NOW)
        self.assertEqual(len(approved), 2)
        for row in approved:
            desk.check_proof(row, NOW)
            self.assertEqual(row["publication_url"], row["discovery_evidence"]["publication_url"])
        self.assertEqual(path.read_bytes(), before)

    def test_clock_provenance_cannot_be_swapped_after_an_independent_approval(self):
        self.publication_cache()
        with patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "PLTR"}):
            self.run_desk(Client(leads=[]))
        row = next(row for row in desk.approved(NOW) if row["publisher_symbol"] == "PLTR")
        for field in ("publication_url", "proof"):
            changed = deepcopy(row)
            if field == "proof": changed["discovery_evidence"]["publication_url"] = "https://attacker.test/clock"
            else: changed["publication_url"] = "https://attacker.test/clock"
            with self.assertRaises(ValueError): desk.check_proof(changed, NOW)

    def test_retired_treasury_feed_identity_is_readable_in_historical_proofs(self):
        self.publication_cache()
        self.run_desk(Client(leads=[]))
        row = next(row for row in desk.approved(NOW) if row["source"] == "U.S. Treasury")
        row["discovery_evidence"]["feed_url"] = "https://home.treasury.gov/rss/press-releases"
        self.assertEqual(desk.check_proof(row, NOW)["name"], "U.S. Treasury")
        row["discovery_evidence"]["feed_url"] = "https://attacker.test/press-releases"
        with self.assertRaises(ValueError): desk.check_proof(row, NOW)

    def test_direct_treasury_lead_reads_the_identified_body_and_original_publication_field(self):
        from xml.sax.saxutils import escape
        url, title = "https://home.treasury.gov/news/press-releases/sb0999/", "Treasury announces new AI export sanctions"
        body = ('<meta property="og:title" content="' + escape(title) + '"><article>Navigation must not be evidence.</article>' +
                '<div class="field--name-field-news-publication-date"><time datetime="' + (NOW-timedelta(minutes=20)).isoformat() + '"></time></div>' +
                '<div class="field--name-field-news-body"><p>' + escape(QUOTE) + '</p></div>').encode()
        value = desk.verified({"url": url}, NOW, lambda _: body)
        self.assertEqual(value["source_excerpt"], QUOTE)
        self.assertEqual(desk.check_proof(value, NOW)["name"], "U.S. Treasury")

    def test_added_issuer_feeds_reach_the_independent_reviewer_without_extra_reads(self):
        from html import escape
        from urllib.parse import urlsplit
        from src.intelligence import news_live_sources as feeds
        values={};symbols={"AMD","CACI","NOC"}
        for source in feeds.NEWS_SOURCES:
            symbol=source.get("company_symbol")
            if symbol not in symbols or source.get("format"):continue
            url="https://"+urlsplit(source["url"]).hostname+"/fixture-original-release"
            title=symbol+" introduces an example AI defense product"
            rss=f'<rss><channel><item><title>{title}</title><link>{url}</link><pubDate>{(NOW-timedelta(minutes=20)).isoformat()}</pubDate><description>{escape(QUOTE)}</description></item></channel></rss>'
            values[source["url"]]={"status":"ok","body":rss,"fetched_at_epoch":NOW.timestamp()}
        path=Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"]);path.write_text(json.dumps(values));before=path.read_bytes()
        client=Client(leads=[])
        with patch.dict(os.environ,{"SPECIAL_ALERT_SYMBOLS":"AMD,CACI,NOC"}):
            result=self.run_desk(client,fetch=lambda _:self.fail("Dated publisher excerpts need no extra source read"))
        self.assertEqual(len(client.calls),2)
        self.assertEqual(result["details"]["original_reads"],0)
        self.assertEqual(result["details"]["approved"],3)
        self.assertEqual({row["verified"]["publisher_symbol"] for row in desk.read_history()},symbols)
        self.assertEqual(path.read_bytes(),before)

    def seed(self, *, symbol="NVDA", url=URL, title=TITLE, published=None, observed=None, description=None, status="ok", final_url=None):
        from html import escape
        from src.intelligence import news_live_sources as feeds
        source = next(row for row in feeds.NEWS_SOURCES if row.get("company_symbol") == symbol) if symbol else feeds.NEWS_SOURCES[0]
        published = (NOW-timedelta(minutes=20)).isoformat() if published is None else published
        observed = NOW-timedelta(minutes=5) if observed is None else observed
        description = QUOTE + " Enterprise deployment and customer validation milestones are described in the release." if description is None else description
        body = f'<rss><channel><item><title>{escape(title)}</title><link>{escape(url)}</link><pubDate>{escape(published)}</pubDate><description>{escape(description)}</description></item></channel></rss>'
        payload = {"status": status, "url": source["url"], "final_url": final_url or source["url"], "fetched_at_epoch": observed.timestamp(), "body": body}
        path = Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"])
        values = json.loads(path.read_text()) if path.exists() else {}
        if source["url"] in values and status == "ok":
            old = values[source["url"]]["body"]
            payload["body"] = old.replace("</channel>", body.split("<channel>", 1)[1].split("</channel>", 1)[0]+"</channel>", 1)
        values[source["url"]] = payload; path.write_text(json.dumps(values))
        return path

    def test_empty_web_search_reviews_dated_original_publisher_evidence(self):
        path = self.seed(); before = path.read_bytes(); client = Client(leads=[])
        value = self.run_desk(client, fetch=lambda _: self.fail("Cached publisher evidence must not trigger HTTP"))
        self.assertEqual(len(client.calls), 2); self.assertEqual(value["details"]["approved"], 1)
        self.assertEqual(value["details"]["search_leads"], 0); self.assertEqual(value["details"]["publisher_candidates"], 1)
        self.assertEqual(value["details"]["publisher_cache_used"], 1); self.assertEqual(value["details"]["original_reads"], 0)
        self.assertEqual(path.read_bytes(), before)
        record = desk.read_history()[0]
        self.assertEqual(record["origin"], "dated publisher cache")
        self.assertEqual(record["verified"]["source"], "Nvidia Newsroom")
        self.assertEqual(record["verified"]["source_checked_at"], (NOW-timedelta(minutes=5)).isoformat())

    def test_publisher_candidate_reaches_brief_with_original_clock_and_attribution(self):
        self.seed(); self.run_desk(Client(leads=[]))
        text = build_daily_news_brief(self.research())
        self.assertIn(TITLE, text); self.assertIn("Nvidia's October 25 announcement", text)
        self.assertTrue(validate_news_brief(text)["passes"])
        from src.intelligence.news_editor_store import read_editions
        records=read_editions(report=text)
        self.assertEqual(len(records), 1)
        self.assertEqual(news_editor.selected_stories(records[0])[0]["source"], "Nvidia Newsroom")

    def test_publisher_hints_are_input_context_not_claimed_as_new_web_results(self):
        self.seed(); client = Client(leads=[]); self.run_desk(client)
        hints = json.loads(client.calls[0]["input"])["publisher_reports_already_collected"]
        self.assertEqual(len(hints), 1); self.assertEqual(hints[0]["url"], URL)
        fake = Client(); fake.responses.create = lambda **_: response({"candidates": fake.leads}, searched=True, urls=[URL+"/other"])
        leads, _ = agents.discover(fake, "gpt-5", NOW.isoformat(), ["NVDA"], ["nvidia.com"], publisher_hints=hints)
        self.assertEqual(leads, [])

    def test_cached_source_still_needs_an_exact_new_model_evidence_quote(self):
        self.seed(); value = self.run_desk(Client(leads=[], quote="An unsupported invented quotation about sales growth."))
        self.assertEqual(value["details"]["approved"], 0); self.assertEqual(desk.approved(NOW), [])

    def test_model_failure_withholds_cached_reports(self):
        self.seed(); value = self.run_desk(Client(leads=[], fail_review=True))
        self.assertEqual(value["status"], "limited"); self.assertEqual(desk.approved(NOW), [])

    def test_cached_clocks_are_not_refreshed_on_repeated_reviews(self):
        self.seed(); self.run_desk(Client(leads=[], decision="hold"))
        old = desk.read_history()[0]["verified"]["source_checked_at"]
        self.run_desk(Client(leads=[]), NOW+timedelta(hours=1))
        self.assertEqual(desk.read_history()[0]["verified"]["source_checked_at"], old)

    def test_approved_publisher_report_is_not_requeued_as_a_new_report(self):
        self.seed(); self.run_desk(Client(leads=[]))
        client = Client(leads=[]); value = self.run_desk(client, NOW+timedelta(hours=1))
        self.assertEqual(value["details"]["publisher_candidates"], 0); self.assertEqual(len(client.calls), 1)

    def test_secondary_feed_and_unread_headlines_never_establish_approval(self):
        self.seed(symbol=None)
        self.assertEqual(self.run_desk(Client(leads=[]))["details"]["approved"], 0)
        Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"]).unlink(); desk.state_path().unlink()
        self.seed(description="")
        self.assertEqual(self.run_desk(Client(leads=[]))["details"]["approved"], 0)

    def test_stale_future_unzoned_and_impossible_cache_clocks_are_rejected(self):
        cases = [{"published": (NOW-timedelta(hours=25)).isoformat()}, {"published": (NOW+timedelta(minutes=1)).isoformat()},
            {"published": "2026-10-25T16:40:00"}, {"observed": NOW-timedelta(hours=7)},
            {"observed": NOW+timedelta(minutes=2)}, {"observed": NOW-timedelta(hours=1)}]
        for case in cases:
            with self.subTest(case=case):
                self.seed(**case); value = self.run_desk(Client(leads=[]))
                self.assertEqual(value["details"]["publisher_candidates"], 0)
                Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"]).unlink(); desk.state_path().unlink()

    def test_failed_or_redirected_official_feeds_do_not_establish_confirmation(self):
        for fields in ({"status": "error"}, {"final_url": "https://attacker.test/feed"}):
            self.seed(**fields); self.assertEqual(self.run_desk(Client(leads=[]))["details"]["approved"], 0)
            Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"]).unlink(); desk.state_path().unlink()

    def test_publisher_proof_binds_feed_scope_attribution_and_text(self):
        self.seed(); self.run_desk(Client(leads=[])); original = desk.approved(NOW)[0]
        for field, changed in (("source", "Unrelated wire"), ("excerpt_scope", "headline only"), ("source_excerpt", "invented")):
            value = deepcopy(original); value[field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError): desk.check_proof(value, NOW)
        value = deepcopy(original); value["discovery_evidence"]["feed_url"] = "https://attacker.test/feed"
        with self.assertRaises(ValueError): desk.check_proof(value, NOW)

    def test_publisher_pool_is_bounded_diverse_and_shares_existing_batch_cap(self):
        for index in range(4): self.seed(url=URL+str(index), title=TITLE+str(index))
        self.seed(symbol="MSFT", url="https://blogs.microsoft.com/blog/fixture", title="Microsoft unveils an Azure enterprise platform")
        value = self.run_desk(Client(leads=[]))
        self.assertEqual(value["details"]["publisher_candidates"], 3)
        self.assertEqual({row["verified"]["source"] for row in desk.read_history()}, {"Nvidia Newsroom", "Microsoft Blog"})

    def test_full_web_batch_does_not_grow_because_of_publisher_inputs(self):
        self.seed(url=URL+"cached")
        leads = [{"title": TITLE, "url": URL+str(i), "topic": "AI"} for i in range(8)]
        value = self.run_desk(Client(leads=leads))
        self.assertEqual(value["details"]["candidates"], 8); self.assertEqual(value["details"]["publisher_candidates"], 0)
        self.assertLessEqual(value["details"]["original_reads"], 6)

    def test_business_overview_leads_are_terminal_skips_without_source_reads(self):
        url = "https://www.lockheedmartin.com/en-us/who-we-are/business-areas/rotary-and-mission-systems.html"
        client = Client(leads=[{"title": "Lockheed Martin closes an acquisition", "url": url, "topic": "defense"}])
        value = self.run_desk(client, fetch=lambda _: self.fail("Business overview fetched"))
        self.assertEqual(value["details"]["skipped"], 1); self.assertEqual(value["details"]["held"], 0)
        self.assertEqual(len(client.calls), 1); self.assertIn("overview", desk.read_history()[0]["review"]["reason"])

    def test_expired_sec_lead_is_retired_with_authoritative_date_and_no_review_call(self):
        FollowupChecks.held(self, SEC_INDEX)
        published = (NOW-timedelta(hours=25)).isoformat(); calls = []
        fetch = SECResearchChecks.fetch(self, metadata=sec_metadata(acceptanceDateTime=[published]), calls=calls)
        client = Client(leads=[]); value = self.run_desk(client, NOW+timedelta(hours=1), fetch)
        self.assertEqual(value["details"]["expired"], 1); self.assertEqual(value["details"]["held"], 0)
        self.assertEqual(len(calls), 1); self.assertEqual(len(client.calls), 1)
        row = desk.read_history()[0]
        self.assertEqual(row["review"]["final"], "skip"); self.assertEqual(row["source_outcome"]["published"], published)
        self.assertEqual(desk.retry_candidates(NOW+timedelta(hours=2), [], desk.read_history()), [])

    def test_expired_publisher_page_is_not_an_unverified_hold(self):
        published = (NOW-timedelta(hours=25)).isoformat()
        value = self.run_desk(Client(), fetch=lambda _: html(clock=published))
        self.assertEqual(value["details"]["expired"], 1)
        self.assertEqual(desk.read_history()[0]["source_outcome"]["published"], published)

    def test_publisher_candidates_can_review_without_changing_scores_or_receipts(self):
        self.seed(); before = {path: path.read_bytes() for path in (self.db, self.ranking)}
        self.run_desk(Client(leads=[]))
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_unknown_terminal_outcome_is_rejected(self):
        with self.assertRaises(ValueError): SourceRejected("not a terminal decision", status="approve")


class SourceRoutingChecks(ResearchFixture):
    seed = PublisherEvidenceChecks.seed

    def test_direct_fed_statement_uses_original_zoned_release_clock_and_body(self):
        from scripts.check_news_editor import PolicyBriefChecks
        fixture=PolicyBriefChecks();source=fixture.source()
        value=desk.verified({"url":source["url"]},NOW,fetch=lambda _:fixture.body().encode())
        self.assertEqual(desk.timestamp(value["published"]),NOW.replace(hour=16))
        self.assertIn(fixture.TARGET,value["discovery_evidence"]["text"])
        self.assertNotIn("Navigation",value["discovery_evidence"]["text"])
        desk.check_proof(value,NOW)

    def test_cached_fed_reference_resolves_without_relaxing_identity_or_read_limits(self):
        from scripts.check_news_editor import PolicyBriefChecks
        from src.intelligence.research_source_routes import SourceResolver
        fixture=PolicyBriefChecks();value=fixture.source();published=value["published"]
        value["publisher_reference"]={"url":value["url"],"title":value["title"],"published":published,
            "observed":NOW.isoformat(),"publisher_clock":published,"feed_url":"https://www.federalreserve.gov/feeds/press_all.xml"}
        calls=[]
        resolver=SourceResolver(NOW,[value],lambda url:calls.append(url) or fixture.body().encode(),desk.identity,agents.url_key,[],{})
        result=resolver.verify(value)
        self.assertEqual(calls,[value["url"]]);desk.check_proof(result,NOW)
        self.assertEqual(result["source_checked_at"],value["source_checked_at"])
        self.assertIn(fixture.TARGET,result["source_excerpt"])

    def test_direct_fed_statement_rejects_a_conflicting_explicit_publication_clock(self):
        from scripts.check_news_editor import PolicyBriefChecks
        fixture=PolicyBriefChecks();body=fixture.body().replace("</head>",'<meta property="article:published_time" content="2026-10-25T15:00:00+00:00"></head>')
        with self.assertRaises(ValueError):
            desk.verified({"url":fixture.source()["url"]},NOW,fetch=lambda _:body.encode())

    def test_fed_publisher_candidate_reaches_independent_review_and_the_policy_brief(self):
        from scripts.check_news_editor import PolicyBriefChecks
        from src.intelligence import news_live_sources as feeds
        from html import escape
        fixture=PolicyBriefChecks();story=fixture.source()
        source=next(row for row in feeds.NEWS_SOURCES if row["name"]=="Federal Reserve")
        rss=f'<rss><channel><item><title>{story["title"]}</title><link>{story["url"]}</link><pubDate>{escape(story["published"])}</pubDate></item></channel></rss>'
        path=Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"])
        path.write_text(json.dumps({source["url"]:{"status":"ok","fetched_at_epoch":NOW.timestamp(),"body":rss}}))
        before=path.read_bytes();calls=[];client=Client(leads=[]);client.quote=fixture.TARGET
        result=self.run_desk(client,fetch=lambda url:calls.append(url) or fixture.body().encode())
        self.assertEqual(len(client.calls),2);self.assertEqual(calls,[story["url"]])
        self.assertEqual(result["details"]["approved"],1)
        text=build_daily_news_brief(self.research())
        self.assertIn("Policy & Economy",text)
        self.assertIn("held its federal funds target range at 3.75 to 4 percent",text)
        self.assertEqual(path.read_bytes(),before)

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "TSLA,NVDA,MSFT,PLTR,LMT"}))

    def brief(self):
        from src.intelligence.company_catalyst_context import build_company_catalyst_brief
        return build_company_catalyst_brief()

    def release(self, title=TITLE, text=QUOTE, *, day="October 25, 2026"):
        return (f'<html><body><h1>{title}</h1><div class="article-date">{day}</div>'
                f'<article><p>{text}</p><p>Deployment depends on customer commitments and the production schedule.</p></article></body></html>').encode()

    def catalogue(self):
        return desk.publisher_reports(NOW, ["NVDA", "MSFT", "LMT"], {}, desk.identity, desk.finding_key, include_unread=True)[0]

    def test_background_pages_do_not_spend_source_reads_or_request_ai_review(self):
        urls = ["https://www.federalreserve.gov/newsevents/2026-october.htm?view=calendar",
            "https://www.microsoft.com/en-us/investor/faq?CollectionId=null",
            "https://www.eia.gov/petroleum/gasdiesel/?os=yahoo.com", "https://ofac.treasury.gov/faqs/added",
            "https://www.apple.com/newsroom/topics/mac/"]
        client = Client(leads=[{"title": "Potential material report", "url": url, "topic": "company"} for url in urls])
        value = self.run_desk(client, fetch=lambda _: self.fail("Background page must not be fetched"))
        self.assertEqual(value["details"]["skipped"], 5); self.assertEqual(value["details"]["original_reads"], 0)
        self.assertEqual(len(client.calls), 1); self.assertFalse(desk.retry_candidates(NOW+timedelta(hours=1), [], desk.read_history()))

    def test_news_index_resolves_to_original_cached_release_and_retains_feed_clock(self):
        title = "Nvidia and Oracle expand cloud infrastructure to multi gigawatt scale"
        self.seed(title=title, description="")
        calls = []; client = Client(leads=[{"title": title, "url": "https://nvidianews.nvidia.com/news/?c=21926", "topic": "AI"}])
        value = self.run_desk(client, fetch=lambda url: calls.append(url) or self.release(title))
        self.assertEqual(calls, [URL]); self.assertEqual(value["details"]["resolved_releases"], 1)
        self.assertEqual(value["details"]["approved"], 1)
        item = desk.approved(NOW)[0]
        self.assertEqual(item["published"], (NOW-timedelta(minutes=20)).isoformat())
        self.assertEqual(item["source_checked_at"], (NOW-timedelta(minutes=5)).isoformat())
        handoff = json.loads(client.calls[1]["input"])["candidates"][0]
        self.assertEqual(handoff["url"], URL); self.assertEqual(handoff["title"], title)

    def test_approved_body_based_development_enters_the_brief_and_editor_history(self):
        title = "Lockheed Martin Welcomes Dedicated Missile Maintenance Facility in Poland"
        url = "https://news.lockheedmartin.com/2026-10-25-missile-maintenance-facility"
        self.seed(symbol="LMT", url=url, title=title, description="")
        client = Client(leads=[]); client.quote = "The new facility adds missile maintenance capacity in Poland."
        self.run_desk(client, fetch=lambda _: self.release(title, client.quote))
        self.assertEqual(len(desk.approved(NOW)), 1)
        text = build_daily_news_brief(self.research())
        self.assertIn(title, text); self.assertTrue(validate_news_brief(text)["passes"])
        from src.intelligence.news_editor_store import read_editions
        edition = read_editions()[0]
        selected = next(row for row in edition["candidates"] if row["decision"] == "selected" and row["title"] == title)
        self.assertEqual(selected["research_review"]["quote"], client.quote)
        self.assertEqual(selected["event_evidence"]["scope"], "original release excerpt")
        self.assertIn("Global and Defense Watch", text)

    def test_ir_mirror_is_replaced_by_the_canonical_publisher_link_before_http(self):
        title = "Lockheed Martin to Add Air Launched Hypersonic Missile to the American Arsenal of Freedom"
        actual = "https://news.lockheedmartin.com/2026-10-25-Lockheed-Martin-to-Add-Air-Launched-Hypersonic-Missile-to-the-American-Arsenal-of-Freedom"
        mirror = "https://investors.lockheedmartin.com/news-releases/news-release-details/lockheed-martin-add-air-launched-hypersonic-missile-american"
        self.seed(symbol="LMT", url=actual, title=title, description="")
        client = Client(leads=[{"title": "Lockheed Martin awarded a hypersonic missile contract", "url": mirror, "topic": "defense"}]); calls=[]
        value = self.run_desk(client, fetch=lambda url: calls.append(url) or self.release(title))
        self.assertEqual(calls, [actual]); self.assertEqual(value["details"]["approved"], 1)
        self.assertEqual(desk.approved(NOW)[0]["url"], actual)
        self.assertEqual(len(desk.latest_findings(desk.read_history())), 2)

    def test_missing_cached_feed_can_resolve_a_specific_ir_mirror_within_existing_budget(self):
        from html import escape
        title = "Nvidia expands Oracle cloud infrastructure with new systems"
        actual = "https://nvidianews.nvidia.com/news/nvidia-expands-oracle-cloud-infrastructure-with-new-systems"
        mirror = "https://investor.nvidia.com/news/press-release-details/2026/Nvidia-expands-Oracle-cloud-infrastructure-with-new-systems/default.aspx"
        rss = f'<rss><channel><item><title>{title}</title><link>{actual}</link><pubDate>{(NOW-timedelta(minutes=20)).isoformat()}</pubDate></item></channel></rss>'.encode()
        calls=[]
        def fetch(url):
            calls.append(url)
            if url == actual: return self.release(title)
            if url == "https://nvidianews.nvidia.com/releases.xml": return rss
            self.fail("Unresolved investor mirror fetched")
        value = self.run_desk(Client(leads=[{"title": title, "url": mirror, "topic": "AI"}]), fetch=fetch)
        self.assertEqual(value["details"]["original_reads"], 2); self.assertEqual(value["details"]["approved"], 1)
        self.assertEqual(len(calls), 2); self.assertFalse(Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"]).exists())

    def test_ambiguous_or_issuer_only_matching_does_not_choose_a_release(self):
        from src.intelligence.research_source_routes import matching_release
        self.seed(title="Nvidia expands Oracle cloud infrastructure to large scale")
        self.seed(url=URL+"2", title="Nvidia expands Oracle cloud infrastructure for large deployments")
        values = self.catalogue()
        for title in ("Nvidia publishes report", "Nvidia expands Oracle cloud infrastructure"):
            self.assertIsNone(matching_release({"title": title, "url": "https://nvidianews.nvidia.com/news/"}, values, desk.identity))
        self.assertIsNone(matching_release({"title": TITLE, "url": "https://www.microsoft.com/news/"}, values, desk.identity))

    def test_unmatched_news_index_is_skipped_without_inventing_publication(self):
        self.seed()
        client = Client(leads=[{"title": "Nvidia another unrelated announcement", "url": "https://nvidianews.nvidia.com/news/", "topic": "AI"}])
        value = self.run_desk(client, fetch=lambda _: b"<rss><channel></channel></rss>")
        record = next(row for row in desk.read_history() if row["lead"]["url"].endswith("/news/"))
        self.assertEqual(record["review"]["final"], "skip"); self.assertIsNone(record["verified"])
        self.assertLessEqual(value["details"]["original_reads"], 6)

    def test_date_only_release_must_match_the_identified_header_not_an_incidental_body_date(self):
        from src.intelligence.news_original_sources import article_excerpt
        body = self.release(text=QUOTE+" The old contract was signed October 25, 2026.", day="October 24, 2026")
        with self.assertRaisesRegex(ValueError, "date does not match"):
            article_excerpt(body.decode(), TITLE, NOW.isoformat())

    def test_original_feed_local_day_is_preserved_when_utc_day_differs(self):
        from src.intelligence.research_source_routes import SourceResolver
        published = "2026-10-24T23:45:00-04:00"
        self.seed(description="", published=published)
        resolver = SourceResolver(NOW, self.catalogue(), lambda _: self.release(day="October 24, 2026"), desk.identity, desk.finding_key, ["NVDA"], {})
        value = resolver.verify(resolver.values[0]); desk.check_proof(value, NOW)
        self.assertEqual(value["published"], "2026-10-25T03:45:00+00:00")

    def test_original_feed_clock_cannot_override_conflicting_explicit_release_metadata(self):
        from src.intelligence.research_source_routes import SourceResolver
        self.seed(description="")
        resolver = SourceResolver(NOW, self.catalogue(), lambda _: html(clock=(NOW-timedelta(hours=2)).isoformat()), desk.identity, desk.finding_key, ["NVDA"], {})
        with self.assertRaises(ValueError): resolver.verify(resolver.values[0])

    def test_failed_article_read_retains_known_publisher_clock_without_approval(self):
        self.seed(description="")
        value=self.run_desk(Client(leads=[]), fetch=lambda _: b"<html><h1>Access denied</h1></html>")
        self.assertEqual(value["details"]["approved"], 0)
        row = desk.read_history()[0]
        self.assertEqual(row["source_outcome"]["published"], (NOW-timedelta(minutes=20)).isoformat())
        self.assertFalse(desk.approved(NOW))

    def test_explicit_publisher_denials_do_not_trigger_fallback_reads(self):
        for status in (403, 429):
            calls=[]
            def fetch(url):
                calls.append(url); raise HTTPError(url, status, "Denied", {}, None)
            value=self.run_desk(Client(), fetch=fetch)
            self.assertEqual(calls, [URL]); self.assertEqual(value["details"]["approved"], 0)
            desk.state_path().unlink()

    def test_review_rejection_and_invented_quotes_withhold_original_feed_candidates(self):
        title="Nvidia and Oracle expand AI infrastructure"
        for decision, quote in (("skip", QUOTE), ("accept", "A claim the original company release did not make.")):
            self.seed(title=title, description="")
            client=Client(leads=[], decision=decision); client.quote=quote
            self.assertEqual(self.run_desk(client, fetch=lambda _: self.release(title))["details"]["approved"], 0)
            desk.state_path().unlink(); Path(os.environ["NEWS_LIVE_SOURCE_CACHE_FILE"]).unlink()

    def test_body_based_editor_admission_requires_a_bound_independent_review(self):
        title="Nvidia and Oracle expand AI infrastructure"
        self.seed(title=title); self.run_desk(Client(leads=[]))
        value=desk.approved(NOW)[0]
        for field, changed in (("quote", "An invented supporting quote."), ("score", 64), ("response_id", "")):
            raw=deepcopy(value); raw["research_review"][field]=changed
            with self.assertRaises(ValueError): desk.check_proof(raw, NOW)
            plan=news_editor.build_editorial_plan(self.brief(), NOW, [raw])
            self.assertFalse(news_editor.selected_stories(plan))

    def test_rediscovery_counts_against_the_same_three_retry_limit(self):
        def unavailable(_): raise ValueError("Unavailable source")
        for index in range(5):
            self.run_desk(Client(), NOW+timedelta(hours=index), unavailable)
        row=desk.read_history()[0]
        self.assertEqual(row["retry_count"], 3); self.assertEqual(row["review"]["final"], "skip")
        self.assertIn("rediscovery", row["review"]["reason"])
        self.assertEqual(row["discovered_at"], NOW.isoformat())

    def test_canonical_and_discovered_aliases_do_not_duplicate_held_followup(self):
        title="Nvidia and Oracle expand cloud infrastructure to multi gigawatt scale"
        self.seed(title=title, description="")
        client=Client(leads=[{"title": title, "url": "https://nvidianews.nvidia.com/news/", "topic": "AI"}], decision="hold")
        self.run_desk(client, fetch=lambda _: self.release(title))
        records=desk.read_history()
        self.assertEqual(len(desk.retry_candidates(NOW+timedelta(hours=1), [], records)), 1)
        self.assertFalse(desk.retry_candidates(NOW+timedelta(hours=1), [{"title": title, "url": URL, "topic": "AI"}], records))

    def test_unread_publisher_candidates_share_the_six_http_read_limit(self):
        for index in range(4):
            self.seed(url=URL+"publisher"+str(index), title=TITLE+" "+str(index), description="")
        calls=[]
        leads=[{"title": TITLE, "url": "https://www.microsoft.com/news/fresh"+str(index), "topic": "AI"} for index in range(4)]
        value=self.run_desk(Client(leads=leads), fetch=lambda url: calls.append(url) or html())
        self.assertLessEqual(len(calls), 6); self.assertEqual(value["details"]["candidates"], 7)
        self.assertLessEqual(value["details"]["original_reads"], 6)

    def test_expired_known_feed_clock_is_not_retried_as_a_new_discovery(self):
        self.seed(description="", published=(NOW-timedelta(hours=23)).isoformat())
        self.run_desk(Client(leads=[]), fetch=lambda _: b"<html><h1>Unavailable</h1></html>")
        self.assertFalse(desk.retry_candidates(NOW+timedelta(hours=2), [], desk.read_history()))


class QuoteSelectionChecks(ResearchFixture):
    seed = PublisherEvidenceChecks.seed

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"SPECIAL_ALERT_SYMBOLS": "TSLA,NVDA,MSFT,PLTR,LMT"}))

    def client(self, *, decision="accept", score=85, reference=None, leads=None):
        client = Client(leads=leads, decision=decision)
        original = client.responses.create
        def create(**options):
            if options["tools"]:
                return original(**options)
            client.calls.append(options)
            candidates = json.loads(options["input"])["candidates"]
            rows=[]
            for candidate in candidates:
                choices=candidate["evidence_options"]
                ref=choices[0]["id"] if choices else ""
                if reference is not None:
                    ref=reference(candidate, candidates)
                rows.append({"id": candidate["id"], "decision": decision, "score": score,
                    "reason": "Original material development; review its deployment, funding and execution conditions.", "evidence_ref": ref})
            return response({"decisions": rows})
        client.responses.create=create
        return client

    def test_review_selects_a_bound_source_passage_instead_of_rewriting_a_quote(self):
        client=self.client(); value=self.run_desk(client)
        self.assertEqual(value["details"]["approved"], 1); self.assertEqual(len(client.calls), 2)
        options=client.calls[1]
        fields=options["text"]["format"]["schema"]["properties"]["decisions"]["items"]
        self.assertIn("evidence_ref", fields["required"]); self.assertNotIn("evidence_quote", fields["properties"])
        row=desk.read_history()[0]
        self.assertEqual(row["review"]["evidence_quote"], QUOTE)
        self.assertTrue(row["review"]["evidence_ref"].startswith(row["id"]+":"))
        self.assertEqual(desk.approved(NOW)[0]["research_review"]["quote"], QUOTE)

    def test_passages_keep_original_unicode_and_punctuation(self):
        quote="The company announced an in\u2011flight demonstration."
        value=self.run_desk(self.client(), fetch=lambda _: html(text=quote))
        self.assertEqual(value["details"]["approved"], 1)
        self.assertEqual(desk.read_history()[0]["review"]["evidence_quote"], quote)

    def test_unknown_quote_reference_is_held_with_an_explicit_publication_gate(self):
        client=self.client(reference=lambda *_:"invented:q99")
        value=self.run_desk(client)
        self.assertEqual(value["details"]["approved"], 0); self.assertEqual(value["details"]["held"], 1)
        self.assertIn("exact passage", desk.read_history()[0]["review"]["publication_gate"])
        self.assertFalse(desk.approved(NOW)); self.assertEqual(len(client.calls), 2)

    def test_a_reference_from_another_candidate_never_establishes_support(self):
        leads=[{"title": TITLE, "url": URL+str(index), "topic":"AI"} for index in range(2)]
        client=self.client(leads=leads, reference=lambda row, rows:next(value for value in rows if value["id"]!=row["id"])["evidence_options"][0]["id"])
        self.assertEqual(self.run_desk(client)["details"]["approved"], 0)
        self.assertTrue(all(row["review"]["final"]=="hold" for row in desk.read_history()))

    def test_legacy_ellipsis_or_paraphrase_remains_held(self):
        for quote in ("The company announced...enterprise AI infrastructure.", "The company revealed AI technology for businesses."):
            client=Client();client.quote=quote
            self.assertEqual(self.run_desk(client)["details"]["approved"], 0)
            self.assertIn("exact passage",desk.read_history()[0]["review"]["publication_gate"])
            desk.state_path().unlink()

    def test_selecting_a_quote_does_not_override_the_reviewer_hold(self):
        self.assertEqual(self.run_desk(self.client(decision="hold"))["details"]["approved"],0)
        self.assertNotIn("publication_gate",desk.read_history()[0]["review"])

    def test_quote_selection_does_not_override_the_relevance_threshold(self):
        self.assertEqual(self.run_desk(self.client(score=64))["details"]["approved"],0)
        self.assertIn("threshold",desk.read_history()[0]["review"]["publication_gate"])

    def test_unverified_original_cannot_gain_approval_from_a_quote_reference(self):
        def failed(_):raise HTTPError(URL,403,"Denied",{},None)
        self.assertEqual(self.run_desk(self.client(),fetch=failed)["details"]["approved"],0)
        self.assertIn("verification",desk.read_history()[0]["review"]["publication_gate"])

    def test_passage_budget_is_bounded_and_does_not_change_source_text(self):
        text=" ".join(f"Sentence {i} describes a disclosed original development." for i in range(200))
        candidate={"id":"fixture", "source_text":text}
        quotes=agents.quote_options(candidate)
        self.assertLessEqual(len(quotes),6);self.assertLessEqual(sum(len(row["text"]) for row in quotes),2000)
        self.assertTrue(all(20<=len(row["text"])<=500 and row["text"] in text[:6000] for row in quotes))
        self.assertEqual(candidate["source_text"],text)
        self.assertFalse(agents.quote_options({"id":"none", "source_text":"x"*700}))

    def test_united_states_abbreviation_does_not_cut_the_quoted_subject(self):
        text="The company and the U.S. Army completed a reported test."
        self.assertEqual(agents.quote_options({"id":"fixture","source_text":text})[0]["text"],text)

    def test_new_protocol_validates_field_types_and_does_not_add_model_requests(self):
        for ref in (None, True, "x"*101):
            client=self.client(reference=lambda *_:ref)
            self.assertEqual(self.run_desk(client)["status"],"limited")
            self.assertEqual(len(client.calls),2);self.assertFalse(desk.approved(NOW))
            desk.state_path().unlink()

    def test_two_publisher_reports_reach_the_brief_with_event_specific_analysis(self):
        title="Nvidia and Oracle Expand AI Cloud Infrastructure to Multi-Gigawatt Scale"
        text="Nvidia and Oracle announced plans to expand their AI cloud infrastructure to multi-gigawatt scale."
        self.seed(title=title,description=text)
        defense="Lockheed Martin Redirects In-flight Rocket During U.S. Army Test"
        disclosed="Lockheed Martin successfully redirected an in-flight rocket during a reported test."
        self.seed(symbol="LMT",url="https://news.lockheedmartin.com/fixture-test",title=defense,description=disclosed)
        client=self.client(leads=[])
        value=self.run_desk(client,fetch=lambda _:self.fail("Cached originals must not fetch"))
        self.assertEqual(value["details"]["approved"],2);self.assertEqual(value["details"]["original_reads"],0)
        report=build_daily_news_brief(self.research())
        self.assertIn(title,report);self.assertIn(defense,report)
        self.assertIn("in-flight retargeting",report);self.assertIn("procurement approvals",report)
        self.assertIn("customer commitments",report);self.assertTrue(validate_news_brief(report)["passes"])
        from src.intelligence.news_editor_store import read_editions
        selected=news_editor.selected_stories(read_editions(report=report)[0])
        self.assertEqual(len(selected),2);self.assertTrue(all(row["event_evidence"]["schema"]==4 for row in selected))

    def test_new_quote_protocol_preserves_time_gates_and_hourly_attempt_limit(self):
        client=self.client();self.run_desk(client)
        self.assertEqual(self.run_desk(client)["status"],"already attempted this hour")
        self.assertEqual(len(client.calls),2);self.assertFalse(desk.approved(NOW+timedelta(hours=25)))

    def test_history_explains_a_code_withheld_approval(self):
        self.run_desk(self.client(reference=lambda *_:"unbound"))
        import asyncio
        from src.commands.hourly_research_commands import researchdesk_command
        async def inspect_history():
            update=SimpleNamespace(message=SimpleNamespace(),effective_chat=SimpleNamespace(type="private"))
            with patch("src.commands.hourly_research_commands.reply_long_message",new_callable=AsyncMock) as reply:
                await researchdesk_command(update,SimpleNamespace(args=["history"]))
            self.assertIn("Publication gate:",reply.call_args.args[1])
            self.assertIn("exact passage",reply.call_args.args[1])
        asyncio.run(inspect_history())


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
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in (ResearchChecks, ContractChecks, FinancialChecks, SECResearchChecks, FollowupChecks, PublisherEvidenceChecks, SourceRoutingChecks, QuoteSelectionChecks))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    ok = result.wasSuccessful() and not traffic["blocked"]
    print(f"Hourly Research Check: {'PASS' if ok else 'FAIL'} ({result.testsRun} tests)")
    raise SystemExit(0 if ok else 1)
